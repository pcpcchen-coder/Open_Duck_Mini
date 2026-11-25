# 導航（robot/navigation）

狀態：**導航核心可用，驗證層級只有單元測試與模擬（2026-11-25～26）**。沒有實機驗證：鏡頭、足底開關、充電座都還沒裝，實機也還不能走。
設計背景：[ADR-0002](../../docs/adr/ADR-0002-indoor-localization-and-navigation.md)（定位與導航）、[ADR-0004](../../docs/adr/ADR-0004-docking-and-charging.md)（回充）、[ADR-0016](../../docs/adr/ADR-0016-navigation-core-and-sim-findings.md)（這次的作法與模擬發現）。
驗證紀錄：[`docs/validation/sim-nav-2026-11-25.md`](../../docs/validation/sim-nav-2026-11-25.md)。

## 職責

在鴨子本機完成：定位（AprilTag＋短程里程，**不用步數**）、房間到房間的路徑規劃、路徑追蹤、`go_to`／`return_home` 任務、回充對位，以及導航相關的安全規則。Nous 只下「去哪裡」，不串流速度。

## 對外介面

導航核心 `duck_nav` 只依賴 numpy 與標準函式庫，**不依賴 MuJoCo、鏡頭驅動或舵機**。對外只有兩個資料型別（[`duck_nav/types.py`](duck_nav/types.py)）：

```python
from duck_nav.mapfile import load_map
from duck_nav.navigator import Navigator

nav = Navigator(load_map(path))          # 模擬或 mock 時加 mock=True，事件會帶 mock: true
nav.set_docked()                         # 選用：確定停在充電座上（電氣訊號或人工確認）
ack = nav.go_to("brother_room")          # 或 nav.return_home()、nav.cancel()
out = nav.step(frame)                    # 每個控制週期（20 ms）呼叫一次
```

### 進：`SensorFrame`

| 欄位 | 內容 | 實機上由誰提供 |
|---|---|---|
| `t`、`dt` | 單調時間與週期（s） | 呼叫端 |
| `tags` | `TagObservation` 清單：標籤 ID、在**機身座標**的位置與朝向、誤差估計 | perception（AprilTag 偵測，再用頭頸關節角換到機身座標） |
| `gyro_z` | 偏航角速度（rad/s）；沒有就 `None` | duckd（IMU） |
| `applied_cmd` | 上一個週期**實際送給步態**的 (vx, vy, yaw_rate)，也就是 safety 夾限與加速度限制之後的值 | duckd（仲裁器） |
| `obstacles`、`obstacles_valid` | 前方障礙點（機身座標，m） | perception（雙目深度） |
| `fallen` | safety 判定跌倒 | duckd |
| `lifted` | 被抱起來（對應 duck-link 的 `picked_up`）；收到就丟掉目前的定位 | duckd（足底開關＋IMU） |
| `stepping` | 有沒有在踏步；`None` 表示不知道 | duckd（足底開關） |
| `charging`、`charging_mock` | 電氣上的充電訊號；`None` 表示沒有這個感測器 | duckd（充電板或電流感測） |
| `head_yaw` | 頭部偏航回讀 | duckd |

### 出：`NavOutput`

| 欄位 | 內容 |
|---|---|
| `vx`、`vy`、`yaw_rate` | 速度指令目標（m/s、rad/s）。**沒有做加速度限制**，那是身體端 safety 的事 |
| `head` | 頭部目標（rad）。走路時一律回正，停下找標籤時才轉 ±0.5 rad |
| `events` | duck-link v0 `event` 訊息形狀的清單：`mission_progress`、`mission_done`、`mission_failed`、`undocked`、`docked`、`charging_started` |
| `active` | `False` 表示導航不要求控制權（速度一定是 0）。`True` 時 duckd 的 `control_source` 是 `mission` |

給 duckd（A 線）的接法：把導航當成仲裁器的一個指令來源。每圈組一個 `SensorFrame` → `step()` → 把 `NavOutput` 的速度與頭部目標交給仲裁器夾限 → 把事件送上 duck-link。手把接管、緊急停止、租約失效時，仲裁器不採用導航的輸出即可；導航會從 `applied_cmd` 知道指令沒有被執行。

### 對應 duck-link 的指令

| duck-link `action` | 呼叫 | 回傳 |
|---|---|---|
| `go_to` | `nav.go_to(place, request_id)` | `{"status": "accepted", "mission_id"}` 或 `rejected`＋`busy_mission`／`unknown_name` |
| `return_home` | `nav.return_home(request_id)` | 同上；沒有充電座回 `unsupported` |
| `cancel_mission` | `nav.cancel(mission_id)` | `accepted`，或 `rejected`＋`no_mission` |
| `mission_status` | `nav.mission_status(mission_id)` | `data`：任務 ID、種類、階段、進度、狀態、原因 |
| `where` | `nav.where()` | 地點 ID、房間 ID、是否定位、不確定度、是否在充電座上。**不含座標** |
| `places` | `nav.places()` | 地圖版本與地點 ID 清單。**不含座標** |
| `state.location`、`state.mission` | `nav.location_state()`、`nav.mission_state()` | 可以直接放進 `state` 訊息 |

