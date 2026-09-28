#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LINE_CHANNEL_DEPLOY_KIT 安裝器 v1.0 — 一條命令把 LINE 通道接收站裝進新機
================================================================================
用法：
  python3 install.py --owner 主人名 --agent-name 值台名 --slug slug [--port 8700]
                     [--skip-launchd] [--with-taskrunner] [--yes]
  參數未給且在互動終端 → 逐項問；非互動缺參數 → 印用法退出。

做的事（全部只動 ~/.{slug}/ 與 ~/Library/LaunchAgents/，絕不碰其他目錄）：
  1. 展開 core/ 工具 → ~/.{slug}/tools/（bridge＋claude_failure＋line_video＋relay_say＋line_push＋task_verify
     ＋queue_backlog_check；v1.15 起加本體側 health_check＋task_runner＋read_doc＋video_digest），
     測試 → ~/.{slug}/tools/tests/（裝完可自行 unittest 覆驗）
  2. 生成 config/kit_config.json（身分參數單一真源）＋queue_hmac.key（隨機生成，600）
  3. 展開 templates/ → 身分檔 CLAUDE.md（{AGENT_NAME}/{OWNER_NAME} 代入）＋secrets 空殼（600）
     ＋member_alias.json＋attach_whitelist.txt＋通道專屬段參考
  4. launchd plist 生成＋載入（--skip-launchd 可跳過）：bridge、每小時自檢；
     任務執行只安裝不載入，要自動執行加 --with-taskrunner（會自動消耗 Claude 額度）
  5. selftest：依賴 import／簽章驗證器自測／secrets 存在性／port 監聽——關鍵項全綠才報安裝成功
  6. 印「下一步人類動作清單」（申請 channel→填 secrets→Funnel→貼 webhook→測試訊息）

設計原則（承 SICJS_DEPLOY_KIT 慣例）：
  既有檔絕不默默覆蓋（secrets/身分檔已存在＝跳過；工具檔更新前備份）／
  fail-closed（selftest 關鍵項不過＝報失敗）／人按的步驟明列成卡，不當障礙繞。
