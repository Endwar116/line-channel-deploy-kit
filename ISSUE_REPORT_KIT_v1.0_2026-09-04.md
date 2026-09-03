# LINE Channel Deploy Kit v1.0 部署缺陷報告

**一次完整部署歷程的實證分析，含四項缺陷之根因、影響評估與修補建議**

| 項目 | 內容 |
|---|---|
| 報告日期 | 2026-09-04 |
| 受測產品 | LINE Channel Deploy Kit（宣稱 KIT v1.0／bridge v1.12） |
| 產品來源 | https://github.com/Endwar116/line-channel-deploy-kit |
| 受測版本 | commit `0ee7e07d865404aad6c45c5af5d5c803a2c1e863`（2026-08-28 02:05 +08:00） |
| 部署者 | Jesse Lin（fwym0.01@gmail.com） |
| 部署情境 | 商業用途——正式營運之 LINE 官方帳號 |
| 部署結果 | **未達成產品定義之 GREEN 驗收** |
| 報告性質 | 缺陷回報與修補建議，非求償文件 |

---

## 摘要

本報告記錄一次完整的 LINE Channel Deploy Kit v1.0 部署歷程。部署環境完全符合產品所列之三項前置條件，
部署者具備相關技術背景，並全程依產品文件（`00_START_HERE.md`、`AGENT_SETUP.md`、`docs/TROUBLESHOOTING.md`）
逐步操作，未自行變更任何流程。

部署歷時 66 分鐘後仍未達成產品所定義之 GREEN 驗收標準（產品宣稱「新機從零到通道活著 ≤ 30 分鐘、
人類動作 ≤ 6 步」）。實際所需之人類動作已達 7 步以上且流程尚未完成。

過程中確認六項缺陷：

| 編號 | 缺陷 | 性質 | 阻斷性 |
|---|---|---|---|
| A | `RELEASE_SHA256.txt` 對核心檔 `core/line_bridge.py` 之指紋錯誤 | 出廠品質 | 否，但使產品之完整性驗證機制失效 |
| B | 前置條件清單遺漏 Tailscale Funnel 之兩項必要後台設定 | 文件缺漏 | **是**，第 3 步必然失敗 |
| C | README 首要承諾之「AI agent 無人值守建置」在主流 agent 預設安全策略下不可執行 | 設計假設 | **是**，第 3 步必然中斷 |
| D | 缺乏公網可達性驗證步驟，且既有診斷指引在故障時給出假陽性結論 | 文件與診斷設計 | **是**，故障時無法脫困 |
| E | `empty_mcp.json` 為 `{}`，不合現行 Claude Code schema，所有訊息無條件失敗 | 相容性缺陷 | **是**，核心功能完全不可用 |
| F | 安裝流程未涵蓋本體側設定，GREEN 後任務功能仍完全未接通且靜默失效 | 流程完整性 | **是**，核心賣點不運作 |

四項缺陷共享同一結構性成因：**產品全篇缺乏「外部視角」的驗證機制**。所有驗證步驟均在部署機本機執行，
而部署機因位於 Tailscale 網路內，其驗證結果與外部服務（LINE 平台）所見之狀態系統性地不一致。

本報告第 6 節提供四項缺陷之具體修補建議，包含可直接採用之文件文字與檢查指令。

---

## Abstract (English)

This report documents a complete deployment of LINE Channel Deploy Kit v1.0 on a fully conforming
environment (macOS 26.6.2, Python 3.9.6, Claude Code 2.1.208, Tailscale 1.102.3), following the
vendor documentation without deviation. The deployment did not reach the vendor-defined GREEN
acceptance state after 56 minutes, against a stated target of ≤30 minutes and ≤6 human actions;
the actual human-action count exceeded 7 with the process still incomplete.

Four defects were confirmed: (A) the published SHA-256 manifest does not match the shipped
`core/line_bridge.py`, defeating the kit's own integrity-verification instruction; (B) the
prerequisite checklist omits two mandatory Tailscale console settings required for Funnel;
(C) the README's headline promise of unattended AI-agent installation is not executable under the
default security policy of the very agent it names; and (D) the kit provides no external-vantage
reachability check, while its documented diagnostic command returns a false-positive "green" during
the exact failure it is meant to diagnose.

All four share a common root: the kit verifies only from inside the deployment host, whose view of
the network differs systematically from that of the external service it must serve.

---

## 1. 前言

### 1.1 報告目的

本報告之目的為協助產品維護者定位並修正缺陷，而非追究責任。所有結論均附可獨立重現之指令與原始輸出，
維護者可在自有環境中逐項驗證。

### 1.2 為何值得撰寫

本產品之核心價值主張為「降低部署門檻」——宣稱新機從零到通道活著 ≤ 30 分鐘、人類動作 ≤ 6 步，
並將安裝工作委由 AI agent 執行。此類主張的成立與否，取決於「非理想路徑」上的表現：
當第三方服務延遲、當執行環境的安全策略與預期不符、當某個記錄尚未同步時，
產品能否讓部署者**知道自己卡在哪裡**。

本次部署中，四項缺陷有三項並非發生在產品的核心邏輯（安裝器與 bridge 的程式碼品質良好，
selftest 設計完善，fail-closed 機制經實測確實有效），而是發生在**產品對外部世界的假設**與
**故障時的可觀測性**上。這正是此類「一鍵部署包」最容易失守、也最值得強化的部分。

### 1.3 應予肯定之處

為求評價之公允，先陳明本次部署中表現良好的設計：

1. **金鑰隔離徹底**：`config/secrets/` 由安裝器建為空殼並設定權限 600，全程由人類親手填入。
   本次部署使用 AI agent 協助，agent 全程未讀取、未複製、未傳輸任何金鑰內容，該設計確實生效。
2. **fail-closed 確實有效**：金鑰填入前 bridge 拒絕啟動，launchd 每 10 秒重試並留下明確日誌
   （`secrets 缺 LINE_CHANNEL_SECRET——拒絕啟動（fail-closed）`），行為與文件描述完全一致。
3. **簽章驗證正確**：對 `/callback` 發送無簽章之 POST 請求，正確回應 403。
4. **安裝器冪等性與 selftest 設計良好**：輸出清晰，關鍵項與非關鍵項區分得當，
   `port 8700 監聽` 一項正確地判為 WARN 而非 FAIL，並附上成因說明。
5. **零第三方依賴**：確認全程未安裝任何 pip 套件，供應鏈風險確實降低。

本報告所列之缺陷，均不涉及上述設計。

---

## 2. 受測環境與方法

### 2.1 環境

| 項目 | 版本／值 | 是否符合產品前置要求 |
|---|---|---|
| 作業系統 | macOS 26.6.2（Build 25G83） | ✅ 要求 macOS |
| Python | 3.9.6（`/usr/bin/python3`） | ✅ 要求 ≥ 3.9 |
| Claude Code CLI | 2.1.208（`~/.local/bin/claude`），已登入 | ✅ 要求已裝且登入 |
| Tailscale | 1.102.3（`/usr/local/bin/tailscale`），已登入 | ✅ 要求已裝且登入 |
| 監聽埠 | 8700，部署前確認未被佔用 | ✅ |
| 網路 | IPv4 + IPv6 皆可用，無 CGNAT 限制，無 captive portal | — |
| Tailnet 權限 | 部署者為 tailnet owner + admin | — |

