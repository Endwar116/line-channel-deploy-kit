# LINE_CHANNEL_DEPLOY_KIT v1.0 — 從這裡開始

> 這包做什麼：把一個 LINE 官方帳號變成你的 AI 值台——新機從零到通道活著 ≤ 30 分鐘。
> 版本：KIT v1.0（2026-08-25 凍結；bridge v1.12）。全包檔案指紋見 `RELEASE_SHA256.txt`。

## 前置（裝之前先確認三件事）

1. **macOS**＋**python3 ≥ 3.9**（`python3 --version`；bridge 零第三方套件，不用 pip）
2. **Claude Code CLI** 已裝且登入（`claude --version`；值台引擎，憑證=你自己的訂閱）
3. **Tailscale** 已裝且登入（`tailscale status`；webhook 公網中繼，免費方案可用）

## 五步安裝

### 第 1 步：跑安裝器

```
python3 install.py --owner 你的稱呼 --agent-name 值台名 --slug 小寫代號 --port 8700
```

例：`python3 install.py --owner 小明 --agent-name 小幫手 --slug xiaobang --port 8700`
它會建好 `~/.{slug}/` 全部結構、載入 launchd 常駐、跑 selftest、印出人類動作清單。
（冪等可重跑；既有 secrets 與身分檔絕不覆蓋。）

### 第 2 步：申請 LINE channel＋填金鑰

照 `docs/LINE_Developers_申請教學.md` 走到第三步——
拿到兩把金鑰填進 `~/.{slug}/config/secrets/line_secrets.env`。
（bridge 在金鑰填齊前會 fail-closed 待命，填完 launchd 自動把它帶活。）

### 第 3 步：開公網中繼

```
tailscale funnel --https=443 8700
```

抄下顯示的 `https://….ts.net/` 網址。

### 第 4 步：貼 webhook URL

LINE Developers console → Messaging API → Webhook URL 填 `https://….ts.net/callback`
→ Verify（應 Success）→ Use webhook 開啟（建議 Webhook redelivery 也開）。

### 第 5 步：認主＋首測

手機掃 bot QR code 加好友 → 傳「我是{你的稱呼}」→ 回「登記完成」
→ 再傳一句話收到回覆 ＝ **通道 GREEN**。

## 驗收定義

新機從零到通道活著 ≤ 30 分鐘、人類動作 ≤ 6 步＝GREEN。沒過就開 `docs/TROUBLESHOOTING.md`（九類坑，全是前人實戰換的）。

## 包內導覽

| 路徑 | 內容 |
|---|---|
| `install.py` | 一鍵安裝器（參數收集→展開→launchd→selftest） |
| `core/` | 接收站＋四工具（全部讀 config，零站點硬編碼） |
| `templates/` | 身分檔母版（插槽）／secrets 空殼／launchd plist／通道專屬段模板 |
| `docs/` | 申請教學／架構圖／TROUBLESHOOTING／迭代史摘要 |
| `RELEASE_SHA256.txt` | 全包指紋（收到包先驗這個） |

## 日常維運速查

- 值台身分微調：改 `~/.{slug}/CLAUDE.md`（各通道自動傳導；通道專屬段見 `config/channel_discipline_參考.md`）
- 本體回報：`python3 ~/.{slug}/tools/relay_say.py "話"`（免費）；急件 `line_push.py`（吃額度）
- 任務驗章：`python3 ~/.{slug}/tools/task_verify.py`；積壓偵測：`queue_backlog_check.py check`
- 改碼部署：改檔 → `python3 -m py_compile` → `kill <bridge PID>` → launchd 4 秒自動重生
