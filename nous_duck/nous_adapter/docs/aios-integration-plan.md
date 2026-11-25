> [繁體中文](aios-integration-plan.md) | [English](aios-integration-plan.en.md)

# AIOS 整合計畫：把鴨子接進 Nous

狀態：**計畫（尚未在 AIOS 動手）**。日期：2026-11-25。這份文件是之後在 AIOS repo 開批次的依據；在 AIOS 完成並驗證之前，不在任何地方宣稱「鴨子已整合進 Nous」。

- 查閱的 AIOS：`pcpcchen-coder/AIOS` `main`，commit `c85307861f7562803fb3776407493da49cdc8a83`（2026-11-24），`git clone` 到暫存目錄**唯讀**查閱；沒有執行、沒有修改、沒有對執行中的 Nous 發請求。
- 除非另外註明，路徑都相對於 AIOS 的 `prototype/ambient-shell/`；`檔案:行號` 是該 commit 的行號。
- 「事實」是直接從程式碼讀到的；「建議」「推論」是本文件的判斷，會明確標示。
- 本 repo 這一端的現況見 [`../README.md`](../README.md)；語音怎麼到鴨子另見 [`voice-path.md`](voice-path.md)。

## 1. 摘要

| 問題 | 答案 |
|---|---|
| DuckAdapter 搬進 AIOS 要改哪些檔 | 新增 1 個 adapter 檔與 1 個測試檔，修改 8 個既有檔與 2 個基準檔（§3） |
| `/duck-link` 端點放哪 | 新模組 `server/duck-link.ts`，在 `server/nous.ts` 建立、掛到 `createApp` 回傳的 `Server` 的 `upgrade` 事件（§4）。**AIOS 目前沒有任何入站 WebSocket 端點**，這是第一個 |
| `presence` 從哪些真實事件產生 | 核心現在只知道工作階段的開始、連上、結束與 live 路徑的部分事件；聽／想／說的完整狀態**只有頁面知道**。要加一個核心的觀察點，再加頁面回報（§6） |
| Nous 的聲音怎麼到鴨子喇叭 | 助理的聲音是**開始這通對話的那個瀏覽器頁面**收到的 WebRTC 音軌，核心完全不經手音訊。所以唯一不必新增音訊管線的作法是 ADR-0003 的路線 A：在鴨子的 Pi 4 上跑 Nous 頁面（[`voice-path.md`](voice-path.md)） |
| AIOS 要開幾個批次 | 7 個，建議順序見 §8；前 3 個做完，鴨子就能被 Nous 用語音叫去做動作 |

## 2. 查到的事實（影響設計的部分）

### 2.1 Adapter 的註冊與啟用

- 已審核清單：`server/integrations/index.ts:36-39` 的 `KNOWN_ADAPTERS`（ID → factory）。目前有 `mock`、`home`、`spotify_soloist`、`voice_relay`、`google_calendar`、`weather`、`lg_tv`、`gmail_gog`。factory 的簽章是 `(config: Config["ail"], log, deps: AdapterDeps) => IntegrationAdapter | null`。
- 啟用：`NOUS_AIL=on` 加上 `NOUS_AIL_SERVICES`（逗號分隔的 adapter ID），由 `server/config.ts:292-312` 的 `parseAil()` 解析；只在啟動時讀一次，模型與頁面都不能啟用工具。
- 把核心已建立的模組交給 adapter 的方式：`AdapterDeps`（`index.ts:30-34`，目前有 `home?: HomeBridgePort`、`weather?`）。`createIntegrations` 只在 `server/nous.ts:321` 呼叫一次。
- 註冊檢查（`registry.ts:32-63`）：工具 ID 格式、`serviceOf(id) === adapter.service`、`effect` 在清單內、`timeoutMs` 100～60 000、`supportedRoutes` 非空且不含 `page`、參數 schema 只能是平面物件加純量（`schema.ts`）。
- effect 的影響（`policy.ts:38-41`、`dispatcher.ts:105-107`）：`read` 與 `reversible_write` 直接執行；`external_commit` 需要確認，但確認卡沒有接到整合層，所以**一律被拒絕**。鴨子的工具都是 `read` 或 `reversible_write`，不受影響。
- Dispatcher 的限制（`dispatcher.ts:71-143`、`policy.ts:44`）：每個 adapter 每分鐘 30 次（各路徑合計）；結果的 `data` 超過 4 096 bytes 會被丟掉；`message` 截到 500 字；adapter 丟錯時，有副作用的工具回 `unknown`。
- 送給模型的名稱：`app__duck__<action>`；兩條語音路徑的工具表在 `server/nous.ts:333`（`api_key`）與 `:337`（`live`）接上。
- live 路徑一次委派最多 2 個工具呼叫（`live-tool-caller.ts:61-69` 的 `maxHostCalls: 2`，頁面工具與整合工具共用）。
- 新增 adapter 的官方清單：`docs/development/adding-an-adapter.md`。

