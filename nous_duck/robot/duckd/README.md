# duckd：鴨子端常駐程式

狀態：**第一版**（2026-11-25）。驗證層級逐項寫在[進度檔](../../docs/companion/progress/a-body.md)與[驗證紀錄](../../docs/validation/duckd-2026-11-25.md)；沒有寫「實機」的就是還沒在真的鴨子上驗證過。

## 職責

在 Pi 4 上常駐，依 [duck-link v0](../../protocol/README.md) 連到 Nous 端（WebSocket client，連自己的 loopback，經 SSH 通道到 Mac），把 Nous 的意圖變成安全的身體動作：

- 收 `command`，每個回恰好一個 `ack`；每秒送 `state`；有事就送 `event`。
- 所有會動的指令都經過**安全仲裁器**（夾限、限速、期限、租約、緊急停止）。
- 目前能動的只有**頭頸 4 顆舵機**（ID 30–33）。走路、天線、喇叭、導航都回報 `unsupported`。
- 眼睛：加 `--eyes-hw` 時送到兩片 GC9A01 實體螢幕（SPI0），`capabilities.eyes` 回報 `degraded`（面板沒有回讀，只確認資料送出）；打不開或送失敗就退回只寫 PNG（虛擬面板），回報 `mock` 並附原因。2026-11-28 在 Pi 上接過（桌上、頭沒接手），對話中約 11 fps（加速後）、idle 15 fps，見 [驗證紀錄](../../docs/validation/eyes-duckd-2026-11-28.md)。

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
| `duckd/eyes_proc.py` | `--eyes-hw` 時眼睛在子行程渲染與傳送（不和控制迴圈搶 GIL）；子行程死掉會標示並重啟 | A6 |
| `duckd/eyes_out.py` | `duck_eyes` 渲染＋實體螢幕（`duck_eyes.gc9a01`）＋虛擬面板（PNG） | A6 |
| `duckd/percept.py` | 感知的本機輸入（UDP `127.0.0.1:8793`）：人臉／聲音方位、來源存活訊息、喚醒服務送來的 `wake_word` | T5 |
| `duckd/voice_out.py` | 把目前的 presence 用 UDP 送給喚醒服務（`127.0.0.1:8794`） | 喚醒 |
| `duckd/track.py` | 聽聲辨位轉頭的目標決定：死區、平滑、舵機自噪音迴避、逾時回正 | T5 |
| [`tools/head_check.sh`](tools/head_check.sh) | 實機頭部檢查：前置檢查 → 接手 → 端到端與租約量測 → 釋放 | T1 |
| `duckd/gait_host.py`、`duckd/gait_fakes.py` | 步態 host：以 importlib 載入上游步態腳本、把手把換成仲裁器；假硬體介面（mock） | A7 |
| `duckd/localctl.py`、`duckd/ctl.py` | 本機控制（UNIX socket）：`status`、`engage`、`release`、`estop`、`clear-estop` | A8 |
| `duckd/settings_in.py` | 讀「[鴨子設定](../settings/README.md)」（ADR-0019）：啟動時讀頭部角速度與活動範圍，之後每秒看一次有沒有變，即時套用功能開關、聽聲轉頭的時間與死區、對話小動作幅度、presence 的表情對應；回報實際在用的值 | 設定 |
| `duckd/mock_hub.py` | **假的** hub（mock）：測試與開發用，不是 Nous，也不是 B 線的 hub | 測試 |
| [`../deploy/pi4/deploy_duckd.sh`](../deploy/pi4/deploy_duckd.sh) | 部署到 Pi、systemd 服務 `duckd` | A8 |

原本規劃的空目錄和這裡的對應（那幾個目錄保留 `.gitkeep`）：

| 原規劃 | 現在在哪 |
|---|---|
| `robot/nous_link/` | `duckd/protocol.py`、`duckd/core.py`、`duckd/link.py` |
| `robot/safety/` | `duckd/arbiter.py` |
| `robot/config/` | `duckd/limits.py`（上限）；偏移仍讀上游的 `~/duck_config.json` |
| `robot/behaviors/library/`（ADR-0015） | `duckd/library/` |

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
- 頭部角速度與活動範圍從[鴨子設定](../settings/README.md)讀（服務帶 `--settings-dir ~/duck/settings`；預設 30°/s、±15°，是 2026-11-25 無人看顧時的規定）。在設定頁改（`http://duck-pi4.local:8081/`，可調 5～60°/s、±5～30°），改完要重啟 duckd。設定讀不到（還沒跑 `deploy_settings.sh`、檔案壞掉）時 duckd 自己退回 30°/s、±15°。命令列的 `--head-speed-deg`、`--head-window-deg` 有給時以命令列為準。
- 其他可以在設定頁即時改的：聽聲轉頭、具名動作、對話時的頭部小動作、說話點頭的開關；停穩等待、回正時間、死區、信心下限；對話小動作幅度；各 presence 狀態的表情。功能被關掉時，對應的指令回 `unsupported`（`detail` 是 `… disabled in duck settings`）。
- 本機控制多一個 `express`（設定頁的「在鴨子上預覽」用）：顯示指定表情最多 10 秒。只在眼睛渲染有開時可用。

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
| 動作庫 | 定義檔超出範圍、插值後超過角速度上限、沒有回到中立：**整個動作拒絕載入**，不偷偷夾限（ADR-0015 §2.4）。只有實機驗證過、硬體設定相符的動作才列給 Nous |
| 協定以外的操作 | 接手／釋放硬體、扭力、解除緊急停止都只有本機入口；`tests/test_core.py` 檢查指令處理的程式裡沒有這些呼叫 |

