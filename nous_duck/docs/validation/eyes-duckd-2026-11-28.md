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
