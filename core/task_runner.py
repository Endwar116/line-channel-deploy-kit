#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""task_runner.py — 無人看管的任務執行（方案 B，限制版）

主人 2026-09-06 核可。**這是 v1，刻意做得很窄。**

安全邊界（寫死在程式裡，不靠 agent 自律）：
  ① 只執行主人的任務。guest=True 一律跳過，訪客任務永遠等人工。
  ② 工具白名單：Read / Glob / Grep / WebFetch。
     **沒有 Write、Edit、Bash** ——它讀得到、查得到，但動不了任何東西。
  ③ 每個任務一個全新的空工作目錄，任務之間互不可見。
     附件要用才複製進去，不是整包掛上。
  ④ 每輪最多 MAX_PER_RUN 筆，避免一次燒掉大量額度。
  ⑤ 執行前驗 HMAC 簽章，驗不過不執行。
  ⑥ 每筆結果都落盤，並用 relay_say 回報——它做了什麼你一定看得見。

為什麼這樣設計：
  2026-09-05 到 09-06 之間，LINE 端的分身至少三次憑空編造
  （不存在的授權提示、不存在的終端機彈窗、看不到的本體進度）。
  講錯話還好，若編造變成動作就不只是講錯。所以 v1 一律不給動手的工具。

用法：
  python3 tools/task_runner.py            # 執行待處理的任務
  python3 tools/task_runner.py --dry      # 只列出會做什麼，不執行
  python3 tools/task_runner.py --max 1    # 這輪只做 1 筆
