# ADR-0001：鴨子在 Nous 中的角色＝身體 adapter 加終端

- 狀態：**草案（Proposed）**
- 日期：2026-11-12；同日依 R-001（行動夥伴需求）修訂，見 [§7](#7-2026-11-12-修訂行動夥伴)
- 相關：[`../architecture.md`](../architecture.md)、AIOS `prototype/ambient-shell/server/integrations/contracts.ts`（AIL-1）、AIOS `terminals/rpi4/`

## 1. 背景

使用者正在製作一隻原版尺寸的 Open Duck Mini v2（Pi Zero 2 W、14 顆 STS3215、BNO055 IMU、上游 RL 步態策略），並且已經有一套跑在 Mac mini 上的 Nous（AIOS）：即時語音、視覺、長期記憶與 Agent 決策都在 Mac。要決定的是：鴨子在 Nous 裡算什麼？

AIOS 現有兩種可以對應的概念：

1. **Integration Adapter（AIL-1）**：`IntegrationAdapter` 介面，提供工具 `app.<service>.<action>`，每個工具宣告 `effect`（`read`／`reversible_write`／`external_commit`）、`timeoutMs`、`supportedRoutes`；結果用 `ToolResult`，只有 `confirmed` 才能說完成。已有 Spotify、LG 電視、家電等 adapter。Adapter 只能在程式碼中明確註冊，由 `NOUS_AIL_SERVICES` 啟用，模型不能新增工具。
2. **終端（Terminal）**：例如 `terminals/rpi4`，Raspberry Pi 4 用自己的螢幕、麥克風、喇叭、鏡頭當 Nous 的輸入輸出端，Agent 與資料都留在 Mac；Pi 經 SSH 轉送連 Mac 的 loopback。

Pi Zero 2 W 的算力只夠跑步態策略與基本 I/O，不適合跑語音或視覺模型。鴨子目前也沒有麥克風與鏡頭。

## 2. 決定

鴨子在 Nous 中有**兩個角色**，都放在 `nous_duck/nous_adapter/`，之後搬進 AIOS：

1. **身體 adapter（DuckAdapter）**：一個 AIOS `IntegrationAdapter`，`service = "duck"`，把鴨子的動作能力以 `app.duck.*` 工具提供給 Nous 的 Agent。這是 Nous **呼叫**鴨子的方向。
2. **終端（DuckTerminal）**：把鴨子的事件（跌倒、被抱起、電量低、斷線）送進 Nous，並把 Nous 決定的表情輸出（天線、眼燈、音效，視硬體而定）送給鴨子。這是鴨子**通知** Nous、以及 Nous 用鴨子**表達**的方向。和 rpi4 終端不同，DuckTerminal 初期**沒有**麥克風、鏡頭或螢幕。（**已由 §7 修訂**：鴨子將有麥克風、喇叭與雙目鏡頭，成為會走路的終端。）

此外：

3. **鴨子本機是安全的唯一權威**。跌倒、過熱、低電壓、通訊中斷、指令超出範圍，由 `robot/safety/` 在本機處理；Nous 送來的任何指令都要通過 safety 才會執行。Nous 不能關閉或繞過 safety。
4. **兩邊只透過 duck-link 協定溝通**（`nous_duck/protocol/` 的版本化 JSON Schema）。
5. **Nous 只下意圖**（速度＋時長、頭部目標姿態、手勢名稱），不串流關節角度；即時控制留在鴨子上的上游 runtime。

## 3. 理由

- 沿用 AIOS 已有、已審核的 adapter 契約，鴨子的工具自動得到 AIOS 的註冊、啟用、頻率限制、結果語意與診斷頁，不需要在 AIOS 新增一套機制。
- 把安全放在鴨子本機，避免 Wi-Fi 延遲或 Nous 當機造成跌倒或燒舵機。這也符合 Nous「工具結果不明時回報 unknown、不假裝成功」的誠實規則：網路斷了，鴨子仍然安全，Nous 誠實回報不知道結果。
- 分成 adapter 與 terminal 兩個角色，是因為方向不同：adapter 是「模型呼叫工具」，有 effect 與確認語意；terminal 是「裝置事件與輸出」，不經過模型的工具表。混在一起會讓事件變成模型要輪詢的工具，或讓輸出繞過 effect 分類。

## 4. `app.duck.*` 工具清單草案

規則：ID 符合 AIOS 的 `^app\.(seg)\.(seg)$`（小寫英數、單一底線分段），wire name 為 `app__duck__<action>`。effect 依 AIOS 定義：`read` 只查詢；`reversible_write` 可撤回的改變；`external_commit` 寄出、發布、付費、永久刪除等。

| 工具 ID | effect | 說明（草案） | 參數草案 | 回讀確認方式 |
|---|---|---|---|---|
| `app.duck.status` | `read` | 連線、模式（idle／standing／walking／fallen／estop）、電池電壓、姿態、溫度摘要、可用能力 | 無 | 直接回傳最新 state（附時間戳；過舊標示 stale） |
| `app.duck.walk` | `reversible_write` | 以有限速度走一段時間，時間到自動停 | `vx`、`vy`（m/s）、`yaw_rate`（rad/s）、`duration_s`（上限待定） | ack accepted 且 state 為 walking → `confirmed`；鴨子端依 safety 上限夾限並在 ack 回報實際值 |
| `app.duck.stop` | `reversible_write` | 停止步態、站好 | 無 | state 為 standing → `confirmed`。鴨子端任何時候都接受，不受頻率限制 |
| `app.duck.look` | `reversible_write` | 頭部看向目標姿態 | `neck_pitch`、`head_pitch`、`head_yaw`、`head_roll`（rad）、`duration_s` | ack＋state 回讀頭部目標 |
| `app.duck.gesture` | `reversible_write` | 執行鴨子端白名單內的預錄動作（例如點頭、搖頭、歪頭） | `name`（列舉，來自鴨子回報的清單） | ack accepted → `confirmed`（代表已開始） |
| `app.duck.antennas` | `reversible_write` | 天線位置或擺動 | `left`、`right`（−1～1）或 `pattern` | ack＋state |
| `app.duck.express` | `reversible_write` | 眼燈、投影燈、音效 | `eyes`、`projector`、`sound`（列舉） | 依上游 `expression_features` 推導；硬體不存在 → capability `unsupported` |

設計說明：

- **初版沒有 `external_commit` 工具**。鴨子的動作對外部世界沒有寄出、付費、永久刪除這類不可撤回的後果。
- 但**物理動作的風險不等於 effect 分類**。AIOS 的 effect 描述資料面的可逆性，不描述「會不會撞到東西或摔下桌」。所以 `walk` 雖然是 `reversible_write`，仍要有鴨子端的速度與時長上限、TTL、跌倒偵測，以及（之後評估）Nous 端的使用情境限制。這些限制的位置是鴨子本機，不是 Nous 的確認對話框。
- `confirmed` 代表「鴨子已接受並開始」，不代表動作完成；工具說明要讓模型明白這點。
- 支援的路徑（`supportedRoutes`）初版只列即時語音兩條（`api_key`、`live`）；`page`、`text`、`background` 待需要時再加。

刻意**不提供**給模型的操作（只能在鴨子本機用 CLI 或實體按鈕）：

| 操作 | 原因 |
|---|---|
| 關閉舵機扭力、關機、重新開機 | 扭力一放鴨子會直接倒下；屬於本機人工操作 |
| 寫入舵機 ID、零點 offset、PID | 會改變硬體設定，錯了可能撞壞機構 |
| 更新 ONNX 策略或 runtime | 部署行為，走 `robot/deploy/` 的人工流程 |
| 原始關節角度串流 | 違反「Nous 只下意圖」；繞過步態策略與 safety |

## 5. 後果

- 需要建立 `protocol/schemas`（command、state、event）並版本化，Mac 與 Pi 兩端都用同一份 schema 驗證。
- AIOS 之後要新增 `duck` adapter 到已審核清單，以及 DuckTerminal 的事件入口；這些變更屬於 AIOS repo 的批次，不在本 repo 宣稱完成。
- 鴨子端要把上游 runtime 的指令來源從手把換成（或並列）duck-link；以包裝為優先，必要時另寫 ADR 決定是否 fork runtime。
- 測試需要兩層：協定與 adapter 可以在雲端用 mock 鴨子測（必須標示 mock）；動作與安全只能在模擬（`sim/`）與實機驗證。

## 6. 待決

1. 傳輸方案（見 [`architecture.md` §6](../architecture.md#6-傳輸待決)）。
2. 各工具的參數上限、TTL、心跳門檻。
3. DuckTerminal 在 AIOS 中對應哪個現有概念（例如終端頁面識別 `ExecutionContext.page`、或新的裝置事件來源）。
4. 是否需要「使用情境限制」（例如只有使用者在場時才能 `walk`）；依 AIOS 2026-10-31「功能便利性優先」的優先順序，初版不做，留待使用者決定。

## 7. 2026-11-12 修訂：行動夥伴

使用者在同日提出 [R-001](../requirements/R-001-mobile-companion.md)：室內導航、鴨子帶麥克風／喇叭／雙目鏡頭到處對話、自己的喚醒詞與找人、自動回充。修訂如下，§1～§6 其餘內容仍然有效。

### 7.1 角色

- **DuckTerminal 改為完整的行動終端**（麥克風、喇叭、雙目鏡頭；沒有螢幕），比照 AIOS rpi4 終端，詳見 [ADR-0003](ADR-0003-mobile-terminal-wake-and-find.md)。
- 「Nous 只下意圖」維持不變，意圖的層級提高到**地點與任務**（「去 `brother_room`」），導航與避障在鴨子本機完成（[ADR-0002](ADR-0002-indoor-localization-and-navigation.md)）。
- 安全仍以鴨子本機為唯一權威；新增樓梯與禁區保護（ADR-0002 §5.3）、充電觸點電氣安全（[ADR-0004](ADR-0004-docking-and-charging.md) §2.3）。

### 7.2 長時間任務（mission）

走到另一個房間要幾十秒到幾分鐘，超過 AIOS 工具單次執行時限（`timeoutMs` 上限 60 s）。因此導航類工具採**非同步任務**：

1. 工具呼叫只負責**下達任務**：鴨子接受並開始執行就回 `confirmed`，`data` 帶 `mission_id`。工具說明要寫清楚：`confirmed` 代表「已出發」，不是「已到達」。
2. 進度與結果以 duck-link 事件（`mission_progress`、`mission_done`、`mission_failed`，附原因代碼）回報，經 DuckTerminal 送進 Nous。
3. 任何時候可以用 `app.duck.cancel_mission` 或 `app.duck.stop` 中止。
4. 同一時間只有一個進行中的任務；新任務要先取消舊的，或由鴨子回 `refused`（原因代碼待定）。

Nous Agent 收到完成事件後接續下一步，需要 AIOS 支援（見 [路線圖](../roadmap.md#aios-端需要的批次在-aios-repo-進行)）。

### 7.3 工具清單（修訂後草案）

§4 的 7 個工具保留，新增：

| 工具 ID | effect | 說明（草案） | 參數草案 | 回讀確認方式 |
|---|---|---|---|---|
| `app.duck.where` | `read` | 目前所在房間／地點、定位不確定度、是否在充電座 | 無 | 最新 state（附時間戳） |
| `app.duck.places` | `read` | 地圖上已命名的地點清單（ID 與本機顯示名稱） | 無 | 鴨子回報的地圖版本 |
| `app.duck.mission_status` | `read` | 目前任務的狀態與進度 | `mission_id`（可省略） | 最新 state |
| `app.duck.go_to` | `reversible_write` | 導航到某個地點 | `place`（地點 ID，來自 `places`） | 接受並開始 → `confirmed`＋`mission_id` |
| `app.duck.find_person` | `reversible_write` | 在附近找人（可指定是誰），找到後面向對方 | `person`（家人 ID，可省略） | 同上 |
| `app.duck.return_home` | `reversible_write` | 回充電座並確認開始充電 | 無 | 同上；「已充電」以電氣訊號為準 |
| `app.duck.cancel_mission` | `reversible_write` | 取消目前任務並停下 | `mission_id`（可省略） | state 無進行中任務 → `confirmed` |
| `app.duck.announce` | `reversible_write` | 用鴨子的喇叭播一段話（不開啟對話） | `text` | 待定；若 AIOS 能把語音工作階段指定到鴨子終端，可能不需要這個工具 |

刻意不提供給模型的操作，新增：

| 操作 | 原因 |
|---|---|
| 建圖、編輯地圖、畫禁區、刪除地圖 | 會影響安全（樓梯禁區）；由使用者在 Mac 上的工具操作 |
| 開關 safety 的樓梯／禁區保護 | 安全是鴨子本機的權威 |
| 讀取或傳送原始影像、錄音 | 違反隱私規則（ADR-0003 §6） |