安裝參數：`--owner 昱捷 --agent-name 昱捷助理 --slug yujie --port 8700`

**環境完全符合產品所列之全部前置條件**，可排除「使用者環境不符」作為缺陷成因。

### 2.2 驗證方法

本報告採用之驗證原則為**內外視角分離**：凡涉及公網可達性之判斷，一律至少取得一個
部署機以外的觀測點，不以部署機自身的測試結果作為結論。具體工具：

- DNS：`dig` 對四台 `ts.net` 權威 NS 逐一查詢，另對多家公共遞迴解析器（1.1.1.1、8.8.8.8、
  9.9.9.9、208.67.222.222）交叉比對；並以 Google／Cloudflare 的 DoH HTTP API 作為第三方路徑驗證。
- HTTP：`curl --resolve` 強制指定公網 ingress 位址，繞開部署機的 MagicDNS 解析；
  另以完全在部署機以外執行之 HTTP 擷取工具取得獨立觀測點。
- TLS：`openssl s_client` 檢視實際簽發之憑證主體、簽發者、效期與 SAN。
- 完整性：`shasum -a 256` 比對工作區檔案，並以 `git cat-file` 比對 git 物件庫內容，
  以區分「傳輸過程竄改」與「上游發布時即已不符」。

### 2.3 資料採集原則

所有輸出均為當下實際執行結果，未經潤飾。涉及金鑰之檔案（`config/secrets/` 下所有檔案）
全程未讀取，僅檢視其 metadata（權限、大小）。

---

## 3. 完整部署時間軸

| 時間 | 事件 | 對應步驟 |
|---|---|---|
| 01:23 | 取得產品（git clone 完成） | — |
| 01:23–01:29 | 前置檢查；**發現缺陷 A**（指紋不符） | AGENT_SETUP 第 1 步 |
| 01:25 | AI agent 執行安裝器 → 被權限層拒絕（第一次） | AGENT_SETUP 第 3 步 |
| 01:26 | 移除 launchd 步驟（`--skip-launchd`）再試 → 仍被拒絕；**確認缺陷 C** | AGENT_SETUP 第 3 步 |
| 01:40 | 部署者於 Tailscale 後台啟用 HTTPS Certificates；**確認缺陷 B 第一項** | 文件未載之步驟 |
| 01:48 | 部署者授權節點 Funnel 屬性；**確認缺陷 B 第二項** | 文件未載之步驟 |
| 01:45 | 部署者改以手動於終端機執行安裝器 → **成功**，selftest 關鍵項全綠 | AGENT_SETUP 第 3 步 |
| 01:50:29 | 金鑰填入後 bridge 首次成功啟動；本機 HTTP 200 | AGENT_SETUP 第 4–5 步 |
| 01:52 | `tailscale funnel --bg --https=443 8700` → CLI 回報成功 | AGENT_SETUP 第 6 步 |
| 01:56 | 四台權威 NS 查無 A/AAAA 記錄 | — |
| 01:58 | **第一次 LINE Verify 失敗**：`A domain name that can't be resolved...` | AGENT_SETUP 第 7 步 |
| 01:59 | funnel off → on 重新註冊 | — |
| 02:01 | 記錄仍未出現 | — |
| 02:05 | A 記錄出現於 4 台 NS 中之 3 台；AAAA 4 台皆有 | — |
| 02:07 | 量測對外解析成功率：`dig @1.1.1.1` 連續 12 次，成功 6 次（失敗率 50%） | — |
| 02:14 | **第二次 LINE Verify 失敗**：`An invalid host was used for the webhook URL.` | AGENT_SETUP 第 7 步 |
| 02:17 | 持續監測判定：`ns1.dnsimple.com` 之 A 記錄缺失為穩定狀態，非傳播延遲 | — |
| 02:19 | 撰寫本報告初版；**仍未達 GREEN** | — |
| 02:24 | 持續監測：`ns1` 仍未同步（已 15 分鐘） | — |
| 02:29 | 執行逐段鏈路檢查，確立單一故障點（見附錄 D）；funnel 啟用後 37 分鐘仍未同步 | — |

**歷時 66 分鐘（01:23–02:29），未達成 ≤ 30 分鐘之驗收標準，且流程仍未完成。**

### 3.1 人類動作步數實測

產品宣稱「人類動作 ≤ 6 步」。本次部署實際發生之人類動作：

| # | 動作 | 文件是否載明 |
|---|---|---|
| 1 | 於 Tailscale 後台啟用 HTTPS Certificates | ❌ 未載明（缺陷 B） |
| 2 | 授權節點 Funnel 屬性 | ❌ 未載明（缺陷 B） |
| 3 | 手動於終端機執行安裝器 | ❌ 文件預期由 agent 執行（缺陷 C） |
| 4 | 填入兩把金鑰 | ✅ 載明 |
| 5 | 貼上 webhook URL 並按 Verify（已失敗 2 次） | ✅ 載明 |
| 6 | 於 LINE Official Account Manager 關閉自動回應訊息 | ✅ 載明 |
| 7 | 加好友、傳認主口令、首測 | ✅ 載明（**尚未執行，因第 5 步未通過**） |

**已達 7 步且流程未完成**，超出宣稱之 ≤ 6 步。

---

## 4. 缺陷發現

### 4.1 缺陷 A — 發布指紋與實際檔案不符

**嚴重度**：高（安全機制失效）　**阻斷性**：否　**發生步驟**：取得產品後之第一道驗證

#### 4.1.1 產品之明文指示

`00_START_HERE.md` 包內導覽章節：

> `RELEASE_SHA256.txt` ｜ 全包指紋（**收到包先驗這個**）

同檔檔頭亦載明：「全包檔案指紋見 `RELEASE_SHA256.txt`」。

#### 4.1.2 觀察

全包 16 個受列檔案中，15 個相符，`core/line_bridge.py` 不符：

```
RELEASE_SHA256.txt 記載：
  6d4e7f6364f5ddd43162f0bf7ffb74fd0d216c988f5ee1f9155d4dc3a1609ad2  ./core/line_bridge.py

實際檔案：
  67014afa1c3f024129e0064a6e0e8c36126848da611a7421d2901e4e35a97840  core/line_bridge.py
```

#### 4.1.3 根因（已排除傳輸竄改）

git 物件庫中之 blob 與工作區檔案完全一致，證明差異源自上游發布本身：

```
$ git cat-file -p HEAD:core/line_bridge.py | shasum -a 256
67014afa1c3f024129e0064a6e0e8c36126848da611a7421d2901e4e35a97840  -
```

且兩個檔案係於**同一 commit** 加入 repo：

```
$ git log --format='%h %s' --diff-filter=A -- core/line_bridge.py RELEASE_SHA256.txt
cd7d267 LINE Channel Deploy Kit v1.0 - public sanitized release (bridge v1.12 frozen)
```

