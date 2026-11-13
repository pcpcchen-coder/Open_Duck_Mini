# ADR-0007：duck-link 傳輸與鴨子端指令橋接

- 狀態：**草案（Proposed）**；設計稿，尚無程式、尚無模擬或實機驗證
- 日期：2026-11-13
- 相關：[ADR-0001](ADR-0001-duck-role-in-nous.md)（角色與工具）、[`architecture.md` §4–§6](../architecture.md#6-傳輸待決)、[ADR-0002](ADR-0002-indoor-localization-and-navigation.md)（導航）、[ADR-0005](ADR-0005-compute-and-sensor-upgrade.md)（雙板）、[`protocol/`](../../protocol/README.md)、[`robot/`](../../robot/README.md)

## 1. 背景

[`architecture.md` §6](../architecture.md#6-傳輸待決) 把 duck-link 的傳輸列為待決，§4 規劃「以和 `XBoxController` 相同介面的指令來源包裝接入上游 runtime」，但還沒確認做不做得到。本 ADR 補上這兩件事：

1. duck-link 用什麼傳輸連到 Nous。
2. 鴨子端怎麼把 duck-link 的意圖接進上游 runtime，讓 safety 成為最後一道關卡，並在不改上游的前提下完成。

本文只描述設計；schema 檔、程式與測試是後續批次。

### 1.1 上游 runtime 的事實（唯讀查閱）

查閱 `apirrone/Open_Duck_Mini_Runtime` `v2` 的 commit `376de65`（2026-09-07）：

| 項目 | 內容 | 位置 |
|---|---|---|
| 主迴圈 | `RLWalk.run()`，50 Hz；超時會印出 `Policy control budget exceeded` | `scripts/v2_rl_walk_mujoco.py` |
| 指令來源 | `--commands` 預設為真；`RLWalk.__init__` 直接建立 `XBoxController(20)`，每圈呼叫 `get_last_command()`，回傳 `(last_commands, buttons, left_trigger, right_trigger)` | 同上、`mini_bdx_runtime/xbox_controller.py` |
| 手把斷線 | `get_last_command()` 讀不到新值時沿用上一筆，**鴨子會照最後的速度繼續走** | `xbox_controller.py` |
| 按鍵 | 主迴圈讀 `buttons.A.triggered`（切換暫停）、`B`（音效）、`X`（投影）、`LB.is_pressed`、`dpad_up／down.triggered` | `v2_rl_walk_mujoco.py`、`buttons.py` |
| 暫停 | `self.paused` 為真時迴圈只 `sleep(0.1)`，不再送馬達目標；扭力仍開著，馬達停在當下目標 | `v2_rl_walk_mujoco.py` |
| IMU | `Imu.get_data()` 會**取走**佇列中的新值；最新值另存在 `last_imu_data`（`gyro`、`accelero`） | `mini_bdx_runtime/raw_imu.py` |
| 跌倒偵測 | 沒有 | — |
| 打包 | `setup.cfg` 只打包 `mini_bdx_runtime`；`scripts/`（含主迴圈與 `polynomial_coefficients.pkl`）**不會**隨 `pip install` 安裝 | `setup.cfg` |

## 2. 決定（草案）

### 2.1 傳輸：鴨子主動經 SSH 通道連 Nous 核心的 loopback，走 WebSocket

採 [`architecture.md` §6](../architecture.md#6-傳輸待決) 的**方案 A**：

```text
鴨子 nous_link（WebSocket client）
  ──ws://127.0.0.1:<AIOS_PORT>/duck-link──> 鴨子本機 127.0.0.1:<AIOS_PORT>
  ──SSH local forward（autossh）──> Mac 127.0.0.1:<AIOS_PORT> ──> Nous 核心 duck-link 端點
```

- **沿用 AIOS `terminals/rpi4` 的作法**（AIOS `main` `7b0257d` 查閱）：核心只聽 `127.0.0.1`，不放寬 `http-guard`；鴨子本機 port 等於 Mac 核心 port；專用 SSH key、`StrictHostKeyChecking=yes`、事先比對主機指紋。
- **一條通道同時給終端和 duck-link 用**。ADR-0003 路線 A 的終端頁面本來就要走這條通道；duck-link 只是同一條通道上的另一個 WebSocket 路徑，不必另外開入站 port。
- **鴨子與 Mac 都不對區域網路開新 port**。認證與加密由 SSH 負責；duck-link 訊息內不再帶密碼或金鑰。
- **端點在哪一片板子**：
  - 只有身體板（P1–P3 初期）：身體板跑 autossh 與 nous_link。
  - 加上感知板之後（ADR-0005）：通道與 nous_link 移到感知板。感知板經內部連線（USB 序列，訊息為 duck-link 子集）把指令交給身體板。身體板的 safety 規則不變，內部連線也要有 TTL。
- **需要 AIOS 的批次**：核心新增 `/duck-link` WebSocket 端點，屬於 AIOS repo 的工作。完成前，`nous_adapter/tests/` 用本機假核心（必須標示 mock）測試。

不採用的方案：

| 方案 | 不採用的原因 |
|---|---|
| B. 鴨子開 WebSocket server | 鴨子要對區域網路開 port，另外做認證與加密；終端頁面仍然需要 SSH 通道，等於維護兩套連線 |
| C. MQTT | 多一個常駐服務，對單一裝置太重 |
| 由 Mac 以 UDP 串流速度設定值 | 違反 ADR-0001「Nous 只下意圖」；Wi-Fi 抖動直接變成步態抖動 |

### 2.2 訊息層：連線租約與指令時效

schema 檔在 `protocol/` 另開批次定義；本節只定行為，欄位名稱為草案。

1. **每則訊息**都有 `protocol_version`、`type`、`sent_at_ms`；指令另有 `request_id`、`ttl_ms`。
2. **連線租約**：Nous 每 500 ms 送一次 `heartbeat`；鴨子連續 1.5 s 沒收到，就視為斷線。
3. **動作的雙重期限**：`walk {vx, vy, yaw_rate, duration_s}` 由鴨子**本機計時執行**，Nous 不串流速度。只要以下任一條件成立就停：
   - `duration_s` 到期（上限 3 s，超過就夾限並在 ack 回報）；
   - 指令的 `ttl_ms` 到期且沒有被新的 `walk` 取代；
   - 連線租約失效。

   所以 Wi-Fi 斷線時，鴨子最慢在 1.5 s 內開始停下，而 Nous 不需要每 20 ms 送一次指令。
4. **ack**：每個指令回 `accepted`／`rejected`，附固定列舉的原因代碼（例如 `estop_latched`、`fallen`、`link_degraded`、`out_of_range`、`busy_mission`），以及**夾限後實際執行的值**。
5. **state**：鴨子每 1 s 送一次；mode、control_source、目前指令與剩餘時間、傾角、足底接觸、迴圈超時次數、故障清單。導航相關欄位依 ADR-0002 另加。
6. **event**：`fell`、`estop`、`link_lost`／`link_restored`、`battery_low`（有電壓來源後）、`controller_takeover`（手把接管）。斷線恢復後**不自動繼續**斷線前的動作。

`app.duck.*` 的結果對應沿用 ADR-0001：`accepted` 且 state 顯示正在執行 → `confirmed`（代表「已接受並開始」，不是「走到了」）；送出後沒有 ack → `unknown`；被拒絕 → `refused`。

### 2.3 鴨子端：三個程序、一個仲裁器

```text
┌ 程序 1：nous_link（systemd，Python）───────────────┐
│ WebSocket client、schema 驗證、心跳、ack／state／event │
│ 把驗證過的意圖寫到本機 UNIX datagram socket            │
└───────────────┬────────────────────────────────────┘
                │ 最新一筆有效（latest-wins），不排隊
┌ 程序 2：runtime host（systemd，Python）─────────────┐
│ 載入上游 RLWalk（不改原檔），把指令來源換成 CommandArbiter │
│ CommandArbiter（每圈呼叫一次，只做便宜的運算）：          │
│   來源：Xbox 手把、duck-link 意圖、（之後）感知板導航     │
│   safety：夾限、加速度限制、期限、跌倒、緊急停止鎖定      │
│   輸出：7 維指令向量＋相容的 Buttons 物件                 │
└──────────────────────────────────────────────────┘
程序 3：autossh 通道（systemd）
```

- **為什麼把 nous_link 拆成獨立程序**：主迴圈本來就接近 50 Hz 的預算上限。WebSocket、JSON 解析與 schema 驗證放在另一個程序，不和步態搶 GIL。nous_link 當掉時，仲裁器因為收不到新意圖，會依期限自己停下。
- **safety 放在仲裁器，與主迴圈同程序**：判斷所需的資料（IMU 最新值、足底接觸、目前指令）都在這裡，而且不依賴任何其他程序是否還活著。

### 2.4 不改上游的接入方式

1. **部署**：在鴨子上 `git clone` runtime 並 checkout 鎖定的 commit，再 `pip install -e`。只用 `pip install git+...` 不夠，因為 `scripts/` 不在套件內（§1.1）。這會修訂 [`robot/README.md`](../../robot/README.md) 原本「以 pip 從 git 安裝」的寫法。
2. **載入**：runtime host 以 `importlib` 從鎖定 commit 的路徑載入 `scripts/v2_rl_walk_mujoco.py`，在建立 `RLWalk` **之前**把該模組的 `XBoxController` 名稱換成 `CommandArbiter` 的工廠。主迴圈完全照上游執行；工作目錄設為 `scripts/`，讓 `./polynomial_coefficients.pkl` 讀得到。
3. **相容介面**：`CommandArbiter.get_last_command()` 回傳與上游相同的四元組，`buttons` 使用上游的 `mini_bdx_runtime.buttons.Buttons`。
4. **暫停**：仲裁器握有 `RLWalk` 實例的參照，直接設定 `paused`，不用模擬按下 A 鍵。
5. **IMU**：仲裁器只讀 `imu.last_imu_data`，**不呼叫** `get_data()`，避免搶走主迴圈要用的新值。
6. **風險**：這依賴上游模組的內部名稱（`XBoxController`、`paused`、`imu`、`last_imu_data`）。只對鎖定的 commit 保證；換 commit 前要重跑 §5 的測試。若上游大改導致做不到，再另寫 ADR 決定是否 fork。

### 2.5 safety 規則（仲裁器內）

數值都是**初始值，待模擬與實機量測後修訂**，寫進 `docs/validation/` 才算定案。

| 規則 | 行為（初始值） |
|---|---|
| 速度夾限 | 先依上游範圍（vx ±0.15、vy ±0.2、yaw ±1.0），再套 `robot/config/` 的室內上限（vx 0.10、vy 0.10、yaw 0.6） |
| 加速度限制 | 每圈最多變化 vx／vy 0.01 m/s、yaw 0.05 rad/s |
| 頭部 | 依上游範圍夾限（neck_pitch −0.34～1.1、head_pitch −0.78～0.3、head_yaw ±0.5、head_roll ±0.5） |
| 期限 | §2.2 第 3 項任一到期 → 速度目標歸零（加速度限制下減速） |
| 停下 | 速度為 0 時策略仍會原地踏步；兩腳足底接觸都為真且持續 0.3 s 後才設 `paused`，避免單腳懸空時凍結；逾時 2 s 仍未達成就維持踏步並回報 |
| 跌倒 | 由 `accelero` 推算傾角，連續 0.2 s 超過 45° → `fallen`：速度歸零、暫停、拒絕所有移動意圖，要本機人工復位 |
| 緊急停止 | duck-link `stop` 永遠接受、不受頻率限制；`estop` 會鎖住，只能本機或手把解除，Nous 不能解除 |
| 手把優先 | 搖桿超過死區或有按鍵 → 手把接管 3 s，duck-link 意圖回 `rejected: controller_active`；手把斷線時**不沿用最後一筆**，直接歸零 |
| 斷線 | 租約失效 → 停下並記錄 `link_lost`；恢復後只回報，不自動繼續 |
| 電壓 | 待決（§6）：讀舵機電壓會和主迴圈搶匯流排；建議只在暫停時讀，或等 ADR-0005 的電流感測器 |
| 啟動 | 以暫停狀態啟動；第一個 `walk` 前需要本機或 Nous 明確 `resume` |

### 2.6 與中控（SmartHomeAI）的關係

- 中控（`pcpcchen-coder/SmartHomeAI`）**不直接指揮鴨子**，也不是 duck-link 的端點。語音或自動化要讓鴨子動，一律經 Nous 的 `app.duck.*`。
- 家裡的掃地機器人地圖可以當 ADR-0002 建圖的參考（房間外框、門寬、可通行範圍），但這些屬於私人地圖資料：只存在 Nous 本機，**不進本 repo**。

## 3. 理由

- SSH 通道沿用 AIOS 已有實機紀錄的模式，並遵守「核心只聽 loopback」；終端與 duck-link 共用一條通道，維護成本最低。
- 由鴨子本機計時，再加上連線租約：滿足「Nous 只下意圖」，同時 Wi-Fi 斷線時仍有明確的停止上限。
- 拆程序：保護步態迴圈的時間預算；任何一個上層程序當掉，最後都會落到「期限到、停下」。
- 用名稱替換的方式包裝上游：不改上游檔案、不 fork，代價是對內部名稱的依賴，由鎖 commit 與測試控制風險。

## 4. 後果

- `protocol/`：新增 `heartbeat`、`walk` 的 `duration_s` 上限、ack 原因代碼列舉、state 的 `control_source` 與 `faults`（另開批次）。
- `robot/`：新增 `nous_link/`（程序 1）、`safety/` 的 `CommandArbiter`、`deploy/` 的 runtime host、三個 systemd 服務。
- `robot/README.md` 的部署方式要改成「git clone 鎖定 commit＋`pip install -e`」（隨實作批次一起改）。
- AIOS：核心新增 `/duck-link` WebSocket 端點與 DuckAdapter（AIOS 批次，不在本 repo 宣稱完成）。
- 手把的 B 鍵行為不變（音效）；緊急停止鍵的配置另行決定（§6）。

## 5. 驗證計畫

| 層級 | 內容 |
|---|---|
| 單元測試（雲端） | 仲裁器：夾限、加速度限制、三種期限、手把接管與斷線歸零、跌倒鎖定、`stop` 不受限、`estop` 只能本機解除；nous_link：schema 錯誤、版本不符、重複 `request_id`、心跳逾時。用假 IMU、假足底、假手把，**標示 mock** |
| 載入測試（雲端） | 在鎖定 commit 上以假 HWI 載入 `v2_rl_walk_mujoco.py`、替換 `XBoxController`，確認主迴圈呼叫到仲裁器且不需要手把 |
| 模擬（`sim/`） | MuJoCo 中以仲裁器輸出驅動策略：停下時兩腳著地才暫停、加速度限制下不跌倒、斷線 1.5 s 內開始減速 |
| 實機 | 架高（腳不著地）→ 地面低速 → 正常速度；每一步先確認手把接管與緊急停止；量測主迴圈超時次數有無增加 |

## 6. 待決

1. 鎖定哪一個 runtime commit（目前查閱的是 `376de65`）。
2. 緊急停止的實體配置：手把組合鍵、機身按鈕，或兩者都要。
3. 電壓來源：暫停時讀舵機電壓，或加裝電流／電壓感測器（ADR-0005 §2.2）。
4. §2.5 的所有初始數值，以及心跳 500 ms／租約 1.5 s 是否適合家中 Wi-Fi（要量往返延遲與丟包）。
5. 內部連線（感知板 → 身體板）的實體介面：USB 序列或 UART。
