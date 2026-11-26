# ADR-0009：duck-link 傳輸與鴨子端指令橋接

- 狀態：**部分採用**（2026-11-26 使用者決定 §6 的三項：runtime 鎖 `376de65`、緊急停止用手把組合鍵加機身按鈕、暫停時讀電壓）；傳輸方案與其餘部分仍為**草案**。設計稿，尚無程式、尚無模擬或實機驗證
- 日期：2026-11-13；2026-11-26 依 [ADR-0008](ADR-0008-single-board-pi4.md)（單板 Pi 4）與使用者決定修訂。原本以 ADR-0007 的編號提出，因 ADR-0007 已用於「跟著我來」而改為 0009
- 相關：[ADR-0001](ADR-0001-duck-role-in-nous.md)（角色與工具）、[`architecture.md` §4–§6](../architecture.md#6-傳輸待決)、[ADR-0002](ADR-0002-indoor-localization-and-navigation.md)（導航）、[ADR-0007](ADR-0007-follow-me-and-wait-here.md)（停止管道）、[ADR-0008](ADR-0008-single-board-pi4.md)（單板 Pi 4）、[`protocol/`](../../protocol/README.md)、[`robot/`](../../robot/README.md)、[`robot/servo_console/`](../../robot/servo_console/README.md)

## 1. 背景

[`architecture.md` §6](../architecture.md#6-傳輸待決) 把 duck-link 的傳輸列為待決，§4 規劃「以和 `XBoxController` 相同介面的指令來源包裝接入上游 runtime」，但還沒確認做不做得到。本 ADR 補上這兩件事：

1. duck-link 用什麼傳輸連到 Nous。
2. 鴨子端怎麼把 duck-link 的意圖接進上游 runtime，讓 safety 成為最後一道關卡，並在不改上游的前提下完成。

本文只描述設計；schema 檔、程式與測試是後續批次。

### 1.1 上游 runtime 的事實（唯讀查閱）

查閱 `apirrone/Open_Duck_Mini_Runtime` `v2` 的 commit `376de65`（2026-09-07）。這也是 [ADR-0008 §2.2](ADR-0008-single-board-pi4.md#22-系統與-python) 與 [`setup_runtime.sh`](../../robot/deploy/pi4/setup_runtime.sh) 在 Pi 4 上鎖定的 commit。

| 項目 | 內容 | 位置 |
|---|---|---|
| 主迴圈 | `RLWalk.run()`，50 Hz；超時會印出 `Policy control budget exceeded` | `scripts/v2_rl_walk_mujoco.py` |
| 指令來源 | `--commands` 預設為真；`RLWalk.__init__` 直接建立 `XBoxController(20)`，每圈呼叫 `get_last_command()`，回傳 `(last_commands, buttons, left_trigger, right_trigger)`。**暫停時也會先呼叫一次**，再 `sleep(0.1)` | 同上、`mini_bdx_runtime/xbox_controller.py` |
| 手把斷線 | `get_last_command()` 讀不到新值時沿用上一筆，**鴨子會照最後的速度繼續走** | `xbox_controller.py` |
| 按鍵 | 主迴圈讀 `A.triggered`（切換暫停）、`B`（音效）、`X`（投影）、`LB.is_pressed`（加快步頻）、`dpad_up／down.triggered`；`Y` 在 `XBoxController` 內部切換頭部模式；**`RB` 沒有用途** | `v2_rl_walk_mujoco.py`、`xbox_controller.py`、`buttons.py` |
| 暫停 | `self.paused` 為真時迴圈只 `sleep(0.1)`，不再送馬達目標；扭力仍開著，馬達停在當下目標 | `v2_rl_walk_mujoco.py` |
| IMU | `Imu.get_data()` 會**取走**佇列中的新值；最新值另存在 `last_imu_data`（`gyro`、`accelero`） | `mini_bdx_runtime/raw_imu.py` |
| 跌倒偵測 | 沒有 | — |
| 打包 | `setup.cfg` 只打包 `mini_bdx_runtime`；`scripts/`（含主迴圈與 `polynomial_coefficients.pkl`）**不會**隨 `pip install` 安裝。`setup_runtime.sh` 已改為 git clone 鎖定的 commit 再 `pip install -e`，所以 Pi 4 上有 `scripts/` | `setup.cfg`、`setup_runtime.sh` |

## 2. 決定

### 2.1 傳輸：鴨子主動經 SSH 通道連 Nous 核心的 loopback，走 WebSocket（草案）

採 [`architecture.md` §6](../architecture.md#6-傳輸待決) 的**方案 A**：

```text
鴨子 nous_link（WebSocket client）
  ──ws://127.0.0.1:<AIOS_PORT>/duck-link──> Pi 4 本機 127.0.0.1:<AIOS_PORT>
  ──SSH local forward（autossh）──> Mac 127.0.0.1:<AIOS_PORT> ──> Nous 核心 duck-link 端點
```

- **沿用 AIOS `terminals/rpi4` 的作法**（AIOS `main` `7b0257d` 查閱）：核心只聽 `127.0.0.1`，不放寬 `http-guard`；鴨子本機 port 等於 Mac 核心 port；專用 SSH key、`StrictHostKeyChecking=yes`、事先比對主機指紋。
- **一條通道給 duck-link 與終端共用**。ADR-0003 路線 A 的終端頁面要走同一條通道（2 GB 的 Pi 4 可能跑不動 Chromium，見 ADR-0008 §4.3；就算改走路線 B，duck-link 仍用這條通道）。
- **duck-link 不對區域網路開 port**。認證與加密由 SSH 負責；duck-link 訊息內不帶密碼或金鑰。舵機控制台（`robot/servo_console/`）是本機開發工具，有自己的網頁 port，不屬於 duck-link，也不能和步態服務同時執行（§2.4 第 6 項）。
- **端點位置**：單板（ADR-0008）時，autossh 與 nous_link 都在 Pi 4，歸在「步態＋安全」這組服務（ADR-0008 §2.1）。若依 ADR-0008 §2.5 拆回雙板，這組服務整個搬到 Pi Zero 2 W，規則不變。
- **需要 AIOS 的批次**：核心新增 `/duck-link` WebSocket 端點，屬於 AIOS repo 的工作。完成前，`nous_adapter/tests/` 用本機假核心（必須標示 mock）測試。

不採用的方案：

| 方案 | 不採用的原因 |
|---|---|
| B. 鴨子開 WebSocket server | 鴨子要對區域網路開 port，另外做認證與加密；終端頁面仍然需要 SSH 通道，等於維護兩套連線 |
| C. MQTT | 多一個常駐服務，對單一裝置太重 |
| 由 Mac 以 UDP 串流速度設定值 | 違反 ADR-0001「Nous 只下意圖」；Wi-Fi 抖動直接變成步態抖動 |

### 2.2 訊息層：連線租約與指令時效（草案）

schema 檔在 `protocol/` 另開批次定義；本節只定行為，欄位名稱為草案。

1. **每則訊息**都有 `protocol_version`、`type`、`sent_at_ms`；指令另有 `request_id`、`ttl_ms`。
2. **連線租約**：Nous 每 500 ms 送一次 `heartbeat`；鴨子連續 1.5 s 沒收到，就視為斷線。
3. **動作的三重期限**：`walk {vx, vy, yaw_rate, duration_s}` 由鴨子**本機計時執行**，Nous 不串流速度。只要以下任一條件成立就停：
   - `duration_s` 到期（上限 3 s，超過就夾限並在 ack 回報）；
   - 指令的 `ttl_ms` 到期且沒有被新的 `walk` 取代；
   - 連線租約失效。

   所以 Wi-Fi 斷線時，鴨子最慢在 1.5 s 內開始停下，而 Nous 不需要每 20 ms 送一次指令。
4. **ack**：每個指令回 `accepted`／`rejected`，附固定列舉的原因代碼（例如 `estop_latched`、`fallen`、`low_voltage`、`link_degraded`、`controller_active`、`out_of_range`、`busy_mission`），以及**夾限後實際執行的值**。
5. **state**：鴨子每 1 s 送一次，內容包括：
   - mode、control_source、目前指令與剩餘時間；
   - 傾角、足底接觸、迴圈超時次數、故障清單；
   - 最近一次電壓讀值與讀取時間（§2.6）。

   導航相關欄位依 ADR-0002 另加。
6. **event**：`fell`、`estop`（附來源：`gamepad`／`body_button`）、`estop_reset`、`link_lost`／`link_restored`、`battery_low`、`controller_takeover`（手把接管）。斷線恢復後**不自動繼續**斷線前的動作。

`app.duck.*` 的結果對應沿用 ADR-0001：`accepted` 且 state 顯示正在執行 → `confirmed`（代表「已接受並開始」，不是「走到了」）；送出後沒有 ack → `unknown`；被拒絕 → `refused`。

### 2.3 鴨子端：三個程序、一個仲裁器（草案）

```text
┌ 程序 1：nous_link（systemd，Python）───────────────────┐
│ WebSocket client、schema 驗證、心跳、ack／state／event    │
│ 把驗證過的意圖寫到本機 UNIX datagram socket               │
└───────────────┬────────────────────────────────────────┘
                │ 最新一筆有效（latest-wins），不排隊
┌ 程序 2：runtime host（systemd，Python；步態專用核心）────────┐
│ 載入上游 RLWalk（不改原檔），把指令來源換成 CommandArbiter    │
│ CommandArbiter（每圈呼叫一次，只做便宜的運算）：             │
│   來源：Xbox 手把、機身緊急停止鈕、duck-link 意圖、感知服務   │
│   safety：夾限、加速度限制、期限、跌倒、電壓、緊急停止鎖定    │
│   輸出：7 維指令向量＋相容的 Buttons 物件                    │
└──────────────────────────────────────────────────────┘
程序 3：autossh 通道（systemd）
```

- **為什麼把 nous_link 拆成獨立程序**：WebSocket、JSON 解析與 schema 驗證不和 50 Hz 步態搶 GIL。步態推論本身在 Pi 4 上很快（p99 0.37 ms，ADR-0008 §3），但 Python 程序內的停頓會直接變成步態抖動。nous_link 當掉時，仲裁器收不到新意圖，會依期限自己停下。
- **CPU 與記憶體隔離照 ADR-0008 §2.4**：runtime host 綁定步態專用核心並提高優先權；nous_link 與 autossh 不和它共用核心。
- **感知服務的指令走同一個 socket**：例如 `behaviors/look_at.py` 的頭部指令與轉身角速度。這就是 ADR-0008 §2.5 要求的「步態＋安全與感知之間的內部介面」的第一版。每筆都帶 TTL，由仲裁器再夾限；感知服務當掉時，指令過期歸零。
- **safety 放在仲裁器，與主迴圈同程序**：判斷所需的資料（IMU 最新值、足底接觸、緊急停止鈕、目前指令）都在這裡，不依賴任何其他程序是否還活著。

### 2.4 不改上游的接入方式（草案）

1. **部署**：沿用 [`setup_runtime.sh`](../../robot/deploy/pi4/setup_runtime.sh)，它已經在 Pi 4 的 `~/duck/` 以 git clone 鎖定 `376de65`，並 `pip install -e`（Python 3.11.18 venv）。
2. **載入**：runtime host 以 `importlib` 從 `~/duck/Open_Duck_Mini_Runtime/scripts/v2_rl_walk_mujoco.py` 載入，在建立 `RLWalk` **之前**把該模組的 `XBoxController` 名稱換成 `CommandArbiter` 的工廠。主迴圈完全照上游執行；工作目錄設為 `scripts/`，讓 `./polynomial_coefficients.pkl` 讀得到。
3. **相容介面**：`CommandArbiter.get_last_command()` 回傳與上游相同的四元組，`buttons` 使用上游的 `mini_bdx_runtime.buttons.Buttons`。仲裁器內部仍建立上游的 `XBoxController` 來讀手把，再決定哪些按鍵要轉給主迴圈（§2.5）。
4. **暫停**：仲裁器握有 `RLWalk` 實例的參照，直接設定 `paused`，不用模擬按下 A 鍵。
5. **IMU**：仲裁器只讀 `imu.last_imu_data`，**不呼叫** `get_data()`，避免搶走主迴圈要用的新值。
6. **硬體衝突**：啟動前確認 `/dev/ttyACM0`、`/dev/i2c-1`、`/dev/gpiochip*` 沒有被其他程式開著（例如舵機控制台），有就拒絕啟動。舵機控制台也做同樣的檢查，兩者互斥。
7. **風險**：這依賴上游模組的內部名稱（`XBoxController`、`paused`、`imu`、`last_imu_data`、`hwi`）。只對 `376de65` 保證；換 commit 前要重跑 §5 的測試。若上游大改導致做不到，再另寫 ADR 決定是否 fork。

### 2.5 緊急停止：手把組合鍵＋機身按鈕（2026-11-26 使用者決定）

緊急停止是鴨子本機的「最高優先」停止管道，和 [ADR-0007 §6.1](ADR-0007-follow-me-and-wait-here.md#61-多條停止管道) 的「手把、鴨子身上的實體按鈕」是同一件事，不需要網路。

**觸發**（任一即觸發，冪等）：

| 管道 | 操作 | 說明 |
|---|---|---|
| 手把組合鍵 | **同時按下 LB＋RB** | `RB` 在上游走路程式沒有用途；`LB` 單按只是加快步頻，兩個一起按不會誤觸其他功能。偵測到兩鍵同時為按下就觸發，不需要長按 |
| 機身按鈕 | 按一下 | 接 Pi 4 的 **GPIO 17（實體腳位 11）**，GND 用腳位 9。GPIO 17 不在 ADR-0008 §2.3 的上游腳位表內。建議用**常閉（NC）**按鈕、內部上拉：按下或線斷了都讀到高電位，都會觸發緊急停止（斷線也停，fail-safe）。`robot/config/` 設定 `estop_button: nc／no／absent`；還沒裝按鈕時設 `absent`，不讀這支腳 |
| duck-link | `stop` | 永遠接受、不受頻率限制，但**不鎖住**；鎖住的緊急停止只能由本機兩個管道觸發 |

**觸發後的行為**：

1. 速度目標立即歸零（不經過加速度限制），頭部維持目前目標。
2. 兩腳足底接觸都為真時立刻設 `paused`；最多等 0.4 s，到時間不論狀態都設 `paused`。這是初始值，待模擬確認。
3. **扭力維持開著**。鴨子靠扭力站著，關扭力會直接倒下，所以走路中的緊急停止只凍結姿勢。關扭力只在舵機控制台或本機 CLI 做；那是不同情境（鴨子沒在走路）的緊急停止。
4. 鎖住：拒絕所有移動意圖（ack `estop_latched`），也不把 A 鍵轉給主迴圈，所以按 A 不會解除暫停。
5. 送 `estop` 事件（附來源）。

**解除**（只能在鴨子本機，Nous 不能解除）：

- **手把：單獨按住 A 3 秒**（同時沒按 LB、RB）。鎖住期間 A 不會傳給主迴圈，所以不會誤觸暫停切換。
- 或本機 CLI。
- 機身按鈕**只負責觸發，不負責解除**。避免慌張時按太久反而解除。
- 解除後仍是暫停狀態，要再按一次 A（或 Nous 送 `resume`）才會開始走。送 `estop_reset` 事件。
- 機身按鈕若是常閉而且還處於斷開（按著或線斷），不能解除。

### 2.6 電壓：只在暫停時讀（2026-11-26 使用者決定）

- **為什麼只在暫停時讀**：電壓要從 STS3215 的匯流排讀；走路時主迴圈每圈都在用這條匯流排，同時讀會打亂步態時序。暫停時主迴圈不送馬達目標，匯流排空著。
- **怎麼讀**：
  - 暫停時主迴圈每圈仍會呼叫 `get_last_command()`（§1.1），仲裁器就在這個呼叫裡、同一個執行緒讀，不會和主迴圈同時用匯流排。
  - 每 2 s 讀一次 14 顆舵機的 present voltage，取最低值。
  - 讀值與讀取時間放進 state。
- **門檻**沿用舵機控制台的暫定值（`servo_console/controller.py`：`VOLT_WARN_V = 6.6`、`VOLT_STOP_V = 6.0`，2S 鋰電每顆 3.3／3.0 V），兩邊一致：
  - 低於 6.6 V：送 `battery_low` 事件，state 標示警告，仍可走。
  - 低於 6.0 V：拒絕 `resume` 與移動意圖（ack `low_voltage`），送事件；電壓回升也不自動恢復，要本機解除或換電池後重新讀到正常值。
- **走路時沒有新讀值**：每次停下都會進入暫停，所以通常每段動作之間都有讀值。若連續走路超過 5 分鐘都沒有暫停（例如之後的長任務），仲裁器主動停下、暫停讀一次再繼續。5 分鐘是初始值。
- 讀值逾時或讀取失敗：記為故障並回報，不當成電壓正常。
- 日後若加裝電流／電壓感測器（ADR-0005 §2.2 選配），就能在走路時讀；屆時另行修訂本節。

### 2.7 其他 safety 規則（仲裁器內，草案）

數值都是**初始值，待模擬與實機量測後修訂**，寫進 `docs/validation/` 才算定案。

| 規則 | 行為（初始值） |
|---|---|
| 速度夾限 | 先依上游範圍（vx ±0.15、vy ±0.2、yaw ±1.0），再套 `robot/config/` 的室內上限（vx 0.10、vy 0.10、yaw 0.6） |
| 加速度限制 | 每圈最多變化 vx／vy 0.01 m/s、yaw 0.05 rad/s（緊急停止不受此限） |
| 頭部 | 依上游範圍夾限（neck_pitch −0.34～1.1、head_pitch −0.78～0.3、head_yaw ±0.5、head_roll ±0.5） |
| 期限 | §2.2 第 3 項任一到期 → 速度目標歸零（加速度限制下減速） |
| 一般停下 | 速度為 0 時策略仍會原地踏步；兩腳足底接觸都為真且持續 0.3 s 後才設 `paused`，避免單腳懸空時凍結；逾時 2 s 仍未達成就維持踏步並回報 |
| 跌倒 | 由 `accelero` 推算傾角，連續 0.2 s 超過 45° → `fallen`：速度歸零、暫停、拒絕所有移動意圖，要本機人工復位 |
| 手把優先 | 搖桿超過死區或有按鍵 → 手把接管 3 s，duck-link 意圖回 `rejected: controller_active`；手把斷線時**不沿用最後一筆**，直接歸零 |
| 斷線 | 租約失效 → 停下並記錄 `link_lost`；恢復後只回報，不自動繼續 |
| 過熱 | 讀 Pi 4 的 `get_throttled` 與溫度（ADR-0008 §4.3）；舵機溫度和電壓一樣，只在暫停時讀，門檻沿用舵機控制台（55 °C 警告、65 °C 停止，暫定） |
| 啟動 | 以暫停狀態啟動；第一個 `walk` 前需要本機或 Nous 明確 `resume` |

### 2.8 與中控（SmartHomeAI）的關係

- 中控（`pcpcchen-coder/SmartHomeAI`）**不直接指揮鴨子**，也不是 duck-link 的端點。語音或自動化要讓鴨子動，一律經 Nous 的 `app.duck.*`。
- 家裡的掃地機器人地圖可以當 ADR-0002 建圖的參考（房間外框、門寬、可通行範圍），但這些屬於私人地圖資料：只存在 Nous 本機，**不進本 repo**。

## 3. 理由

- SSH 通道沿用 AIOS 已有實機紀錄的模式，並遵守「核心只聽 loopback」；終端與 duck-link 共用一條通道，維護成本最低。
- 由鴨子本機計時，再加上連線租約：滿足「Nous 只下意圖」，同時 Wi-Fi 斷線時仍有明確的停止上限。
- 拆程序：保護步態迴圈的時間；任何一個上層程序當掉，最後都會落到「期限到、停下」。
- 用名稱替換的方式包裝上游：不改上游檔案、不 fork，代價是對內部名稱的依賴，由鎖 commit 與測試控制風險。
- 緊急停止兩個本機管道：
  - 手把組合鍵用的是上游沒用到的 RB，不會撞到既有功能。
  - 機身按鈕用常閉接法，斷線也會停。
  - 觸發與解除分開，避免慌張時誤解除。
- 暫停時讀電壓：不用加硬體，也不打亂步態時序；和舵機控制台用同一組門檻。

## 4. 後果

- `protocol/`：新增 `heartbeat`、`walk` 的 `duration_s` 上限、ack 原因代碼列舉（含 `estop_latched`、`low_voltage`）、state 的 `control_source`、`faults` 與電壓欄位、`estop`／`estop_reset` 事件（另開批次）。
- `robot/`：
  - `nous_link/`（程序 1）；
  - `safety/` 的 `CommandArbiter`（含緊急停止、電壓與溫度讀取）；
  - `deploy/` 的 runtime host 與三個 systemd 服務（CPU 隔離照 ADR-0008 §2.4）；
  - `config/` 的 `estop_button` 設定。
- `hardware/wiring/`：加入機身緊急停止鈕（GPIO 17／腳位 11、GND 腳位 9、常閉）。按鈕的位置與型號未定。
- AIOS：核心新增 `/duck-link` WebSocket 端點與 DuckAdapter（AIOS 批次，不在本 repo 宣稱完成）。
- 手把：B 鍵行為不變（音效）。LB＋RB 同時按下改為緊急停止；緊急停止鎖住期間，A 鍵改為「按住 3 秒解除」。

## 5. 驗證計畫

| 層級 | 內容 |
|---|---|
| 單元測試（雲端） | 用假 IMU、假足底、假手把、假 GPIO、假匯流排，**標示 mock**。<br>**仲裁器**：夾限、加速度限制、三種期限；手把接管與斷線歸零；跌倒鎖定；`stop` 不受限也不鎖住；緊急停止（LB＋RB、機身鈕 NC 斷開與斷線、`absent` 不讀）；解除只能按住 A 3 秒或 CLI，機身鈕斷開時不能解除，鎖住時 A 不轉給主迴圈；電壓只在暫停時讀、門檻、讀取失敗回報故障、5 分鐘強制暫停。<br>**nous_link**：schema 錯誤、版本不符、重複 `request_id`、心跳逾時 |
| 載入測試（雲端） | 在 `376de65` 上以假 HWI 載入 `v2_rl_walk_mujoco.py`、替換 `XBoxController`，確認主迴圈呼叫到仲裁器，而且暫停時也會呼叫 |
| 模擬（`sim/`） | MuJoCo 中以仲裁器輸出驅動策略：停下時兩腳著地才暫停、緊急停止 0.4 s 內凍結且不跌倒、加速度限制下不跌倒、斷線 1.5 s 內開始減速 |
| 實機 | 架高（腳不著地）→ 地面低速 → 正常速度；每一步先確認 LB＋RB、機身按鈕、手把接管都有效；量暫停時讀電壓的時間；量主迴圈超時次數有無增加 |

## 6. 待決

已決定（2026-11-26 使用者）：

1. ~~鎖定哪一個 runtime commit~~：**`376de65`**（和 ADR-0008、`setup_runtime.sh` 一致）。
2. ~~緊急停止的實體配置~~：**手把組合鍵加機身按鈕**，細節見 §2.5。
3. ~~電壓來源~~：**暫停時讀舵機電壓**，細節見 §2.6。

仍待決：

4. 傳輸方案（§2.1）是否採用。
5. §2.2、§2.5～§2.7 的所有初始數值，以及心跳 500 ms／租約 1.5 s 是否適合家中 Wi-Fi（要量往返延遲與丟包）。
6. 機身緊急停止鈕的型號與安裝位置（要按得到、不會被碰到；機身空間同 ADR-0008 §5）。
