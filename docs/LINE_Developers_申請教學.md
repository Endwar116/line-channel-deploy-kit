# LINE Developers 申請教學（文字版圖文步驟）

> 目標：拿到兩把金鑰（Channel secret／Channel access token）＋把 webhook URL 指到你的機器。
> 全程免費（LINE 官方帳號輕用量方案 $0；push 200 則/月，reply 不限量）。

## 第一步：LINE Official Account（官方帳號）

1. 開 https://entry.line.biz/ → 用你自己的 LINE 帳號登入
2. 「建立 LINE 官方帳號」→ 帳號名稱填你想要的 bot 顯示名（例：你的值台 agent 名）
3. 類別隨意選（個人/其他即可），完成建立
4. 進入 LINE Official Account Manager（manager.line.biz）→ 設定 → 回應設定：
   - 「聊天」關閉（Chat off）
   - 「Webhook」開啟
   - 「自動回應訊息」關閉（不關的話官方罐頭訊息會跟你的 bot 搶話）

## 第二步：Messaging API channel

1. 開 https://developers.line.biz/console/ → 同帳號登入
2. 若尚無 Provider：Create Provider（名字隨意，例：你的名字）
3. 在官方帳號管理頁（manager.line.biz → 設定 → Messaging API）按「啟用 Messaging API」，
   綁定剛才的 Provider——這會把官方帳號變成一個 Messaging API channel
4. 回到 developers console → 你的 Provider → 點進該 channel

## 第三步：抄兩把金鑰

1. 「Basic settings」頁 → **Channel secret**（32 字 hex）→ 填進 `config/secrets/line_secrets.env` 的 `LINE_CHANNEL_SECRET=`
2. 「Messaging API」頁 → **Channel access token (long-lived)** → 按 **Issue** → 整串抄下 → 填 `LINE_CHANNEL_ACCESS_TOKEN=`
3. 紅線：這兩個值不貼給任何人、任何 AI、任何聊天視窗；檔案權限 600（install.py 已設）

## 第四步：公網中繼（Tailscale Funnel）

bridge 只監聽本機 127.0.0.1，LINE 的 webhook 需要公網 HTTPS——用 Tailscale Funnel 免費中繼：

1. 裝 Tailscale：https://tailscale.com/download（登入你的帳號；免費方案即可）
2. 終端機執行：`tailscale funnel --https=443 8700`（port 換成你安裝時選的）
3. 執行後會顯示你的公網網址：`https://<機器名>.<尾巴>.ts.net/`——抄下來
4. 注意：`.ts.net` 憑證會上公開的 CT log＝這網址可能被掃描到。不用怕：bridge 對每個請求驗 LINE 簽章，驗不過一律 403

## 第五步：webhook 填注＋驗證

1. developers console → 該 channel →「Messaging API」頁 → Webhook settings
2. **Webhook URL** 填：`https://<你的節點>.ts.net/callback`（注意結尾 /callback）
3. 按 **Verify** → 應顯示 Success（bridge 需已在跑；沒過見 TROUBLESHOOTING）
4. **Use webhook** 開關打開
5. 建議同頁把 **Webhook redelivery** 也打開（漏接補投；bridge 有去重，不會重複執行）

## 第六步：認主與首測

1. 「Messaging API」頁有 bot 的 QR code → 手機掃碼加好友
2. 傳認主口令（安裝時設定的「我是◯◯」）→ 收到「登記完成」＝你的 userId 已入白名單
3. 再傳任意一句話 → 收到回覆＝通道全線 GREEN

## 金鑰輪替（外洩疑慮時）

console → Messaging API → access token 按 Issue 重發（舊 token 即作廢）→ 更新 line_secrets.env → bridge 重啟（launchd：`kill <bridge PID>` 會自動帶新值重生）。
