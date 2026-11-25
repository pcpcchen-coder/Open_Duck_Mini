# duckd：鴨子端常駐程式

狀態：**第一版**（2026-11-25）。驗證層級逐項寫在[進度檔](../../docs/companion/progress/a-body.md)與[驗證紀錄](../../docs/validation/duckd-2026-11-25.md)；沒有寫「實機」的就是還沒在真的鴨子上驗證過。

## 職責

在 Pi 4 上常駐，依 [duck-link v0](../../protocol/README.md) 連到 Nous 端（WebSocket client，連自己的 loopback，經 SSH 通道到 Mac），把 Nous 的意圖變成安全的身體動作：

- 收 `command`，每個回恰好一個 `ack`；每秒送 `state`；有事就送 `event`。
- 所有會動的指令都經過**安全仲裁器**（夾限、限速、期限、租約、緊急停止）。
- 目前能動的只有**頭頸 4 顆舵機**（ID 30–33）。走路、天線、喇叭、導航都回報 `unsupported`。
- 眼睛：沒有實體螢幕，只把畫面寫成 PNG（虛擬面板），`capabilities.eyes` 回報 `mock`。

duckd 不做語音、視覺、決策（那是 Nous 的事，[ADR-0001](../../docs/adr/ADR-0001-duck-role-in-nous.md)）。設計決定見 [ADR-0014](../../docs/adr/ADR-0014-duckd-head-direct-and-single-process.md)。

## 結構

| 檔案 | 內容 | 對應的 Step |
|---|---|---|
| `duckd/protocol.py` | 載入 `duck-link.v0.schema.json`，驗證收發的每一則訊息 | A1 |
| `duckd/core.py` | 核心（不做 I/O）：`hello`、心跳回聲、`ack`（重複 `request_id` 回原本的）、`state`、`event`、各 action 的處理、本機入口（接手／釋放／緊急停止） | A1 |
| `duckd/link.py` | WebSocket client（斷線自動重連）＋ 50 Hz 控制迴圈（獨立執行緒） | A1 |
| `duckd/body.py` | 身體後端介面與 `MockBody`（`mock: true`） | A1 |
| `duckd/limits.py` | 安全上限與時間常數（**初始值、待實機修訂**） | A2 |
| `duckd/arbiter.py` | 安全仲裁器：純邏輯、可測 | A2 |
| `duckd/head_real.py` | 頭部實機後端：重用舵機控制台的 `Controller`、`FeetechBus`，外加只放行 ID 30–33 的白名單 | A3 |
| `duckd/gestures.py`、`duckd/library/*.json` | 動作庫：定義檔、載入時檢查、播放（`nod`、`shake`、`tilt`、`look_around`） | A4 |
| `duckd/presence.py` | `presence` → 眼睛表情＋頭部目標 | A5 |
| `duckd/eyes_out.py` | `duck_eyes` 渲染＋虛擬面板（PNG） | A6 |
| `duckd/percept.py` | 感知的本機輸入（UDP `127.0.0.1:8793`），給 `track` 用 | （配合 D 線） |
| `duckd/gait_host.py`、`duckd/gait_fakes.py` | 步態 host：以 importlib 載入上游步態腳本、把手把換成仲裁器；假硬體介面（mock） | A7 |
| `duckd/localctl.py`、`duckd/ctl.py` | 本機控制（UNIX socket）：`status`、`engage`、`release`、`estop`、`clear-estop` | A8 |
| `duckd/mock_hub.py` | **假的** hub（mock）：測試與開發用，不是 Nous，也不是 B 線的 hub | 測試 |
| [`../deploy/pi4/deploy_duckd.sh`](../deploy/pi4/deploy_duckd.sh) | 部署到 Pi、systemd 服務 `duckd` | A8 |

原本規劃的空目錄和這裡的對應（那幾個目錄保留 `.gitkeep`）：

| 原規劃 | 現在在哪 |
|---|---|
| `robot/nous_link/` | `duckd/protocol.py`、`duckd/core.py`、`duckd/link.py` |
| `robot/safety/` | `duckd/arbiter.py` |
| `robot/config/` | `duckd/limits.py`（上限）；偏移仍讀上游的 `~/duck_config.json` |
| `robot/behaviors/library/`（ADR-0011） | `duckd/library/` |