## duck-link 各 action 的現況

| action | 現況 |
|---|---|
| `status`、`stop`、`resume` | 支援 |
| `look` | 支援（頭部接手後） |
| `gesture` | 支援 `nod`、`shake`、`tilt`、`look_around`；一次一個，進行中再來一個會被拒絕 |
| `presence` | 支援：眼睛表情＋頭部小動作；`speech_level` 有持續更新才會點動 |
| `express` | 支援（實體螢幕或虛擬面板；確認的是渲染端的表情，不是螢幕回讀）；代表鴨子實際狀態的表情（例如沒電）Nous 叫不出來 |
| `track` | 有感知來源在餵 UDP 8793 時支援（只動頭；`body: true` 會被改成 false 並回報）；沒有來源回 `unsupported`。`sound` 見下面「聽聲辨位轉頭」 |
| `walk` | `unsupported`：步態 host 還沒接進主程式、足底開關沒接、實機走路要有人在場 |
| `antennas`、`sound` | `unsupported`：沒有天線舵機；聲音還沒接進 duckd（D 線） |
| `where`、`places`、`go_to`、`find_person`、`return_home`、`follow_me`、`wait_here` | `unsupported`（導航還沒接進 duckd，C 線）；`mission_status`、`cancel_mission` 回 `no_mission` |

## 聽聲辨位轉頭（`track sound`）

驗證層級：單元測試＋ Mac↔Pi 真實通道（模擬身體、模擬 DOA，都是 mock）。**還沒有接真的麥克風，也還沒有在真的頭上跑過。**

