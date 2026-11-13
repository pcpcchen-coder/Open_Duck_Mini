# assembly_viewer/data

狀態：**規劃中**。

## 預計內容

| 檔案 | 內容 |
|---|---|
| `bom.yaml` | BOM：每一項的 ID、中英名稱、數量、類別（列印件／舵機／電子／緊固件／線材）、來源（CAD 網格、列印 STL 或示意）、對應的上游 BOM 列 |
| `steps.yaml` | 組裝步驟：標題、說明、要用的零件、操作、驗收項目、上游參考圖與連結 |
| `part_names.yaml` | 零件的繁體中文與英文名稱（介面雙語用） |

## 資料來源

- 上游 BOM：[`../../docs/handoff/upstream_bom.csv`](../../docs/handoff/upstream_bom.csv)
- 列印清單：上游 `docs/print_guide.md`（36 種、51 件）
- 組裝順序：上游 `docs/assembly_guide.md`、ChatGPT 版的 14 步（見交接摘要）
- 舵機 ID：上游 `docs/configure_motors.md`

## 規則

- 每一項都要標明來源；CAD 沒有的零件標 `schematic: true`。
- 不憑空補規格（例如螺絲長度）；上游沒有寫的就標「未知」或「依實物」。