## 在 Mac 上用模擬身體跑（不碰硬體）

需要 `uv`（系統 Python 3.9 太舊）。

```bash
cd nous_duck/robot/duckd && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements-dev.txt
```

測試（Mac：107 項通過、3 項略過；略過的是要在 Pi 上對真上游腳本跑的載入測試）：

```bash
cd nous_duck/robot/duckd && .venv/bin/python -m pytest tests -q
```

手動玩：一個終端機開假 hub，另一個開 duckd。

```bash
cd nous_duck/robot/duckd && .venv/bin/python -m duckd.mock_hub --e2e
```

```bash
cd nous_duck/robot/duckd && .venv/bin/python -m duckd --body mock --engage --allow-unverified-gestures --eyes-panel /tmp/duck_eyes.png
```

`--e2e` 會依序下 `look`、`gesture nod`、`presence`，印出一份 JSON 量測；`/tmp/duck_eyes.png` 是虛擬面板（兩眼並排）。輸出裡 `mock: true` 代表身體是模擬的。

## 部署到 Pi

```bash
bash nous_duck/robot/deploy/pi4/deploy_duckd.sh
```

做的事：複製到 `~/duck/duckd/`；建獨立的 `~/duck/duckd-venv`（只裝 `requirements.txt` 的 websockets、jsonschema）；**不動 `~/duck/runtime-venv`**，pypot、numpy、onnxruntime 用一個 `.pth` 把 runtime-venv 的 site-packages 接在後面唯讀沿用；安裝 systemd 服務 `duckd`，**不 enable、不啟動**。加 `--test` 會在 Pi 上跑全部測試（含上游步態腳本的載入測試）；`--uninstall` 移除服務。

使用（都在 Mac 上下指令）：

```bash
ssh -N -R 127.0.0.1:8791:127.0.0.1:8791 duck-pi4
```

```bash
ssh duck-pi4 'sudo systemctl start duckd'
```

```bash
ssh duck-pi4 '~/duck/duckd/duckd-ctl engage'
```

```bash
ssh duck-pi4 '~/duck/duckd/duckd-ctl status'
```

```bash
ssh duck-pi4 'sudo systemctl stop duckd'
```

- 服務啟動時**不碰硬體**。`engage` 才會開匯流排、讀頭部 4 顆的位置、把沒出力的開扭力（先寫目前位置，不跳）。
- `engage` 前會檢查 `/dev/ttyACM0` 有沒有被別的程式開著（舵機控制台、上游腳本）。有就拒絕並說是誰；**不會搶**。要先在控制台頁面按「釋放硬體」。
- `release`（或停止服務）：頭以限速回到接手時的位置，恢復接手前的扭力狀態，放開匯流排。
- 服務的預設參數是 `--head-window-deg 15 --head-speed-deg 30`（2026-11-25 無人看顧時的規定）。要放寬就改 `/etc/systemd/system/duckd.service` 的 `ExecStart`。

## 安全規則

數值都在 [`duckd/limits.py`](duckd/limits.py)，**全部是初始值、待實機修訂**（ADR-0009 §2.5）。