### 2.2 既有 adapter 的寫法

- 回讀確認的範本是 `adapters/lg-tv.ts`（檔頭 `:13-14`）：有回讀且符合 → `confirmed`；送出但讀不到或不符 → `unconfirmed`；送出後斷線或沒回覆 → `unknown`；連不上、沒有送出 → `failed`。本 repo 的 DuckAdapter 用同一套語意。
- **沒有任何 adapter 持有長連線**：LG 電視每次工具呼叫開一條連線（`server/lgtv/ssap.ts:6`）；Spotify Soloist 每次健康檢查開一條；家電是每次 HTTP。鴨子會是第一個「背後是裝置主動連進來的長連線」的 adapter。最接近的作法是 `adapters/home.ts` 的 `HomeBridgePort`：adapter 只拿到一個介面，真的物件由核心建立、經 `AdapterDeps` 傳入、測試傳假的。
- mock 的標示：`mock: true` 的 adapter，工具要標 `catalog.hidden`（`catalog.ts:148`）；`mock: "config"`（例如 `voice_relay`）表示依設定決定，adapter 的 `mock` 由實際的輸出端決定（`voice-relay.ts:95`）。DuckAdapter 用 `"config"`：對面是真的鴨子還是模擬，看連進來的那一端的 `hello.mock`。
- 測試：全部在 `tests/*.test.ts`（vitest 5.0.3，沒有設定檔）；adapter 測試命名 `tests/integration-<name>.test.ts`；LG 電視的測試用 `ws` 的 `WebSocketServer` 在臨時埠架一台假電視，註明「fixture，不是實機驗證」。

### 2.3 HTTP 與 WebSocket

- `createApp`（`server/app.ts:278`）是單純的 `node:http` server，只綁 `127.0.0.1`（`server/nous.ts:578`），預設 port 8787。
- **沒有入站 WebSocket**：`createApp` 沒有註冊 `upgrade`；`ws` 套件在核心只當 client 用（LG 電視、OpenAI sideband）。
- 守門（`server/http-guard.ts`）：`Host` 必須是 `localhost:<port>` 或 `127.0.0.1:<port>`；**GET 只檢查 Host，不檢查 Origin**。沒有給本機用戶端的權杖機制。
- 核心 → 頁面的推送是 SSE（`GET /api/events`）。

### 2.4 終端（`terminals/rpi4/`）

- 一台「終端」就是**帶 `?terminal=<id>` 的瀏覽器頁面**。核心沒有終端登記表、能力描述或配對；語音、喚醒詞、狀態、輸出裝置的選擇全部在頁面裡。
- 連線：**Pi 主動** SSH 到 Mac，用 local forward（`terminals/rpi4/bin/aios-tunnel:12-25`，`-L 127.0.0.1:$AIOS_PORT:127.0.0.1:$AIOS_PORT`）；Mac 要開「遠端登入」。Pi 本機的 port 必須等於核心的 port，否則過不了 Host 檢查。
- 心跳：頁面每 10 秒 `POST /api/terminal/heartbeat`；核心 25 秒沒收到視為離線（`server/terminal-presence.ts:21-75`）。程式註解說明：SSH 轉送的 TCP 連線在 Pi 消失後 Mac 這端可能還開著，所以只認應用層心跳（`shared/terminal.ts:4-5`）。
- 終端 ID：`/^[a-z0-9][a-z0-9-]{0,31}$/`，不能是 `main`；`rpi4` 寫死在 kiosk 腳本裡。
- Pi 上唯一「非瀏覽器程式讀核心狀態」的例子是 `bin/aios-display`：每 2 秒用 `curl` 輪詢 `GET /api/terminal/display`。

