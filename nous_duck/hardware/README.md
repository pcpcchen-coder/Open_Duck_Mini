# ⑥ 硬體改裝（hardware）

狀態：**規劃中**。原版機身依上游 CAD 與 `print/` 製作，這裡只放**偏離原版**的改裝與我們自己的接線紀錄。

| 子目錄 | 內容 | 狀態 |
|---|---|---|
| `mg995_head_proto/` | 用手上 5 顆 MG995 做的**頭部原型**（只用於原型，正式機身用 STS3215）：支架、控制方式、與 STS3215 的差異 | 規劃中 |
| `expression_mods/` | 表情相關改裝：**眼燈改 RGB LED、由 Pi 4 驅動，用顏色提示鏡頭狀態**（[ADR-0006 §4.2](../docs/adr/ADR-0006-privacy-settings.md#42-鏡頭狀態提示眼燈顏色2026-11-12-決定)）、投影燈、喇叭（上游 BOM 的「Expression package」） | 規劃中 |
| `wiring/` | 本機身實際的接線圖與 GPIO 對照、電源路徑、線材規格；以上游 `docs/open_duck_mini_v2_wiring_diagram.png` 為基礎；**實體隱私開關**（切斷鏡頭與麥克風電源、狀態接 Pi 4 GPIO，[ADR-0006 §4.1](../docs/adr/ADR-0006-privacy-settings.md#41-實體隱私開關2026-11-12-決定加裝)） | 規劃中 |
| `sensors/` | 重新設計的頭殼（AR0144 雙目鏡頭裝頭上）；機身頂面的麥克風支架（reSpeaker XVF3800 USB 4-Mic Array 標準版，裝身體上）；喇叭位置（[ADR-0005](../docs/adr/ADR-0005-compute-and-sensor-upgrade.md)）；[麥克風陣列選型](sensors/mic_array_selection.md) | 規劃中（型號已決定） |
| `compute/` | 感知板（已決定 Raspberry Pi 4）的安裝位置、散熱、身體板與感知板的連線與供電（ADR-0005） | 規劃中 |
| [`dock/`](dock/README.md) | 充電座「屋形靠背扶手椅」：V 形導引座＋彈簧頂針、AprilTag、狀態燈、電子艙；鴨子背後的外掛觸點板（[ADR-0004](../docs/adr/ADR-0004-docking-and-charging.md)） | **設計 v0**：STL 已產生、幾何測試通過；未列印、未實機 |

**列印提醒（2026-11-13 更新）**：使用者回報原版 51 件已全部印完（[列印進度](../docs/build_log/print_status.md)）。背後充電觸點改用**外掛觸點板**貼在已印好的 `body_back` 上，不用重印（[`dock/`](dock/README.md#21-背後觸點板建議外掛在已印好的原版-body_back-上)）。以下是 2026-11-12 的原始提醒，保留作紀錄：`body_back` 確定要改（背後充電觸點），**不要印原版**；`head`（**確定要重新設計**：AR0144 裝頭上）、`body_middle_bottom`、`battery_pack_lid`（Pi 4 安裝與散熱）可能要改，**先暫緩**，等量完內部空間再決定。`left_cache`、`right_cache`、`body_front`、`head_bot_sheet`、`left_eye`、`right_eye`、`bulb`、`flash_light_module`、`flash_reflector_interface`、`speaker_interface`、`speaker_stand` 可以先印。

## MG995 頭部原型注意事項

- MG995 是 PWM 控制的類比/數位舵機（依實際型號而定），**不是** STS3215 那種匯流排舵機；沒有位置、溫度回讀。原型的控制程式與正式機身不同，不能直接沿用 runtime 的匯流排驅動。
- 尺寸、扭力、安裝孔與 STS3215 不同，需要另外設計支架；不改上游 STL，改裝件放本目錄。
- 原型結果（例如頭部動作是否好看）不能直接當成正式機身的驗證。

## 規則

- 每個改裝要寫：為什麼改、改了什麼、材料與列印參數、影響哪些上游零件、驗證結果。
- CAD 或 STL 改裝檔放在對應子目錄，註明基於上游哪個檔案與 commit。
