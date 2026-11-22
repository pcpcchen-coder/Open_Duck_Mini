# ADR-0008：單板 Pi 4（取代 Pi Zero 2 W）

- 狀態：**採用（試用期）**（2026-11-22 使用者決定「用 Pi 4 取代 Pi Zero 2 W」，並說明「先用單板 RPI4 試試看，之後實在不行，再拆開」）；達不到 §2.5 的門檻就拆回雙板；§5 的事項待決
- 日期：2026-11-22
- 相關：取代 [ADR-0005](ADR-0005-compute-and-sensor-upgrade.md) §2.1 的雙板決定（ADR-0005 其餘部分照舊）；[ADR-0001](ADR-0001-duck-role-in-nous.md)（安全在鴨子本機）、[ADR-0006](ADR-0006-privacy-settings.md)（眼燈與隱私開關接 Pi 4）
- 驗證：[Pi 4 首次開機](../validation/pi4-firstboot-2026-11-22.md)、[Pi 4 上的上游 runtime](../validation/pi4-runtime-2026-11-22.md)

## 1. 背景

ADR-0005 在 2026-11-12 決定雙板：Pi Zero 2 W 當身體板（上游 runtime 的步態與本機安全），Pi 4 當感知板。2026-11-22 Pi 4 已經燒好卡、開機檢查 27 項全部通過。同一天使用者決定**不用 Pi Zero 2 W**，改由 Pi 4 單板負責全部工作，等於 ADR-0005 表中的方案 B，板子用 Pi 4。

手上的板子：Raspberry Pi 4 Model B Rev 1.5，revision `b03115`，**2 GB**（系統看到 1.8 GiB）。

## 2. 決定

### 2.1 Pi 4 是鴨子唯一的電腦

| 工作 | 原本（ADR-0005） | 現在 |
|---|---|---|
| 上游 runtime：步態策略 50 Hz、舵機匯流排、IMU、足底開關、天線、眼燈 | Pi Zero 2 W | **Pi 4** |
| `robot/safety/`、`robot/nous_link/`、`robot/behaviors/` | Pi Zero 2 W | **Pi 4** |
| `robot/perception/`、`robot/navigation/`、`robot/audio/` | Pi 4 | Pi 4 |
| 兩板之間的內部協定（ADR-0005 §3） | 需要 | **不需要** |

### 2.2 系統與 Python

- 作業系統沿用已經燒好的 Raspberry Pi OS Lite 64-bit **Trixie**（2026-10-06），不重燒 Bookworm。
- 上游 runtime 跑在 **uv 裝的 Python 3.11.18** venv（`~/duck/runtime-venv`），不用系統的 Python 3.13：上游 `setup.cfg` 鎖的 `onnxruntime==1.18.1`、`numpy==1.26.4`、`pygame==2.6.0` 沒有 3.13 版，上游 Pi Zero 2 W 的環境是 Bookworm（Python 3.11）。
- runtime 鎖 commit `376de65`，全部套件版本鎖在 [`robot/deploy/pi4/runtime-constraints.txt`](../../robot/deploy/pi4/runtime-constraints.txt)。上游 runtime 照舊**不 fork、不改**。
- 比上游多裝一個 `gpiod==2.6.0`：Blinka 10.2 在 Pi 4 的 kernel 6.18 上要它才能載入 `board`。
- 安裝用 [`robot/deploy/pi4/setup_runtime.sh`](../../robot/deploy/pi4/setup_runtime.sh)，可以重複執行。

### 2.3 接線：GPIO 腳位照上游

Pi 4 和 Pi Zero 2 W 的 40 pin 排針腳位相同，上游 runtime 寫死的腳位不用改（上游 [`docs/assembly_guide.md`](../../../docs/assembly_guide.md) 的 Pi Zero 腳位表）：