"""
import argparse
import base64
import glob
import hashlib
import hmac
import json
import os
import re
import shutil
import socket
import subprocess
import sys

KIT = os.path.dirname(os.path.abspath(__file__))


def ask(prompt, current, pattern=None, hint=""):
    if current:
        return current
    if not sys.stdin.isatty():
        sys.exit(f"✗ 缺參數：{prompt}（非互動環境請用命令列參數，見 --help）")
    while True:
        v = input(f"{prompt}{'（' + hint + '）' if hint else ''}：").strip()
        if v and (pattern is None or re.match(pattern, v)):
            return v
        print(f"  格式不符{'（需 ' + hint + '）' if hint else ''}，再來一次")


def render(tmpl_path, mapping):
    with open(tmpl_path, encoding="utf-8") as f:
        s = f.read()
    for k, v in mapping.items():
        s = s.replace("{" + k + "}", str(v))
    return s


def put(path, content, mode=None, skip_if_exists=False, label=""):
    """寫檔：既有檔依策略跳過或備份，絕不默默覆蓋。"""
    if os.path.exists(path):
        old = open(path, encoding="utf-8").read()
        if old == content:
            print(f"  = {label or path}（已是最新）")
            return
        if skip_if_exists:
            print(f"  ↷ {label or path}（已存在且有差異——保留現況不覆蓋）")
            return
        bak = path + ".bak_kit_install"
        shutil.copy2(path, bak)
        print(f"  ↻ {label or path}（舊版備份 {os.path.basename(bak)}）")
    else:
        print(f"  + {label or path}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    if mode is not None:
        os.chmod(path, mode)


def build_ocr(base):
    """編譯 macOS Vision OCR。沒有 swiftc（未裝 Xcode Command Line Tools）不算失敗：
    read_doc 讀圖片時會明說 OCR 未安裝。KIT_NO_SWIFTC=1 供測試模擬。"""
    src = os.path.join(base, "tools", "bin", "ocr.swift")
    out = os.path.join(base, "tools", "bin", "ocr")
    swiftc = None if os.environ.get("KIT_NO_SWIFTC") else shutil.which("swiftc")
    if not swiftc:
        return "PENDING", "沒有 swiftc——`xcode-select --install` 後重跑安裝器即可啟用圖片 OCR"
    r = subprocess.run([swiftc, "-O", src, "-o", out], capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        return "PENDING", f"編譯失敗：{(r.stderr or '')[:160]}"
    return "PASS", "已編譯 tools/bin/ocr"


def install_extra_agents(slug, home, base, plist_dir, port, with_taskrunner, run=subprocess.run):
    """自檢（每小時，一律啟用）與任務執行（每 15 分，預設不啟用）的 launchd。

    「不啟用」＝根本不放進 LaunchAgents：launchd 登入時會載入那個資料夾裡所有 plist，
    只 unload 不移走的話，重開機後就自己跑起來、開始自動消耗額度（2026-09-26 審查 C1）。
    未啟用時 plist 放 config/launchd/ 備查。已經在 LaunchAgents 裡的＝主人之前啟用過，重跑安裝器保留啟用。
    任務執行先載入：自檢 RunAtLoad 會立刻跑，順序反過來第一輪自檢就報「未載入」。"""
    mapping = {"SLUG": slug, "PORT": port, "HOME": home, "BASE": base, "PYTHON": "/usr/bin/python3"}

    def tmpl(name):
        return render(os.path.join(KIT, "templates", "launchd", f"com.SLUG.{name}.plist.tmpl"), mapping)

    def load(p):
        run(["launchctl", "unload", p], capture_output=True)
        r = run(["launchctl", "load", p], capture_output=True, text=True)
        return "已載入" if r.returncode == 0 else f"載入失敗 rc={r.returncode}"

    tr_la = os.path.join(plist_dir, f"com.{slug}.taskrunner.plist")
    if with_taskrunner or os.path.exists(tr_la):
        put(tr_la, tmpl("taskrunner"), label=tr_la)
        print(f"launchd：taskrunner {load(tr_la)}" + ("" if with_taskrunner else "（之前已啟用，保留）"))
    else:
        ref_dir = os.path.join(base, "config", "launchd")
        os.makedirs(ref_dir, exist_ok=True)
        ref = os.path.join(ref_dir, f"com.{slug}.taskrunner.plist")
        put(ref, tmpl("taskrunner"), label=ref)
        print("launchd：taskrunner 未啟用（會自動消耗 Claude 額度）——要啟用請加 --with-taskrunner 重跑安裝器")

    hc = os.path.join(plist_dir, f"com.{slug}.healthcheck.plist")
    put(hc, tmpl("healthcheck"), label=hc)
    print(f"launchd：healthcheck {load(hc)}")


def selftest(base, port, launchd_loaded, ocr=("PENDING", "")):
    """回 (results, hard_fail)。關鍵項：依賴/簽章/secrets 檔在。port 未監聽在未載入時=PENDING 非失敗。"""
    results = []
    hard_fail = False

    # ① 依賴 import（bridge/工具全 stdlib）＋python 版本
    try:
        assert sys.version_info >= (3, 9), f"python {sys.version.split()[0]} < 3.9"
        import http.server, urllib.request, unicodedata, threading  # noqa: F401
        results.append(("依賴 import（stdlib）＋python>=3.9", "PASS", sys.version.split()[0]))
    except Exception as e:
        results.append(("依賴 import", "FAIL", str(e)))
        hard_fail = True

    # ② webhook 簽章驗證器自測（與 bridge 同款演算法：HMAC-SHA256 → base64 → compare_digest）
    try:
        key, body = b"kit_selftest_key", b"kit_selftest_body"
        sig = base64.b64encode(hmac.new(key, body, hashlib.sha256).digest()).decode()
        ok_good = hmac.compare_digest(sig, base64.b64encode(hmac.new(key, body, hashlib.sha256).digest()).decode())
        ok_bad = not hmac.compare_digest(sig, base64.b64encode(hmac.new(key, b"tampered", hashlib.sha256).digest()).decode())
        assert ok_good and ok_bad
        results.append(("簽章驗證器自測（正簽收/偽簽拒）", "PASS", "HMAC-SHA256+b64"))
    except Exception as e:
        results.append(("簽章驗證器自測", "FAIL", str(e)))
        hard_fail = True

    # ③ secrets 存在性（可空值——空值=待填提示，不算失敗；缺檔=失敗）
    sec_p = os.path.join(base, "config", "secrets", "line_secrets.env")
    if os.path.exists(sec_p):
        vals = {}
        for line in open(sec_p, encoding="utf-8"):
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.strip().split("=", 1)
                vals[k] = v
        empty = [k for k in ("LINE_CHANNEL_SECRET", "LINE_CHANNEL_ACCESS_TOKEN") if not vals.get(k)]
        if empty:
            results.append(("secrets 檔存在", "PASS", f"待填：{','.join(empty)}（填完 bridge 才會啟動）"))
        else:
            results.append(("secrets 檔存在", "PASS", "已填值"))
    else:
        results.append(("secrets 檔存在", "FAIL", sec_p))
        hard_fail = True

    # ④ queue_hmac.key 存在
    key_p = os.path.join(base, "config", "secrets", "queue_hmac.key")
    if os.path.exists(key_p):
        results.append(("任務簽章鍵存在", "PASS", "600"))
    else:
        results.append(("任務簽章鍵存在", "FAIL", key_p))
        hard_fail = True

    # ⑤ bridge 語法（py_compile）
    br = os.path.join(base, "tools", "line_bridge.py")
    r = subprocess.run([sys.executable, "-m", "py_compile", br], capture_output=True, text=True)
    if r.returncode == 0:
        results.append(("bridge py_compile", "PASS", ""))
    else:
        results.append(("bridge py_compile", "FAIL", (r.stderr or "")[:120]))
        hard_fail = True

    # ⑤b 本體側工具 import（v1.15）——py_compile 不解析 import，漏檔要真的 import 才會炸（缺陷 F 模式）
    tools = os.path.join(base, "tools")
    r = subprocess.run([sys.executable, "-c", "import health_check, task_runner, read_doc, video_digest, line_video"],
                       cwd=tools, capture_output=True, text=True)
    if r.returncode == 0:
        results.append(("本體側工具 import", "PASS", "health_check／task_runner／read_doc／video_digest／line_video"))
    else:
        results.append(("本體側工具 import", "FAIL", (r.stderr or "").strip().splitlines()[-1][:160]))
        hard_fail = True

    # ⑤c 可選能力：圖片 OCR、影片逐字稿（缺了只降級，不擋裝）
    results.append(("OCR（圖片／掃描檔）", ocr[0], ocr[1]))
    r = subprocess.run([sys.executable, "-c",
                        "import json, os, video_digest as v; "
                        "print(json.dumps([v.missing_tools(), os.path.exists(v.MODEL), v.INSTALL_HINT]))"],
                       cwd=tools, capture_output=True, text=True)
    try:
        miss, model_ok, hint = json.loads(r.stdout)
        if miss or not model_ok:
            results.append(("影片逐字稿", "PENDING",
                            f"缺 {'、'.join(miss + ([] if model_ok else ['whisper 模型']))}——{hint}"))
        else:
            results.append(("影片逐字稿", "PASS", "ffmpeg＋whisper＋模型齊全"))
    except Exception:
        results.append(("影片逐字稿", "WARN", "無法檢查"))

    # ⑥ port 監聽（launchd 載入且 secrets 已填才會真監聽）
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            results.append((f"port {port} 監聽", "PASS", "bridge 活著"))
    except OSError:
        if launchd_loaded:
            results.append((f"port {port} 監聽", "WARN", "已載入但未監聽——多半是 secrets 未填（fail-closed 拒啟動）；填完後 launchd 會自動重試"))
        else:
            results.append((f"port {port} 監聽", "PENDING", "launchd 未載入（--skip-launchd）——載入後再驗"))

    # ⑦ 周邊指令存在性（警告不擋裝）
    for cmd, why in (("claude", "值台引擎（Claude Code CLI）"), ("tailscale", "Funnel 公網中繼")):
        found = shutil.which(cmd) or (os.path.exists(os.path.expanduser(f"~/.local/bin/{cmd}")) and f"~/.local/bin/{cmd}")
        results.append((f"指令 {cmd}", "PASS" if found else "WARN", found or f"未找到——{why}，見 00_START_HERE 前置"))
    return results, hard_fail


def main():
    ap = argparse.ArgumentParser(description="LINE_CHANNEL_DEPLOY_KIT v1.0 安裝器")
    ap.add_argument("--owner", default=None, help="主人稱呼（值台對他的稱呼；認主口令=我是<owner>）")
    ap.add_argument("--agent-name", default=None, help="值台 agent 名（身分檔/標頭用）")
    ap.add_argument("--slug", default=None, help="小寫英數代號（家目錄 ~/.{slug}/ 與 launchd label 用）")
    ap.add_argument("--port", type=int, default=8700, help="bridge 本機監聽埠（預設 8700）")
    ap.add_argument("--skip-launchd", action="store_true", help="不生成/載入 launchd（測試或稍後手動）")
    ap.add_argument("--with-taskrunner", action="store_true",
                    help="載入每 15 分鐘的唯讀任務執行（會自動消耗 Claude 額度；預設只安裝不載入）")
    ap.add_argument("--yes", action="store_true", help="略過確認提問")
    a = ap.parse_args()

    owner = ask("主人稱呼", a.owner, r"^[\w一-鿿]+$", "中英數")
    agent = ask("值台 agent 名", a.agent_name, r"^[\w一-鿿]+$", "中英數")
    slug = ask("slug", a.slug, r"^[a-z][a-z0-9_]*$", "小寫英數，如 linekit")
    port = a.port
    if not (1024 <= port <= 65535):
        sys.exit(f"✗ port 需在 1024-65535：{port}")

    home = os.path.expanduser("~")
    base = os.path.join(home, f".{slug}")
    plist_dir = os.path.join(home, "Library", "LaunchAgents")
    plist_p = os.path.join(plist_dir, f"com.{slug}.linebridge.plist")

    print(f"\n安裝計畫：owner={owner} agent={agent} slug={slug} port={port}")
    print(f"  ① core 工具 11 支＋OCR＋測試 → {base}/tools/")
    print(f"  ② config（kit_config.json＋queue_hmac.key＋member_alias＋attach_whitelist＋empty_mcp）")
    print(f"  ③ 身分檔 → {base}/CLAUDE.md（既有不覆蓋）；secrets 空殼 → config/secrets/（既有不覆蓋）")
    print(f"  ④ launchd → {plist_p}＋每小時自檢" + ("＋任務執行" if a.with_taskrunner else "（任務執行不啟用）")
          + ("（--skip-launchd：跳過）" if a.skip_launchd else "＋launchctl load"))
    print(f"  ⑤ selftest ＋ 人類動作清單")
    if not a.yes and sys.stdin.isatty():
        if input("繼續？[y/N] ").strip().lower() != "y":
            sys.exit("中止（未動任何檔案）")

    # ── ① 目錄與 core ──
    for d in ("tools", os.path.join("tools", "tests"), os.path.join("tools", "bin"), "models",
              "config/secrets", "LOG", "chats",
              "attachments", os.path.join("media", "incoming")):
        os.makedirs(os.path.join(base, d), exist_ok=True)
    print("展開：")
    # claude_failure.py 是 line_bridge 的頂層 import（from claude_failure import classify_failure）。
    # 漏掉它 bridge 會 ImportError 死在啟動，不是功能降級——名單少一個檔就是整站不起來。
    # line_video.py 是 bridge 的頂層 import（v1.16），漏了 bridge 會 ImportError 死在啟動
    CORE_TOOLS = ("line_bridge.py", "claude_failure.py", "line_video.py", "relay_say.py", "line_push.py",
                  "task_verify.py", "queue_backlog_check.py",
                  # v1.15：本體側工具（自檢、唯讀任務執行、文件／影片讀取）
                  "health_check.py", "task_runner.py", "read_doc.py", "video_digest.py")
    for f in CORE_TOOLS:
        put(os.path.join(base, "tools", f), open(os.path.join(KIT, "core", f), encoding="utf-8").read(),
            label=f"tools/{f}")
    put(os.path.join(base, "tools", "bin", "ocr.swift"),
        open(os.path.join(KIT, "core", "bin", "ocr.swift"), encoding="utf-8").read(),
        label="tools/bin/ocr.swift")
    # 測試隨工具一起出貨：裝完可用 `cd ~/.{slug}/tools && python3 -m unittest discover -s tests`
    # 自證核心行為真的接在 bridge 上，不必只信 selftest 的 GREEN 字樣。
    # 用 glob 而非寫死名單——寫死的話每加一個測試就要記得改這裡，
    # 跟當初漏掉 claude_failure.py 是同一類錯誤，而且漏了不會有任何徵兆。
    # test_install.py 是 kit 專用：它要在 kit 樹跑安裝器，裝進客戶樹會找不到 install.py 且會遞迴安裝。
    KIT_ONLY_TESTS = {"test_install.py"}
    for f in sorted(os.path.basename(p) for p in
                    glob.glob(os.path.join(KIT, "core", "tests", "*.py"))):
        if f in KIT_ONLY_TESTS:
            continue
        put(os.path.join(base, "tools", "tests", f),
            open(os.path.join(KIT, "core", "tests", f), encoding="utf-8").read(),
            label=f"tools/tests/{f}")

    # ── ② config ──
    cfg = {"owner_name": owner, "agent_name": agent,
           "body_label": "【本體】", "register_phrase": f"我是{owner}",
           "mention_keywords": [f"@{agent}"], "s_tier_channels": [],
           "port": port, "chat_model": "sonnet"}
    put(os.path.join(base, "config", "kit_config.json"),
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", label="config/kit_config.json")
    key_p = os.path.join(base, "config", "secrets", "queue_hmac.key")
    if not os.path.exists(key_p):
        with open(key_p, "w", encoding="utf-8") as f:
            f.write(base64.b64encode(os.urandom(32)).decode() + "\n")
        os.chmod(key_p, 0o600)
        print("  + config/secrets/queue_hmac.key（隨機生成，600）")
    else:
        print("  = config/secrets/queue_hmac.key（既有保留）")
    put(os.path.join(base, "config", "member_alias.json"),
        open(os.path.join(KIT, "templates", "member_alias.json.tmpl"), encoding="utf-8").read(),
        skip_if_exists=True, label="config/member_alias.json")
    put(os.path.join(base, "config", "attach_whitelist.txt"),
        "# 附件白名單：每行一個 userId（可先留空；高信任通道另見 kit_config s_tier_channels）\n",
        skip_if_exists=True, label="config/attach_whitelist.txt")
    # Claude Code 需要 mcpServers 鍵才通得過 schema 驗證；空物件 {} 會被拒：
    #   Error: Invalid MCP configuration: mcpServers: Does not adhere to MCP server configuration schema
    # 實測環境 Claude Code 2.1.208（2026-09-04）
    put(os.path.join(base, "config", "empty_mcp.json"), '{"mcpServers": {}}\n',
        skip_if_exists=True, label="config/empty_mcp.json")
    put(os.path.join(base, "config", "channel_discipline_參考.md"),
        open(os.path.join(KIT, "templates", "channel_discipline.tmpl"), encoding="utf-8").read(),
        skip_if_exists=True, label="config/channel_discipline_參考.md")
    put(os.path.join(base, "config", "system_brief.md"),
        open(os.path.join(KIT, "templates", "system_brief.md.tmpl"), encoding="utf-8").read(),
        skip_if_exists=True, label="config/system_brief.md（任務執行的系統說明，請依實況改寫）")
    ocr_status, ocr_detail = build_ocr(base)
    print(f"  OCR：{ocr_status} {ocr_detail}")

    # ── ③ 身分檔＋secrets（既有一律不覆蓋） ──
    put(os.path.join(base, "CLAUDE.md"),
        render(os.path.join(KIT, "templates", "CLAUDE.md.tmpl"),
               {"AGENT_NAME": agent, "OWNER_NAME": owner}),
        skip_if_exists=True, label="CLAUDE.md（身分檔）")
    sec_p = os.path.join(base, "config", "secrets", "line_secrets.env")
    if not os.path.exists(sec_p):
        shutil.copy(os.path.join(KIT, "templates", "secrets.env.tmpl"), sec_p)
        os.chmod(sec_p, 0o600)
        print("  + config/secrets/line_secrets.env（空殼，600——**值等你填**）")
    else:
        os.chmod(sec_p, 0o600)
        print("  = config/secrets/line_secrets.env（既有保留，權限校正 600）")

    # ── ④ launchd ──
    launchd_loaded = False
    if a.skip_launchd:
        print("launchd：跳過（--skip-launchd）。稍後手動：")
        print(f"  python3 install.py --owner {owner} --agent-name {agent} --slug {slug} --port {port} --yes")
    else:
        os.makedirs(plist_dir, exist_ok=True)
        put(plist_p, render(os.path.join(KIT, "templates", "launchd", "com.SLUG.linebridge.plist.tmpl"),
                            {"SLUG": slug, "PORT": port, "HOME": home,
                             "BASE": base, "PYTHON": "/usr/bin/python3"}),
            label=plist_p)
        subprocess.run(["launchctl", "unload", plist_p], capture_output=True)
        r = subprocess.run(["launchctl", "load", plist_p], capture_output=True, text=True)
        if r.returncode == 0:
            launchd_loaded = True
            print("launchd：已載入（KeepAlive 常駐；secrets 未填時 bridge 會 fail-closed 等你填）")
        else:
            print(f"launchd：載入失敗 rc={r.returncode} {(r.stderr or '').strip()[:120]}")
        install_extra_agents(slug, home, base, plist_dir, port, a.with_taskrunner)

    # ── ⑤ selftest ──
    print("\nselftest：")
    results, hard_fail = selftest(base, port, launchd_loaded, (ocr_status, ocr_detail))
    for name, st, detail in results:
        icon = {"PASS": "✅", "FAIL": "🔴", "WARN": "⚠️", "PENDING": "⏳"}[st]
        print(f"  {icon} {st:<7} {name}" + (f"　{detail}" if detail else ""))

    print("\n【下一步人類動作清單】（≤6 步，逐步照做）")
    print("  1. 申請 LINE Official Account＋Messaging API channel → docs/LINE_Developers_申請教學.md")
    print(f"  2. 把 Channel secret＋access token 填進 {base}/config/secrets/line_secrets.env")
    print(f"  3. 裝 Tailscale 並開 Funnel：tailscale funnel --https=443 {port}（教學同上 docs）")
    print("  4. LINE Developers console → Messaging API → Webhook URL 貼 https://<你的節點>.ts.net/callback → Verify → Use webhook 開")
    print(f"  5. 手機加 bot 好友，傳認主口令「我是{owner}」→ 回「登記完成」")
    print("  6. 再傳一句話收到回覆＝通道 GREEN（詳 00_START_HERE.md 驗收定義）")

    if hard_fail:
        sys.exit("\n🛑 安裝未完成：selftest 有關鍵項失敗（見上）。修復後重跑本安裝器（冪等，可重跑）。")
    print(f"\n✅ 安裝完成：{base}（selftest 關鍵項全綠；port/secrets 類待人類步驟後轉綠）")


if __name__ == "__main__":
    main()