推定成因：於製作 public sanitized release 時修改了 `core/line_bridge.py`，
但未重新產生 `RELEASE_SHA256.txt`。指紋檔在出廠當下即為錯誤。

#### 4.1.4 影響

1. 任何依產品指示「收到包先驗這個」的部署者，第一道步驟即得到驗證失敗。
2. **產品之完整性驗證機制對唯一的核心檔失效**。`core/line_bridge.py` 為 877 行之接收站主程式，
   負責驗證 LINE 官方 HMAC 簽章、決定請求接受與否、並以使用者身分 spawn Claude CLI 子行程。
   指紋檔存在之唯一目的即為分辨此檔是否遭竄改；當它對此檔恆為失敗時，
   部署者無從區分「維護者未重算」與「檔案確實遭植入」。
3. 產品 README 設有「安全設計」專章作為賣點，本缺陷直接損及該章之可信度。

---

### 4.2 缺陷 B — 前置條件遺漏 Tailscale Funnel 之兩項必要設定

**嚴重度**：高　**阻斷性**：是　**發生步驟**：`AGENT_SETUP.md` 第 6 步 ／ `00_START_HERE.md` 第 3 步

#### 4.2.1 產品之明文說法

`00_START_HERE.md` 前置條件第 3 條：

> **Tailscale** 已裝且登入（`tailscale status`；webhook 公網中繼，免費方案可用）

`AGENT_SETUP.md` 第 1 步之檢查指令僅有：

```
tailscale version    # 沒裝＝請人類到 https://tailscale.com/download 裝好並登入
```

兩份文件與 `docs/TROUBLESHOOTING.md` 均未提及任何 Tailscale 後台設定需求。

#### 4.2.2 觀察

「已裝且登入」並不足以執行 `tailscale funnel`。本機於前置檢查時之狀態：

```
CertDomains: None                    ← HTTPS Certificates 未啟用
節點能力清單中 funnel 相關項目：[]     ← 節點未取得 funnel 屬性
```

#### 4.2.3 遺漏之必要條件

1. **HTTPS Certificates**：須於 Tailscale admin console → DNS 頁啟用。
   未啟用則無法為 `*.ts.net` 簽發憑證，`tailscale funnel --https=443` 無法運作。
2. **節點 funnel 屬性**：須於 ACL policy 之 `nodeAttrs` 授予，或於首次執行時
   點擊 CLI 印出之授權連結。未授予則指令直接拒絕。

補做後之狀態變化，證實兩者皆為硬性前置條件：

```
補做前：CertDomains: None          ／ funnel 能力：[]
補做後：CertDomains: ['<你的節點>.ts.net']
        funnel 能力：['funnel', 'https://tailscale.com/cap/funnel-ports?ports=443,8443,10000']
```

#### 4.2.4 影響

依文件操作之部署者，會在第 6 步（開 Funnel）遭遇硬中斷，且文件三處
（前置清單、AGENT_SETUP 檢查指令、TROUBLESHOOTING 九類坑）均無對應指引，
須自行至外部尋找解法。此與「人類動作 ≤ 6 步」之驗收承諾直接衝突——
本項即為實測中額外增加的第 1、2 步。

---

### 4.3 缺陷 C — 「AI agent 無人值守建置」之承諾在主流 agent 預設安全策略下不可執行

**嚴重度**：中高　**阻斷性**：是　**發生步驟**：`AGENT_SETUP.md` 第 3 步

#### 4.3.1 產品之明文承諾

`README.md` 之「快速開始（人類看這裡就夠）」章節：

> 對你機器上的 AI agent（例如 Claude Code）說一句：
> 「clone … 然後照裡面的 AGENT_SETUP.md 一步一步做，不要自由發揮。」
> 接下來 agent 會自己建環境，**只在兩個地方停下來請你動手**

此為 README 置頂之首要價值主張，且明確點名 Claude Code。

#### 4.3.2 觀察

以 Claude Code 2.1.208（預設 auto mode）執行安裝器，權限分類器連續兩次拒絕：

```
$ python3 install.py --owner 昱捷 --agent-name 昱捷助理 --slug yujie --port 8700 --yes
→ Permission for this action was denied by the Claude Code auto mode classifier.
  Reason: Blocked by classifier.

$ python3 install.py ... --skip-launchd --yes      （已主動移除 launchd 常駐步驟）
→ Permission for this action was denied by the Claude Code auto mode classifier.
  Reason: Blocked by classifier.
```

第二次已將操作範圍縮減為「僅寫入 `~/.yujie/` 之檔案」，仍遭拒絕。

#### 4.3.3 對照實驗：安裝器本身無缺陷

**同一條指令**改由部署者手動於終端機執行，一次成功，selftest 關鍵項全綠：

```
✅ PASS  依賴 import（stdlib）＋python>=3.9   3.9.6
✅ PASS  簽章驗證器自測（正簽收/偽簽拒）      HMAC-SHA256+b64
✅ PASS  secrets 檔存在                       待填：LINE_CHANNEL_SECRET,LINE_CHANNEL_ACCESS_TOKEN
✅ PASS  任務簽章鍵存在                       600
✅ PASS  bridge py_compile
⚠️ WARN  port 8700 監聽                       已載入但未監聽（secrets 未填，fail-closed）
✅ PASS  指令 claude                          /Users/jlin/.local/bin/claude
✅ PASS  指令 tailscale                       /usr/local/bin/tailscale
```

**此對照實驗確立了缺陷的邊界**：問題不在安裝器的程式碼品質，而在產品對 agent 執行環境的假設。

#### 4.3.4 成因分析（力求公允）

被拒絕之行為特徵為「執行一個剛從網際網路下載、未經審查的第三方腳本」，
且該腳本會安裝 launchd 常駐服務。此為 AI coding agent 安全機制之**正常且正確的運作**，
不應視為 Claude Code 之缺陷。

問題在於：**產品將「agent 可無人值守執行下載而來的安裝腳本」設定為理所當然的前提**，
而主流 agent 的預設安全策略恰好禁止此行為。README 之首要承諾因此在預設環境下不成立。

#### 4.3.5 影響

1. 產品最主要的差異化價值（AI agent 自動化部署）在預設環境下無法兌現。
2. 部署者被迫二擇一：降低 agent 的安全防護等級，或改為手動執行——後者使該價值主張歸零。
3. `docs/TROUBLESHOOTING.md` 之九類坑完全未涵蓋此情境，遭遇者無排除指引。
4. 出現了 README 明文承諾之外的**第三個停止點**。

---

### 4.4 缺陷 D — 缺乏公網可達性驗證，且既有診斷指引於故障時給出假陽性

**嚴重度**：高　**阻斷性**：是　**發生步驟**：`AGENT_SETUP.md` 第 6 步與第 7 步之間

本缺陷為本次部署最終未達 GREEN 之直接原因，亦為四項缺陷中影響最深者。

#### 4.4.1 觸發本缺陷的外部事件（非供應商責任）

`tailscale funnel` 執行成功後，主機名之公網 DNS 記錄僅同步至 `ts.net` 四台權威 NS 中之三台。
`ns1.dnsimple.com` 於觀測期間（30 分鐘以上）穩定缺少 A 記錄：

