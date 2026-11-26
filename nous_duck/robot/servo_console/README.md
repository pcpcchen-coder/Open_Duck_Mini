# 舵機控制台（servo_console）

狀態：**第一版可用**（2026-11-25）。驗證層級：單元測試（模擬匯流排）、本機瀏覽器（模擬匯流排）、**實機**（Pi 4＋14 顆 STS3215，頭部小幅移動；見[驗證紀錄](../../docs/validation/servo-console-2026-11-25.md)）。還沒有在實機上用網頁長時間操作腿部。

在 Pi 4 上跑的網頁工具：用瀏覽器（電腦或手機，同一個區網）控制 14 顆舵機，畫面中間是**跟著實際舵機角度動的 3D 鴨子**（沿用 [組裝檢視器](../../assembly_viewer/README.md) 的模型）。

這是**本機的開發／調校工具**，不是 duck-link，也不經過 Nous（[ADR-0001](../../docs/adr/ADR-0001-duck-role-in-nous.md)）。安全規則全部在 Pi 上的伺服器執行，不依賴瀏覽器。

## 功能

| 區塊 | 功能 |
|---|---|
| 上方列 | 連線匯流排／釋放硬體、全部出力、全部放鬆、停在這裡、最高速度（15／30／60／90 °/s）、全部 kp（2／8／16／32）、**緊急停止**（也可按 Esc） |
| 舵機清單 | 14 顆依 ID 分組（右腳 10–14、左腳 20–24、頭頸 30–33）：出力開關、目標角度滑桿（範圍來自 `robot.xml`）、目標與實際角度、溫度 |
| 3D | 依舵機回讀（扣掉偏移）擺姿勢；可切換顯示「目標」；沒出力的舵機畫成灰色；點舵機選取；透視外殼、舵機 ID、六個視角 |
| 選取 | 選取舵機的角度、指令、範圍、偏移、溫度、電壓、負載、kp；±1／5／10° 微調；這顆出力／放鬆；這顆的 kp |
| 姿勢 | 內建「零點」「站姿（上游 `init_pos`）」；儲存目前目標成自訂姿勢（存在 Pi 的 `~/duck/console_poses.json`）、套用、刪除 |
| 偏移 | 14 顆的零點偏移 ±0.2／±1° 微調（關節角度不變，舵機轉同樣角度），存入上游 `~/duck_config.json`（先備份）、還原 |
| 電力 | 電池電壓（由 14 顆舵機回報電壓的中位數推估）、每顆電芯電壓、電壓條（停止／警告門檻）；舵機總電流與估計功率；每顆舵機的電壓、電流、功率、溫度、負載、異常旗標；Pi 4 的 `get_throttled`、核心／SDRAM 電壓、ARM 時脈、CPU 溫度；最近 15 分鐘的電池電壓、總電流、溫度趨勢圖（每秒一筆，只在記憶體） |
| 感測 | BNO055（尤拉角、加速度與合力、角速度、校準狀態）、足底開關（GPIO 22／27）、Pi 4（`get_throttled`、CPU 溫度、負載、記憶體、開機時間） |
| 音效 | 播放上游 runtime 附的 9 個 wav（ALSA 預設輸出） |
| 紀錄 | 連線、扭力、姿勢、偏移、警報、緊急停止的事件 |

## 安全規則（伺服器端）

| 規則 | 做法 |
|---|---|
| 角度上限 | 目標夾在 `robot.xml` 的關節範圍內，再往內縮 2°。**這是模擬模型的範圍，不保證實際機構、線材不會卡** |
| 限速 | 目標不直接寫給舵機：控制迴圈（50 Hz）以最高速度（預設 30°/s）一步步逼近 |
| 開扭力不跳 | 開扭力前先讀目前位置、把目標設成目前位置 |
| 緊急停止 | 全部關扭力並鎖住；沒連線時也會臨時開序列埠關扭力。要按「解除」才能再出力，解除後扭力維持關閉 |
| 溫度 | 任一顆 ≥ 55 °C 警告、≥ 65 °C 自動緊急停止（**暫定值**） |
| 電壓 | 任一顆 < 6.6 V 警告、< 6.0 V 自動緊急停止（2S 每顆 3.3／3.0 V，**暫定值**） |
| 讀取失敗 | 連續 5 次失敗：停止移動並警告；恢復後自動解除。pypot 的通訊例外（封包損壞）也算失敗，並清掉序列埠緩衝區 |
| 舵機異常旗標 | 舵機自己回報的電壓、溫度、電流、過載等旗標：警告（不自動停止） |
| 瀏覽器斷線 | 超過 2 秒沒有任何請求：停止移動、**維持出力**（避免懸空時摔下來） |
| 釋放／服務重啟 | 只釋放序列埠、I2C、GPIO，**不改扭力狀態** |
| 硬體衝突 | 連線前檢查 `/dev/ttyACM0`、`/dev/i2c-1`、`/dev/gpiochip*` 有沒有被其他程式開著（例如上游走路程式），有就拒絕 |
| 存取 | **預設不需要 token**（使用者在家裡區網使用，2026-11-25 決定）：同一個網路裡任何人只要知道網址，都能讓舵機動、改偏移設定，頁面上方會標「不需 token」。要開：伺服器加 `--require-token`（部署時 `CONSOLE_REQUIRE_TOKEN=1`），API 就要標頭 `X-Duck-Token`；token 在 Pi 的 `~/.config/nous-duck/console_token`（600），網址用 `#t=<token>` 帶進頁面 |