"""
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone, timedelta

ROOM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE = os.path.join(ROOM, "LOG", "task_queue.jsonl")
MARKER = os.path.join(ROOM, "LOG", "task_harvest_marker.json")
RESULTS = os.path.join(ROOM, "LOG", "task_results.jsonl")
WORKSPACE = os.path.join(ROOM, "workspace")
INCOMING = os.path.join(ROOM, "media", "incoming")
MCP = os.path.join(ROOM, "config", "empty_mcp.json")
BRIEF = os.path.join(ROOM, "config", "system_brief.md")
TZ = timezone(timedelta(hours=8))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from video_digest import MEDIA_EXT, digest  # noqa: E402
from video_link import LinkRejected, find_video_links, fetch as fetch_link  # noqa: E402

TOOLS = "Read,Glob,Grep,WebFetch"      # 白名單：只有讀與查
MAX_PER_RUN = 3
TIMEOUT = 600

# 部署者沒寫 system_brief.md 時用這份。只描述 kit 本身保證存在的東西，
# 不寫任何特定主人的網域、雲端服務或日曆——那些由部署者寫進 system_brief.md。
DEFAULT_BRIEF = """- LINE webhook 直接進 `line_bridge.py`（Python，跑在主人的 Mac 上）。
- 附件由 bridge 直接下載，落在 media/incoming/。
  docx / xlsx / pptx / pdf / txt / md / csv 都讀得到；
  掃描檔與圖片會自動走 macOS Vision OCR（有安裝的話）。
  影片／音檔會先被轉成 `<檔名>_digest/`（INDEX.md 逐字稿＋frames/*.jpg 關鍵畫格），
  用 Read 讀 INDEX.md 與畫格就能分析影片內容。
- 任務裡的影片連結（YouTube、Facebook、Instagram 等公開影片）也會先被下載並轉成同樣的 `_digest/`；
  抓不到的，檔案清單會寫原因，照實轉告主人。
- 你（本體）跟 LINE 上的分身是兩個角色：分身無工具、只接待；
  你有讀取工具、處理「任務」開頭的訊息。
- 其他系統細節這裡沒寫，就代表你不知道——不要猜。"""


def load_brief():
    try:
        s = open(BRIEF, encoding="utf-8").read()
        s = re.sub(r"<!--.*?-->", "", s, flags=re.S).strip()   # 給部署者看的註解不進 prompt
        return s or DEFAULT_BRIEF
    except OSError:
        return DEFAULT_BRIEF


def build_prompt(text, ctx, copied, brief):
    return f"""你是本體，正在無人看管的排程中執行一筆來自 LINE 的任務。

**這套系統長什麼樣（不要猜，照這裡寫的）**
{brief}
- 本次附件收件區的實際路徑：`{INCOMING}`

**回答前先確認你講的東西在上面這個架構裡真的存在。**
不確定就說不確定，不要用一般常識推測主人的系統怎麼搭。

**你的能力邊界（不要嘗試繞過，也不要假裝有）**
- 可以：讀檔案、搜尋檔案、讀網頁
- 不能：寫檔案、改檔案、跑指令
- 工作目錄只有這一個任務的資料，看不到其他任務

**輸出要求**
- 直接給結果，不要說「我將要…」
- 做不到就明說做不到，**絕對不要編造你沒做過的事**
- 需要主人決定或提供東西才能繼續，就明確說要什麼
- 控制在 400 字內，這會被送到 LINE

任務內容：
{text}

前後脈絡：
{ctx or "（無）"}

工作目錄裡的檔案：{('、'.join(copied)) if copied else "（無）"}"""


def claude_bin():
    import shutil as sh
    return sh.which("claude") or os.path.expanduser("~/.local/bin/claude")


def load_queue():
    if not os.path.exists(QUEUE):
        return []
    out = []
    for l in open(QUEUE, encoding="utf-8"):
        l = l.strip()
        if l:
            try:
                out.append(json.loads(l))
            except Exception:
                pass
    return out


def harvested():
    if os.path.exists(MARKER):
        try:
            return json.load(open(MARKER, encoding="utf-8")).get("line", 0)
        except Exception:
            pass
    return 0


def verify_task(entry):
    """單筆驗章，回 (ok, 原因)。fail-closed：未簽章、金鑰不見、驗章器出錯一律不執行。

    2026-09-26 審查發現舊版 fail-open：只看 task_verify --all 的輸出有沒有 ✗/🔴，
    未簽章（LEGACY）與驗章器 crash（例如金鑰檔不見）都被當成通過——
    只要能往佇列檔寫一行不帶 sig 的任務，就能驅動一個有 Read＋WebFetch 的無人看管 agent。
    傳副本進去：task_verify.verify 會把 sig 從 dict 裡 pop 掉。"""
    try:
        import task_verify
        v = task_verify.verify(dict(entry))
    except Exception as e:
        return False, f"驗章器無法執行（{type(e).__name__}）"
    if v == "OK":
        return True, ""
    return False, "沒有簽章" if v == "LEGACY" else "簽章不符"


def pick(tasks, limit):
    out = []
    for idx, t in enumerate(tasks):
        if t.get("guest"):
            continue                                   # 訪客任務永不自動執行
        txt = (t.get("text") or "")
        if txt.startswith("【附件到達"):
            continue                                   # 附件通知不是任務
        out.append((idx, t))
        if len(out) >= limit:
            break
    return out


def names_file(text, fname):
    """任務文字有沒有點名這個檔。完整檔名，或長於 6 字的主檔名；
    前後不能緊接英數（避免 IMG_1234 吃到 IMG_12345、短檔名吃到較長檔名的前段）（審查 M3）。
    中文字前後相接不算越界：「請看報價單2026版的內容」要認得。"""
    stem = os.path.splitext(fname)[0]
    for c in [fname] + ([stem] if len(stem) > 6 else []):
        if re.search(r"(?<![A-Za-z0-9_])" + re.escape(c) + r"(?![A-Za-z0-9_\-])(?!\.[A-Za-z0-9])", text):
            return True
    return False


def prepare_workspace(tid, task_text):
    d = os.path.join(WORKSPACE, tid)
    if os.path.exists(d):
        shutil.rmtree(d)
    os.makedirs(d, exist_ok=True)
    copied = []
    if os.path.isdir(INCOMING):
        for f in os.listdir(INCOMING):
            # 只複製任務文字裡點名的檔案，不整包掛上
            if names_file(task_text, f):
                shutil.copy2(os.path.join(INCOMING, f), os.path.join(d, f))
                copied.append(f)
    # 影片／音檔：由這支 Python（不是 agent）先跑 video_digest，
    # 把逐字稿與關鍵畫格放進工作目錄。agent 仍然只有讀取工具。
    for f in list(copied):
        if os.path.splitext(f)[1].lower() in MEDIA_EXT:
            try:
                out_dir, _ = digest(os.path.join(INCOMING, f))
                dst = os.path.join(d, os.path.splitext(f)[0] + "_digest")
                shutil.copytree(out_dir, dst)
                copied.append(os.path.basename(dst) + "/INDEX.md（逐字稿＋畫格清單，畫格 jpg 可用 Read 看）")
            except Exception as e:
                copied.append(f"（{f} 影片處理失敗：{type(e).__name__}）")
    # 任務帶影片連結（2026-09-28）：同樣由 Python 下載＋轉逐字稿，agent 只讀結果。
    # 抓不到的原因寫進檔案清單，讓 agent 照實告訴主人，而不是假裝看過。
    for url in find_video_links(task_text):
        try:
            out_dir, _ = digest(fetch_link(url))
            dst = os.path.join(d, os.path.basename(out_dir) + "_digest")
            shutil.copytree(out_dir, dst)
            copied.append(f"{os.path.basename(dst)}/INDEX.md（{url} 的逐字稿＋畫格清單，畫格 jpg 可用 Read 看）")
        except LinkRejected as e:
            copied.append(f"（{url} 抓不到：{e}）")
        except Exception as e:
            copied.append(f"（{url} 影片處理失敗：{type(e).__name__}）")
    return d, copied


def run_one(t, idx):
    tid = f"t{idx:04d}_" + re.sub(r"\W+", "", (t.get("ts") or ""))[-8:]
    text = t.get("text") or ""
    ws, copied = prepare_workspace(tid, text)
    ctx = "\n".join(f"・{c[:160]}" for c in (t.get("context") or [])[-4:])

    prompt = build_prompt(text, ctx, copied, load_brief())

    try:
        r = subprocess.run(
            [claude_bin(), "-p", prompt, "--model", "sonnet",
             "--strict-mcp-config", "--mcp-config", MCP,
             "--tools", TOOLS, "--allowedTools", TOOLS,
             "--output-format", "json"],
            cwd=ws, capture_output=True, text=True, timeout=TIMEOUT,
            stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            return False, f"claude 執行失敗 rc={r.returncode}：{(r.stderr or '')[:200]}"
        d = json.loads(r.stdout)
        out = (d.get("result") or "").strip()
        denials = d.get("permission_denials") or []
        if denials:
            names = ", ".join(sorted({p.get("tool_name", "?") for p in denials}))
            out += f"\n\n（它嘗試使用被禁止的工具：{names}，已被擋下）"
        return bool(out), out or "（無輸出）"
    except subprocess.TimeoutExpired:
        return False, f"逾時（{TIMEOUT} 秒）"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def main():
    limit = MAX_PER_RUN
    if "--max" in sys.argv:
        i = sys.argv.index("--max")
        if i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit():
            limit = int(sys.argv[i + 1])

    rows = load_queue()
    done = harvested()
    pending = rows[done:]
    todo = pick(pending, limit)

    skipped_guest = sum(1 for t in pending if t.get("guest"))
    if not todo:
        print(f"沒有可自動執行的任務"
              + (f"（{skipped_guest} 筆訪客任務保留給人工）" if skipped_guest else ""))
        return

    checked = [(idx, t) + verify_task(t) for idx, t in todo]

    if "--dry" in sys.argv:
        print(f"=== 會執行 {len(todo)} 筆（--dry 未實際執行）===")
        for idx, t, ok_sig, why in checked:
            print(f"  #{done+idx+1} {'' if ok_sig else '🔴 不執行（' + why + '）'}{t.get('text','')[:70]}")
        if skipped_guest:
            print(f"  （另有 {skipped_guest} 筆訪客任務不會自動執行）")
        return

    results, lines = [], []
    for idx, t, ok_sig, why in checked:
        label = (t.get("text") or "")[:44].replace("\n", " ")
        if ok_sig:
            print(f"── 執行 #{done+idx+1}：{label}")
            ok, out = run_one(t, done + idx + 1)
        else:
            # 不執行，但照樣記錄、回報、推進標記——一筆偽造的任務不能卡住後面所有任務
            print(f"── 🔴 擋下 #{done+idx+1}：{label}（{why}）")
            ok, out = False, f"⚠️ 簽章驗證未通過（{why}），沒有執行。這筆不是從 LINE 正常進來的，請查看佇列檔。"
        print(f"   {'✓' if ok else '✗'} {out[:120]}")
        rec = {"ts": datetime.now(TZ).isoformat(timespec="seconds"),
               "queue_line": done + idx + 1, "task": t.get("text", "")[:200],
               "ok": ok, "output": out}
        results.append(rec)
        lines.append(f"・{label}\n　{out[:300]}")

    with open(RESULTS, "a", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 只推進到實際處理過的最後一筆
    last = max(done + idx + 1 for idx, _ in todo)
    json.dump({"line": last, "ts": datetime.now(TZ).isoformat(timespec="seconds"),
               "by": "task_runner（自動）"},
              open(MARKER, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    msg = ("【本體】自動處理了 %d 筆任務。\n\n" % len(results)) + "\n\n".join(lines) + \
          "\n\n這是排程自動執行的，\n只給了讀取類工具，\n它動不了任何檔案。\n有做錯的跟我說。"
    try:
        subprocess.run([sys.executable, os.path.join(ROOM, "tools", "relay_say.py"), "-"],
                       input=msg, text=True, timeout=30)
    except Exception as e:
        print(f"（回報失敗 {type(e).__name__}）")
    print(f"\n✓ 完成 {len(results)} 筆，收割標記推進到 {last}")


if __name__ == "__main__":
    main()