```
                          AAAA(IPv6)                          A(IPv4)
ns1.dnsimple.com          ✅ 2403:2500:400:20::25a, ::e8e      ❌ 無（連續查詢 4 次皆空）
ns2.dnsimple-edge.net     ✅ 同上                              ✅ 103.84.155.153, .217
ns3.dnsimple.com          ✅ 同上                              ✅ 同上
ns4.dnsimple-edge.org     ✅ 同上                              ✅ 同上

四台之 SOA serial 均為 1627495866（相同）→ 自稱已同步，實際資料不一致
對照組 hello.ts.net 於四台皆正常 → 排除「ns1 整台故障」
```

實測對外解析成功率：

```
dig @1.1.1.1 連續 12 次 → 成功 6 次、失敗 6 次（失敗率 50%）
dig @8.8.8.8 連續 12 次 → 成功 12 次（該解析器恰快取到正解，TTL 300 秒後重新輪詢）
```

**此為 Tailscale／DNSimple 端之 DNS 同步問題，明確不屬本 KIT 之缺陷，亦非部署者設定錯誤。**
本節列出僅為說明缺陷 D 的觸發條件。

此外部事件亦解釋了兩次 LINE 錯誤訊息之差異：AAAA 記錄同步完整而 A 記錄不完整，
故 LINE（其 webhook 發送端推定為純 IPv4）由「無法解析網域」轉為「主機存在但無可用位址」：

```
第一次（01:58）：A domain name that can't be resolved or an incorrect parameter or value...
第二次（02:14）：An invalid host was used for the webhook URL.
```

#### 4.4.2 缺陷本體之一：文件之診斷指引在此故障下給出假陽性

`docs/TROUBLESHOOTING.md`「第 2 類：Verify 按了失敗／訊息完全進不來」第 3 點：

> 3. bridge 活著但 Verify 失敗 → Funnel 沒起或 URL 抄錯：`tailscale funnel status` 查；
>    URL 結尾必須是 `/callback`

此為文件針對本次症狀所指定之唯一檢查方法。實際執行結果：

```
$ tailscale funnel status
# Funnel on:
#     - https://<你的節點>.ts.net
https://<你的節點>.ts.net (Funnel on)
|-- / proxy http://127.0.0.1:8700
```

**回報「Funnel on」——完全正常的綠燈，而該端點在公網上正有 50% 機率無法解析。**

依文件操作之部署者，將據此排除 Funnel 因素，轉而懷疑「URL 抄錯」；
而 URL 完全正確，遂陷入在正確設定上反覆重試的無解迴圈。

**這並非「缺少指引」，而是指引本身將部署者導向錯誤結論。**

#### 4.4.3 缺陷本體之二：本機自測必然產生假陽性，且文件未予警告

部署機位於 Tailscale 網路內，MagicDNS 會將同一主機名解析至**內網位址**，而非公網 Funnel 路徑：

```
（部署機上執行 —— 看似完全成功）
$ dig +short <你的節點>.ts.net
100.82.211.97                                   ← 內網 CGNAT 位址
$ curl -o /dev/null -w "%{http_code}" https://<你的節點>.ts.net/
200                                             ← 走的是內網，與 LINE 的路徑無關

（同一時刻，外部視角）
$ dig @8.8.8.8 A <你的節點>.ts.net
（無記錄）
```

任何在部署機上進行連通性自測的部署者——**包含依 `AGENT_SETUP.md` 操作的 AI agent**——
都會取得 HTTP 200 的假陽性，據此判定「公網鏈路已通」並放行至下一步，
直至 LINE 端 Verify 失敗方才察覺；而此時文件的診斷路徑又如 4.4.2 所述指向錯誤方向。

本報告撰寫過程中，協助部署的 AI agent 本身即先落入此陷阱，於部署機上取得 200 後
作出「公網鏈路全通」之錯誤結論，其後才經由外部觀測點自行更正。此可作為該陷阱普遍性之佐證。

#### 4.4.4 缺陷本體之三：第 6 步與第 7 步之間缺少驗證關卡

`AGENT_SETUP.md` 第 6 步（開 Funnel）與第 7 步（貼 webhook URL 並 Verify）之間，
文件無任何等待、確認或驗證之指示。Funnel 公網 DNS 記錄之建立本質上為非同步操作，
需時數分鐘至十餘分鐘不等；在此必然存在的時間窗內依文件操作，Verify 必然失敗。

產品全篇（`00_START_HERE.md`、`AGENT_SETUP.md`、`docs/TROUBLESHOOTING.md`）
**未提供任何一個能反映外部視角的驗證步驟**。

#### 4.4.5 影響

在一個**必然會發生**的時間窗內，產品提供了兩個都會給出錯誤結論的診斷方法
（`tailscale funnel status` 假綠燈；本機 curl 假陽性），且未提供任何能給出正確結論的方法。
部署者除非具備 DNS 除錯經驗並主動查詢權威 NS，否則無法定位問題。

---

### 4.5 缺陷 E — `empty_mcp.json` 格式不相容於現行 Claude Code，導致所有訊息無條件失敗

**嚴重度**：最高（產品核心功能完全不可用）　**阻斷性**：是　**發生步驟**：`AGENT_SETUP.md` 第 8 步（首測）

本缺陷為五項中唯一使產品**核心功能完全無法運作**者。前述四項均為流程或文件問題，
本項則是：即使部署者克服了 A 至 D 全部障礙、通道完全建立、認主成功，
**bot 仍無法回覆任何一則訊息**。

#### 4.5.1 現象

通道建立完成、LINE Verify 通過、認主口令成功後，對 bot 發送任何訊息，
一律收到固定回覆：

```
（本體呼叫失敗，稍後再試或檢查 line_bridge.log）
```

#### 4.5.2 證據

```
2026-09-04T02:53:57+08:00 OWNER_REGISTERED Ua4adbf632c5b059b8ff1ade9f20a43f2
2026-09-04T02:54:27+08:00 MSG_IN dm:Ua4adbf632c5 owner '那我們要如何開始？'
2026-09-04T02:54:43+08:00 CONTINUE_MISS rc=1——開新對話 (dm)
2026-09-04T02:54:47+08:00 CLAUDE_ERROR rc=1 stderr=Error: Invalid MCP configuration:
                          mcpServers: Does not adhere to MCP server configuration schema
2026-09-04T02:54:47+08:00 REPLIED len=32
```

認主流程（`OWNER_REGISTERED`）與訊息接收（`MSG_IN`）皆正常，
失敗發生在 bridge spawn Claude CLI 的環節。

#### 4.5.3 根因

`install.py` 產生的 MCP 設定檔內容為空物件：

```python
put(os.path.join(base, "config", "empty_mcp.json"), "{}\n",
    skip_if_exists=True, label="config/empty_mcp.json")
```

`core/line_bridge.py` 於每次 spawn 時將此檔以 `--strict-mcp-config` 帶入：

```python
extra = ["--strict-mcp-config", "--mcp-config",
         os.path.join(ROOM, "config", "empty_mcp.json")]
```