| 規則 | 做法 |
|---|---|
| 不碰腿 | 頭部後端的 `Controller` 只拿到 4 個頭部關節；匯流排外面再包 `HeadOnlyBus`，任何讀寫帶到 ID 30–33 以外就丟例外、不送出。`tests/test_head_real.py` 用模擬匯流排跑完整流程，確認腿的扭力、目標、kp 都沒被寫過 |
| 頭部範圍 | ADR-0009 §2.5 的範圍與「上游 `robot.xml` 內縮 2°」取交集：neck_pitch −0.314～1.1、head_pitch −0.75～0.3、head_yaw ±0.5、head_roll ±0.489 rad。超出就夾限，`ack` 回 `applied` 與 `clamped: true` |
| 視窗（可選） | `--head-window-deg N`：每軸只能在接手時的位置 ±N° 內 |
| 限速 | 仲裁器輸出的設定值每圈最多走 `上限 × dt`（預設 30°/s）；底下舵機控制台的 `Controller` 再限一次 |
| 期限 | `look`：`ttl_ms` 到期就停在目前位置。`walk`：`duration_s`（上限 3 s）、`ttl_ms`、租約，任一到期就停。動作（gesture）由鴨子自己計時，長度上限 10 s |
| 租約 | 1.5 s 沒收到 `heartbeat`（或 socket 關了）：停下、送 `link_lost`；恢復後只送 `link_restored`，**不自動繼續** |
| `stop` | 永遠接受（沒有租約、鎖定中也接受） |
| 緊急停止 | 鎖住，拒絕所有動作。來源：本機 `duckd-ctl estop`、`SIGUSR1`、後端自動（過熱、低電壓）。**duck-link 沒有解除的指令**，只能在 Pi 上 `duckd-ctl clear-estop`；解除後要 `release` 再 `engage` 才會再出力 |
| 過熱、低電壓、讀取失敗 | 頭部舵機 ≥ 55 °C、電壓 < 6.6 V、匯流排連續讀取失敗：停下並拒絕新動作（`overheat`／`low_battery`／`hardware_fault`）。≥ 65 °C 或 < 6.0 V 由舵機控制台的核心自動緊急停止（只關頭部扭力） |
| 動作庫 | 定義檔超出範圍、插值後超過角速度上限、沒有回到中立：**整個動作拒絕載入**，不偷偷夾限（ADR-0011 §2.4）。只有實機驗證過、硬體設定相符的動作才列給 Nous |
| 協定以外的操作 | 接手／釋放硬體、扭力、解除緊急停止都只有本機入口；`tests/test_core.py` 檢查指令處理的程式裡沒有這些呼叫 |

## duck-link 各 action 的現況

| action | 現況 |
|---|---|
| `status`、`stop`、`resume` | 支援 |
| `look` | 支援（頭部接手後） |
| `gesture` | 支援 `nod`、`shake`、`tilt`、`look_around`；一次一個，進行中再來一個會被拒絕 |
| `presence` | 支援：眼睛表情＋頭部小動作；`speech_level` 有持續更新才會點動 |
| `express` | 支援（虛擬面板）；代表鴨子實際狀態的表情（例如沒電）Nous 叫不出來 |
| `track` | 有感知來源在餵 UDP 8793 時支援（只動頭；`body: true` 會被改成 false 並回報）；沒有來源回 `unsupported` |
| `walk` | `unsupported`：步態 host 還沒接進主程式、足底開關沒接、實機走路要有人在場 |
| `antennas`、`sound` | `unsupported`：沒有天線舵機；聲音還沒接進 duckd（D 線） |
| `where`、`places`、`go_to`、`find_person`、`return_home`、`follow_me`、`wait_here` | `unsupported`（導航還沒接進 duckd，C 線）；`mission_status`、`cancel_mission` 回 `no_mission` |

## 還沒做

- **實機走路**：`gait_host.py` 只做到「不改上游、載入鎖定 commit 的腳本、把手把換成仲裁器」的載入測試（假硬體）。主程式還沒有把 `walk` 接過去，duckd 與步態 host 之間的本機通道（ADR-0009 §2.3 的 UNIX datagram）也還沒做。頭部直控與步態 host 不能同時用匯流排，切換流程還沒設計。
- GC9A01 的 SPI 驅動（等螢幕到貨）。眼睛渲染在 Pi 4 上兩眼一幀約 124 ms（見驗證紀錄），上實體螢幕前要先加速。
- 天線、音效 cue、動作定義檔的 `vel`／`antennas`／`cues` 軌。
- 頭部角速度、角加速度上限的模擬量測（ADR-0011 §2.3 要求；目前直接用 30°/s 的保守值）。
- 跌倒偵測、手把接管的規則寫在仲裁器裡並有單元測試，但主程式沒有 IMU 與手把輸入可餵（BNO055 還沒校準）。
- `state.link.rtt_ms` 一直是 `null`：往返時間由 Nous 端用心跳回聲量，鴨子端量不到。
- 協定上的缺口寫在 [`protocol/proposals/a-duckd-gaps.md`](../../protocol/proposals/a-duckd-gaps.md)。
