> [繁體中文](README.md) | [English](README.en.md)

# Nous Duck

把一隻原版 100% 尺寸的 [Open Duck Mini v2](../README.md) 做出來，並接上 [Nous（AIOS）](https://github.com/pcpcchen-coder/AIOS)：**Nous 是大腦，鴨子是身體。**

本目錄是這個 fork 自己的全部開發；上游檔案一律不改（規則見根目錄 [`CLAUDE.md`](../CLAUDE.md)）。

## 目前狀態（2026-11-13）

| 項目 | 狀態 |
|---|---|
| 列印 | 原版 51／51 件已印完（[進度](docs/build_log/print_status.md)） |
| 採購 | 周邊零件採購中（[清單與賣場](docs/build_log/README.md)） |
| 組裝 | 尚未開始 |
| 軟體 | 組裝檢視器的資料處理程式（pipeline）已完成：從上游 CAD 算出 138 個零件的位置、對上 14 顆舵機 ID，單元測試與 MuJoCo 交叉驗證通過（[驗證紀錄](docs/validation/viewer-pipeline-2026-11-13.md)）。前端與其他模組仍是「規劃中」 |
| 設計 | 行動夥伴需求 [R-001](docs/requirements/R-001-mobile-companion.md)（導航、行動對話、喚醒找人、自動回充）與 ADR-0002～0006（含可開關的隱私設定）為草案或部分採用；階段見 [路線圖](docs/roadmap.md) |
| 實機驗證 | 無 |

## 分工

- **Nous（Mac mini）**：語音、視覺、記憶、決策。
- **鴨子（身體板 Pi Zero 2 W＋感知板 Pi 4）**：步態、動作、安全（安全判斷只在鴨子本機）；R-001 後加上室內定位導航、收音與播放、喚醒詞、找人、自動回充。
- 兩邊只透過 [`protocol/`](protocol/README.md) 的版本化 JSON Schema 溝通。

詳見 [架構](docs/architecture.md) 與 [ADR-0001](docs/adr/ADR-0001-duck-role-in-nous.md)。

## 目錄

| 路徑 | 內容 | 狀態 |
|---|---|---|
| [`docs/handoff/`](docs/handoff/README.md) | 交接摘要、環境調查、ChatGPT 對話紀錄、上游 BOM | 完成 |
| [`docs/requirements/`](docs/requirements/README.md) | 需求紀錄 | R-001 |
| [`docs/architecture.md`](docs/architecture.md) | 鴨子與 Nous 的分工和資料流 | 草案 |
| [`docs/roadmap.md`](docs/roadmap.md) | 階段與 gate、待使用者決定的事 | 草案 |
| [`docs/adr/`](docs/adr/README.md) | 架構決策紀錄 | ADR-0001～0006 |
| [`docs/build_log/`](docs/build_log/README.md) | 列印、採購、組裝、校正進度 | 列印完成，周邊採購中 |
| [`docs/validation/`](docs/validation/README.md) | 實機與測試紀錄 | 尚無紀錄 |
| [`assembly_viewer/`](assembly_viewer/README.md) | ① 離線單一 HTML 3D 組裝檢視器（第一個交付） | pipeline 已完成；BOM、步驟、前端規劃中 |
| [`protocol/`](protocol/README.md) | ② duck-link 協定（JSON Schema） | 規劃中 |
| [`robot/`](robot/README.md) | ③ 機上程式（Pi Zero 2 W，Python） | 規劃中 |
| [`nous_adapter/`](nous_adapter/README.md) | ④ 要搬進 AIOS 的 `app.duck.*` adapter 與終端（TypeScript） | 規劃中 |
| [`sim/`](sim/README.md) | ⑤ MuJoCo 模擬 | 規劃中 |
| [`hardware/`](hardware/README.md) | ⑥ 改裝：MG995 頭部原型、表情模組、接線、感測頭、感知板、充電座 | 規劃中 |
| [`tools/`](tools/README.md) | 開發工具（上游未修改檢查、ChatGPT 分享頁轉檔） | 可用 |

## 主要硬體

- Feetech STS3215-C001（7.4 V、1:345）× 14；ID：右腿 10–14、左腿 20–24、頸部與頭部 30–33。
- Raspberry Pi Zero 2 W、Waveshare Bus Servo Adapter、BNO055 IMU、2S 18650 電池（依[上游 BOM](docs/handoff/upstream_bom.csv)）。
- 手上 5 顆 MG995 只用於頭部原型。
- R-001 加裝（規劃中）：感知板 Raspberry Pi 4、Waveshare AR0144 雙目鏡頭、麥克風陣列 reSpeaker Flex XVF3800 Circular-4（鏡頭裝頭上、麥克風裝身體上）、實體隱私開關、RGB 眼燈、背後充電觸點與充電座。

## 依賴

機上 runtime 使用 [apirrone/Open_Duck_Mini_Runtime](https://github.com/apirrone/Open_Duck_Mini_Runtime)（`v2`），以 pip 從 git 安裝並鎖定 commit，暫時不 fork。

## 同步上游

```bash
git remote add upstream https://github.com/apirrone/Open_Duck_Mini.git   # 第一次
git fetch upstream
git merge upstream/v2
bash nous_duck/tools/check_upstream_untouched.sh upstream/v2
```