現行 Claude Code（實測 2.1.208）要求該設定檔必須具備 `mcpServers` 鍵，
空物件 `{}` 無法通過 schema 驗證，CLI 以 rc=1 結束。
由於 bridge 的兩條 spawn 路徑（`-c` 續接與開新對話）使用相同參數，
**兩條路徑皆必然失敗**，故任何訊息都無法取得回覆。

#### 4.5.4 修復與驗證

將該檔內容改為 `{"mcpServers": {}}` 後實測通過：

```json
{"type":"result","subtype":"success","is_error":false,
 "result":"【昱捷助理】\n測試通過","num_turns":1,...}
```

身分檔（`CLAUDE.md`）亦正確生效，回覆帶有安裝時設定的值台名稱。

#### 4.5.5 影響

1. **產品在現行 Claude Code 版本上完全不可用**。並非部分功能異常或偶發失敗，
   而是每一則訊息都失敗，且為永久性失敗。
2. **失敗發生在整個流程的最末端**。部署者需先通過安裝、selftest、金鑰填入、
   Funnel、webhook Verify、認主等全部環節，才會遭遇此問題。
   此時所有指標皆顯示成功，部署者極易誤判為「已部署完成」。
3. **selftest 未涵蓋此路徑**。現行 selftest 檢查 `claude` 指令是否存在
   （`✅ PASS 指令 claude /Users/jlin/.local/bin/claude`），
   但未實際 spawn 一次以驗證能否成功執行。此為 selftest 設計上的盲點——
   它驗證了依賴的**存在**，未驗證依賴的**可用性**。
4. **錯誤訊息誤導**。「稍後再試」暗示為暫時性問題，將促使部署者反覆重試；
   實際上此為確定性失敗，重試永遠不會成功。真正的錯誤原因僅存在於 log 中。

#### 4.5.6 修補建議

1. **修正設定檔內容**（必要）：

```python
# Claude Code 需要 mcpServers 鍵才通得過 schema 驗證；空物件 {} 會被拒
put(os.path.join(base, "config", "empty_mcp.json"), '{"mcpServers": {}}\n',
    skip_if_exists=True, label="config/empty_mcp.json")
```

   注意：因該項使用 `skip_if_exists=True`，既有部署重跑安裝器**不會**修復此問題，
   需另行提供升級指引或改為版本比對後覆寫。

2. **selftest 增列端到端驗證**（強烈建議）：實際 spawn 一次 Claude CLI，
   使用與 bridge 完全相同的參數組合，確認 rc=0 且有輸出。
   此項可在安裝當下攔截本缺陷，而非留到部署者做首測時才爆發。

```python
r = subprocess.run([claude_bin, "-p", "ok", "--strict-mcp-config",
                    "--mcp-config", mcp_path, "--output-format", "json"],
                   capture_output=True, text=True, timeout=120)
# rc != 0 → FAIL，並將 stderr 前 200 字納入 selftest 輸出
```

3. **錯誤訊息帶出成因**（建議）：將 stderr 摘要併入回覆，
   例如「（本體呼叫失敗：Invalid MCP configuration——請檢查 config/empty_mcp.json）」，
   使部署者無須翻 log 即可定位。

---

### 4.6 缺陷 F — 安裝流程未涵蓋「本體側」設定，核心功能於 GREEN 後仍完全未接通

**嚴重度**：最高（產品核心賣點於宣告安裝完成後仍不運作）　**阻斷性**：是
**發生步驟**：`AGENT_SETUP.md` 第 8 步之後（即產品宣告「任務完成」之後）

#### 4.6.1 產品的設計意圖（架構圖有畫）

`docs/架構圖_客戶版.md` 明確描繪了任務執行鏈路：

```
S4 -->|"任務(主人)"| Q["LOG/task_queue.jsonl + 未讀脈絡 + HMAC簽章"]
Q  -->|"Monitor 盯佇列"| MAIN["本體（Claude Code session，全工具權限）"]
MAIN -->|"執行後回報 relay_say(免費)/line_push"| LP
```

亦即：LINE 端的分身無工具，「任務」訊息寫入佇列，
**須有一個 Claude Code session 以 Monitor 盯著佇列，撿取並執行**，再回報。

#### 4.6.2 觀察：兩份安裝文件都沒有這一步

```
$ grep -n "本體\|佇列\|queue" AGENT_SETUP.md
（無任何結果）

$ grep -n "本體\|佇列" 00_START_HERE.md
65:- 本體回報：`python3 ~/.{slug}/tools/relay_say.py "話"`（免費）；急件 `line_push.py`
```

`00_START_HERE.md` 僅在「日常維運速查」提到本體**回報**用的工具，
未說明本體如何**接上佇列**；`AGENT_SETUP.md` 則完全未提及。

而 `AGENT_SETUP.md` 第 8 步在通道能對話時即宣告結束：

> 再傳任意一句 → 收到回覆＝**通道 GREEN，任務完成**。

`00_START_HERE.md` 的驗收定義同樣只涵蓋通道：

> 新機從零到通道活著 ≤ 30 分鐘、人類動作 ≤ 6 步＝GREEN。

**產品的驗收標準（GREEN）不包含核心功能可用。**

#### 4.6.3 實測後果

依文件完成部署並達到 GREEN 後，使用者於 LINE 發出六筆「任務」訊息，
時間橫跨 03:17 至 03:59。全部僅寫入佇列，**無一執行，且使用者未收到任何提示**：

```
$ python3 tools/task_verify.py --all
✅ OK 03:17:53 '任務：請讀取 https://gomarketing.cc/ 的網頁內容，整理出…'
✅ OK 03:19:17 '任務：讀取 Presire.tw 的網頁內容，整理出我的服務項目清單'
✅ OK 03:25:55 '任務：我會把我的課程紀錄都放在資料夾，你去讀'
✅ OK 03:35:30 '任務：讀取我電腦上 … 這個資料夾，整理出課程清單'
✅ OK 03:41:30 '任務：幫我規劃 Google Calendar 串接流程…'
✅ OK 03:59:13 '任務：我要同時做兩件事——①開啟 Claude 網頁瀏覽權限，②…'
封包鏈驗畢
```

值得注意的是：**簽章機制完全正常**（6/6 驗章通過），佇列寫入完全正常。
失效的環節是「沒有任何程序在讀這個佇列」。

#### 4.6.4 使用者被主動給予錯誤保證

問題不僅是「沒有執行」，而是**產品主動告訴使用者任務已被接手**。
身分檔母版（`templates/CLAUDE.md.tmpl`）的 persona 規範要求分身：

> **接線員三美德**：…②交代去向（「已轉本體，它處理完我帶回來給你」）

於是每次派任務，分身都會回覆類似「已轉本體，它處理完我帶回來給你」。
而分身依設計**結構上讀不到佇列**，無從得知任務是否被執行，
也無法在使用者追問「之前的任務都有做嗎」時給出正確答案。

實測中使用者確實提出了此一追問：

```
03:59:52 MSG_IN … owner '之前的任務都有做嗎？'
04:00:18 MSG_IN … owner '我都有發出去'
04:00:30 MSG_IN … owner '你看一下之前的紀錄 看是哪邊有問題'
```

