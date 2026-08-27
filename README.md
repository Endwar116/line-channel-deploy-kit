# LINE Channel Deploy Kit

把一個 LINE 官方帳號，變成你的 AI 值台（macOS）。
新機從零到通道活著 ≤ 30 分鐘，零第三方套件（python3 標準庫）。

## 快速開始（人類看這裡就夠）

對你機器上的 AI agent（例如 Claude Code）說一句：

```
clone https://github.com/Endwar116/line-channel-deploy-kit 到家目錄，
然後照裡面的 AGENT_SETUP.md 一步一步做，不要自由發揮。
```

接下來 agent 會自己建環境，只在兩個地方停下來請你動手：

1. **填金鑰**：照 `docs/LINE_Developers_申請教學.md` 拿兩把金鑰，親手貼進設定檔（agent 全程不碰金鑰）
2. **LINE 後台**：把 webhook 網址貼進 LINE Developers console、按 Verify

最後手機掃 QR 加好友、傳認主口令，收到回覆＝通道上線。

## 安全設計

- **金鑰不進 repo、不給 agent 讀**：`config/secrets/` 由安裝器建成空殼（權限 600），人類親手填
- **fail-closed**：金鑰沒填齊，接收站待命不對外
- **簽章驗證**：每個進站請求驗 LINE 官方 HMAC 簽章，驗不過一律拒絕
- **零第三方依賴**：不裝 pip 套件，少一整層供應鏈風險

## 包內導覽

| 路徑 | 內容 |
|---|---|
| `AGENT_SETUP.md` | 給 agent 的逐步安裝指南（含兩個人類動作停點） |
| `00_START_HERE.md` | 人類版五步總覽 |
| `install.py` | 一鍵安裝器（冪等可重跑） |
| `core/` | 接收站（bridge）＋四個維運工具 |
| `templates/` | 身分檔／secrets 空殼／launchd 模板 |
| `docs/` | LINE 申請教學／架構圖／TROUBLESHOOTING（九類實戰坑） |

## 授權與出身

由 IMCC 通道工程實戰迭代而來（bridge v1.12 凍結版）。歡迎自用與改作。