資料怎麼走：XVF3800 → [`duck_audio.doa`](../audio/README.md#聲源方向doat4)（服務 `duck-doa`）→ UDP `127.0.0.1:8793` 的 `sound` 訊息 → duckd → 頭部 yaw。

| 規則 | 數值（初始值，[`duckd/track.py`](duckd/track.py)） |
|---|---|
| 只在偵測到語音時才有方位 | DOA 服務只在 `speech_detected` 為真時送 |
| 平滑 | 0.8 s 內至少 2 筆、彼此不超過 25° 才採用，取環狀平均 |
| 死區 | 新方位和目前目標差不到 8° 不動 |
| 舵機自噪音 | 頭在動、或停下不到 1.0 s 時收到的方位全部丟掉（2026-11-26 實機：頭一動，舵機聲就被 XVF3800 判成語音，能量比人聲還大；原本的 0.5 s 會來回擺） |
| 超出頭部範圍 | 轉到極限（±0.5 rad），`tracking_acquired` 事件的 `data.at_limit` 是 `true`。坐著不轉身：`body: true` 會被改成 false |
| 回正 | 8 s 沒有聽到聲音，頭回正（送 `tracking_lost`，`reason: quiet`）；追蹤本身不結束 |
| 來源不見 | 5 s 沒有收到 DOA 服務的存活訊息（麥克風拔掉、服務停了）：結束追蹤，`capabilities.tracking_sound` 變 `unsupported` |

**麥克風裝在哪**（在[設定頁](../settings/README.md)的「機體量測值」改，約 1 秒內生效；還沒裝設定頁時才改 Pi 的 `~/duck/doa/config/doa.json` 並重啟 `duck-doa`）：

| `mount` | 意思 | 換算 |
|---|---|---|
| `head` | 裝在頭上、跟著頭轉（[ADR-0005 §2.3.1](../../docs/adr/ADR-0005-compute-and-sensor-upgrade.md) 的規劃） | 方位相對頭部；duckd 加上當下的頭部 yaw 換成相對身體（[ADR-0003 §4.1](../../docs/adr/ADR-0003-mobile-terminal-wake-and-find.md) 的簡化式 φ ≈ α＋ψ；頭的俯仰、側擺沒有修正） |
| `body` | 裝在身體上 | 方位就是相對身體 |
| `desk`（預設） | 放在桌上、不在鴨子身上 | 當成相對身體。只有麥克風緊靠鴨子、說話的人比較遠時才近似正確 |

`front_angle_deg` 是「麥克風回報的哪個角度對應鴨子正前方」，用 `--calibrate` 量（步驟在 [`robot/audio` 的 README](../audio/README.md#聲源方向doat4)）。沒校準時 `calibrated: false`，服務的存活訊息會帶 `front angle not calibrated`。`counterclockwise` 是角度增加的方向，**要在實機上確認**（站到鴨子左邊說話，方位應該是正的）。

## 喚醒詞：轉給 Nous、把對話狀態送回喚醒服務

喚醒詞由 [`duck-voice`](../audio/README.md)（D 線）在本機偵測；duckd 只負責轉手，不碰音訊。

```text
duck-voice ──UDP 8793 {"v":1,"kind":"wake_word","keyword_id":…,"doa_deg":null,"t_ms":…,"mock":…}──► duckd ──事件 wake_word──► Nous
duck-voice ◄──UDP 8794 {"v":1,"kind":"presence","state":…}── duckd ◄──指令 presence── Nous
```

- 每一則喚醒送一個 `wake_word` 事件，`data` 是 `keyword_id`、`doa_deg`（往鴨子的左邊為正；不知道是 `null`）、`doa_frame`、`doa_source`、`mock`。方位用 2 秒內最新的聲音方位補（`duck-doa` 沒在跑就是 `null`）。
- 連不上 Nous（沒連線或租約過期）時**丟掉、不補送**；`duckd-ctl status` 的 `wake` 有計數。
- 本機反應：目前是 `idle`／`sleeping`／`error` 時先把 presence 設成 `wake`（抬頭；有方位而且「聽聲轉頭」開著就轉向聲源）。Nous 的 presence 一來就由它接手；8 秒沒人接手自己回 `idle`。對話期間頭維持朝向聲源。
- presence 每次改變就送給喚醒服務，另外每 5 秒重送；喚醒服務在不是 `idle` 時不偵測喚醒詞。`--voice-port 0` 可以關掉。
- 不需要頭部接手就能轉送事件（頭沒接手時只是不動）。

驗證層級：單元測試、對假 hub 的端到端、Pi 上不出力的實測（手動觸發）。**頭部出力時的反應、真的說話觸發、對真的 Nous 都還沒做**；頭在動時舵機聲會不會誤觸發喚醒詞也沒量。見[驗證紀錄](../../docs/validation/duckd-wake-relay-2026-11-27.md)。

在 Pi 上手動檢查（不會讓舵機出力；`duck-voice` 要先停著，因為假 hub 要占 8794）：

```bash
ssh duck-pi4 'cd ~/duck/duckd && ~/duck/duckd-venv/bin/python -m duckd.mock_hub --port 8795 --wake'   # 另一邊用 --url ws://127.0.0.1:8795/duck-link 啟動 duckd
```

## 還沒做

- **實機走路**：`gait_host.py` 只做到「不改上游、載入鎖定 commit 的腳本、把手把換成仲裁器」的載入測試（假硬體）。主程式還沒有把 `walk` 接過去，duckd 與步態 host 之間的本機通道（ADR-0009 §2.3 的 UNIX datagram）也還沒做。頭部直控與步態 host 不能同時用匯流排，切換流程還沒設計。
- 眼睛：對話中約 11 fps（目標 15）；眼睛執行緒和 50 Hz 控制迴圈共用 GIL，對話中 overrun 約 15 次／分鐘（只有虛擬面板時約 1.5）。要把眼睛移到自己的行程，或提高 SPI 時脈。
- 天線、音效 cue、動作定義檔的 `vel`／`antennas`／`cues` 軌。
- 頭部角速度、角加速度上限的模擬量測（ADR-0015 §2.3 要求；目前直接用 30°/s 的保守值）。
- 跌倒偵測、手把接管的規則寫在仲裁器裡並有單元測試，但主程式沒有 IMU 與手把輸入可餵（BNO055 還沒校準）。
- `state.link.rtt_ms` 一直是 `null`：往返時間由 Nous 端用心跳回聲量，鴨子端量不到。
- **實機頭部**（T1）：2026-11-26 舵機沒有電，還沒做。電源接上後跑 `tools/head_check.sh`。
- 協定上的缺口寫在 [`protocol/proposals/a-duckd-gaps.md`](../../protocol/proposals/a-duckd-gaps.md)。
- 原地蹲低／起立（**規劃中**，還沒實作）：設計見 [ADR-0020 草案](../../docs/adr/ADR-0020-crouch-and-stand.md)，協定提案見 [`protocol/proposals/a-posture-command.md`](../../protocol/proposals/a-posture-command.md)，模擬在 [`sim/posture_sim/`](../../sim/posture_sim/)。