使用者已察覺異常，但依產品所提供的資訊無法定位問題——
因為問題不在他操作的任何一個環節，而在一個文件從未告知其存在的環節。

#### 4.6.5 影響

1. **產品核心賣點在宣告安裝完成後仍完全不運作**。README 首句定位為
   「把一個 LINE 官方帳號，變成你的 AI 值台」；「值台」之所以是值台，
   在於它能執行任務。僅能聊天的通道不構成產品所主張的價值。
2. **失效是靜默的**。任務持續累積、佇列持續增長、使用者持續得到「已轉本體」的保證，
   沒有任何一環會告訴他這件事沒有發生。
3. **GREEN 的定義本身有瑕疵**。以「通道活著」作為驗收標準，
   使部署者在核心功能未接通的狀態下被告知「任務完成」。
4. `queue_backlog_check.py`（積壓偵測）雖已隨包提供，但同樣未出現在安裝流程中；
   首次執行時回報「無收割標記——先跑 mark 初始化」，
   顯示該工具亦預期由一個從未被設定起來的本體側流程使用。

#### 4.6.6 修補建議

1. **`AGENT_SETUP.md` 增列第 9 步：接上本體側**（必要）。
   至少需說明：由誰擔任本體、如何盯佇列、執行前須跑 `task_verify.py` 驗章、
   如何以 `relay_say.py` 回報。此步驟目前僅存在於架構圖，未進入任何操作流程。

2. **修改 GREEN 的定義**（強烈建議），使其涵蓋核心功能。例如：

   > **GREEN 判定**（兩項都要通過）
   > ① 通道活著：傳一句話收到回覆
   > ② 任務通：傳「任務：現在幾點」→ 本體執行 → 收到帶【本體】標記的回覆
   >
   > 只過①＝通道通了但值台還不會做事，尚未完成部署。

3. **讓靜默失效變成可見**（建議）。例如 bridge 於寫入佇列時檢查積壓：
   若佇列中存在超過 N 分鐘未被收割的任務，於回覆中附加提示
   「（提醒：目前有 N 筆任務尚未被本體取走，請確認本體側是否運作中）」。
   此舉可將「使用者永遠不會發現」轉為「使用者當場知道」。

4. **調整分身的話術**（建議）。在本體側未確認運作前，
   「已轉本體，它處理完我帶回來給你」是一句無法兌現的承諾。
   建議改為描述已發生的事實：「已排進本體佇列」，而非承諾結果。

---

## 5. 綜合討論

### 5.1 四項缺陷的共同結構

四項缺陷表面上分屬完整性驗證、文件、產品定位與診斷設計，但共享同一結構性成因：

> **產品的所有驗證機制均在部署機本機執行，而部署機的視角與外部世界系統性地不一致。**

- 缺陷 A：以本機檔案與本機指紋檔比對，但指紋檔本身未經發布前驗證。
- 缺陷 B：以本機 `tailscale version` 判定前置滿足，但真正的前置條件在遠端後台。
- 缺陷 C：以本機可執行 python3 為前提，但實際執行者（agent）有本機以外的策略約束。
- 缺陷 D：以本機 `tailscale funnel status` 與本機 curl 判定公網可達，但兩者皆不反映外部視角。

此結構性成因亦解釋了為何 `docs/TROUBLESHOOTING.md` 之「九類坑」雖已相當完整
（涵蓋 launchd、reply token、push 額度、白名單、prompt 回聲、多進程競爭、睡眠等實戰情境），
卻仍未涵蓋本次遭遇的任何一項——因為九類坑全部是**本機視角**可觀測的問題。

### 5.2 對「安全設計」主張的影響

產品 README 設有「安全設計」專章，列舉四項：金鑰不進 repo、fail-closed、簽章驗證、零第三方依賴。
本次部署實測確認**後三項均確實有效**（見 1.3 節），第一項亦徹底落實。

然而缺陷 A 使產品的**完整性驗證**環節失效。完整性驗證與上述四項共同構成安全鏈；
當部署者無法驗證所收到的 `core/line_bridge.py` 是否即為維護者所發布者，
其餘三項安全機制的可信度均建立在未經驗證的前提上。

建議將指紋檔之正確性納入發布流程的自動檢查（見 6.1）。

### 5.3 驗收標準達成情形

| 產品宣稱 | 實測 | 達成 |
|---|---|---|
| 新機從零到通道活著 ≤ 30 分鐘 | 66 分鐘且未完成 | ❌ |
| 人類動作 ≤ 6 步 | ≥ 7 步且未完成 | ❌ |
| agent 自己建環境，只停兩次 | 出現第三個停止點，agent 無法執行安裝器 | ❌ |
| 收到包先驗指紋 | 16 檔中 1 檔不符 | ❌ |

---

## 6. 修補建議

以下建議按優先順序排列，均為具體可執行之變更。

### 6.1 缺陷 A：重新產生指紋檔，並納入發布流程檢查

1. 以現行 `core/line_bridge.py` 重算並更新 `RELEASE_SHA256.txt`。
2. 於發布流程加入自動校驗，避免同類問題再次發生。建議於 release 前執行：

```bash
# 產生指紋
find . -type f \( -name '*.py' -o -name '*.md' -o -name '*.tmpl' \) \
  -not -path './.git/*' -not -name 'RELEASE_SHA256.txt' \
  | sort | xargs shasum -a 256 > RELEASE_SHA256.txt

# 發布前自檢——不通過就不允許 tag
shasum -a 256 -c RELEASE_SHA256.txt || { echo "指紋不符，中止發布"; exit 1; }
```

3. 建議於 `00_START_HERE.md` 補充驗證指令，讓部署者知道**如何**驗，而不只是知道要驗：

```bash
shasum -a 256 -c RELEASE_SHA256.txt
```

### 6.2 缺陷 B：補齊 Tailscale 前置條件

建議將 `00_START_HERE.md` 前置條件第 3 條修改為：

> 3. **Tailscale** 已裝且登入，**且已完成下列兩項後台設定**（`tailscale status`；免費方案可用）：
>    - admin console → DNS → 啟用 **HTTPS Certificates**（未啟用則無法簽發 `.ts.net` 憑證）
>    - 節點取得 **funnel 屬性**：首次執行 `tailscale funnel` 時點擊 CLI 印出的授權連結，
>      或於 Access Controls 的 `nodeAttrs` 加入 `funnel`
>
>    確認指令：
>    ```bash
>    tailscale status --json | grep -i certdomains   # 應有網域，非 None
>    tailscale status --json | grep -i funnel        # 應有 funnel 能力項目
>    ```

並將 `AGENT_SETUP.md` 第 1 步之檢查指令由 `tailscale version` 擴充為上述兩條確認指令。

### 6.3 缺陷 C：修正產品定位敘述，並提供官方認可之執行路徑

README 之快速開始章節建議調整為誠實描述實際情形，例如：

