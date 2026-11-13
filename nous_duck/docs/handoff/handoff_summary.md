# 交接摘要（2026-11-12）

這份文件整理從前一個雲端對話與 ChatGPT 對話交接過來、**已經確定**的事項。之後的 agent 開工前先讀這份。原始資料：

- ChatGPT 對話紀錄：[`chatgpt_conversation_2026-11.md`](chatgpt_conversation_2026-11.md)（13 則使用者訊息、63 則回覆，含 ChatGPT 執行過的程式碼）
- 上游 BOM（原作者 Google Sheets 匯出）：[`upstream_bom.csv`](upstream_bom.csv)
- 雲端環境調查：[`environment_survey.md`](environment_survey.md)

## 1. Repo 狀態

- 本 repo fork 自 [apirrone/Open_Duck_Mini](https://github.com/apirrone/Open_Duck_Mini)，分支 `v2`。
- 2026-11-12 確認：fork 的 `v2` 與上游 `v2` 同為 commit `b23317a`（`Update README.md`），沒有任何差異。
- 上游檔案一律不改，新開發放在 `nous_duck/`（規則見根目錄 [`CLAUDE.md`](../../../CLAUDE.md)）。

## 2. 製作目標

- 依原版 **100% 尺寸**製作一隻 Open Duck Mini v2（腿伸直約 42 cm）。
- 之後把 AIOS（產品名 Nous，跑在 Mac mini 上的 TypeScript 認知作業系統）的功能整合進來；分工見 [`../architecture.md`](../architecture.md) 與 [ADR-0001](../adr/ADR-0001-duck-role-in-nous.md)。

## 3. 舵機

| 項目 | 決定 |
|---|---|
| 主舵機 | Feetech **STS3215-C001**（7.4 V、減速比 1:345，約 19 kg·cm）× 14 |
| 匯流排 | 半雙工 TTL 匯流排，經 Waveshare Bus Servo Adapter (A) 接 Pi Zero 2 W（依上游 BOM） |
| MG995 × 5 | **只拿來做頭部原型**，不上正式機身（見 [`../../hardware/README.md`](../../hardware/README.md)） |

舵機 ID（與上游 `docs/configure_motors.md` 一致）：

| 部位 | 關節 | ID |
|---|---|---|
| 右腿 | hip_yaw / hip_roll / hip_pitch / knee / ankle | 10 / 11 / 12 / 13 / 14 |
| 左腿 | hip_yaw / hip_roll / hip_pitch / knee / ankle | 20 / 21 / 22 / 23 / 24 |
| 頸部與頭部 | neck_pitch / head_pitch / head_yaw / head_roll | 30 / 31 / 32 / 33 |

另外天線由 2 顆小舵機驅動（上游 BOM 列為「9g servos ×2」，`robot.xml` 的 `left_antenna`、`right_antenna` 關節）。

## 4. 列印進度

依上游 `docs/print_guide.md`：36 種 STL、共 **51 件**；49 件 PLA 15% 填充，2 件 `foot_bottom_tpu` 用 TPU 40% 填充。

- **已印完（36 件）**：腳（foot_top、foot_side、foot_bottom_pla、foot_bottom_tpu 各 2）、小腿（knee_to_ankle 左右 sheet 各 4、leg_spacer 4）、大腿與髖部（left/right_roll_to_pitch、roll_motor_bottom/top 各 2）、軀幹（trunk_bottom、trunk_top）、頸部（neck_left/right_sheet）、頭部關節（head_pitch_to_yaw、head_yaw_to_roll、head_roll_mount）、天線座（left/right_antenna_holder）、body_middle_top。
- **還剩 15 件**（每種 1 件）：head、head_bot_sheet、left_cache、right_cache、body_front、body_middle_bottom、body_back、battery_pack_lid、left_eye、right_eye、bulb、flash_light_module、flash_reflector_interface、speaker_interface、speaker_stand。

逐件追蹤表見 [`../build_log/print_status.md`](../build_log/print_status.md)。

## 5. CAD 的缺口

上游 MuJoCo 模型（`mini_bdx/robots/open_duck_mini_v2/robot.xml` 與同目錄的 STL）**沒有**：

- 足底開關（SS-10 ×4）、喇叭、LED、5V 穩壓器、線材、螺絲與熱熔螺帽。
- 眼燈與喇叭相關的 7 件列印件（left_eye、right_eye、bulb、flash_light_module、flash_reflector_interface、speaker_interface、speaker_stand）只有 `print/` 的 STL，**CAD 裡沒有擺放位置**。

組裝檢視器顯示這些零件時，必須標成「示意」（見根目錄 `CLAUDE.md` 的誠實規則）。

## 6. 第一個軟體交付：離線 3D 組裝檢視器

需求（使用者 2026-11-12 對 ChatGPT 提出，見對話紀錄最後一則使用者訊息）：

- 可離線開啟的**單一 HTML**。
- 整隻鴨子的 3D 模型。
- **BOM 爆炸檢視**：每個元件都能看，包含所有電子元件與馬達。
- **逐步組裝指引**。

ChatGPT 做過一版（`Open_Duck_Mini_v2_Assembly_Viewer.html`），但**檔案拿不到**（只存在 ChatGPT 的沙箱 `/mnt/data`）。對話紀錄裡保留了它的產生程式碼，已抽成 10 個檔案放在 [`chatgpt_viewer_src/`](chatgpt_viewer_src/README.md)。這些程式可以當設計參考，但不能直接當成已驗證的實作：

| 面向 | ChatGPT 版的作法（參考） |
|---|---|
| 運動樹 | Python 解析 `robot.xml`，遞迴累積 body 的 `pos`／`quat`，算出每個 geom（STL 網格）的世界座標；套一個基底旋轉把 MuJoCo 座標轉成 three.js 的 Y-up |
| 舵機對應 | 把 `wj-*` 與 `*palonier` 網格依位置分成 14 組，用匈牙利演算法（`scipy.optimize.linear_sum_assignment`）以舵盤中心到關節位置的距離，對到 14 個關節與 ID |
| 網格壓縮 | STL 頂點量化成 int16，gzip 後 base64 內嵌進 HTML |
| 組裝步驟 | 14 步：舵機編號與零位 → 主軀幹與兩顆軸承 → 兩隻腳與足底開關 → 小腿、膝與穿線 → 大腿與髖俯仰零位 → 髖部與雙腿上身 → 頸部與頭俯仰 → 頭部關節、底板與上殼 → 機身控制板與 IMU → 2S 電池艙與供電 → 頭內電子與天線 → 機身外殼與電池艙上機 → 線束檢查與 GPIO 對照 → 上電與首次動作測試 |
| 檢視模式 | three.js：組裝、爆炸、透視三種模式；點模型或 BOM 選取零件、單獨查看；BOM 可搜尋（例如 `ID 24`）；步驟完成狀態存在 localStorage |
| BOM | 75 類（51 件列印件、14 顆主舵機、2 顆天線舵機、Pi Zero 2 W、驅動板、IMU、電池、BMS、充電板、接頭與線束） |
| 已知限制 | ChatGPT 自己說明：部分電子板、線束、緊固件是示意；它的測試瀏覽器沒能驗證本機 HTML 的 WebGL 畫面 |

本 repo 的實作計畫見 [`../../assembly_viewer/README.md`](../../assembly_viewer/README.md)。

## 7. 環境調查結論（摘要）

詳見 [`environment_survey.md`](environment_survey.md)。

- Playwright Chromium 能跑 WebGL 2.0（SwiftShader 軟體算圖），可以截圖驗證 3D 畫面。
- `codeload.github.com`（GitHub 的 zip 下載）與 GitHub 附件圖片（`user-attachments`）在雲端環境回 **403**。
- `raw.githubusercontent.com`、`git clone`、jsDelivr、Google Sheets 的 CSV 匯出都可以用。
- ChatGPT 分享頁可以用 `curl` 加瀏覽器 User-Agent 下載，資料內嵌在 HTML 裡（解法見 [`../../tools/chatgpt_share_to_md.py`](../../tools/chatgpt_share_to_md.py)）。

## 8. 還沒決定的事

- 喇叭、眼燈、麥克風、鏡頭（上游 BOM 的「Expression package」）要不要做、怎麼接；上游 BOM 標註麥克風與鏡頭「not integrated yet」。
- 鴨子與 Mac mini 之間的傳輸方式（WebSocket 或其他），見 [ADR-0001](../adr/ADR-0001-duck-role-in-nous.md) 的待決事項。
- 鎖定的 Open_Duck_Mini_Runtime commit。
