# 眼睛：duckd 接上兩片實體螢幕（2026-11-28）

- 批次：E2（眼睛接進 duckd）（[眼睛硬體設計 §6](../../hardware/expression_mods/gc9a01_eyes.md#6-批次)）
- 驗證層級：**實機（桌上）**。Pi 4＋兩片 GC9A01；duckd 是 systemd 服務，連著 Nous；**頭沒有接手（`engaged: false`），舵機沒有出力**。單元測試另外跑過（假的 SPI／GPIO）。
- 畫面內容：**這份紀錄寫的時候使用者還沒看過**；面板沒有回讀，程式只能確認資料送出去。
- 沒有做的：裝上頭、舵機在動時、長時間穩定性、亮度與耗電。

## 1. 做了什麼

- `duckd/eyes_out.py`：`EyesOutput(hardware=...)` 把每幀送到 `duck_eyes.gc9a01`（只送變動的 24×24 格子）；PNG 預覽每秒最多寫一次。送失敗就放開螢幕、退回只寫 PNG，`capabilities.eyes` 改回 `mock` 並附原因。
- `capabilities.eyes`：實體螢幕在用時回報 `degraded`（"no pixel readback"），不回報 `available`。`app.duck.express` 的 `confirmed` 讀回的是渲染端的表情。
- `duckd/__main__.py`：`--eyes-hw`、`--eyes-spi-hz`（預設 20 MHz）、`--eyes-rotation`、`--eyes-swap`。
- `deploy_duckd.sh`：duckd-venv 加裝 `spidev==3.6`（gpiod 2.6.0 沿用 runtime-venv）；服務改成 `--eyes-hw --eyes-fps 15`。

## 2. Pi 上的步驟（使用者同意「Yes, restart」）

1. 重開前紀錄：duckd 從 11-27 23:29 跑到 11-28 00:25，控制迴圈 overrun 84 次，`throttled=0x0`，頭沒接手。
2. `deploy_duckd.sh`（會先停 duckd）→ `sudo systemctl start duckd`。
3. 啟動後：重新連上 Nous；`eyes.panel = gc9a01`；表情跟著 presence（listening／speaking）走。

## 3. 量測（啟動後約 80 秒，對話進行中）

| 項目 | 數值 |
|---|---|
| 實際幀率 | 約 6～6.5 fps（目標 15）：477 幀／約 80 秒；之後 listening 每 5 秒約 33 幀 |
| 渲染中位數／最大 | 50 ms／89 ms（11-27 單獨跑約 21 ms；這時 Pi 上 chromium 吃掉約 75% CPU，load 3.2） |
| 傳送中位數／最大 | 108～111 ms／134 ms |
| 控制迴圈 | 50 Hz；啟動後 80 秒 overrun 3 次（之前約 1.5 次／分鐘），單次 tick 最長 33 ms |
| 溫度／降頻 | 65 °C；`throttled=0x0` |

## 4. 為什麼慢：對話中的狀態環

11-27 的桌上測試（16 fps）狀態環是靜止的；對話中（`conversation_active`）狀態環在動，環經過的格子每幀都要重送。在 Mac 上用同一套渲染算每幀要送的像素（一眼，平均 39 幀）：

| 表情 | 對話中？ | 24×24 格 | 12×12 格 | 8×8 格 |
|---|---|---|---|---|
| listening | 否 | 24,310 | 19,384 | 16,968 |
| listening | 是 | **44,514** | 33,415 | 28,416 |
| speaking | 是 | 21,902 | 15,699 | 13,019 |
| neutral | 是 | 20,898 | 14,573 | 11,933 |

一眼 57,600 像素；listening 對話中每幀要送 77%。兩眼 44.5k 像素 × 2 bytes × 2 ≈ 178 KB，20 MHz 理論約 71 ms，加上指令開銷就是量到的 ~110 ms。

改善方向（都還沒做）：更小的格子（8×8 少送約 36%，但指令數變 4 倍，要在 Pi 上量指令開銷）、狀態環另外用逐列的精確範圍、提高 SPI 時脈（31 MHz 沒看過畫面）、渲染與傳送重疊。

## 5. 加速後（PR #60：渲染與傳送重疊＋逐條只送有變的欄，使用者同意再重開一次）

使用者在第一版看過螢幕：「Works, speed it up」（畫面有跟著對話換表情）。加速版部署後，使用者跟 Nous 講話約 100 秒，每 5 秒記一次 `duckd-ctl status`（頭**沒接手**）。

| 狀態 | 第一版（§3） | 加速後 |
|---|---|---|
| idle（狀態環靜止） | — | **約 15 fps**（每 5.3 秒約 80 幀；目標 15） |
| 對話中（listening／speaking／working 交替） | 約 6～6.5 fps | **約 11 fps**（81 秒 889 幀；每段 6.4～14 fps，working 最低） |
| 傳送中位數（最近 100～200 幀） | 108～111 ms | 對話中 52～117 ms；idle 4～5 ms |
| 渲染中位數 | 50 ms | 對話中 2～16 ms（重疊後渲染不再卡住傳送；中位數含快取命中） |

**代價：控制迴圈 overrun 變多。** overrun＝50 Hz 控制迴圈有一圈晚於 20 ms 排程（`link.py`）。

| | overrun |
|---|---|
| 只有虛擬面板、1 fps（11-27 23:29 起約 56 分鐘） | 84 次，約 1.5 次／分鐘 |
| 第一版（串行） | 開機 80 秒 3 次；之後約 12 分鐘到 22 次，約 2 次／分鐘 |
| 加速後 | idle 60 秒 1 次；對話約 100 秒 25 次（約 15 次／分鐘）；單圈最長 34.6 ms；平均仍 49.9 Hz |

推測原因：眼睛的渲染與傳送現在幾乎一直在跑，Python 的 GIL 被眼睛執行緒占的時間變多（spidev 每次 ioctl 與 gpiod 切 DC 都是很短的 Python 呼叫，每幀約 20～40 次 blit）。頭沒接手時沒有影響；**接手時偶爾一圈晚 10～15 ms**，頭的命令本來就經過限速，風險低，但要先處理再拿來跑步態。根本做法是把眼睛移到自己的行程（不和控制迴圈共用 GIL），還沒做。

`blit_cost_px`（400）還沒校正：stats 的 `px_per_frame`／`blits_per_frame` 是開機以來的平均，不能直接拆出單次 blit 開銷，要另外量。量測時 Pi 上 chromium 仍在跑（load 4.6），67 °C，`throttled=0x0`。

## 6. 眼睛搬到子行程（使用者同意再重開一次）

`duckd/eyes_proc.py`：`--eyes-hw` 時 duckd spawn 一個子行程負責渲染與 SPI，duckd 每 50 ms 送狀態快照、子行程每秒回報。子行程 nice 0（這一輪還沒調優先權）。部署後使用者跟 Nous 講話，每 5 秒記一次（頭**沒接手**）：

| | idle | 對話中 |
|---|---|---|
| overrun | 開機前 15 秒 4 次（spawn 時 import），之後約 110 秒 0 次 | 約 45 秒 8 次（約 10 次／分鐘） |
| 眼睛幀率 | 約 15 fps | 約 10 fps（27 秒 278 幀） |
| 子行程 | 活著、沒有重啟 | 同左 |

和 §5（同一行程，約 15 次／分鐘）比只少了三分之一，所以 GIL 不是主因。量的時候 4 核心上：chromium 兩個行程約 55%（nice 5），眼睛子行程三個執行緒合計約 36%；load 2.9。推測是 CPU 排程搶不到（對話中眼睛渲染＋傳送＋chromium＋語音服務同時在跑）。下一步先把子行程設成 nice 5（和 chromium 同級，低於 duckd），**還沒量**。

單圈最長 43.9 ms 出現在剛啟動時（spawn 子行程 import numpy 的那幾秒）。

## 7. 設定頁調亮度與幀率（使用者同意重開 duckd 與 duck-settings）

`eyes.brightness`（0.1～1，軟體調暗）與 `eyes.fps`（2～20）上了設定頁，duckd 即時套用（子行程經快照）。

- 部署：`deploy_duckd.sh` → 啟動 duckd；`deploy_settings.sh` 只複製檔案、**沒有重啟**正在跑的 duck-settings（頁面還是舊版、`eyes.brightness` 仍是「硬體未到」），所以另外 `sudo systemctl restart duck-settings`。
- 在 Pi 上用設定頁的 API（和頁面送的一樣）存 `eyes.brightness=0.5`、`eyes.fps=8`：約 1 秒內 duckd 回報 `brightness 0.5`、`fps_target 8`、**實際 8.0 fps**；設定頁兩項都顯示「已生效」。改回 `eyes.fps=15`：實際 15.0 fps。頭**沒接手**。
- 亮度留在 0.5 給使用者目視：使用者回覆「Dimmer, works」（兩片眼睛確實變暗）。
- 無頭瀏覽器（Mac，模擬的 duckd）：改亮度、改幀率都顯示「已生效」，幀率 30 被拒絕。