### 2.5 即時語音工作階段

- 兩條路徑都是**瀏覽器直接用 WebRTC 連雲端模型**；核心只代轉 SDP，有時另外握一條控制用的 WebSocket（sideband）。
- 完整的狀態機只在頁面：`RealtimePhase = "off" | "connecting" | "listening" | "hearing" | "thinking" | "speaking"`（`src/realtime.ts:32`），經 `onPhase`（`src/main.ts:482`）給電子腦。**頁面從不把 phase 回報給核心。**
- 核心知道的（兩條路徑都有）：`POST /api/realtime/start`（帶 `source`：`user`／`look_to_talk`／`wake_word`，以及 `page`）、連上、每 15 秒的 `alive`、`POST /api/realtime/end` 與內部的 `finish(session, reason)`。
- live 路徑另外從 sideband 得到（`server/live-route.ts:469-551`）：`session.started`、使用者與助理的逐字稿（部分與最終）、`delegation`（工具工作開始與結束）、`error`；`speech.started` 與 `audio.done` 這兩個事件在 live 的線上是否真的會送，程式註解寫明**未證實**（`shared/frameless.ts:14-17`）。
- api_key 路徑：核心只有在這通對話帶記憶規則時才接 sideband；否則連上之後到結束之間，核心什麼都看不到。
- `RealtimeSessions`（`server/realtime-routes.ts:300`）**沒有觀察用的 hook**（`RealtimeSessionsOptions` `:135-169` 沒有 `onSessionChange` 之類的欄位）。
- 助理語音的音量：核心完全沒有。頁面在 live 路徑對助理的音軌量 RMS（`src/live-voice.ts:860-883`，每 50 ms），只拿來跟門檻 `SPEAKING_RMS = 0.02` 比；api_key 路徑沒有量助理的音軌。

### 2.6 聲音輸出與喚醒

- 助理的聲音在**擁有這通對話的頁面**播放（`src/main.ts:815-846` 的 `playRemote`）；輸出裝置用 `setSinkId`（`src/audio-devices.ts:105-125`），偏好存在核心的 `audio.json`，**全域一份、不分終端**（`server/app.ts:326`）。
- 核心從不處理原始音訊；**沒有任何把助理語音送到非瀏覽器裝置的路徑**。
- 喚醒詞在頁面執行（sherpa-onnx 2.0.1 的 wasm，關鍵詞「Hello Nous」「Hey Nous」）；每個頁面用自己的麥克風偵測。喚醒後頁面 `POST /api/realtime/start {source: "wake_word"}`，核心限制每分鐘 3 次。
- `spike/wake/direction/` 量的是「不同角度的喚醒成功率」，**不是**聲源方向估計；AIOS 沒有 DOA 或波束成形的程式。
- 頁面收音在聲道數不是 1、2、4、6 時只留第 1 聲道（`spike/wake/direction/logic.ts:31-35`）。
- AIOS 裡沒有任何 duck、robot 或行動終端的概念（全 repo 搜尋）。

## 3. 批次 D2：把 DuckAdapter 搬進 AIOS

要搬的檔（本 repo → AIOS）：

| 本 repo（`nous_duck/nous_adapter/`） | AIOS | 說明 |
|---|---|---|
| `adapters/duck.ts`、`adapters/duck-exec.ts`、`adapters/duck-text.ts` | `server/integrations/adapters/duck.ts`（可合成一檔，或 `server/duck/` 放後兩個） | `import` 改成 AIOS 的 `../contracts.ts`、`../../../shared/integrations.ts` |
| `shared/aios-contracts.ts` | **刪掉** | 它只是 AIOS 型別的最小重新宣告 |
| `shared/duck-link.ts`、`shared/capabilities.ts` | `shared/duck-link.ts` | 純型別與常數，放 `shared/` 符合 AIOS 的分層 |
| `adapters/duck-text.ts` 的 `DUCK_TEXT_EN`、`DUCK_REJECT_TEXT_EN` | `server/messages.en.json` | AIOS 的英文句子用中文原文當 key |
| `mock/mock-duck.ts` | `tests/fixtures/mock-duck.ts` | 只給測試用 |
| `tests/duck-adapter.test.ts` | `tests/integration-duck.test.ts` | 命名比照 `integration-lg-tv.test.ts` |

