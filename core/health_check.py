#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""health_check.py — 靜默故障偵測（本體側維運工具）

為什麼需要這個：
  2026-09-04 實故障——部署者把日曆網址誤貼進 line_secrets.env 的
  LINE_CHANNEL_ACCESS_TOKEN 欄位，覆蓋了原本的 token。
  但 bridge 是啟動時把 token 讀進記憶體的，**通道照常運作了六分鐘沒人發現**。
  若非人工比對檔案修改時間，這個問題會潛伏到下次重啟或關機才爆發，
  屆時完全無從聯想成因。

  安裝器的 selftest 只在安裝當下檢查「檔案存在、值非空」，之後再也不看。
  金鑰被改壞、憑證過期、服務掛掉——這些它全都偵測不到。

設計原則：
  ① 絕不輸出任何金鑰內容，只驗結構與格式
  ② 每一項都是「會靜默失敗」的東西，不做無謂檢查
  ③ 發現異常用 relay_say 通知主人（免費），不打 push
  ④ 自己壞掉不能影響 bridge——完全獨立的程序

用法：
  python3 tools/health_check.py           # 檢查，有異常才通知
  python3 tools/health_check.py --always  # 不管有沒有異常都印出完整報告
  python3 tools/health_check.py --quiet   # 只回 exit code（0=健康 1=有異常）