kp 寫的是 STS3215 的 P 係數暫存器（位址 21，在 EEPROM 區）。上游 `turn_on` 每次啟動也會寫；控制台只在按下時寫，不會在迴圈裡反覆寫。

## 安裝與使用

部署（在 Mac 的 repo checkout 裡，Pi 已經跑過 [`setup_runtime.sh`](../deploy/pi4/setup_runtime.sh)）：

```bash
bash nous_duck/robot/deploy/pi4/deploy_console.sh
```

腳本會建置頁面、複製到 Pi 的 `~/duck/console/`、安裝並啟動 systemd 服務 `duck-console`（開機自動啟動），最後印出網址 `http://duck-pi4.local:8080/`。

要開 token 檢查：

```bash
CONSOLE_REQUIRE_TOKEN=1 bash nous_duck/robot/deploy/pi4/deploy_console.sh
```

這時腳本印出的網址會帶 `#t=<token>`；之後要再看 token：`ssh duck-pi4 'cat ~/.config/nous-duck/console_token'`。

服務啟動時**不碰硬體**，要在頁面按「連線匯流排」。要跑上游的腳本（`check_motors.py`、走路等）前，先按「釋放硬體」，或：

```bash
ssh duck-pi4 'sudo systemctl stop duck-console'
```

移除服務：`bash nous_duck/robot/deploy/pi4/deploy_console.sh --uninstall`。

## 程式結構

| 檔案 | 內容 |
|---|---|
| `servo_console/joints.py` | 關節表（ID、中文名稱）、上游站姿、讀 `console_joints.json` 的範圍 |
| `servo_console/bus.py` | 真的匯流排（pypot `FeetechSTS3215IO`，讀不到就丟錯，不回傳假值）與模擬匯流排 `MockBus` |
| `servo_console/controller.py` | 控制核心：連線、50 Hz 迴圈、限速、安全規則、偏移、姿勢 |
| `servo_console/system.py` | Pi 狀態、BNO055、足底開關、音效 |
| `servo_console/server.py` | HTTP 伺服器（只用標準函式庫）與 API |
| `tests/` | 單元測試（模擬匯流排，19 項） |
| 頁面原始碼 | [`assembly_viewer/web/src/console/`](../../assembly_viewer/web/src/console/)（沿用檢視器的網格解碼、樣式與打包；`npm run build:console` 產生 `dist/duck_console.html` 與 `dist/console_joints.json`） |

3D 擺姿勢的公式（每個 body 的矩陣 = 平移(p)·旋轉(軸, q)·平移(−p)，由根往下相乘）由 [`tests/pipeline/test_pose_fk.py`](../../assembly_viewer/tests/pipeline/test_pose_fk.py) 和 MuJoCo 比對：20 組隨機角度，位置誤差 < 0.001 mm、方向誤差 < 0.0001°。

依賴：Pi 上沿用 `~/duck/runtime-venv`（pypot、Blinka、adafruit_bno055，版本鎖在 [`runtime-constraints.txt`](../deploy/pi4/runtime-constraints.txt)），伺服器本身只用標準函式庫。測試只需要 pytest。

## 在電腦上試（模擬匯流排，不碰硬體）

需要 Python 3.10 以上與 Node.js 22（先依 [assembly_viewer/pipeline](../../assembly_viewer/pipeline/README.md) 產生 `dist/build/`）。

```bash
cd nous_duck/assembly_viewer/web && npm ci && npm run build:console
```

```bash
cd nous_duck/robot/servo_console && python3 -m servo_console --mock --bind 127.0.0.1 --port 8765 --html ../../assembly_viewer/dist/duck_console.html --joints ../../assembly_viewer/dist/console_joints.json --config /tmp/duck_config.json --poses /tmp/duck_poses.json
```

開 `http://127.0.0.1:8765/`。頁面會標「模擬匯流排」，IMU 也是模擬資料。

## API

`GET /api/state`、`GET /api/history`（電力歷史）；`POST /api/<動作>`（JSON）：`connect`、`release`、`estop`、`reset_estop`、`torque {joints, on}`、`targets {targets_deg}`、`hold`、`speed {deg_s}`、`kp {joints, kp}`、`offset {joint, delta_deg}`、`offsets_save`、`offsets_reload`、`pose_apply {key}`、`pose_save {name}`、`pose_delete {name}`、`sound {name}`。`joints` 是關節名稱清單或 `"all"`。指令不能執行時回 409 與中文原因。

## 還沒做

- 動作錄製與播放（多個姿勢依時間串起來）。
- IMU 姿態套到 3D 模型（要等 BNO055 裝進機身、確認方向與校準）。
- 天線舵機、眼燈、投影燈（表情套件還沒接）。
- 長時間出力下的溫度、電流量測與門檻校正。