> 對你機器上的 AI agent 說一句：「clone … 照 AGENT_SETUP.md 做，不要自由發揮。」
>
> **注意**：多數 AI agent 的預設安全策略會拒絕執行剛下載的第三方安裝腳本。
> 若 agent 回報權限被拒，這是它的安全機制正常運作，請改由你自己在終端機執行安裝器
> （agent 會把完整指令給你），其餘步驟仍可交給 agent。

同時建議於 `AGENT_SETUP.md` 第 3 步加入預期失敗之處置說明，並於 TROUBLESHOOTING 新增一類。

### 6.4 缺陷 D：新增公網可達性驗證關卡（最高優先）

建議於 `AGENT_SETUP.md` 第 6 步與第 7 步之間，插入一個新的驗證步驟：

> ### 第 6.5 步：確認公網真的看得到你（**不可略過**）
>
> Funnel 的公網 DNS 記錄是非同步建立的，需時數分鐘至十餘分鐘。
> **在下列兩項都通過之前，不要去 LINE 後台按 Verify——按了必然失敗。**
>
> ```bash
> HOST=<你的節點>.<你的tailnet>.ts.net
>
> # ① 公網 DNS 是否已可解析（務必指定外部解析器，不可用本機預設）
> dig @1.1.1.1 A $HOST +short
> dig @8.8.8.8 A $HOST +short
> # 兩者都要回傳 IP。任一為空＝還沒好，等 2 分鐘再試。
>
> # ② 四台權威 NS 是否都已同步（避免部分同步造成間歇性失敗）
> for ns in ns1.dnsimple.com ns2.dnsimple-edge.net ns3.dnsimple.com ns4.dnsimple-edge.org; do
>   printf "%-26s -> " $ns; dig @$ns A $HOST +short | tr '\n' ' '; echo
> done
> # 四台都要有 IP。只要有一台是空的，對外解析就會間歇性失敗，LINE 的 webhook 會隨機掉。
>
> # ③ 公網路徑實測（強制走公網 IP，繞開 MagicDNS）
> IP=$(dig @1.1.1.1 A $HOST +short | head -1)
> curl --resolve $HOST:443:$IP https://$HOST/     # 應回 line_bridge alive
> ```
>
> **⚠️ 為什麼不能在這台機器上直接 curl 測試**
>
> 這台機器在 Tailscale 網路內，MagicDNS 會把主機名解析到內網位址（100.x.x.x），
> 你會得到 HTTP 200——但那走的是內網，跟 LINE 會走的路徑完全無關。
> **本機直接 curl 得到 200 不能作為公網已通的證據。** 一定要用上面的 `--resolve` 寫法。

並建議修改 `docs/TROUBLESHOOTING.md` 第 2 類第 3 點：

> 3. bridge 活著但 Verify 失敗 →
>    **先查公網 DNS，不要用 `tailscale funnel status`**。
>    `tailscale funnel status` 只反映本機設定，記錄還沒同步到公網時它一樣顯示「Funnel on」，
>    會讓你誤以為 Funnel 正常而去懷疑 URL。正確查法見第 6.5 步的三項檢查。
>    - 三項全過、URL 結尾是 `/callback`，Verify 仍失敗 → 才往下查第 4 點
>    - `dig` 查得到但只有部分權威 NS 有記錄 → Tailscale 端尚未同步完成，只能等；
>      若逾 30 分鐘未同步，建議改用其他公網入口（Cloudflare Tunnel 等）

### 6.5 補充建議：正式營運場景之公網入口

Tailscale Funnel 的 DNS 記錄由第三方掌控，部署者在故障時無任何控制權或補救手段。
建議於文件中補充說明：若用於正式營運之官方帳號，可考慮改用部署者自有網域之通道
（如 Cloudflare Tunnel），bridge 端無須任何修改，僅替換公網入口層。
此舉可將缺陷 D 所述之外部依賴風險降至部署者可控範圍。

---

## 7. 結論

LINE Channel Deploy Kit v1.0 的核心工程品質良好：安裝器冪等、selftest 設計完善、
fail-closed 與簽章驗證經實測確實有效、金鑰隔離徹底落實、零第三方依賴的承諾確實兌現。
本報告所列四項缺陷均不涉及上述核心邏輯。

四項缺陷集中於產品與外部世界的介面：對第三方服務前置條件的假設（缺陷 B）、
對執行環境安全策略的假設（缺陷 C）、對自身發布流程的驗證（缺陷 A），
以及對外部視角可觀測性的缺位（缺陷 D）。

其中缺陷 D 影響最深。產品在一個必然發生的時間窗內，提供了兩個都會導向錯誤結論的診斷方法，
且未提供任何正確的方法。對一個以「降低部署門檻」為核心價值的產品而言，
**故障時能否讓部署者知道自己卡在哪裡，與順利路徑上的步數同等重要**。

第 6 節之建議多為文件層級的修改，實作成本低，但可實質改善非理想路徑上的部署體驗。
其中第 6.4 節之驗證關卡建議優先採納。

本報告之全部原始指令與輸出見附錄，維護者可於自有環境獨立重現。

---

## 附錄 A：完整重現指令

```bash
# ── 取得與本報告相同之版本 ──
git clone https://github.com/Endwar116/line-channel-deploy-kit.git
cd line-channel-deploy-kit
git rev-parse HEAD        # 應為 0ee7e07d865404aad6c45c5af5d5c803a2c1e863

# ── 缺陷 A：指紋不符 ──
shasum -a 256 core/line_bridge.py
grep line_bridge RELEASE_SHA256.txt
git cat-file -p HEAD:core/line_bridge.py | shasum -a 256          # 證明非傳輸竄改
git log --format='%h %s' --diff-filter=A -- core/line_bridge.py RELEASE_SHA256.txt

# ── 缺陷 B：前置條件不足 ──
tailscale status --json | grep -i certdomains                     # None = HTTPS 憑證未開
tailscale status --json | grep -i funnel                          # 空 = 節點無 funnel 屬性

# ── 缺陷 C：agent 執行受阻 ──
# 於 Claude Code 預設 auto mode 中執行：
python3 install.py --owner <名> --agent-name <名> --slug <slug> --port 8700 --yes
# 對照組：同一指令由人類於終端機手動執行 → 成功

# ── 缺陷 D：公網 vs 本機視角落差 ──
HOST=<節點>.<tailnet>.ts.net
dig +short A $HOST                                                # 本機：內網 100.x 位址
dig @8.8.8.8 A $HOST +short                                       # 外部：真實公網視角
for ns in ns1.dnsimple.com ns2.dnsimple-edge.net ns3.dnsimple.com ns4.dnsimple-edge.org; do
  printf "%-26s -> " $ns; dig @$ns A $HOST +short | tr '\n' ' '; echo
done
tailscale funnel status                                           # 觀察其是否給出假綠燈
IP=$(dig @8.8.8.8 A $HOST +short | head -1)
curl --resolve $HOST:443:$IP https://$HOST/                        # 真實公網路徑
```

## 附錄 B：關鍵原始輸出

### B.1 安裝器 selftest（人類手動執行，成功）