"""
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

ROOM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEC = os.path.join(ROOM, "config", "secrets")
CFG_P = os.path.join(ROOM, "config", "kit_config.json")

SERVICE_NAMES = {"linebridge": "接收站", "cloudflared": "公網入口", "taskrunner": "任務執行",
                 "healthcheck": "自檢", "calendarsync": "行程同步", "queuewatch": "佇列通知",
                 "todopipeline": "待辦擷取", "restaurant": "餐廳收集", "backup": "備份",
                 "nosleep": "防睡眠"}


def slug_from_room(room):
    """安裝目錄是 ~/.{slug}，launchd label 是 com.{slug}.*——兩者由安裝器保證一致。"""
    return os.path.basename(os.path.normpath(room)).lstrip(".")


def discover_services(la_dir, slug):
    """只看實際存在的 com.{slug}.*.plist。
    寫死清單的話，客戶沒裝的服務（例如行程同步）會被當成「從沒跑過」報紅。"""
    prefix = f"com.{slug}."
    try:
        names = os.listdir(la_dir)
    except OSError:
        return {}
    out = {}
    for n in sorted(names):
        if n.startswith(prefix) and n.endswith(".plist"):
            label = n[:-len(".plist")]
            short = label[len(prefix):]
            out[label] = SERVICE_NAMES.get(short, short)
    return out


def owner_registered():
    """認主完成＝line_owner.txt 存在。之前是安裝後的設定期：憑證空白是待辦不是故障，通知也送不出去。"""
    return os.path.exists(os.path.join(SEC, "line_owner.txt"))


def unharvested(rows, runner_line, queue_marker):
    """還沒被收割的任務數。兩種收割標記任一涵蓋就算收過：
    task_runner 的行號（自動執行）、queue_backlog_check mark 的時間戳（本體手動收割）。
    只認其中一種的話，沒啟用任務執行的部署會永遠顯示積壓（審查 M1）。附件通知不是任務。"""
    from datetime import datetime
    n = 0
    for i, r in enumerate(rows):
        if (r.get("text") or "").startswith("【附件到達") or i < runner_line:
            continue
        if queue_marker is not None:
            try:
                if datetime.fromisoformat(r.get("ts") or "") <= queue_marker:
                    continue
            except (ValueError, TypeError):
                pass                     # 時間壞掉的寧可算成未收割
        n += 1
    return n


def resolve_public_host(cfg, port, cf_text, ts_status, funnel_text):
    """找「真的轉到本機 bridge port」的公網主機名（審查 M2）。
    順序：kit_config 的 public_host → cloudflared ingress 指向本 port 的 hostname →
    Tailscale Funnel 正在轉發本 port 時的節點名。其他不相干的 tunnel 一律不認。"""
    if cfg.get("public_host"):
        return cfg["public_host"]
    to_port = rf"(localhost|127\.0\.0\.1):{port}\b"
    for m in re.finditer(r"hostname:\s*(\S+)\s*\n\s*service:\s*(\S+)", cf_text or ""):
        if re.search(to_port, m.group(2)):
            return m.group(1)
    if ts_status and re.search(to_port, funnel_text or ""):
        name = ((ts_status.get("Self") or {}).get("DNSName") or "").rstrip(".")
        if name:
            return name
    return None


def local_port():
    try:
        return int(json.load(open(CFG_P, encoding="utf-8")).get("port") or 8700)
    except Exception:
        return 8700

FAIL, WARN, OK = "🔴", "⚠️", "✅"
results = []


def add(level, name, detail=""):
    results.append((level, name, detail))


def read_env(path):
    vals = {}
    if not os.path.exists(path):
        return None
    for line in open(path, encoding="utf-8"):
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        vals[k.strip()] = v.strip()
    return vals


def check_perms():
    """600 權限——被改鬆了不會有任何症狀，但金鑰就暴露了。"""
    for fn in ("line_secrets.env", "calendar_ics.env", "queue_hmac.key", "line_owner.txt"):
        p = os.path.join(SEC, fn)
        if not os.path.exists(p):
            continue
        mode = oct(os.stat(p).st_mode)[-3:]
        if mode != "600":
            add(FAIL, f"權限 {fn}", f"是 {mode}，應為 600")
        else:
            add(OK, f"權限 {fn}", "600")


def check_line_secrets():
    """今天出事的就是這裡：值被別的東西覆蓋，但欄位仍非空，所以看起來正常。"""
    p = os.path.join(SEC, "line_secrets.env")
    vals = read_env(p)
    if vals is None:
        add(FAIL, "line_secrets.env", "檔案不存在")
        return
    sec = vals.get("LINE_CHANNEL_SECRET", "")
    tok = vals.get("LINE_CHANNEL_ACCESS_TOKEN", "")

    # 還沒認主＝安裝後的設定期，空白是待辦
    empty_lv, empty_msg = (FAIL, "空值") if owner_registered() else (WARN, "尚未填寫（安裝後的待辦步驟）")
    if not sec:
        add(empty_lv, "LINE_CHANNEL_SECRET", empty_msg)
    elif not re.fullmatch(r"[0-9a-f]{32}", sec):
        add(FAIL, "LINE_CHANNEL_SECRET", f"格式不符（應為 32 位小寫 hex，實際 {len(sec)} 字元）")
    else:
        add(OK, "LINE_CHANNEL_SECRET", "32 位 hex")

    if not tok:
        add(empty_lv, "LINE_CHANNEL_ACCESS_TOKEN", empty_msg)
    elif len(tok) < 100:
        add(FAIL, "LINE_CHANNEL_ACCESS_TOKEN", f"長度僅 {len(tok)}，不像 LINE token")
    elif "://" in tok or "basic.ics" in tok:
        add(FAIL, "LINE_CHANNEL_ACCESS_TOKEN", "內容是網址——很可能誤貼了別的東西")
    elif " " in tok:
        add(FAIL, "LINE_CHANNEL_ACCESS_TOKEN", "含空白字元，複製時可能夾帶雜訊")
    else:
        add(OK, "LINE_CHANNEL_ACCESS_TOKEN", f"{len(tok)} 字元，格式合理")

    # 交叉污染：這個檔裡不該出現任何網址
    txt = open(p, encoding="utf-8").read()
    body = "\n".join(l for l in txt.splitlines() if not l.strip().startswith("#"))
    if "basic.ics" in body or "calendar.google" in body:
        add(FAIL, "交叉污染", "line_secrets.env 裡出現日曆網址")


def check_calendar():
    p = os.path.join(SEC, "calendar_ics.env")
    vals = read_env(p)
    if vals is None:
        add(WARN, "calendar_ics.env", "未設定（行程同步不會運作）")
        return
    filled = {k: v for k, v in vals.items() if v}
    if not filled:
        add(WARN, "日曆網址", "全部空白")
        return
    for k, url in filled.items():
        if "/private-" not in url:
            add(FAIL, f"日曆 {k}", "不是密件位址（缺 /private-），抓不到資料")
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "health/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = r.read().decode("utf-8", "ignore")
            n = data.count("BEGIN:VEVENT")
            add(OK, f"日曆 {k}", f"可抓取，{n} 筆事件")
        except Exception as e:
            add(FAIL, f"日曆 {k}", f"抓取失敗 {type(e).__name__}")


def check_mcp():
    """空物件 {} 會讓每一則訊息都失敗（2026-09-04 實故障）。"""
    p = os.path.join(ROOM, "config", "empty_mcp.json")
    try:
        d = json.load(open(p, encoding="utf-8"))
        if "mcpServers" not in d:
            add(FAIL, "empty_mcp.json", "缺 mcpServers 鍵——所有訊息都會失敗")
        else:
            add(OK, "empty_mcp.json", "格式正確")
    except Exception as e:
        add(FAIL, "empty_mcp.json", f"讀取失敗 {type(e).__name__}")


def boot_time():
    """本機開機時間（epoch 秒）；查不到回 None。"""
    try:
        out = subprocess.run(["sysctl", "-n", "kern.boottime"], capture_output=True,
                             text=True, timeout=5).stdout
        m = re.search(r"sec = (\d+)", out)
        return int(m.group(1)) if m else None
    except Exception:
        return None


def effective_log_age(mtime, now, boot):
    """排程型 log 的「過期秒數」，從 log 最後寫入與開機時間兩者較晚的那個起算。

    2026-09-24 重開機實測：自檢是 RunAtLoad、開機第一個跑，其他排程服務還沒輪到第一輪，
    log 停在關機前，於是五個服務全被判「跑過但停了」並掛了假警報。
    關機期間本來就不該跑，不能算進去；開機後一直沒跑的，距開機時間照樣會累積到被抓出來。
    """
    start = max(mtime, boot) if boot else mtime
    return now - start


def log_state(logp, interval, plist_mtime, now, boot):
    """排程型服務的 log 狀態：ok／stale（跑過但停了）／pending（剛安裝還沒輪到）／missing（從沒跑過）。
    寬限＝三個排程間隔、至少 15 分鐘；起算點一律避開關機時間（見 effective_log_age）。"""
    limit = max(int(interval) * 3, 900)
    if not os.path.exists(logp):
        age = effective_log_age(plist_mtime, now, boot)
        return ("pending" if age <= limit else "missing"), age
    age = effective_log_age(os.path.getmtime(logp), now, boot)
    return ("stale" if age > limit else "ok"), age


def check_services():
    """偵測「靜默死亡」的排程服務。

    檢查邏輯借自 SIC-SIT-Heartbeat 的 heartbeat/health.py（同一作者的另一專案）。
    它記錄的事故是：六個背景服務死了三個月沒人發現——排程器連 log 檔都打不開
    （log 在外接碟），所以在執行腳本「之前」就放棄了，回傳 exit 78，什麼都沒寫；
    而要查原因得讀 log，log 正是它打不開的那個東西。

    所以不看 log 內容找錯誤，改看四種形狀：
      ① exit status 不在 {0, -15, -9}（78 = EX_CONFIG：排程器 exec 前就放棄）
      ② 宣告的 log 路徑不存在 → 這個 job 從來沒成功跑過
      ③ log 存在但對排程型 job 已過期 → 跑過一次然後停了
      ④ log 路徑在外接／可移除磁區（已知的壞設定）

    紀律（照抄他們的 law 007）：這些是**症狀**不是結論。
    宣告服務死亡前，要先讀該服務自己寫的紀錄，排除「它是正常做完才結束」。
    """
    import plistlib
    from datetime import datetime

    EXTERNAL = ("/Volumes/", "/mnt/", "/media/")
    OK_EXITS = {"0", "-15", "-9"}
    LA = os.path.expanduser("~/Library/LaunchAgents")

    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True,
                             text=True, timeout=15).stdout
    except Exception:
        add(WARN, "launchctl", "查詢失敗")
        return

    slug = slug_from_room(ROOM)
    watched = discover_services(LA, slug)

    boot = boot_time()
    seen = set()
    for line in out.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        pid, status, label = parts[0], parts[1], parts[2].strip()
        if label not in watched:
            continue
        seen.add(label)
        name = watched[label]
        plist_p = os.path.join(LA, f"{label}.plist")
        conf = {}
        if os.path.exists(plist_p):
            try:
                conf = plistlib.load(open(plist_p, "rb"))
            except Exception:
                conf = {}
        periodic = bool(conf.get("StartInterval") or conf.get("StartCalendarInterval"))
        interval = conf.get("StartInterval")
        logp = conf.get("StandardOutPath") or conf.get("StandardErrorPath")
        running = pid not in ("-", "")

        # ① exit status
        # 例外：自檢自己。它發現問題時故意 exit 1 當訊號，那是設計行為不是故障；
        # 不排除的話會變成「上次有異常 → 這次報自己異常 → 永遠紅」的自我指涉迴圈。
        if label == f"com.{slug}.healthcheck" and status == "1":
            add(OK, f"服務 {name}", "排程型，上次回報有異常（exit 1 是它的訊號，非故障）")
            continue
        if status not in OK_EXITS:
            hint = "（78=排程器在 exec 前就放棄，通常是 log 路徑開不了）" if status == "78" else ""
            add(FAIL, f"服務 {name}", f"上次退出碼 {status}{hint}")
            continue

        # ④ log 在外接碟
        if logp and logp.startswith(EXTERNAL):
            add(FAIL, f"服務 {name}", f"log 在可移除磁區：{logp}")
            continue

        # ②③ 排程型：log 從沒建立／過期；剛安裝還沒輪到第一輪不算故障
        if periodic and interval and logp:
            state, age = log_state(logp, interval, os.path.getmtime(plist_p),
                                   datetime.now().timestamp(), boot)
            if state == "pending":
                add(OK, f"服務 {name}", f"排程型，剛安裝，還沒輪到第一輪（{int(interval)//60} 分鐘一次）")
                continue
            if state == "missing":
                add(FAIL, f"服務 {name}", "宣告的 log 不存在——這個 job 從沒成功跑過")
                continue
            if state == "stale":
                add(FAIL, f"服務 {name}",
                    f"log 已 {int(age//60)} 分鐘沒更新（排程 {int(interval)//60} 分鐘一次）"
                    f"——跑過但停了")
                continue
        elif logp and not os.path.exists(logp):
            add(FAIL, f"服務 {name}", "宣告的 log 不存在——這個 job 從沒成功跑過")
            continue

        if periodic:
            add(OK, f"服務 {name}", f"排程型，{int(interval)//60 if interval else '?'} 分鐘一次，log 新鮮")
        elif running:
            add(OK, f"服務 {name}", f"常駐 PID {pid}")
        else:
            add(FAIL, f"服務 {name}", "常駐型但沒有 PID")

    for label, name in watched.items():
        if label not in seen:
            add(FAIL, f"服務 {name}", "未載入 launchd")


def check_endpoints():
    try:
        with urllib.request.urlopen(f"http://localhost:{local_port()}/", timeout=10) as r:
            body = r.read().decode("utf-8", "ignore")
        add(OK if "alive" in body else WARN, "本機端點", f"HTTP {r.status}")
    except Exception as e:
        add(FAIL, "本機端點", f"連不上 {type(e).__name__}")

    try:
        cfg = json.load(open(CFG_P, encoding="utf-8"))
    except Exception:
        cfg = {}
    cf_text = ""
    cf = os.path.expanduser("~/.cloudflared/config.yml")
    if os.path.exists(cf):
        cf_text = open(cf, encoding="utf-8").read()
    ts_status, funnel_text = None, ""
    ts_bin = shutil.which("tailscale") or "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
    if os.path.exists(ts_bin):
        try:
            ts_status = json.loads(subprocess.run([ts_bin, "status", "--json"], capture_output=True,
                                                  text=True, timeout=10).stdout or "null")
            funnel_text = subprocess.run([ts_bin, "funnel", "status"], capture_output=True,
                                         text=True, timeout=10).stdout
        except Exception:
            ts_status = None
    host = resolve_public_host(cfg, local_port(), cf_text, ts_status, funnel_text)
    if not host:
        add(WARN, "公網端點", f"找不到轉到本機 port {local_port()} 的公網主機名——"
                            "可在 config/kit_config.json 加 \"public_host\" 指定")
        return
    try:
        req = urllib.request.Request(f"https://{host}/", headers={"User-Agent": "health/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode("utf-8", "ignore")
        add(OK if "alive" in body else WARN, "公網端點", f"{host} HTTP {r.status}")
    except Exception as e:
        add(FAIL, "公網端點", f"{host} 失敗 {type(e).__name__}")


def check_queue_backlog():
    """任務堆積代表本體沒在收割——這正是缺陷 F 的症狀。"""
    from datetime import datetime
    q = os.path.join(ROOM, "LOG", "task_queue.jsonl")
    if not os.path.exists(q):
        return
    rows = []
    for l in open(q, encoding="utf-8"):
        if l.strip():
            try:
                rows.append(json.loads(l))
            except Exception:
                rows.append({})
    runner_line = 0
    try:
        runner_line = json.load(open(os.path.join(ROOM, "LOG", "task_harvest_marker.json"),
                                     encoding="utf-8")).get("line", 0)
    except Exception:
        pass
    queue_marker = None
    try:
        queue_marker = datetime.fromisoformat(json.load(open(
            os.path.join(ROOM, "LOG", "queue_harvest_marker.json"), encoding="utf-8"))["harvested_until"])
    except Exception:
        pass
    pending = unharvested(rows, runner_line, queue_marker)
    if pending > 5:
        add(WARN, "任務佇列", f"{pending} 筆未收割——本體可能沒在盯佇列"
                              "（處理完請跑 tools/queue_backlog_check.py mark）")
    else:
        add(OK, "任務佇列", f"共 {len(rows)} 筆，未收割 {pending}")


def main():
    check_perms()
    check_line_secrets()
    check_calendar()
    check_mcp()
    check_services()
    check_endpoints()
    check_queue_backlog()

    fails = [r for r in results if r[0] == FAIL]
    warns = [r for r in results if r[0] == WARN]

    if "--quiet" in sys.argv:
        sys.exit(1 if fails else 0)

    if fails or warns or "--always" in sys.argv:
        for lv, name, detail in results:
            print(f"  {lv} {name:28} {detail}")
        print()
    print(f"結果：{len(fails)} 項失敗、{len(warns)} 項警告、"
          f"{len(results)-len(fails)-len(warns)} 項正常")

    # 有失敗才通知主人（免費路徑）；還沒認主時送不出去，不發
    if fails and not owner_registered():
        print("（尚未認主，不發通知）")
    elif fails:
        lines = ["【通道】自檢發現異常，", ""]
        for _, name, detail in fails:
            lines.append(f"・{name}：{detail}")
        lines += ["", "這類問題不會自己顯現，", "請盡快到電腦端處理。"]
        try:
            subprocess.run([sys.executable, os.path.join(ROOM, "tools", "relay_say.py"), "-"],
                           input="\n".join(lines), text=True, timeout=20)
        except Exception as e:
            print(f"（通知失敗：{type(e).__name__}）")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
