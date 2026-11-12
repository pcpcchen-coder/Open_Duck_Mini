# CLAUDE.md — Nous Duck 開發規則（本 fork 專用）

給在這個 repo 工作的開發 agent（Claude Code 等）與開發者。建立日期：2026-11-12。

這個 repo 是 [apirrone/Open_Duck_Mini](https://github.com/apirrone/Open_Duck_Mini)（分支 `v2`）的 fork。作者依原版 100% 尺寸製作一隻 Open Duck Mini v2，並把 [AIOS／Nous](https://github.com/pcpcchen-coder/AIOS) 的能力整合進來。我們自己的開發全部放在 [`nous_duck/`](nous_duck/README.md)。

## 開工前

1. 讀 [`nous_duck/README.md`](nous_duck/README.md)、[`nous_duck/docs/roadmap.md`](nous_duck/docs/roadmap.md)、[`nous_duck/docs/handoff/handoff_summary.md`](nous_duck/docs/handoff/handoff_summary.md)、[`nous_duck/docs/architecture.md`](nous_duck/docs/architecture.md) 與 [`nous_duck/docs/adr/`](nous_duck/docs/adr/README.md)。
2. 讀要動的模組的 README，確認它的職責、輸入輸出與「目前狀態」。
3. 一次只做一個可驗收的批次。

## 1. 上游檔案不改

- 上游原有的檔案與目錄（`docs/`、`experiments/`、`mini_bdx/`、`print/`、`README.md`、`.gitignore`、`pyproject.toml`、`setup.cfg`、`*.onnx` 等）**一律不修改、不刪除、不搬移**。這樣 `git merge upstream/v2` 才不會衝突。
- 我們只能新增或修改：`nous_duck/**`、根目錄的 `CLAUDE.md`、`.github/**`（上游沒有這些路徑）。CI（`.github/workflows/nous-duck-ci.yml`）會檢查這一點。
- 需要上游資料時（例如 `mini_bdx/robots/open_duck_mini_v2/robot.xml`、`print/*.stl`），從原路徑**唯讀**取用；產生的東西寫到 `nous_duck/` 底下。
- 想改上游的行為，先寫 ADR；能用包裝、設定或在 `nous_duck/` 覆寫解決就不碰原檔。真的要改上游，應該是對上游開 PR，而不是在這裡改。
- 同步上游：`git fetch upstream && git merge upstream/v2`（remote `upstream` = `https://github.com/apirrone/Open_Duck_Mini.git`）。
- 機上 runtime 依賴 [apirrone/Open_Duck_Mini_Runtime](https://github.com/apirrone/Open_Duck_Mini_Runtime)（`v2`），用 pip 從 git 安裝並**鎖定 commit**，暫時不 fork。

## 2. 模組分工

| 路徑 | 職責 | 語言 |
|---|---|---|
| `nous_duck/assembly_viewer/` | ① 離線單一 HTML 3D 組裝檢視器（第一個交付） | Python pipeline＋TypeScript/three.js |
| `nous_duck/protocol/` | ② duck-link：鴨子與 Nous 之間唯一的介面（版本化 JSON Schema） | JSON Schema |
| `nous_duck/robot/` | ③ 機上程式（Pi Zero 2 W）：連線、行為、安全 | Python |
| `nous_duck/nous_adapter/` | ④ 之後要搬回 AIOS 的 `app.duck.*` adapter 與終端 | TypeScript |
| `nous_duck/sim/` | ⑤ MuJoCo 模擬 | Python |
| `nous_duck/hardware/` | ⑥ 硬體改裝（MG995 頭部原型、表情模組、接線） | 文件、CAD、STL |
| `nous_duck/tools/` | 開發輔助腳本 | Python／shell |
| `nous_duck/docs/` | 交接、需求、架構、ADR、路線圖、進度、驗證紀錄 | Markdown |

系統分工（詳見 [ADR-0001](nous_duck/docs/adr/ADR-0001-duck-role-in-nous.md)）：

- **Nous（Mac mini）** 負責語音、視覺、記憶與決策。
- **鴨子（Pi Zero 2 W）** 負責步態、動作與安全。安全判斷（跌倒、過熱、低電壓、通訊中斷）一律在鴨子本機完成，不依賴 Nous 或網路。
- 兩邊**只**透過 `nous_duck/protocol/` 的版本化 JSON Schema 溝通。不共用程式碼、不直接呼叫對方內部函式。改協定先改 schema 並升版，再改兩端。

## 3. AIOS 整合規則

- `nous_duck/nous_adapter/` 的程式之後要搬回 AIOS，所以**沿用 AIOS 的慣例**：TypeScript、AIOS 的 `IntegrationAdapter` 契約（AIOS `prototype/ambient-shell/server/integrations/contracts.ts`）、工具 ID 格式 `app.<service>.<action>`（本專案 service 固定為 `duck`），每個工具標明 effect（`read`／`reversible_write`／`external_commit`）。
- 結果一律用 AIOS 的 `ToolResult` 狀態語意：只有 `confirmed`（有回讀確認）才算完成；送出但沒回讀是 `unconfirmed`；逾時或斷線是 `unknown`，不能推定沒有執行。
- AIOS repo 只能**唯讀**參考（`git clone` 到暫存目錄），不在這裡複製大段 AIOS 程式；需要的型別在 `nous_adapter/shared/` 以最小介面重新宣告並註明來源 commit。
- 不把 Nous 的能力說成鴨子的能力：鴨子沒有麥克風或鏡頭之前，不宣稱「鴨子聽得到／看得到」。

## 4. 語言規則

- 預設**繁體中文**：文件、README、ADR、commit 說明、PR 說明。
- 中英雙語：`nous_duck/nous_adapter/`、`nous_duck/protocol/` 的 README 與說明文件，以及 `nous_duck/README.md`。依 AIOS 的 [BILINGUAL.md](https://github.com/pcpcchen-coder/AIOS/blob/main/docs/BILINGUAL.md)：中文放 `name.md`，英文放 `name.en.md`，兩份頂端互相連結，內容完整對應（摘要不能取代翻譯），改一版就同步改另一版。
- 程式碼識別字、JSON Schema 欄位、工具 ID 用英文。上游的英文原檔保持英文。
- 不把「規劃中」「mock」「未校準」「待實機驗證」翻成或寫成「已完成」。

## 5. 誠實規則

- **mock、fixture、示意模型必須明確標示**（檔名、UI 標籤或 `mock: true`），不能拿來宣稱真實能力。例如組裝檢視器裡 CAD 沒有的零件（足底開關、喇叭、LED、5V 穩壓器、線材、螺絲）必須標成「示意」。
- **不宣稱未經實機驗證的能力**。只在雲端、模擬或單元測試通過的東西，要寫明驗證層級（單元測試／模擬／無頭瀏覽器／實機）。
- 尚未實作的模組在 README 標「規劃中」，**不寫假程式、不放空殼函式充數**。空資料夾用 `.gitkeep`。
- 工具失敗、逾時、缺資料，回報真實狀態，不顯示假成功。
- 數字先計算再陳述；計算方式寫進測試或 `nous_duck/docs/validation/`。

## 隱私（本 repo 是公開的）

- **不把家人的真實姓名、房間照片、平面圖、地圖資料、錄音或影像放進 repo**（包括 commit 訊息、PR 與 issue）。文件與程式只用 ID（例如 `brother`、`brother_room`），ID 與真實名稱的對照只存在 Nous 本機設定。
- 測試用的地圖、影像、音訊一律用合成或公開資料，並標示為 fixture。
- 鴨子的鏡頭與麥克風沿用 AIOS 紅線：原始影像與未喚醒音訊不寫檔、不進 trace、不外傳（見 `nous_duck/docs/adr/ADR-0003-mobile-terminal-wake-and-find.md` §6）。

## 6. Commit 與 PR

- [Conventional Commits](https://www.conventionalcommits.org/)：`feat:`、`fix:`、`docs:`、`test:`、`chore:`、`ci:`、`refactor:`；可加 scope，例如 `feat(viewer): ...`、`docs(adr): ...`。
- **一個 PR 對應一個批次**，不夾帶無關重構。
- PR 說明包含：變更檔案清單、如何執行、測試結果、畫面或量測證據、未完成項目、下一步。
- 新開發分支從 `v2` 開出。

## 7. 技術慣例

- Python：3.10 以上，pipeline 與機上程式各自宣告依賴並鎖版本。
- TypeScript：沿用 AIOS 的無框架 TypeScript 風格；前端用 three.js（鎖版本）。
- 組裝檢視器輸出是**單一 HTML、可離線開啟**，所有資源內嵌，不從網路載入。
- 建置輸出（`nous_duck/assembly_viewer/dist/`）不進版控。忽略規則寫在 `nous_duck/.gitignore`，不改上游的 `.gitignore`。
- 上游 `.gitignore` 忽略所有 `*.txt`；`nous_duck/.gitignore` 已用 `!*.txt` 重新納入，`requirements.txt` 等檔案才會進版控。
- 雲端環境注意：`codeload.github.com` 與 GitHub 附件圖片會回 403；`raw.githubusercontent.com`、`git clone`、jsDelivr 可用。Playwright Chromium 可跑 WebGL 2.0（SwiftShader）做截圖驗證。
