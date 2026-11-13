# assembly_viewer/data

狀態：**已完成**（2026-11-13）。三個檔案都由 pipeline 讀取並檢查；資料有錯時建置會直接失敗。

## 內容

| 檔案 | 內容 |
|---|---|
| [`cad_parts.yaml`](cad_parts.yaml) | 上游 robot.xml 每個網格的類別、對應列印檔、中英文名稱，以及 CAD 沒有擺放位置的 7 件列印件要借用哪個零件的座標 |
| [`bom.yaml`](bom.yaml) | 採購件、耗材與工具，共 35 項。每項標明對應上游 BOM 的哪一列、在 3D 模型中是哪些零件；3D 中沒有的零件要寫原因 |
| [`steps.yaml`](steps.yaml) | 17 個組裝步驟：每一步裝上哪些零件、要看哪些零件、用到哪些 BOM 項目、中英文操作說明、完成檢查、上游參考圖 |

**列印件不寫在 `bom.yaml`**。36 種列印件的 BOM 列由 pipeline 依 `cad_parts.yaml` 和上游 `docs/print_guide.md` 自動產生，避免兩份清單不同步。完整 BOM 有 71 項：列印件 36 種，加上 `bom.yaml` 的 35 項。

## pipeline 會檢查什麼

- **cad_parts.yaml**
  - 涵蓋 robot.xml 的每個網格。
  - 列印件指向的列印檔確實存在。
- **bom.yaml**
  - 有 3D 模型的項目，數量要等於模型裡選到的數量（例如 18650 電池 2 顆就要選到 2 個網格）。
  - 每個 3D 零件剛好屬於一個 BOM 項目。CAD 有、但上游 BOM 和列印清單都沒有的零件（目前只有天線），要列在 `cad_without_bom` 並說明原因。
  - 3D 中沒有的零件要寫 `scene_note_zh` 說明原因。材料與工具不是組裝零件，免寫。
  - 數量寫 `null` 時必須用 `qty_note_zh` 說明原因。
  - 每個 `*_zh` 欄位都要有對應的 `*_en`，清單的項目數要相同。
- **steps.yaml**
  - 每個 3D 零件剛好在一步裡裝上。
  - 選擇器打錯名稱會報錯。
  - 引用的 BOM 項目要存在。
  - 參考圖要是 GitHub 附件 ID，或 repo 內存在的檔案。

測試（`../tests/pipeline/test_bom.py`）還會逐列比對 `bom.yaml` 和上游 BOM 的 CSV：名稱、數量、單價都要相同，而且上游的 29 列零件都要剛好被引用一次。

## 選擇器

`bom.yaml` 的 `scene`，以及 `steps.yaml` 的 `adds`、`focus`，用同一種寫法選零件：

| 寫法 | 選到什麼 |
|---|---|
| `{servos: all}`、`{servos: [24, 14]}` | 舵機，每顆包含 5 個網格 |
| `{mesh: foot_top}` | 這種 CAD 網格的所有實例 |
| `{mesh: board, body: trunk_assembly}` | 只取指定 body 裡的實例（body 可以是清單） |
| `{print_only: all}`、`{print_only: [left_eye]}` | CAD 沒有擺放位置的列印件 |

## 資料來源

- 上游 BOM：[`../../docs/handoff/upstream_bom.csv`](../../docs/handoff/upstream_bom.csv)，2026-11-12 從原作者的 Google 試算表匯出。
- 列印清單：上游 `docs/print_guide.md`（36 種、51 件）。
- 組裝順序與內容：上游 `docs/assembly_guide.md`、`docs/configure_motors.md`。
- 接線與腳位：上游 `docs/open_duck_mini_v2_wiring_diagram.png`、`docs/assembly_guide.md` 的腳位表。

## 規則

- 不憑空補規格。上游沒寫的型號、螺絲長度、數量、扭力一律不填，寫在 `note` 或 `qty_note` 裡。
- 推定的內容要標明依據。例如兩片電路板是依接線圖推定的，寫在 `identification` 或 `note`。
- 和上游順序或內容不同的地方，寫在步驟的 `deviation`。目前有兩處：
  - **配線**移到頭頸接合之後，因為接線需要 Pi Zero 已經裝上。
  - **腿部側蓋**放在最後裝外殼時，因為上游沒有寫何時裝。
- 價格照抄上游原作者的歐元估價，不代表台灣價格。