```
✅ PASS    依賴 import（stdlib）＋python>=3.9　3.9.6
✅ PASS    簽章驗證器自測（正簽收/偽簽拒）　HMAC-SHA256+b64
✅ PASS    secrets 檔存在　待填：LINE_CHANNEL_SECRET,LINE_CHANNEL_ACCESS_TOKEN（填完 bridge 才會啟動）
✅ PASS    任務簽章鍵存在　600
✅ PASS    bridge py_compile
⚠️ WARN    port 8700 監聽　已載入但未監聽——多半是 secrets 未填（fail-closed 拒啟動）；填完後 launchd 會自動重試
✅ PASS    指令 claude　/Users/jlin/.local/bin/claude
✅ PASS    指令 tailscale　/usr/local/bin/tailscale
```

### B.2 fail-closed 機制實測（設計正確，予以肯定）

```
secrets 缺 LINE_CHANNEL_SECRET——拒絕啟動（fail-closed）      ← launchd 每 10 秒重試
（重複 19 次）
2026-09-04T01:50:29+08:00 START port=8700 test_mode=False    ← 金鑰填入後自動啟動
```

### B.3 bridge 健康狀態（本機與公網皆正常）

```
本機          curl http://localhost:8700/            → 200，line_bridge alive
公網 IPv4     curl --resolve …:443:103.84.155.153    → 200，0.57s
公網 IPv6     curl -6 --resolve …:443:2403:2500:…   → 200，1.35s
簽章驗證      POST /callback（無簽章）                → 403（正確拒絕）
TLS 憑證      CN=<你的節點>.ts.net
              issuer=Let's Encrypt, CN=YE1
              效期 2026-09-03 16:53 GMT ~ 2026-12-02，SAN 相符
```

### B.4 DNS 部分同步狀態（缺陷 D 之觸發條件）

```
                          AAAA(IPv6)                        A(IPv4)
ns1.dnsimple.com          2403:2500:400:20::25a, ::e8e      （空，連查 4 次）
ns2.dnsimple-edge.net     2403:2500:400:20::25a, ::e8e      103.84.155.153, .217
ns3.dnsimple.com          2403:2500:400:20::25a, ::e8e      103.84.155.153, .217
ns4.dnsimple-edge.org     2403:2500:400:20::25a, ::e8e      103.84.155.153, .217

四台 SOA serial 均為 1627495866
對照組 hello.ts.net 於四台皆回 100.101.102.103（正常）

對外解析成功率：dig @1.1.1.1 × 12 → 成功 6 / 失敗 6
                dig @8.8.8.8 × 12 → 成功 12（快取命中正解）
```

## 附錄 C：責任歸屬聲明

為免爭議，本報告明確區分責任歸屬：

| 項目 | 責任方 | 是否列為本報告之缺陷 |
|---|---|---|
| 缺陷 A 指紋不符 | 產品維護者 | ✅ 是 |
| 缺陷 B 前置條件缺漏 | 產品維護者 | ✅ 是 |
| 缺陷 C agent 承諾不可兌現 | 產品維護者（設計假設） | ✅ 是 |
| 缺陷 D 診斷指引誤導、驗證關卡缺位 | 產品維護者 | ✅ 是 |
| DNS 記錄部分同步 | Tailscale／DNSimple | ❌ **否**，僅為缺陷 D 之觸發條件 |
| Claude Code 拒絕執行下載腳本 | 無人有責（安全機制正常運作） | ❌ **否**，為缺陷 C 之觸發條件 |
| 部署環境不符 | — | ❌ 不適用，環境完全符合前置要求 |

本報告不主張任何金錢求償，目的為協助維護者改善產品。

---

## 附錄 D：故障點定位——逐段鏈路檢查（2026-09-04 02:29）

本附錄記錄一次完整的端到端鏈路檢查，用以精確定位單一故障點。
執行時間為 `tailscale funnel` 啟用後第 37 分鐘。

```
  1. bridge 本機              200                          ✅
  2. funnel 設定              Funnel on                    ✅
  3. TLS 憑證                 有效（未過期，SAN 相符）      ✅
  4. 公網 IPv4 連通性          200（--resolve 強制走 ingress）✅
  5. 公網 IPv6 連通性          200（--resolve 強制走 ingress）✅

  6. DNS ── ts.net 四台權威 NS 的 A 記錄：
        ns1.dnsimple.com          （空）                    ❌
        ns2.dnsimple-edge.net     103.84.155.153, .217      ✅
        ns3.dnsimple.com          103.84.155.153, .217      ✅
        ns4.dnsimple-edge.org     103.84.155.153, .217      ✅
```

### D.1 結論

**六段鏈路中，前五段全部正常。唯一故障點為 `ns1.dnsimple.com` 缺少 A 記錄。**

部署機、bridge、TLS 憑證、Funnel 設定、公網 IPv4／IPv6 連通性均無任何問題。
此結果進一步確認：本次未達 GREEN 與本 KIT 之程式碼品質無關。

### D.2 故障機制

LINE 平台在投遞 webhook 前須解析主機名，該查詢會被導向四台權威 NS 中之任一台：

- 命中 ns2／ns3／ns4 → 取得 IPv4 位址 → 連線成功
- 命中 **ns1** → 無 IPv4 位址可用 → 回報 `An invalid host was used for the webhook URL`

失敗結果會被遞迴解析器負面快取 300 秒，故單次失敗後短時間內重試亦將持續失敗。
此即部署者在 LINE 後台觀察到之「Verify 有時失敗、重按仍失敗」現象之成因。

### D.3 已排除之其他可能

| 假設 | 排除依據 |
|---|---|
| 設定錯誤 | 同一份設定於另外三台 NS 上正確生效 |
| DNS 快取問題 | 直接查詢權威 NS（`aa` 旗標），已繞過所有快取層 |
| 傳播延遲未完成 | 觀測 37 分鐘；且 AAAA 記錄早已四台同步完成，僅 A 記錄未同步 |
| 可經重試修復 | 已執行 `tailscale funnel off` → `on` 重新註冊，無效 |
| 憑證或連線問題 | 第 3～5 段實測全數正常 |

### D.4 此故障對本報告缺陷 D 之意義

本故障本身屬 Tailscale／DNSimple 責任範圍，不列為對本 KIT 之缺陷主張（見附錄 C）。

其意義在於：**這是一個部署者完全無法自行修復、亦無任何操作介面可介入的外部故障。**
在此種情境下，產品文件唯一能提供的價值即為「讓部署者迅速知道問題不在自己這裡」。

而本次實測中，產品提供的兩個診斷方法均未能達成此目的：

- `tailscale funnel status` 回報「Funnel on」→ 指向「設定正常，應是 URL 抄錯」
- 部署機本機 curl 回應 200 → 進一步強化「我這邊都正常」之判斷

部署者若無 DNS 除錯經驗，將無從得知問題出在四台權威 NS 中的一台，
亦無從判斷應「繼續等待」或「更換公網入口方案」。

本報告第 6.4 節所建議之驗證關卡，正是為此類情境而設計：
其中「四台權威 NS 逐一檢查」一項，可在 10 秒內給出正確結論。

---

*本報告全部內容基於單次真實部署歷程之即時採證，所有指令輸出均為當下實際結果，未經事後補作或潤飾。*
