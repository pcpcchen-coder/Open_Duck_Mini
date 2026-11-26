> [繁體中文](README.md) | [English](README.en.md)

# Nous Duck

把一隻原版 100% 尺寸的 [Open Duck Mini v2](../README.md) 做出來，並接上 [Nous（AIOS）](https://github.com/pcpcchen-coder/AIOS)：**Nous 是大腦，鴨子是身體。**

本目錄是這個 fork 自己的全部開發；上游檔案一律不改（規則見根目錄 [`CLAUDE.md`](../CLAUDE.md)）。

## 目前狀態（2026-11-19）

| 項目 | 狀態 |
|---|---|
| 列印 | 原版 51／51 件已印完（[進度](docs/build_log/print_status.md)） |
| 採購 | 周邊零件採購中（[清單與賣場](docs/build_log/README.md)） |
| 組裝 | 尚未開始 |
| 軟體 | 組裝檢視器第一版可用（[直接下載 HTML](assembly_viewer/release/duck_viewer.html)）：單一 HTML、離線開啟，依上游 CAD 顯示 138 個零件、14 顆舵機 ID 與 15 步組裝順序，可爆炸、透視（[pipeline 驗證](docs/validation/viewer-pipeline-2026-11-13.md)、[前端驗證](docs/validation/viewer-web-2026-11-15.md)，層級為單元測試與無頭瀏覽器）。V3「說話時看著對方」的頭部控制器完成，單元測試與 MuJoCo 模擬通過（[驗證](docs/validation/look-at-sim-2026-11-16.md)，未實機）。BOM 與其他模組仍是「規劃中」 |
| 設計 | 行動夥伴需求 [R-001](docs/requirements/R-001-mobile-companion.md)（導航、行動對話、喚醒找人、自動回充）與 ADR-0002～0006（含可開關的隱私設定）為草案或部分採用；「跟著我來／在這等我」需求 [R-002](docs/requirements/R-002-follow-me.md) 與 [ADR-0007](docs/adr/ADR-0007-follow-me-and-wait-here.md) 為草案（只有設計，實作晚點做）；鴨子的語音（Nous 的聲音加變聲）見 [ADR-0010](docs/adr/ADR-0010-duck-voice.md)，只有設計；記憶系統 [ADR-0011](docs/adr/ADR-0011-duck-memory.md) 已採用（沿用 Nous 記憶層，可以在鴨子旁邊說「記住」；只有設計）；低電量回家互動需求 [R-003](docs/requirements/R-003-low-battery-return.md) 與 [ADR-0012](docs/adr/ADR-0012-low-battery-return-interaction.md) 部分採用（夜間安靜回家、斷線也回家、只用電壓估電量；只有設計與名目推算）；階段見 [路線圖](docs/roadmap.md) |
| 實機驗證 | 無 |

## 分工

- **Nous（Mac mini）**：語音、視覺、記憶、決策。
- **鴨子（目前單板 Pi 4 試用，步態＋安全與感知分成獨立服務；不行再拆回 Pi Zero 2 W＋Pi 4，見 [ADR-0008](docs/adr/ADR-0008-single-board-pi4.md)）**：步態、動作、安全（安全判斷只在鴨子本機）；R-001 後加上室內定位導航、收音與播放、喚醒詞、找人、自動回充。
- 兩邊只透過 [`protocol/`](protocol/README.md) 的版本化 JSON Schema 溝通。

詳見 [架構](docs/architecture.md) 與 [ADR-0001](docs/adr/ADR-0001-duck-role-in-nous.md)。

**2026-11-26 更新**：夥伴功能（對話、眼睛、走路、視覺連動、導航、回充）的實作進度看 [`docs/companion/steps.md`](docs/companion/steps.md)，設計看 [`docs/companion/README.md`](docs/companion/README.md)。

## 目錄

| 路徑 | 內容 | 狀態 |
|---|---|---|
| [`docs/handoff/`](docs/handoff/README.md) | 交接摘要、環境調查、ChatGPT 對話紀錄、上游 BOM | 完成 |
| [`docs/requirements/`](docs/requirements/README.md) | 需求紀錄 | R-001、R-002、R-003 |
| [`docs/architecture.md`](docs/architecture.md) | 鴨子與 Nous 的分工和資料流 | 草案 |
| [`docs/roadmap.md`](docs/roadmap.md) | 階段與 gate、待使用者決定的事 | 草案 |
| [`docs/stereo_vision_plan.md`](docs/stereo_vision_plan.md) | 雙目視覺規劃：AR0144 裝上鴨子後可以做什麼、限制、順序 | 規劃（草案） |
| [`docs/adr/`](docs/adr/README.md) | 架構決策紀錄 | ADR-0001～0011 |
| [`docs/build_log/`](docs/build_log/README.md) | 列印、採購、組裝、校正進度 | 列印完成，周邊採購中 |
| [`docs/validation/`](docs/validation/README.md) | 實機與測試紀錄 | 10 份（3 份含 Pi 4 與舵機的實機紀錄；鴨子尚未組裝行走） |
| [`assembly_viewer/`](assembly_viewer/README.md) | ① 離線單一 HTML 3D 組裝檢視器（第一個交付） | 第一版可用（pipeline、步驟、前端）；BOM 規劃中 |
| [`protocol/`](protocol/README.md) | ② duck-link 協定（JSON Schema） | v0 草案可用（schema、範例、測試） |
| [`robot/`](robot/README.md) | ③ 機上程式（單板 Pi 4 試用，Python） | [`duckd/`](robot/duckd/README.md)（單元測試、通道端到端用模擬身體；實機頭部未測）、[`navigation/`](robot/navigation/README.md)（模擬）、[`perception/`](robot/perception/README.md) 與 [`audio/`](robot/audio/README.md)（合成資料、Pi 量測）、`eyes/`（預覽圖）、[`servo_console/`](robot/servo_console/README.md)（實機） |
| [`nous_adapter/`](nous_adapter/README.md) | ④ 要搬進 AIOS 的 `app.duck.*` adapter 與終端（TypeScript） | hub、17 個工具、`duckctl` 可用（對 mock 與 duckd 模擬身體）；還沒進 AIOS |
| [`sim/`](sim/README.md) | ⑤ MuJoCo 模擬 | `walk_sim/`（全身走路）、`nav_sim/`（導航與回充）、`look_at_sim/` 可用；都未對照實機 |
| [`hardware/`](hardware/README.md) | ⑥ 改裝：MG995 頭部原型、表情模組、接線、感測頭、感知板、充電座 | 規劃中；[充電座](hardware/dock/README.md)為設計 v0（STL 已產生，未列印、未實機） |
| [`tools/`](tools/README.md) | 開發工具（上游未修改檢查、ChatGPT 分享頁轉檔、ChatGPT 版檢視器比對） | 可用 |

## 主要硬體

- Feetech STS3215-C001（7.4 V、1:345）× 14；ID：右腿 10–14、左腿 20–24、頸部與頭部 30–33。
- Raspberry Pi Zero 2 W、Waveshare Bus Servo Adapter、BNO055 IMU、2S 18650 電池（依[上游 BOM](docs/handoff/upstream_bom.csv)）。
- 手上 5 顆 MG995 只用於頭部原型。
- R-001 加裝（規劃中）：感知板 Raspberry Pi 4、Waveshare AR0144 雙目鏡頭、麥克風陣列 reSpeaker XVF3800 USB 4-Mic Array 標準版（與 FamilyRecorder 同款；鏡頭與麥克風都裝頭上）、實體隱私開關、兩片 1.28 吋圓形螢幕當眼睛、背後充電觸點與充電座。

## 依賴

機上 runtime 使用 [apirrone/Open_Duck_Mini_Runtime](https://github.com/apirrone/Open_Duck_Mini_Runtime)（`v2`），以 pip 從 git 安裝並鎖定 commit，暫時不 fork。

## 同步上游

```bash
git remote add upstream https://github.com/apirrone/Open_Duck_Mini.git   # 第一次
git fetch upstream
git merge upstream/v2
bash nous_duck/tools/check_upstream_untouched.sh upstream/v2
```