| 用途 | 腳位（實體） | GPIO |
|---|---|---|
| 左／右眼燈 | 16／18 | 23／24 |
| 投影燈 | 22 | 25 |
| 左／右天線 PWM | 32／33 | 12／13 |
| 左／右足底開關 | 15／13 | 22／27 |
| BNO055 SDA／SCL | 3／5 | 2／3 |
| MAX98357A LRC／BCLK／DIN | 35／12／40 | 19／18／21 |

舵機驅動板（Waveshare Bus Servo Adapter (A)）照上游用 USB 接，裝置名 `/dev/ttyACM0`。

### 2.4 單板裡的隔離（取代「安全在另一片板子」）

ADR-0005 選雙板的主要理由是步態與安全不要和感知搶 CPU、不要同一個故障域。單板之後改用作業系統層的隔離。**以下是做法，數字待 P2 量測**：

1. 步態＋安全是一個獨立的 systemd 服務，綁定專用 CPU 核心（`CPUAffinity`），用即時排程或較高優先權。
2. 感知、導航、音訊各自在 systemd slice 裡，限制 `CPUQuota`、`MemoryMax`，綁在其他核心。記憶體只有 2 GB，感知程式超量時被 OOM 砍掉的要是感知，不能是步態。
3. 安全判斷只放在步態服務這一側，不依賴感知服務活著；感知服務當掉時，鴨子停下、站好，不會倒。
4. 硬體 watchdog（`bcm2835_wdt`）：步態服務卡住時重開機，前提是舵機先失去指令會停住（要實測舵機的行為）。

### 2.5 試用期與拆回雙板的門檻（2026-11-22 補充）

使用者說明這是**試用**：「先用單板 RPI4 試試看，之後實在不行，再拆開」。所以單板先試，下表任一項達不到、且調低解析度、幀率、調整 §2.4 的核心與優先權之後仍達不到，就拆回 [ADR-0005](ADR-0005-compute-and-sensor-upgrade.md) 的方案 A（加回 Pi Zero 2 W 當身體板，Pi 4 只做感知）。

拆回時 §2.4 的步態＋安全服務整個搬到 Pi Zero 2 W，感知服務留在 Pi 4，所以兩組程式從一開始就分成獨立服務、只用之後要定義的內部介面溝通，不直接呼叫對方。

以下是**建議值，尚未實測**；第一次實測後依結果調整，量法與數據寫進 `docs/validation/`：

| 項目 | 通過條件 | 量法 |
|---|---|---|
| 步態迴圈時序 | 感知全開（鏡頭、AprilTag、喚醒詞、語音串流）時，50 Hz 迴圈每圈間隔的 p99 ≤ 25 ms，且沒有連續 2 圈以上延遲 | 步態服務記錄每圈時間戳，連續 10 分鐘 |
| 供電 | `vcgencmd get_throttled` 為 `0x0`；排針 5V 在負載下 ≥ 4.9 V | 負載測試前後讀取；萬用表量腳位 4、6 |
| 溫度 | 外殼裝好時 CPU 維持在 80 °C 以下（Pi 4 約 80 °C 起降速） | `vcgencmd measure_temp` |
| 走路 | 感知全開與全關各在平地走 5 分鐘，都沒有跌倒 | 實機 |
| 故障隔離 | 強制結束感知服務時，步態不中斷，鴨子維持站立或安全停下 | `systemctl kill` 感知服務 |

頭殼重新設計時（ADR-0005 §2.3，AR0144）仍保留 Pi Zero 2 W 的位置，拆回雙板時用得到。

## 3. 理由

- 使用者的決定（2026-11-22）。
- 少一片板子、少一組板間連線與協定，接線與維護都簡單。
- 運算餘裕：步態策略 `BEST_WALK_ONNX_2.onnx` 在這片 Pi 4 上推論一次 p50 0.29 ms、p99 0.37 ms（閒置，500 次），50 Hz 每步的預算是 20 ms（[驗證紀錄](../validation/pi4-runtime-2026-11-22.md)）。步態本身只占很小的一部分，主要的負擔還是感知。
- Pi 4 已經燒好卡、檢查通過、runtime 裝好，可以直接往下做。

