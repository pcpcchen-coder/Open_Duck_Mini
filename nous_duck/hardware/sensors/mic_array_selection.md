# 麥克風陣列選型

- 日期：2026-11-12（網路查詢結果，價格與庫存會變動，購買前請再確認）；2026-11-13 改選標準版；2026-11-16 改裝頭上並補標準版尺寸
- 相關：[ADR-0005 §2.2](../../docs/adr/ADR-0005-compute-and-sensor-upgrade.md#22-感測器)、[ADR-0003 §4](../../docs/adr/ADR-0003-mobile-terminal-wake-and-find.md#4-找人被叫醒後走去找是誰叫它)

## 決定（2026-11-16 改）

**用 FamilyRecorder 同款的標準版 reSpeaker XVF3800 USB 4-Mic Array（不含 XIAO，USB VID `0x2886`、PID `0x001A`），水平裝在頭頂。** 型號在 2026-11-13 由 Flex Circular-4 改過來（台灣好買；Flex 只有海外通路）；位置在 2026-11-16 由身體上改到頭上。理由與 CAD 檢查見 [ADR-0005 §2.3.1](../../docs/adr/ADR-0005-compute-and-sensor-upgrade.md#231-麥克風陣列裝在頭上2026-11-16-使用者改決定) 與[驗證紀錄](../../docs/validation/mic-placement-2026-11-16.md)：

- 和 FamilyRecorder 同款、台灣好買，方向讀取的程式在 FamilyRecorder 用過。
- 放在脖子後方的機身頂面雖然放得下，但頭最多只能抬 30°（沒裝時 40°）；放頭頂不影響頭部動作，天線也碰不到。
- 麥克風在頭上，聲音方向要加上頸頭關節角度換算成相對身體，見 [ADR-0003 §4.1](../../docs/adr/ADR-0003-mobile-terminal-wake-and-find.md#41-聲源方向換算麥克風在頭上)。

### 標準版的尺寸（Seeed 官方資料）

| 項目 | 數字 | 來源 |
|---|---|---|
| 板子 | 直徑 100 mm 圓板，PCB 厚 1.2 mm，含零件總高約 6.2 mm | [2D 機構圖](https://files.seeedstudio.com/wiki/respeaker_xvf3800_usb/respeaker_xvf3800_2d_mechanical_drawing.pdf) |
| 麥克風 | 4 顆，邊長 66 mm 的正方形（Flex 圓形版是 44 mm） | 同上；[商品頁](https://www.seeedstudio.com/ReSpeaker-XVF3800-USB-Mic-Array-p-6488.html) |
| 接頭 | USB-C 與 3.5 mm 耳機孔，在板邊 | 2D 機構圖 |
| 規格表外框 | 108×108×18 mm（推測含包裝或外框；機構圖的板子是 Ø100） | 商品頁 |
| 重量 | 沒有找到，要秤手上那一片 | — |

### 與 FamilyRecorder 的關係

[FamilyRecorder](https://github.com/pcpcchen-coder/FamilyRecorder)（Mac 上的常駐錄音與逐字稿）用的就是這一款（USB VID `0x2886`、PID `0x001A`），所以這些可以直接沿用（Apache-2.0）：

- 方向遙測：USB vendor control 讀原始 DoA 角度與語音旗標、四束 Speech Energy（`src/family_recorder/direction.py`）。
- 角度環狀分群、多方向判斷、正前方校準（`docs/hardware.md`）。
- USB 斷線後自動恢復收音（FamilyRecorder #10）。

要注意的差異：

| | FamilyRecorder | 鴨子 |
|---|---|---|
| 型號 | 標準版 XVF3800 | **同款**標準版 XVF3800 |
| 主機 | Mac（Apple Silicon、CoreAudio） | Pi 4（Linux、ALSA、libusb 需 udev 權限） |
| 擺放 | 固定在房間，水平 | 裝在會轉動的頭上；角度要加上頸頭關節換算（ADR-0003 §4.1） |
| 噪音 | 房間環境音 | 頭偏航、側擺舵機就在板子正下方；走路時的舵機與腳步聲 |
| 驗證狀態 | Mac 上已使用 | **尚未驗證**：Linux 上的 USB 音訊、方向讀取指令、斷線恢復 |

<details>
<summary>之前的決定（已被取代）</summary>

- 2026-11-12：**reSpeaker Flex XVF3800 Circular-4（USB 版、不含 XIAO）**，水平裝在機身頂面，讓 0° 固定是身體正前方。
- 2026-11-13：改選標準版（台灣好買），仍裝身體上，待 CAD 確認不擋頸部。
- 2026-11-16：CAD 檢查發現裝背上會讓頭少抬約 10°，改裝頭上。

</details>

> FamilyRecorder 正在使用的那一片如果直接拿到鴨子上，FamilyRecorder 就會沒有麥克風。可以先借來在 Pi 4 上做早期測試，正式裝上鴨子時再買一片同款。

## 需求

| 需求 | 原因 |
|---|---|
| **聲源方向（DoA）** | 被叫醒後要知道往哪裡走（ADR-0003）；單一麥克風做不到 |
| 回音消除（AEC） | 鴨子自己在說話時，仍要聽得到使用者（插話）；也避免自我觸發 |
| 降噪、波束成形 | 舵機與腳步噪音大 |
| USB 隨插即用，接 **Raspberry Pi 4**（感知板） | 不佔 GPIO、Linux 免驅動 |
| 放得下 | 2026-11-16 決定裝頭頂：頭頂平坦區約 156×108 mm，可以水平放 Ø100 的標準版（[驗證紀錄](../../docs/validation/mic-placement-2026-11-16.md)）。機身頂面寬 110 mm 也放得下，但頭會少抬約 10° |
| 重量輕 | 頭部舵機負擔與步態（ADR-0005 §2.4） |

## 候選比較

| 型號 | 晶片／麥克風 | DoA | AEC | 介面 | 尺寸 | 參考價格 | 適合度 |
|---|---|---|---|---|---|---|---|
| reSpeaker Flex XVF3800 Circular-4（不含 XIAO，USB 韌體） | XMOS XVF3800，4 麥克風圓形陣列（間距 44 mm） | 有 | 有 | USB-C（UAC 2.0）；麥克風板以 24-pin FPC 排線接處理板 | 圓形陣列直徑約 73 mm | Seeed 官網約 US$57.99（2026-11-13 查詢，型號 100005504） | 原本的第一推薦（2026-11-12）：專為機器人設計，麥克風板與處理板分離；**台灣沒有通路，2026-11-13 改用標準版** |
| **reSpeaker XVF3800 USB 4-Mic Array（標準版，不含 XIAO）** | XMOS XVF3800，4 麥克風（邊長 66 mm 正方形） | 有 | 有 | USB（UAC 2.0），出廠為 USB 音訊韌體 | 直徑 100 mm 圓板（官方機構圖） | 約 £38～48（英國 The Pi Hut）、A$128（澳洲）、含外殼版在 Amazon 約 US$80 | **採用**：與 FamilyRecorder 同款、台灣好買、DoA 讀法已有可沿用的程式（2026-11-13）；裝在頭頂（2026-11-16） |
| ReSpeaker Lite | XMOS XU316，2 麥克風 | **Seeed 規格表沒有列 DoA** | 有 | USB／I2S | 小 | — | 不建議：沒有方向判斷 |
| ReSpeaker 4-Mic Array for Raspberry Pi（HAT） | 4 麥克風，沒有板上 DSP | 要用軟體算（例如 ODAS） | 沒有 | GPIO（I2S） | Pi HAT | — | 不建議：佔 Pi 4 的 GPIO、沒有 AEC，運算要 Pi 4 自己扛 |
| miniDSP UMA-8 | 7 麥克風 | 要另外刷韌體並自行測試 | 依韌體 | USB | 較大 | — | 不建議：DoA 資料少、較舊 |

## 建議

1. **採用標準版 reSpeaker XVF3800 USB 4-Mic Array**（與 FamilyRecorder 同款），裝在頭頂。購買時注意：
   - 選**不含 XIAO ESP32S3** 的 USB 版本；含 XIAO 的版本是給 MCU 用的另一種韌體與用法。
   - 確認買到的是 USB VID `0x2886`、PID `0x001A` 的同款（FamilyRecorder 的 `list-devices` 可以檢查）。
   - 建議用**不含外殼的裸板**，比較輕、比較薄；支架做進新頭殼（ADR-0005 §2.3.1）。
2. Flex Circular-4 留作備案：麥克風板 73 mm、可與處理板分開放，但只有海外通路。

## 要驗證的事（尚未做）

- 在 Pi 4 上以 USB 音訊裝置辨識、錄音品質。
- DoA 讀取：FamilyRecorder 的 USB control 指令（resource 20／command 18）在 Linux（libusb）上是否一樣能用。
- 秤板子重量；裝上頭頂後對頸部舵機扭力與步態的影響（ADR-0005 §2.4）。
- 頭偏航、側擺舵機在板子正下方，轉頭時的噪音；頭靜止時的喚醒率。
- 四個方向的分類正確率：校準與驗收矩陣見 [ADR-0003 §4.1](../../docs/adr/ADR-0003-mobile-terminal-wake-and-find.md#41-聲源方向換算麥克風在頭上)。
- 鴨子自己說話時的回音消除效果；播放要經 XVF3800 的音訊輸出，AEC 才有參考訊號（ADR-0005 §2.3.1）。

## 查詢來源

- [Seeed：XVF3800 2D 機構圖（PDF）](https://files.seeedstudio.com/wiki/respeaker_xvf3800_usb/respeaker_xvf3800_2d_mechanical_drawing.pdf)
- [Seeed：reSpeaker XVF3800 USB Mic Array 商品頁](https://www.seeedstudio.com/ReSpeaker-XVF3800-USB-Mic-Array-p-6488.html)
- [Seeed Wiki：reSpeaker XVF3800 介紹](https://wiki.seeedstudio.com/respeaker_xvf3800_introduction/)
- [Seeed：reSpeaker Flex XVF3800 Circular-4 商品頁](https://www.seeedstudio.com/reSpeaker-Flex-XVF3800-Circular-4-p-6737.html)

- [Seeed：reSpeaker Flex 入門（wiki）](https://wiki.seeedstudio.com/respeaker_flex_introduction/)
- [GitHub：respeaker/reSpeaker_Flex](https://github.com/respeaker/reSpeaker_Flex)
- [RobotShop：reSpeaker Flex XVF3800 Circular-4](https://www.robotshop.com/products/respeaker-flex-xvf3800-circular-4-ai-powered-microphone-array-for-robotics-embedded-applications)
- [OpenELab：reSpeaker Flex XVF3800 Circular-4 USB Mic Array](https://openelab.io/products/seeed-studio-respeaker-flex-xvf3800-circular-4-without-xiao-esp32s3)
- [FabToLab：reSpeaker Flex XVF3800 Linear/Circular-4](https://www.fabtolab.com/seeed-studio-respeaker-flex-xvf3800-circular-linear)
- [Seeed：reSpeaker XVF3800 USB 4-Mic Array with Case](https://www.seeedstudio.com/ReSpeaker-XVF3800-USB-4-Mic-Array-With-Case-p-6490.html)
- [The Pi Hut：ReSpeaker XMOS XVF3800](https://thepihut.com/products/respeaker-xmos-xvf3800-ai-powered-4-mic-array-for-clear-voice-even-in-noise)
- [Pakronics：ReSpeaker XVF3800 USB 4-Mic Array](https://www.pakronics.com.au/products/respeaker-xvf3800-usb-4-mic-array-with-aec-agc-beamforming-doa-noise-suppression-360-far-field-voice-processing-for-xiao-esp32s3-raspberry-pi-jetson-device-ss101991441)
- [SpecPicks：XVF3800 含外殼版（Amazon 價格）](https://specpicks.com/product/B0GVJ5YQ58)
- [CNX Software：ReSpeaker XMOS XVF3800 介紹](https://www.cnx-software.com/2025/07/29/respeaker-xmos-xvf3800-4-mic-array-board-features-esp32-s3-module-works-over-usb/)
- [OpenELab：Seeed ReSpeaker 系列比較](https://openelab.io/blogs/learn/seeed-studio-respeaker-series-guide)
- [GitHub：respeaker/ReSpeaker_Lite](https://github.com/respeaker/ReSpeaker_Lite/)
- [Medium：麥克風陣列比較（2017，含 miniDSP UMA-8）](https://medium.com/snips-ai/benchmarking-microphone-arrays-respeaker-conexant-microsemi-acuedge-matrix-creator-minidsp-950de8876fda)