AIOS 既有檔要改的地方（依 `docs/development/adding-an-adapter.md`）：

1. `server/integrations/index.ts`：`AdapterDeps` 加 `duck?: DuckLink`；`KNOWN_ADAPTERS` 加 `duck: (_config, _log, deps) => (deps.duck ? new DuckAdapter(deps.duck) : null)`（hub 沒啟用就不註冊）。
2. `server/nous.ts:321`：`createIntegrations(...)` 的 deps 傳入 hub（hub 要在這一行之前建立，見 §4）。
3. `server/integrations/catalog.ts:24-35`：`ADAPTER_CATALOGS` 加 `DUCK_CATALOG`。
4. `server/messages.en.json`：服務名稱「鴨子」、每個工具的 `summary`、例句、`needs` 的英文（`checkCatalog()` 會檢查，`catalog.ts:130-133`）。
5. `tests/fixtures/model-tools.ts:34-48`：`modelToolAdapters()` 加一個 DuckAdapter 實例。
6. `tests/fixtures/model-tools.baseline.json`：重新產生（`npx tsx scripts/write-model-tools-baseline.ts --model-tools`）——模型看到的工具變了。
7. `tests/fixtures/commands-page.baseline.json` 與指令表：重新產生（`--commands`、`npm run docs:commands`）。
8. `tests/capability-catalog.test.ts:81`：整合工具數寫死 32，要改（加 17 個是 49；若分階段啟用就是實際數字）。
9. `.env.example:94-108`：在 AIL 區塊說明 `duck`。
10. （建議）`server/realtime.ts:309-336` 的 `realtimeToolRules()`：加一段 `DUCK_RULE`，比照 `TV_RULE`（`:291`）。內容：`confirmed` 只代表開始；任務類要等事件；`unknown` 要請使用者看一下鴨子；鴨子沒有的能力不要重試。

交付前的檢查（同一份清單 §5）：`npm run catalog -- --check`、`npm run typecheck`、`npx vitest run tests/capability-catalog.test.ts tests/commands-from-catalog.test.ts`、repo 根目錄 `node scripts/verify-aios.mjs`。

風險與建議：

| 風險 | 說明 | 建議 |
|---|---|---|
| 一次多 17 個工具 | 兩條語音路徑的工具表都變長（token、模型選錯工具的機率）；live 路徑一次委派只能呼叫 2 個工具 | **分階段啟用**：第一階段只開鴨子現在有硬體的 `status`、`stop`、`look`、`gesture`（加上到貨後的 `express`）；其餘在 `ToolDefinition.enabled` 設 `false`，硬體到了再開。這是建議，要使用者決定 |
| 每分鐘 30 次的頻率限制 | `stop` 也算在內；ADR-0001 希望 `stop` 不受限 | `presence` 不走 Dispatcher（走 DuckTerminal），不佔額度。`stop` 是否豁免要改 `policy.ts`，屬於 AIOS 的決定；鴨子端另有租約與本機安全，不依賴這裡 |
| `data` 上限 4 096 bytes | 超過會整個被丟掉 | 本 repo 的測試已確認每個工具的 `data` 都在上限內（見驗證紀錄）；之後加欄位要再量 |
| `ToolResult.reason` 是固定清單 | 沒有「鴨子拒絕」「能力不支援」的代碼 | 目前用 `unavailable`／`invalid_arguments`／`timeout`，鴨子的原因放 `data.duck_reason`。要不要在 `shared/integrations.ts` 加新代碼由 AIOS 決定 |
| 依賴 | schema 驗證用 Ajv 8.20.0；AIOS 整合層目前刻意不加依賴（`schema.ts` 檔頭） | 兩個選擇：AIOS 加 `ajv`（鎖版本），或用 Ajv 的 standalone 模式在建置時把 schema 編成純程式碼、不帶執行期依賴。**尚未驗證** standalone 產出在 AIOS 的 `tsx` 環境可用 |
| `architecture.test.ts` | `server/` 只能 import `server/` 與 `shared/` | 搬的時候 `shared/duck-link.ts` 放 `shared/`、hub 放 `server/`，不會違反 |

## 4. 批次 D1：`/duck-link` 端點（duck-link hub 進核心）

