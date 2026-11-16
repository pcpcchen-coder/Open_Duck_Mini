# 麥克風陣列選型

- 日期：2026-11-12（網路查詢結果，價格與庫存會變動，購買前請再確認）；2026-11-13 改選標準版
- 相關：[ADR-0005 §2.2](../../docs/adr/ADR-0005-compute-and-sensor-upgrade.md#22-感測器)、[ADR-0003 §4](../../docs/adr/ADR-0003-mobile-terminal-wake-and-find.md#4-找人被叫醒後走去找是誰叫它)

## 決定（2026-11-13 更新）

使用者決定用 **reSpeaker XVF3800 USB 4-Mic Array 標準版**，也就是 FamilyRecorder 正在用的同一款（USB VID `0x2886`、PID `0x001A`），理由是台灣好買。2026-11-12 原本選的 Flex Circular-4 只在海外通路找得到，不再採用。

麥克風陣列**裝在鴨子身體上**（水平安裝在機身頂面，讓 0° 固定是身體正前方；見 [ADR-0005 §2.3.1](../../docs/adr/ADR-0005-compute-and-sensor-upgrade.md#231-麥克風陣列裝在身體上2026-11-12-使用者決定)）。

### 與 FamilyRecorder 的關係

使用者的 [FamilyRecorder](https://github.com/pcpcchen-coder/FamilyRecorder) 專案（Mac 上的常駐錄音與逐字稿）用的是**標準版** reSpeaker XVF3800 USB 4-Mic Array（USB VID `0x2886`、PID `0x001A`），**與鴨子用的是同一款**。所以 FamilyRecorder 已經做好的這些可以直接參考或沿用（Apache-2.0）：

- 方向遙測：USB vendor control 讀原始 DoA 角度與語音旗標、四束 Speech Energy（`src/family_recorder/direction.py`）。
- 角度環狀分群、多方向判斷、正前方校準（`docs/hardware.md`）。
- USB 斷線後自動恢復收音（FamilyRecorder #10）。

要注意的差異：

| | FamilyRecorder | 鴨子 |
|---|---|---|
| 型號 | 標準版 XVF3800 | **同款**標準版 XVF3800 |
| 主機 | Mac（Apple Silicon、CoreAudio） | Pi 4（Linux、ALSA、libusb 需 udev 權限） |
| 擺放 | 固定在房間 | 裝在會走動的身體上、靠近髖部舵機噪音 |
| 驗證狀態 | Mac 上已使用 | **尚未驗證**：USB ID 與控制指令相同（同款），要驗證的是 Pi 4／Linux 上的收音、DoA 讀取（udev 權限）與走路噪音 |

> FamilyRecorder 正在使用的那一片如果直接拿到鴨子上，FamilyRecorder 就會沒有麥克風。可以先借來在 Pi 4 上做早期測試，正式裝上鴨子時再買一片同款。

## 需求

| 需求 | 原因 |
|---|---|
| **聲源方向（DoA）** | 被叫醒後要知道往哪裡走（ADR-0003）；單一麥克風做不到 |
| 回音消除（AEC） | 鴨子自己在說話時，仍要聽得到使用者（插話）；也避免自我觸發 |
| 降噪、波束成形 | 舵機與腳步噪音大 |
| USB 隨插即用，接 **Raspberry Pi 4**（感知板） | 不佔 GPIO、Linux 免驅動 |
| 放得進機身（原本評估頭部） | 機身頂面要能水平放一片直徑約 99 mm 的板子（標準版；Flex 的麥克風板只有 73 mm）。原版 `body_middle_top` 外框約 150×110 mm（從 STL 量的），放得下但很貼邊，要在 CAD 確認不擋到頸部活動 |
| 重量輕 | 頭部舵機負擔與步態（ADR-0005 §2.4） |

## 候選比較

| 型號 | 晶片／麥克風 | DoA | AEC | 介面 | 尺寸 | 參考價格 | 適合度 |
|---|---|---|---|---|---|---|---|
| reSpeaker Flex XVF3800 Circular-4（不含 XIAO，USB 韌體，型號 100005504） | XMOS XVF3800，4 麥克風圓形陣列（間距 44 mm） | 有 | 有 | USB-C（UAC 2.0）；麥克風板以 24-pin FPC 排線接處理板 | 圓形陣列直徑約 73 mm | Seeed 官網約 US$57.99（2026-11-13 查詢） | 原本的第一推薦（麥克風板與處理板分離、較小）；**台灣沒有通路，已改用標準版** |
| **reSpeaker XVF3800 USB 4-Mic Array（標準版，不含 XIAO）** | XMOS XVF3800，4 麥克風 | 有 | 有 | USB（UAC 2.0），出廠為 USB 音訊韌體 | 板子直徑約 99 mm（含外殼版約 102×102×10 mm） | 約 £38～48（英國 The Pi Hut）、A$128（澳洲）、含外殼版在 Amazon 約 US$80 | **採用（2026-11-13）**：與 FamilyRecorder 同款、台灣好買、DoA 讀法已有可沿用的程式；缺點是整片較大、不能拆開 |
| ReSpeaker Lite | XMOS XU316，2 麥克風 | **Seeed 規格表沒有列 DoA** | 有 | USB／I2S | 小 | — | 不建議：沒有方向判斷 |
| ReSpeaker 4-Mic Array for Raspberry Pi（HAT） | 4 麥克風，沒有板上 DSP | 要用軟體算（例如 ODAS） | 沒有 | GPIO（I2S） | Pi HAT | — | 不建議：佔 Pi 4 的 GPIO、沒有 AEC，運算要 Pi 4 自己扛 |
| miniDSP UMA-8 | 7 麥克風 | 要另外刷韌體並自行測試 | 依韌體 | USB | 較大 | — | 不建議：DoA 資料少、較舊 |

## 建議

1. **採用標準版 reSpeaker XVF3800 USB 4-Mic Array**（與 FamilyRecorder 同款）。購買時注意：
   - 選**不含 XIAO ESP32S3** 的 USB 版本；含 XIAO 的版本是給 MCU 用的另一種韌體與用法。
   - 確認買到的是 USB VID `0x2886`、PID `0x001A` 的同款（FamilyRecorder 的 `list-devices` 可以檢查）。
   - 裝在機身上建議用**不含外殼的裸板**，比較輕、比較薄；但要另外做固定支架並保護板子。
2. Flex Circular-4 留作備案：如果標準版的 99 mm 板子在機身頂面放不下或擋到頸部，再考慮 Flex（麥克風板 73 mm，可與處理板分開放），但它只有海外通路。

## 到貨後要驗證的事（尚未做）

- 在 Pi 4 上以 USB 音訊裝置辨識、錄音品質。
- DoA 讀取：FamilyRecorder 的 USB control 指令（resource 20／command 18）在 Pi 4 的 Linux 上能不能讀（libusb 與 udev 權限）。
- 在鴨子走路時的噪音下，喚醒率與 DoA 準確度。
- 鴨子自己說話時的回音消除效果。
- 重量與裝上身體後對步態的影響；被頭頸遮擋時後方聲音的方向準確度。

## 查詢來源

- [Seeed：reSpeaker Flex XVF3800 Circular-4 產品頁](https://www.seeedstudio.com/reSpeaker-Flex-XVF3800-Circular-4-p-6737.html)
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
