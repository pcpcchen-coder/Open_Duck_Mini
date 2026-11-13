# Open Duck Mini v2 原版組裝指引

適用於原版 100% 尺寸、14 顆 STS3215-C001 舵機、Raspberry Pi Zero 2 W 與 BNO055。51 件原版列印件已完成。以下從零件到貨點收開始，到第一次站立、短步行為止。步驟與命令已對照上游文件及程式碼，實機結果請隨組裝記錄。

**到貨後先做兩件事：核對電源零件規格，再逐顆設定舵機 ID 和零位。** 等舵機到貨前，可以先試配軸承、整理左右件、準備 microSD。

[原版周邊採購清單](Open_Duck_Mini_v2_Procurement.html) · [3D 組裝檢視器原始碼與說明](../handoff/chatgpt_viewer_src/README.md) · [原版組裝照片](https://github.com/pcpcchen-coder/Open_Duck_Mini/blob/v2/docs/assembly_guide.md) · [原版整機接線圖](https://github.com/pcpcchen-coder/Open_Duck_Mini/blob/v2/docs/open_duck_mini_v2_wiring_diagram.png)

## 1. 到貨點收與試配

- [ ] 清點 14 顆主舵機、舵盤、隨附螺絲和線材。確認每顆的型號、電壓版本與插頭線序。兩顆 9 g 天線舵機用 PWM，另外放一盤。
- [ ] 核對三顆薄壁軸承候選 `6804ZZ`（20 × 32 × 7 mm），試配軀幹兩顆和頭部一顆。卡住先查列印毛邊或尺寸。
- [ ] 準備 M3 熱熔螺母、烙鐵和萬用表。原手冊明列軀幹用 **M3×10 共 2 支**、腳底用 **M3×6 每腳 2 支**。其餘螺絲長度和總數按孔位、螺紋深度與舵機配件確認。Loctite 243 用於上游指示的金屬對金屬鎖點，塑膠螺絲跳過。
- [ ] 按鴨子面向前方時的自身左右貼標籤。軀幹、兩腿、頭頸、外殼分盤。

驗收：要裝入的零件能試配，左右件和螺絲可辨認，接頭可插拔。

[原版列印清單](https://github.com/pcpcchen-coder/Open_Duck_Mini/blob/v2/docs/print_guide.md) · [軀幹照片與工具清單](https://github.com/pcpcchen-coder/Open_Duck_Mini/blob/v2/docs/assembly_guide.md#assemble-the-trunk)

## 2. 設定 14 顆舵機

先讓舵機在桌上空載，舵盤周圍留空。用一台已裝 Runtime `v2` 的電腦或 Pi，透過 Waveshare 板連線，並給舵機符合該批規格的限流電源。每次只接一顆，換插頭前關閉舵機供電。USB 資料線與舵機電源分別確認。

| 關節 | 右側 | 左側 |
|---|---:|---:|
| 髖偏航 | 10 | 20 |
| 髖側擺 | 11 | 21 |
| 髖俯仰 | 12 | 22 |
| 膝 | 13 | 23 |
| 踝 | 14 | 24 |

| 頭頸關節 | ID |
|---|---:|
| 頸俯仰 | 30 |
| 頭俯仰 | 31 |
| 頭偏航 | 32 |
| 頭側擺 | 33 |

從 Runtime 根目錄、在已安裝依賴的 Python 環境執行。這裡用右腳踝舵機示範，`--port` 換成系統實際辨識到的序列埠。

```bash
python3 scripts/configure_motor.py --port /dev/ttyACM0 --id 14
```

- [ ] 看見設定完成和目標 ID，確認舵機已轉到電子零位。依原圖對齊舵盤，固定前先比對舵盤方向。每顆貼上 ID 與部位，再換下一顆。
- [ ] 記下每顆 ID 與安裝方向。若單顆讀不到，先查電源、資料線、序列埠和 D／V／G 線序。

驗收：14 顆都逐顆讀回，ID 無重複，舵盤已依零位和安裝圖對齊。整機軟體偏移量在第 6 步校正。

[舵機 ID 與舵盤照片](https://github.com/pcpcchen-coder/Open_Duck_Mini/blob/v2/docs/configure_motors.md) · [Runtime 安裝](https://github.com/apirrone/Open_Duck_Mini_Runtime/blob/v2/README.md#install-the-runtime) · [設定程式](https://github.com/apirrone/Open_Duck_Mini_Runtime/blob/v2/scripts/configure_motor.py)

## 3. 組軀幹、腳與腿

| 順序 | 怎麼裝 | 裝完先確認 |
|---|---|---|
| 軀幹 | 把兩顆軸承放進 `trunk_bottom`，依圖熱熔 M3 螺母，底面留給外殼的 4 個孔也先做。用 2 支 M3×10 合上 `trunk_top`，裝中央頸俯仰 ID 30，依圖放入兩個 `roll_motor_bottom`。 | 軸承就位，軀幹上下平貼，底面外殼鎖點仍可用。 |
| 雙腳 | 疊合 PLA 腳底與 TPU 腳墊，每腳 2 支 M3×6。將踝舵機 14／24 的主動舵盤側朝 `foot_top`，按原圖試裝 SS-10。 | 腳掌能平放，開關壓下和放開都有動作。 |
| 小腿 | 為 `leg_spacer` 裝熱熔螺母。先接踝舵機線，依圖穿過 `right_sheet`，再合側板與膝舵機 13／23。 | 右腿的小腿與腳以同一組件轉 180°。依 repo 的 CAD 驗證，膝、踝舵機左腿在外側、右腿在內側。先對圖再鎖。 |
| 大腿 | 裝側板、間隔件及髖俯仰 12／22，照照片核對髖俯仰零位，再接小腿。 | 在可自由活動的範圍內輕試配，線束有餘量，側板沒有夾線。 |
| 髖與雙腿 | 將左右 `roll_to_pitch` 接到髖側擺 11／21。先從下方把 `roll_motor_top` 鎖到髖偏航 10／20，再裝髖側擺子總成及整條腿。 | 左右髖座、舵機 ID 及舵盤方向逐一對上，雙腿能裝入主軀幹。 |

[軀幹](https://github.com/pcpcchen-coder/Open_Duck_Mini/blob/v2/docs/assembly_guide.md#assemble-the-trunk) · [腳與小腿](https://github.com/pcpcchen-coder/Open_Duck_Mini/blob/v2/docs/assembly_guide.md#assemble-the-feet) · [大腿與髖](https://github.com/pcpcchen-coder/Open_Duck_Mini/blob/v2/docs/assembly_guide.md#assemble-the-thighs) · [左右腳 CAD 驗證](https://github.com/pcpcchen-coder/Open_Duck_Mini/blob/v2/nous_duck/docs/validation/viewer-pipeline-2026-11-13.md#驗證中發現的事組裝有用)

## 4. 頭頸、主控與感測器

- [ ] 將左右頸板接到頸俯仰 30，按圖接頭俯仰 31。組起 `head_pitch_to_yaw`、`head_yaw_to_roll`、`head_roll_mount` 與舵機 32／33。
- [ ] 鎖死頭部關節前，先套進 **`head_bot_sheet` 和 `body_middle_top`**。頭殼預裝嵌件與第三顆軸承。先試配，再裝 Pi Zero 2 W、microSD 與已到貨的天線舵機。留出 USB、GPIO 和 CSI 排線的空間。
- [ ] 機身內固定 Waveshare 板與 BNO055，給接頭及絕緣留空間。記下 IMU 實際朝向，後面用 Runtime 核對。
- [ ] 先把機身殼與電池艙試合，保留外殼開放以便量測。上游外殼次序從 `body_middle_bottom` 開始，接著安裝前殼、上殼與電池艙。等通訊和配線確認後再鎖齊。

驗收：頭頸接線不跨過夾點，USB 和電源開關仍可操作，外殼能試合。眼燈、喇叭、相機等選配可依原圖另做試配，初次測試先保持未裝選配關閉。

[頸部與頭部機構](https://github.com/pcpcchen-coder/Open_Duck_Mini/blob/v2/docs/assembly_guide.md#assemble-the-neck) · [頭殼內部照片](https://github.com/pcpcchen-coder/Open_Duck_Mini/blob/v2/docs/assembly_guide.md#head)

## 5. 接線與分段上電

原版電池經 BMS 和電源開關分成兩支路。一支進 Waveshare 板供主舵機，另一支經 UBEC 降為 5 V 給 Pi 與相關周邊。Pi 的資料埠再以 USB 連到舵機板。先對照原版總圖、實際電池板與充電板端子圖，再接電池。

| 訊號 | Pi 實體腳位 | GPIO／電源 |
|---|---:|---|
| BNO055 VIN、GND | 1、9 | 3.3 V、GND |
| BNO055 SDA、SCL | 3、5 | GPIO 2、GPIO 3 |
| 左腳、右腳開關 | 15、13 | GPIO 22、GPIO 27 |
| 足底開關地 | 9 | GND |
| 左、右天線 PWM（如安裝） | 32、33 | GPIO 12、GPIO 13 |
| 天線供電、地（原圖） | 2、6 | 5 V、GND |

- [ ] **不帶電檢查。** 核對極性、電池中點與 BMS 實物端子圖、接頭線序和絕緣。量有無短路後才接電池。2S 充電板要對應 8.4 V 鋰電組。兩顆電芯裝入前先核對電壓，原作者要求兩顆電壓一致。
- [ ] **先量電源，再接負載。** 量主電池輸出及 UBEC 的 5 V 輸出，確認電壓、極性再接 Pi。Pi 官方的 Zero 系列供電建議是 5 V／2.5 A；共用 UBEC 的天線舵機和選配電流要另外納入。Feetech C001 型號頁列 6–7.4 V，部分通路列到 8.4 V。實際批次確認支援 **8.4 V** 後，才讓滿電 2S 直接供這批舵機。
- [ ] **逐段驗證。** 先 Pi 與 IMU，再單顆舵機，接著分組查通訊。最後以架空機體、小行程測試記錄舵機支路峰值及兩支路最低電壓。改線前先斷電。

**Waveshare Bus Servo Adapter (A) 整片額定上限 5 A。** 官方也說輸出電壓跟隨輸入。把 5 A 視為板子的承受上限，按峰值和壓降核對通過它的供電路徑。若達到上限、出現掉壓、重啟、接頭發熱或 BMS 跳保護，立即停測。超出板子額定時，先評估額定足夠的舵機配電，再進入站立測試。

[原版配線與 GPIO](https://github.com/pcpcchen-coder/Open_Duck_Mini/blob/v2/docs/assembly_guide.md#electronics) · [Waveshare 規格 FAQ](https://docs.waveshare.com/Bus_Servo_Adapter_A/FAQ) · [Feetech C001 型號頁](https://ftservo.github.io/ftservo-wiki/products/models/st-3215-c001/main/) · [iCShop C001 規格](https://www.icshop.com.tw/products/388400200025) · [Pi 電源規格](https://www.raspberrypi.com/documentation/computers/getting-started.html#recommended-power-supply) · [P30B 電芯規格](https://www.molicel.com/wp-content/uploads/Product-Data-Sheet-of-INR-18650-P30B-80111-1.pdf)

## 6. Runtime 校正與第一次站立

- [ ] Pi 已可登入、I²C 已開啟。把 Runtime 的 `example_config.json` 複製為 `~/duck_config.json`，依實際方向填 `imu_upside_down`，關閉未安裝的 `expression_features`。先查 IMU 俯仰、側傾方向，再分別壓放足底開關，確認左右觸發。
- [ ] 固定軀幹、讓腳離地且關節有活動空間，準備可立即切斷舵機供電。執行 `python3 scripts/check_motors.py`，核對 14 軸回報及各軸小幅試動。這個程式會命令舵機移動。若有軸失聯，出現繼續提示時選 `n`，回查線路與 ID。
- [ ] 全部小幅試動正常後，依 Runtime 指引從 `scripts/` 執行 `python3 find_soft_offsets.py`。這支程式啟動後會把整機帶到零位，維持架空，先核對機械朝向及行程。將各軸實測值寫入 `duck_config.json` 的 `joints_offsets`。
- [ ] 首次啟動步態程式也保持支撐。Runtime 啟動時會先命令初始姿勢，即使 `start_paused` 已開也要保留空間。確認姿勢、停機方式、壓降及峰值後，再在平坦空地做短時間站立與短步行。通過後關機，整理束線與外殼，最後複查接頭、線束餘量和可操作的開關。

[Runtime v2 測試與步態指令](https://github.com/apirrone/Open_Duck_Mini_Runtime/blob/v2/README.md#test-motors) · [逐軸測試程式](https://github.com/apirrone/Open_Duck_Mini_Runtime/blob/v2/scripts/check_motors.py) · [偏移校正程式](https://github.com/apirrone/Open_Duck_Mini_Runtime/blob/v2/scripts/find_soft_offsets.py) · [步態程式](https://github.com/apirrone/Open_Duck_Mini_Runtime/blob/v2/scripts/v2_rl_walk_mujoco.py)

| 驗收項目 | 實測或紀錄 |
|---|---|
| 主舵機 ID、朝向與零位 | ＿＿／14 顆通過 |
| 左／右足底開關、IMU 方向 | 左＿＿　右＿＿　IMU＿＿ |
| 舵機支路／電池端峰值 | ＿＿ A／＿＿ A（測試動作＿＿） |
| 舵機電源／5 V 支路最低電壓 | ＿＿ V／＿＿ V |
| 站立、短步行與停機 | ＿＿ |