要搬的檔：`hub/duck-link-hub.ts` → `server/duck-link.ts`；`shared/validator.ts` → `server/duck-link-schema.ts`；schema 檔複製到 AIOS（例如 `shared/duck-link.v0.schema.json`，並在檔頭註明來源 repo 與 commit——schema 的正本在本 repo 的 `protocol/schemas/`）；`tests/hub.test.ts` → `tests/duck-link.test.ts`。

接法（建議）：

1. 把 `DuckLinkHub` 拆成「協定邏輯」與「掛到既有 `http.Server`」兩部分。本 repo 的 hub 自己開 `http.Server`；進 AIOS 後改成 `attach(server: Server, hosts: Set<string>)`，在裡面 `server.on("upgrade", …)`。
2. `server/nous.ts`：在第 321 行（`createIntegrations`）**之前** `const duckLink = config.duck.enabled ? new DuckLinkHub({ log }) : null`，傳進 `AdapterDeps`；在第 519 行（`createApp`）**之後** `duckLink?.attach(server, hosts)`。
3. `server/config.ts`：新增 `NOUS_DUCK=on`（預設關閉）。只有它開著才掛 `upgrade`；`NOUS_AIL_SERVICES` 含 `duck` 但 `NOUS_DUCK` 沒開時，factory 回 `null`（不註冊）。
4. `upgrade` 處理要自己做的檢查（既有守門不會套用到 upgrade）：
   - 路徑完全等於 `/duck-link`，否則 404。
   - `checkRequest("GET", req.headers, hosts)`（Host 檢查，沿用 `http-guard.ts`）。
   - **有 `Origin` 標頭就拒絕**。`checkRequest` 對 GET 不檢查 Origin，瀏覽器對 WebSocket 也不套用 CORS；不擋的話，Mac 或 Pi 上任何開著的網頁都能連進來冒充鴨子。本 repo 的 hub 已經這樣做並有測試。
   - 訊息大小上限（本 repo 用 64 KiB）。
   - 同一時間只有一條鴨子連線；新的完成 `hello` 後取代舊的。
   - 用應用層心跳判斷連線是否還活著（本 repo：3 秒沒有任何訊息就關閉），不信任 TCP 狀態——和 AIOS 對終端心跳的理由相同（§2.4）。
5. 通道：鴨子端連 `ws://127.0.0.1:8787/duck-link`（本機 port 要等於核心 port，才過得了 Host 檢查）。可以沿用 rpi4 的 Pi 主動 `-L`（要開 Mac 的「遠端登入」），也可以由 Mac 主動 `ssh -R 127.0.0.1:8787:127.0.0.1:8787`（不必開遠端登入）。**方向要使用者決定**；對鴨子端的程式沒有差別。

風險：

| 風險 | 說明 |
|---|---|
| 第一個入站 WebSocket | AIOS 沒有先例，守門要自己寫；本 repo 的測試（路徑、Origin、Host、非 loopback）要一起搬 |
| 沒有鴨子的身分驗證 | 和 AIOS 現況一致：信任邊界是「loopback＋SSH」。Pi 上能連 `127.0.0.1:<port>` 的程式都能冒充鴨子。要不要加共用密鑰是新的機制，AIOS 目前沒有類似的東西（rpi4 的配對只是草案） |
| 通道一起轉了整個核心 | 用 `-L`／`-R` 轉核心的 port，Pi 上的程式就能呼叫核心的所有 HTTP API（rpi4 終端本來就是這樣）。若只想給 duck-link，可以讓 hub 留在獨立的 port（現在的 8791）——那就是「不搬進核心 HTTP server、只搬進核心行程」的變體 |
| 核心 port 會變 | Electron 版在 port 被占用時會換 port（`fallbackPort`，`nous.ts:235`），鴨子端的 port 設定要跟著 |

## 5. 批次 D3：鴨子事件進 Nous（DuckTerminal 的事件入口）

事實：AIOS 沒有接收裝置事件的入口；核心也沒有「主動開始一通語音」的機制可以確認（`server/proactive.ts` 是早安簡報的設定與句子，是否能由核心觸發說話**沒有查證**）。

