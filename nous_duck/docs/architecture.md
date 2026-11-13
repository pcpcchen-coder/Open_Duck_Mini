# Nous Duck 架構：鴨子與 Nous 的分工和資料流

狀態：**草案**（2026-11-12；同日依 [R-001 行動夥伴需求](requirements/R-001-mobile-companion.md) 修訂，見 [§9](#9-2026-11-12-修訂行動夥伴)）。本文件描述目標架構；除了特別標明的上游既有程式，其餘都是**規劃中**，還沒有實作。決策理由見 [ADR-0001](adr/ADR-0001-duck-role-in-nous.md)。

參考來源（唯讀查閱，2026-11-12）：

- AIOS `main`：`prototype/ambient-shell/server/integrations/contracts.ts`、`prototype/ambient-shell/shared/integrations.ts`、`terminals/rpi4/README.md`、`docs/Current_Implementation_Status.md`、`docs/BILINGUAL.md`。
- 上游 Open_Duck_Mini_Runtime `v2`（commit `376de65`）：`scripts/v2_rl_walk_mujoco.py`、`mini_bdx_runtime/xbox_controller.py`、`example_config.json`。

## 1. 一句話

**Nous 是大腦，鴨子是身體。** Nous（Mac mini）負責聽、看、記、想；鴨子（Pi Zero 2 W）負責站、走、動頭、做表情，並且**自己保護自己**。兩邊只透過 duck-link 協定（`nous_duck/protocol/`）交換 JSON 訊息。

## 2. 元件與部署

```text
┌──────────────────────── Mac mini（Nous App，AIOS） ────────────────────────┐
│  即時語音 / 視覺 / 記憶 / Agent 決策                                          │
│        │ 呼叫工具 app.duck.*                    ▲ 事件（跌倒、電量低…）        │
│        ▼                                        │                            │
│  DuckAdapter（IntegrationAdapter）  ◄──►  DuckTerminal（事件、表情輸出）      │
│        └──────────────┬──────────────────────────┘    nous_adapter/（TS）    │
│                       │ duck-link client（JSON，依 protocol/schemas 驗證）    │
└───────────────────────┼─────────────────────────────────────────────────────┘
                        │ 傳輸：待決（見 §6）
┌───────────────────────┼──────────── Pi Zero 2 W（鴨子） ─────────────────────┐
│  nous_link（duck-link server，驗證 schema）                 robot/nous_link/   │
│        │ 意圖（走、看、手勢、表情）            ▲ 狀態與事件                     │
│        ▼                                        │                            │
│  behaviors（意圖 → runtime 指令、預錄動作）                 robot/behaviors/   │
│        │                                                                    │
│  safety（指令上限、TTL、跌倒/過熱/低電壓/斷線處理）—— 最後一道關卡  robot/safety/ │
│        │ 7 維指令向量                                                       │
│        ▼                                                                    │
│  Open_Duck_Mini_Runtime v2（上游，pip 鎖 commit）：ONNX 步態策略 50 Hz         │
│        │                                                                    │
│  STS3215 × 14（匯流排）、IMU BNO055、足底開關 × 4、天線舵機 × 2、（表情套件）   │
└─────────────────────────────────────────────────────────────────────────────┘
```

| 元件 | 位置 | 狀態 |
|---|---|---|
| Open_Duck_Mini_Runtime v2 | 鴨子 | **上游既有**；尚未在本機身實機跑過 |
| `robot/nous_link`、`behaviors`、`safety` | 鴨子 | 規劃中 |
| `protocol/schemas` | 共用 | 規劃中 |
| `nous_adapter/adapters`（DuckAdapter） | Mac（之後搬進 AIOS） | 規劃中 |
| `nous_adapter/terminal`（DuckTerminal） | Mac（之後搬進 AIOS） | 規劃中 |
| `sim/` | 開發機 | 規劃中 |

## 3. 職責切分

| 能力 | Nous（Mac mini） | 鴨子（Pi Zero 2 W） |
|---|---|---|
| 語音辨識、對話、TTS | ✅ | 收音與播放（麥克風陣列、喇叭；R-001 修訂，見 §9），不做辨識與生成 |
| 視覺（人臉、手勢） | 人臉比對（gallery 留在 Mac） | 雙目擷取、人臉偵測與特徵、定位與避障（R-001 修訂，見 §9） |
| 記憶、決策、排程 | ✅ | ✗ |
| 步態（ONNX 策略推論） | ✗ | ✅（上游 runtime，50 Hz） |
| 頭部、天線、預錄動作 | 下達意圖 | ✅ 執行與插值 |
| 安全（跌倒、過熱、低電壓、斷線、指令上限） | ✗（只能接收事件） | ✅ **唯一權威** |
| 舵機設定、ID、零點校正 | ✗（刻意不提供工具） | ✅ 只能在本機以 CLI 執行 |

原則：

1. **安全在鴨子本機**。Nous 當機、Wi-Fi 斷線或模型下錯指令時，鴨子仍能停住並保持站立或安全姿勢。
2. **Nous 只下意圖，不下關節角度流**。例如「往前走 0.1 m/s、最多 3 秒」，而不是每 20 ms 送一次 14 個關節角度。即時控制迴圈留在鴨子上。
3. **協定是唯一介面**。兩邊不共用程式碼；改介面先改 `protocol/schemas` 並升版。

## 4. 與上游 runtime 的接點

上游 `v2_rl_walk_mujoco.py` 在 `--commands` 模式下，每個迴圈從 `XBoxController.get_last_command()` 讀一個 7 維指令向量：

| 索引 | 意義 | 上游手把映射範圍（`xbox_controller.py`） |
|---|---|---|
| 0 | lin_vel_x（前後，m/s） | −0.15～0.15 |
| 1 | lin_vel_y（左右，m/s） | −0.2～0.2 |
| 2 | ang_vel（轉向，rad/s） | −1.0～1.0 |
| 3 | neck_pitch（rad） | −0.34～1.1（手把目前固定 0） |
| 4 | head_pitch（rad） | −0.78～0.3 |
| 5 | head_yaw（rad） | −0.5～0.5 |
| 6 | head_roll（rad） | −0.5～0.5 |

規劃：`robot/` 提供一個與 `XBoxController` 相同介面的指令來源（來自 duck-link，經 `safety` 夾限），以**包裝**方式接進 runtime，而不 fork runtime。若包裝做不到（例如需要改 runtime 內部迴圈），先寫 ADR 再決定是否 fork。手把仍保留為本機優先的人工控制來源。

上游 `example_config.json` 的 `expression_features`（eyes、projector、antennas、speaker、microphone、camera）決定哪些表情硬體存在；`app.duck.*` 的 capability 狀態要從這份設定推導，硬體不存在就回 `unsupported`。

## 5. 資料流

### 5.1 Nous 叫鴨子做事

```text
使用者說「鴨子往前走兩步」
 → Nous Agent 選工具 app.duck.walk {vx: 0.1, duration_s: 2}
 → DuckAdapter.execute：依 protocol 組 command 訊息（含 request_id、ttl_ms）
 → duck-link → nous_link 驗證 schema → behaviors 轉成指令 → safety 夾限
 → runtime 執行；鴨子回 ack（accepted / rejected + 原因）與 state
 → DuckAdapter 依回讀結果對應 ToolResult：
     ack accepted 且 state 顯示 mode=walking → confirmed
     已送出但沒收到 ack → unknown（不能推定沒執行）
     safety 拒絕（例如已跌倒、電量低） → refused
```

`confirmed` 的意思是「鴨子已接受並開始執行」，**不是**「已走完兩步」；完成與否由後續 `state`／`event` 回報。這要寫進工具說明，讓模型不要說「已經走到了」。

### 5.2 鴨子主動回報

```text
IMU 偵測跌倒 → safety 立即停止步態（本機，不等 Nous）
 → nous_link 送 event {type: "fell", ...}
 → DuckTerminal 轉成 Nous 的事件；Nous 決定要不要說「我跌倒了」
```

事件草案：`fell`、`picked_up`、`battery_low`、`overheat`、`motor_error`、`link_lost`／`link_restored`、`estop`（本機按鈕或手把）。

### 5.3 斷線

- 每個會產生動作的 command 都帶 `ttl_ms`；逾時沒有續約，鴨子自己停下並站好（deadman）。
- duck-link 心跳中斷超過門檻，鴨子進入安全姿勢並記錄 `link_lost`；恢復後回報 `link_restored`，**不自動恢復斷線前的動作**。
- 門檻數值待模擬與實機量測後決定，現在不寫死。

## 6. 傳輸（待決）

候選方案與考量，決定前不實作：

| 方案 | 優點 | 缺點 |
|---|---|---|
| A. 比照 AIOS `terminals/rpi4`：鴨子以 autossh 本地轉送連 Mac 的 `127.0.0.1:<AIOS_PORT>`，走 WebSocket | 沿用 AIOS 已有實機紀錄的模式；Nous 核心維持只聽 loopback，不放寬 `http-guard` | Pi Zero 2 W 要維持 SSH 通道；需要 AIOS 核心新增 duck-link 端點 |
| B. 鴨子自己開 WebSocket server，Mac 端 adapter 當 client 連過去 | AIOS 核心不用開新的入站端點 | 鴨子對區域網路開 port，要另外做驗證 |
| C. MQTT broker | 解耦、可重連 | 多一個常駐服務；對單一裝置而言過重 |

AIOS 的 rpi4 終端文件明確要求核心只聽 `127.0.0.1`、不要為了連線放寬檢查；選方案時必須遵守。

## 7. `app.duck.*` 工具（初版草案）

完整清單、effect 分類與刻意不提供的操作見 [ADR-0001 §4](adr/ADR-0001-duck-role-in-nous.md#4-appduck-工具清單草案)。摘要：

| 工具 ID | effect |
|---|---|
| `app.duck.status` | read |
| `app.duck.walk` | reversible_write |
| `app.duck.stop` | reversible_write |
| `app.duck.look` | reversible_write |
| `app.duck.gesture` | reversible_write |
| `app.duck.antennas` | reversible_write |
| `app.duck.express` | reversible_write（需要表情套件；沒有硬體時 `unsupported`） |

初版沒有 `external_commit` 工具。R-001 修訂後新增 `where`、`places`、`mission_status`、`go_to`、`find_person`、`return_home`、`cancel_mission`、`announce`，見 [ADR-0001 §7.3](adr/ADR-0001-duck-role-in-nous.md#73-工具清單修訂後草案)。

## 8. 待決事項

1. 傳輸方案（§6）。
2. 心跳、TTL、跌倒判定的門檻（需要模擬與實機數據）。
3. 表情套件（喇叭、眼燈、投影）是否製作；決定後才定 `app.duck.express` 與 DuckTerminal 的輸出能力。
4. ~~鴨子要不要接麥克風或鏡頭成為完整的 Nous 終端~~：已由 R-001 決定要接，見 §9 與 ADR-0003。
5. 鎖定的 Open_Duck_Mini_Runtime commit，以及包裝指令來源的方式是否可行（需要實際讀 runtime 並在模擬中驗證）。

## 9. 2026-11-12 修訂：行動夥伴

使用者提出 [R-001](requirements/R-001-mobile-companion.md)：室內導航（不能用步數推估）、鴨子帶麥克風／喇叭／雙目鏡頭到處對話、自己的喚醒詞與找人、自動回充。本節是修訂後的架構；§1～§8 未被本節取代的部分仍然有效。

### 9.1 修訂後的元件

```text
┌──────────────────── Mac mini（Nous） ────────────────────┐
│ 語音辨識／對話／TTS、記憶、Agent、任務編排              │
│ 聲紋與人臉比對（gallery 只在這裡）、離線建圖              │
│ DuckAdapter（app.duck.*）  DuckTerminal（語音、事件）    │
└──────────────┬───────────────────────────────────────────┘
               │ duck-link（JSON 控制）＋ 媒體串流（語音）；傳輸待決
┌──────────────┼──────────── 鴨子 ────────────────────────┐
│ 感知板 Raspberry Pi 4（ADR-0005）＋AR0144 雙目＋麥克風陣列 │
│   雙目 → VIO＋AprilTag＋深度 → 定位、導航、避障（ADR-0002）│
│   麥克風陣列 → 喚醒詞、聲源方向、語音串流（ADR-0003）    │
│   人臉偵測與特徵（比對送 Mac）、喇叭                     │
│   回充對位（ADR-0004）                                   │
│        │ 速度指令（vx, vy, yaw_rate）＋頭部目標           │
│ 身體板（Pi Zero 2 W，上游 runtime）                      │
│   safety（最後一道關卡）→ ONNX 步態 50 Hz → 舵機 × 14    │
│ 電池＋充電板＋BMS ← 充電座觸點                           │
└──────────────────────────────────────────────────────────┘
```

### 9.2 分工更新

| 能力 | Nous（Mac mini） | 鴨子 |
|---|---|---|
| 定位與導航 | 離線建圖、地點命名、任務決策 | 即時定位（**不用步數**）、路徑規劃、避障、禁區保護（感知板） |
| 對話 | 語音辨識、生成、TTS | 收音、播放、聲源方向 |
| 喚醒 | 多裝置仲裁、聲紋辨認 | 本機喚醒詞偵測 |
| 找人 | 臉部與聲紋比對、決定目標 | 移動、人臉偵測與特徵 |
| 回充 | 決定何時回家 | 對位、確認充電（電氣訊號） |
| 安全 | 接收事件 | 唯一權威（身體板） |

### 9.3 資料流：長時間任務

```text
Nous：app.duck.go_to {place: "brother_room"}
 → 鴨子接受 → ToolResult confirmed（data: mission_id）——代表「已出發」
 → 導航中：event mission_progress（目前地點、剩餘路段）
 → 到達：event mission_done ／ 失敗：event mission_failed（door_closed、lost、blocked、fell、low_battery…）
 → DuckTerminal 把事件送進 Nous，Agent 接續下一步（例如 find_person、說話、return_home）
```

詳見 [ADR-0001 §7](adr/ADR-0001-duck-role-in-nous.md#7-2026-11-12-修訂行動夥伴)。各階段順序與 gate 見 [路線圖](roadmap.md)。

### 9.4 隱私設定

隱私規則可開關（全域、房間、家人、模式），在資料產生處執行：鏡頭、麥克風、房間進入由鴨子（Pi 4）檢查；臉部與聲紋比對由 Mac 核心檢查。模型只能收緊、不能放寬。見 [ADR-0006](adr/ADR-0006-privacy-settings.md)。
