# AGENT_SETUP — 給 agent 的環境建立指南

> 你是被派來建環境的 agent。照做，不要自由發揮，不要跳步。
> 你只負責建立環境。金鑰與 LINE 後台由人類親手操作。

## 三條鐵則

1. `config/secrets/` 與 `~/.{slug}/config/secrets/` 底下任何檔案：**不讀、不印、不 cat、不猜內容**。
2. 每一步做完先驗證再往下。驗證失敗＝停下來，把錯誤原文回報人類，並開 `docs/TROUBLESHOOTING.md` 對照。
3. 這個 repo 就是全部所需，不要另外下載任何東西、不要 pip install 任何套件。

## 步驟

### 第 1 步：前置檢查

```
python3 --version    # 需 ≥ 3.9，不足請人類升級
tailscale version    # 沒裝＝請人類到 https://tailscale.com/download 裝好並登入
```

### 第 2 步：問人類三個參數

- `owner`＝主人的稱呼（之後認主口令＝「我是{owner}」）
- `agent-name`＝值台的名字（LINE 上顯示的人格名）
- `slug`＝小寫英文代號（家目錄會建 `~/.{slug}/`）

### 第 3 步：跑安裝器

```
python3 install.py --owner {owner} --agent-name {agent-name} --slug {slug} --port 8700
```

冪等可重跑；既有 secrets 與身分檔不會被覆蓋。
結束時 selftest 要全過，並把它印出的「人類動作清單」整理給人類看。

### 第 4 步：🛑 停——人類動作（填金鑰）

請人類照 `docs/LINE_Developers_申請教學.md` 第一～三步拿兩把金鑰，
親手填進 `~/.{slug}/config/secrets/line_secrets.env`（用文字編輯器，不經過你）。
你在這一步只做一件事：等人類說「填好了」。

### 第 5 步：確認接收站活著

```
curl -s -o /dev/null -w "%{http_code}" http://localhost:8700/
```

金鑰填齊後 launchd 會自動把 bridge 帶活，應回 200。
沒回應＝等 10 秒再試一次；仍失敗走 TROUBLESHOOTING「launchd 類」。

### 第 6 步：開公網中繼

```
tailscale funnel --https=443 8700
```

把顯示的 `https://….ts.net/` 網址交給人類。這個指令會持續佔住終端機屬正常；
背景常駐版：`tailscale funnel --bg --https=443 8700`。

### 第 7 步：🛑 停——人類動作（LINE 後台）

請人類照 `docs/LINE_Developers_申請教學.md` 第五步：
Webhook URL 填 `https://….ts.net/callback`（結尾必須是 /callback）
→ Verify 顯示 Success → Use webhook 開啟（建議 Webhook redelivery 也開）。

### 第 8 步：首測（GREEN 判定）

人類手機掃 bot QR code 加好友
→ 傳「我是{owner}」→ 收到「登記完成」
→ 再傳任意一句 → 收到回覆＝**通道 GREEN，任務完成**。

## 完成後回報格式

跟人類回報四行：
1. selftest 結果
2. bridge HTTP 狀態碼
3. funnel 網址
4. GREEN 與否；沒 GREEN 附卡住的步驟編號與錯誤原文