本 repo 已有：`terminal/duck-terminal.ts` 把 duck-link 事件整理成 `TerminalEvent`（分類 `safety`／`link`／`mission`／`motion`／`wake`／`dock`／`config`，標 `notify` 或 `info`、來源是鴨子還是 hub、是否模擬），交給 `DuckEventSink`。搬進 AIOS 後要實作一個 sink。建議分三步，都是**建議**：

1. 只記錄：寫進核心的 log，並在整合狀態（`GET /api/integrations/status`）看得到鴨子是否連線。最小、沒有風險。
2. 顯示：經 SSE 給頁面（電子腦旁邊顯示「鴨子跌倒了」「鴨子到了」）。要新增一種 SSE 事件與頁面的文字。
3. 接續對話：`mission_done`／`mission_failed` 發生時，如果下指令的那通對話還在，讓模型知道結果並說出來。live 路徑的核心有 sideband，可能做得到；api_key 路徑的對話在頁面，要經頁面轉。**這一步的可行性沒有查證**，要在 AIOS 做 spike。

## 6. 批次 D4：`presence` 的真實事件來源

本 repo 已有：`terminal/presence.ts` 的 `PresenceDriver`，輸入是 `VoiceSessionEvent`（形狀對照下表的 AIOS 訊號），輸出是節流後的 `presence` 指令。現在唯一的來源是**開發用手動來源**（`duckctl presence`）。

每個 `presence` 狀態在 AIOS 有哪些真實來源（事實，取自 §2.5）：

| `presence` | 核心現在就有的來源 | 只有頁面有的來源 | 缺口 |
|---|---|---|---|
| `idle` | 沒有進行中的工作階段；`finish()` 之後 | phase `off` | 核心沒有「狀態改變」的通知 |
| `wake` | `RealtimeSessions.start(…, source = "wake_word")`（`realtime-routes.ts:378`） | 喚醒觸發 → 提示音 → 開始對話 | 核心要到 `/start` 才知道，已經在提示音之後 |
| `listening` | 已連上；live：`session.started`、助理一輪結束 | `listening`／`hearing` | api_key 路徑連上之後核心看不到 |
| `thinking` | live：使用者一輪結束、委派開始 | `thinking` | api_key（沒有記憶）沒有 |
| `speaking` | live：助理逐字稿在增加（依文字，不是依聲音） | `speaking`（api_key：`output_audio_buffer.started/stopped`；live：音軌 RMS） | 準確的「開始說／說完」只有頁面有 |
| `working` | 委派開始與結束、背景任務執行中、Dispatcher 正在執行工具 | `brain.working` | 核心有 |
| `error` | `finish(session, "connect_failed")`、`closed` 的原因是 `connection_lost`／`auth`／`usage_limit`／`error` | 電子腦的 error | 核心有 |
| `sleeping` | 沒有對應的語音概念（最接近：日夜模式、終端螢幕關閉回報、Mac 鎖定或睡眠） | — | 要先定義 |

建議分兩步做：

- **D4a（核心觀察點，粗略但兩條路徑都有）**：在 `RealtimeSessionsOptions`（`server/realtime-routes.ts:135-169`）加一個 `onSessionEvent?` 回呼，在 `start()`（帶 `source`）、`call()`（已連上）、`finish()`（帶 `reason`）以及 live 的 `LiveCoreEvent`（`delegation`、`closed`）觸發。`server/nous.ts` 把它接到 `PresenceDriver.handle()`。這樣就有 `wake`、`listening`（連上之後一律算 listening）、`working`、`error`、`idle`。**沒有** `thinking` 與 `speaking` 的邊界。
- **D4b（頁面回報 phase，準確）**：新增 `POST /api/realtime/phase {session_id, owner, phase}`，頁面在 `onPhase`（`src/main.ts:482`）呼叫；核心用既有的 `sessionAuth`（`app.ts:877-884`）驗證後轉給 `PresenceDriver`。這是在 api_key 路徑（沒有記憶）拿到「說話中」唯一的方法。只在鴨子連線時才回報，避免平常多送請求。

`speech_level`（說話時的音量）有兩個來源可選：

1. 頁面把助理音軌的 RMS 以 5 Hz 以下回報給核心 → hub → 鴨子。要改頁面與核心；api_key 路徑現在沒量助理音軌，要加。
2. **在鴨子上算**：當聲音真的從鴨子的喇叭播（路線 A），鴨子的音訊層自己量正在播的聲音，不必經過 AIOS，也沒有網路延遲。**建議採用這個**，`presence` 只送狀態、不送音量。這是建議；鴨子端的實作在 D 線（`robot/audio/`）。

