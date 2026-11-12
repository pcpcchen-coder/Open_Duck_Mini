# 麥克風陣列選型

- 日期：2026-11-12（網路查詢結果，價格與庫存會變動，購買前請再確認）
- 相關：[ADR-0005 §2.2](../../docs/adr/ADR-0005-compute-and-sensor-upgrade.md#22-感測器)、[ADR-0003 §4](../../docs/adr/ADR-0003-mobile-terminal-wake-and-find.md#4-找人被叫醒後走去找是誰叫它)

## 需求

| 需求 | 原因 |
|---|---|
| **聲源方向（DoA）** | 被叫醒後要知道往哪裡走（ADR-0003）；單一麥克風做不到 |
| 回音消除（AEC） | 鴨子自己在說話時，仍要聽得到使用者（插話）；也避免自我觸發 |
| 降噪、波束成形 | 舵機與腳步噪音大 |
| USB 隨插即用，接 **Raspberry Pi 4**（感知板） | 不佔 GPIO、Linux 免驅動 |
| 放得進頭部 | 原版 `head.stl` 外形約 200×197×59 mm（從 STL 量的外框，內部可用空間要再量） |
| 重量輕 | 頭部舵機負擔與步態（ADR-0005 §2.4） |

## 候選比較

| 型號 | 晶片／麥克風 | DoA | AEC | 介面 | 尺寸 | 參考價格 | 適合度 |
|---|---|---|---|---|---|---|---|
| **reSpeaker Flex XVF3800 Circular-4（不含 XIAO，USB 韌體）** | XMOS XVF3800，4 麥克風圓形陣列（間距 44 mm） | 有 | 有 | USB-C（UAC 2.0）；麥克風板以 24-pin FPC 排線接處理板 | 圓形陣列直徑約 73 mm | 查詢時沒找到明確售價 | **第一推薦**：專為機器人設計，麥克風板與處理板分離，可以把麥克風放在頭頂、處理板放在頭內或機身 |
| reSpeaker XVF3800 USB 4-Mic Array（標準版，不含 XIAO） | XMOS XVF3800，4 麥克風 | 有 | 有 | USB（UAC 2.0），出廠為 USB 音訊韌體 | 板子直徑約 99 mm（含外殼版約 102×102×10 mm） | 約 £38～48（英國 The Pi Hut）、A$128（澳洲）、含外殼版在 Amazon 約 US$80 | 第二推薦：同晶片，資料最多；但整片較大，要確認頭內空間 |
| ReSpeaker Lite | XMOS XU316，2 麥克風 | **Seeed 規格表沒有列 DoA** | 有 | USB／I2S | 小 | — | 不建議：沒有方向判斷 |
| ReSpeaker 4-Mic Array for Raspberry Pi（HAT） | 4 麥克風，沒有板上 DSP | 要用軟體算（例如 ODAS） | 沒有 | GPIO（I2S） | Pi HAT | — | 不建議：佔 Pi 4 的 GPIO、沒有 AEC，運算要 Pi 4 自己扛 |
| miniDSP UMA-8 | 7 麥克風 | 要另外刷韌體並自行測試 | 依韌體 | USB | 較大 | — | 不建議：DoA 資料少、較舊 |

## 建議

1. 首選 **reSpeaker Flex XVF3800 Circular-4（不含 XIAO ESP32S3 的 USB 版本）**。購買時注意：
   - 選**不含 XIAO** 的版本；含 XIAO 的版本出廠是 I2S 韌體（給 MCU 用），不是 USB。
   - 同系列還有 Linear-4（線性陣列、長約 110 mm），只能判斷半平面方向，**要選 Circular-4**。
2. 買不到時改用標準版 **reSpeaker XVF3800 USB 4-Mic Array（不含 XIAO）**，並先量頭內空間。
3. 台灣沒有查到本地通路的售價；可查 Seeed 官網或國內電子零件通路。

## 到貨後要驗證的事（尚未做）

- 在 Pi 4 上以 USB 音訊裝置辨識、錄音品質。
- DoA 的輸出方式與讀取方法（查詢時零售頁面沒有說明輸出格式，要看 Seeed wiki 與 GitHub `respeaker/reSpeaker_Flex`）。
- 在鴨子走路時的噪音下，喚醒率與 DoA 準確度。
- 鴨子自己說話時的回音消除效果。
- 重量與裝在頭上後的頸部舵機負載。

## 查詢來源

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