## 4. 後果

### 4.1 Pi 4 不能裝在頭裡

上游把 Pi Zero 2 W 裝在**頭殼裡**（上游 assembly guide「Head」一節）。Pi 4 板子約 85×56 mm，Pi Zero 2 W 約 65×30 mm，頭裡放不下；就算放得下，頭會更重、頸部舵機負擔更大。所以：

- Pi 4 改裝在**機身**。機身已經有 Waveshare 板與 BNO055（組裝指引第 3 步），USB 與 I2C 線都變短。
- 原本頭裡接 Pi 的線（天線舵機 PWM、眼燈、投影燈、喇叭功放），改成**穿過頸部 4 個關節接到機身**，要留餘量並避開夾點。
- 機身空間（外框約 150×110 mm，裡面還有電池與舵機驅動板）**放不放得下要實際量**，改裝件放 `hardware/compute/`，不改上游 STL。

### 4.2 5 V 電源要重新選

- 樹莓派官方建議 Pi 4 用 5 V／3 A；Pi 4 在約 4.63 V 以下就會報電壓不足並降頻。
- 原版周邊採購清單列的 UBEC 是好盈 **3 A**（5／6 V 可切換）。3 A 給 Pi 4 單獨用就到上限，還要加上天線舵機、眼燈、投影燈、喇叭功放，以及之後的 AR0144、XVF3800 與紅外線補光燈，**不夠**。
- 建議改用 **5 A 以上**的 5 V UBEC，到貨後在負載下量 Pi 端的最低電壓與 `vcgencmd get_throttled`。實際需要多少電流要量。
- 2026-11-22 手上現況：兩顆同規格 UBEC（標籤：輸入 5–23V、輸出 5V 3A，固定 5V，輸出是 3 pin 舵機插頭）。試用期先拿**一顆專給 Pi 4**（插排針腳位 4＝5V、6＝GND），天線舵機等 5V 周邊另外接，照 §2.5 的供電項目量；量不過先把輸出線剪短或換粗線，仍不過就換 5 A。第二顆留給拆回雙板時的 Pi Zero 2 W。**兩顆輸出不並聯**（沒有均流，並聯反而不穩）。

### 4.3 散熱、記憶體、重量

- 機身是封閉的。Pi 4 至少要加散熱片，可能要風扇；過熱是安全條件之一，`get_throttled` 與溫度要接進 `robot/safety/`。
- 2 GB 記憶體：步態服務加感知（雙目、AprilTag、喚醒詞）會很緊，ADR-0003 路線 A（Chromium 終端）大概跑不動。不夠時可以換 4／8 GB 的 Pi 4（尺寸相同，軟體不用改）。
- Pi 4 比 Pi Zero 2 W 重，質量位置也從頭移到機身。ADR-0005 §2.4 的模擬（更新質量、必要時重新訓練步態）照樣要做，**要秤實際重量**。

### 4.4 文件

- `architecture.md`、`robot/README.md` 裡「鴨子（Pi Zero 2 W）」改讀成「鴨子（Pi 4）」；ADR-0005 的雙板段落保留當紀錄。
- 組裝指引寫的是 Pi Zero 2 W（裝在頭裡、5 V 2.5 A）。照本 ADR 調整，**另外寫，不改上游文件**。

## 5. 待決

1. Pi 4 在機身裡的安裝位置與固定方式（要量 `body_middle_bottom`、`battery_pack_lid` 附近的空間）。
2. 5 V UBEC 的型號與額定電流。
3. 散熱：只用散熱片，還是加風扇。
4. §2.4 的核心分配、優先權、記憶體上限數字（P2 spike）。
5. 2 GB 夠不夠；不夠就換 4／8 GB 的 Pi 4。
6. §2.5 的門檻數字在第一次實測後確認；達不到時何時拆回雙板。