風險：`presence` 每次改變都是一則 duck-link 指令；`PresenceDriver` 已經做了去抖動（120 ms）、`wake`／`error` 的最短維持時間、音量節流（每 200 ms 最多一則、變化不到 0.1 不送），並有測試。這些數值都**未經實機調整**。

## 7. 批次 D5～D7：聲音到鴨子、喚醒、指定終端

細節與理由在 [`voice-path.md`](voice-path.md)。對 AIOS 的要求整理如下：

| 批次 | 內容 | AIOS 要改什麼 |
|---|---|---|
| D5 鴨子當頁面終端（路線 A） | 鴨子的 Pi 4 跑 Chromium 開 `/?terminal=<鴨子 ID>`，聲音就從鴨子的喇叭出來 | 最少可以**完全不改 AIOS**（終端 ID 只是網址參數）；`terminals/rpi4/` 的套件要另做一份給鴨子（沒有螢幕、終端 ID 不同）。輸出裝置偏好現在是全域一份，Pi 與 Mac 的裝置 ID 不同，可能要改成分終端 |
| D6 鴨子自己的喚醒詞與多裝置仲裁 | 鴨子有自己的喚醒詞；多台同時聽到只回應一次 | 喚醒關鍵詞要能依終端設定；核心新增仲裁（ADR-0003 §3）。現況是每個頁面各自偵測、各自開始對話 |
| D7 把一通對話指定到某台終端 | 讓 Nous 透過鴨子主動開口（例如「去叫他起床」） | 現況：一通對話屬於開始它的頁面，聲音只在那個頁面播。要新增核心 → 指定頁面「開始一通對話」的推送。**可行性未查證** |

## 8. AIOS 批次清單與建議順序

| 順序 | 批次 | 內容 | 完成後多了什麼 | 主要風險 |
|---|---|---|---|---|
| 1 | D1 | `/duck-link` 端點與 hub 進核心（`NOUS_DUCK`） | 鴨子能連上 Nous 核心 | 第一個入站 WebSocket、守門、通道方向 |
| 2 | D2 | 註冊 `duck` adapter（先開有硬體的工具） | 用語音叫鴨子轉頭、點頭、停下、查狀態 | 工具表變長、基準檔、依賴 |
| 3 | D4a | 核心的工作階段觀察點 → `presence`（粗略） | 鴨子在 Nous 對話開始、結束、工具執行時有反應 | 要動 `RealtimeSessions` |
| 4 | D3 | 鴨子事件進核心（先記錄與顯示） | 跌倒、斷線、任務結果看得到 | 「接續對話」的可行性未查證 |
| 5 | D4b | 頁面回報 phase → `presence`（準確） | 鴨子跟著「聽、想、說」做動作 | 頁面與核心都要改 |
| 6 | D5 | 鴨子當頁面終端（要先有麥克風） | Nous 的聲音從鴨子出來、對鴨子說話 | Pi 4 的負載、無螢幕跑 Chromium、回音消除，都要 spike |
| 7 | D6、D7 | 喚醒詞與仲裁、指定終端 | 叫鴨子的名字、Nous 透過鴨子主動開口 | 都是新機制 |

順序 1～3 不需要任何新硬體，用現在的頭部舵機就能驗證。每一個批次在 AIOS 都要有自己的測試與驗證紀錄；本 repo 這一端對應的程式與測試已經有了（見 [`../README.md`](../README.md)），但「在 AIOS 裡能用」要等那邊做完才算。

## 9. 還沒查證的事

- Ajv standalone 產出在 AIOS 的環境是否可用。
- live 路徑的 sideband 是否真的送 `speech.started` 與 `audio.done`（AIOS 自己也標示未證實）。
- 核心能不能主動讓某個頁面開始一通對話；鴨子事件能不能插進進行中的對話。
- `mock: "config"` 的 adapter 在 `checkCatalog()` 與指令頁的表現（`voice_relay` 是先例，但沒有實際跑過 duck 的 catalog）。
- 沒有麥克風時，Nous 頁面能不能開始一通對話（推測不行，沒有驗證）。