同時只有一個任務。失敗原因是固定代碼：`door_closed`、`lost`、`blocked`、`forbidden`、`timeout`、`fell`、`cancelled`、`dock_failed`（後兩個不在協定目前的文字說明裡，見 [`protocol/proposals/c-nav-mission-events.md`](../../protocol/proposals/c-nav-mission-events.md)）。

## 內容

| 路徑 | 內容 |
|---|---|
| [`duck_nav/mapfile.py`](duck_nav/mapfile.py) | 地圖檔格式 `duck-map` 第 1 版：載入、驗證、查詢（欄位定義在檔頭） |
| [`duck_nav/localization.py`](duck_nav/localization.py) | EKF：標籤觀測＋短程里程，帶不確定度；未定位判定；被搬動後重新定位 |
| [`duck_nav/planner.py`](duck_nav/planner.py) | 拓撲層（房間與門）＋柵格 A*；外形膨脹、禁區保留邊界、會過期的動態障礙 |
| [`duck_nav/navigator.py`](duck_nav/navigator.py) | 路徑追蹤、任務狀態機、找標籤的掃描、回充、安全規則 |
| [`duck_nav/gait.py`](duck_nav/gait.py) | 步態反應表（指令 → 實際機身速度）與導航可用的指令集合 |
| [`duck_nav/data/gait_response.sim.json`](duck_nav/data/gait_response.sim.json) | **模擬量測**的步態反應表 |
| [`duck_nav/data/dock_trim.sim.json`](duck_nav/data/dock_trim.sim.json) | **模擬量測**的回充橫向校正量 |
| [`duck_nav/mock_sensors.py`](duck_nav/mock_sensors.py) | **mock**：幾何合成的標籤觀測與障礙點、幾何判定的充電訊號 |
| [`duck_nav/testing.py`](duck_nav/testing.py) | **mock**：運動學假鴨與共用的閉迴路（測試用，不是物理模擬） |
| [`maps/synthetic_home.duckmap.json`](maps/synthetic_home.duckmap.json) | **合成的家**（fixture）。由 `maps/make_synthetic_home.py` 產生，不是任何真實住家 |
| `tests/` | 66 項（其中 1 項標 `slow`） |

真的家的地圖含格局資料，**不進 repo**，只存在 Nous 與鴨子本機（`CLAUDE.md` 隱私規則）。

## 執行測試

```bash
cd nous_duck/robot/navigation
uv venv --python 3.11 .venv && uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m pytest tests -q            # 65 通過、1 跳過，約 13 秒
.venv/bin/python -m pytest tests -q --runslow  # 66 通過，約 21 秒
python maps/make_synthetic_home.py --check     # 合成的家跟產生器一致
```

物理層級（MuJoCo＋上游步態策略）的端到端在 [`sim/nav_sim`](../../sim/README.md)。

## 行為摘要

- **速度指令**：上游步態策略在模擬裡有起步門檻，所以只用前進 0.15、後退 −0.15、原地轉 ±1.0／±0.6，轉向連續可調，不用側移。
- **定位**：看不到標籤時不確定度一直長。偏高時先停下轉頭看；超過「未定位」門檻就不再前進，原地轉身找標籤；找不到回報 `lost`。
- **門關著**：走到門前 0.5 m 停下，回報 `door_closed`（帶門的 ID）。
- **被擋住**：重新規劃；真的沒路，有限次數後回報 `blocked`。
- **禁區**：規劃時留 0.45 m 的邊界；估計位置離禁區小於 0.20 m ＋不確定度就立刻停下，回報 `forbidden`。
- **回充**：走到充電座前 1.25 m → 看著標籤沿對位線前進到預備點 → 停下確認 → 原地轉 180° → 倒退進座 → 收到充電訊號才算完成。倒退是盲退，沒對準會退出重來，最多 3 次。

## 已知限制與待辦

- 步態反應表與回充校正量都是模擬值，**實機能走之後要重量**；量法寫在 `sim/walk_sim/measure.py` 的 `gait_table()` 與 `dock_trim.sim.json` 的說明。
- 短程里程是「指令 → 步態反應表」＋陀螺儀的替身，還不是視覺慣性里程。
- 標籤觀測與障礙點在這個目錄裡只有 mock；真的偵測器屬於 `robot/perception/`。
- 沒有做：太暗就不走、落差偵測、跨樓層、建圖工具、`find_person`、`follow_me`、`wait_here`。
- 還沒跟 duckd 實際接起來。
