# assembly_viewer/tests

狀態：**部分完成**。pipeline 單元測試已完成（`tests/pipeline/`，72 項，2026-11-13）；前端截圖驗證與輸出檢查規劃中。

## 預計內容

| 類型 | 工具 | 驗證什麼 |
|---|---|---|
| pipeline 單元測試（已完成） | pytest | 運動樹（含與 MuJoCo 逐一比對）、14 顆舵機 ID 對應與上游一致、左右位置、列印件數量對照上游清單、網格從 `meshes.bin` 解回的誤差、爆炸向量、建置可重現；BOM 逐列比對上游 CSV、每個 3D 零件剛好屬於一個 BOM 項目、剛好在一步裡裝上，以及資料寫錯時會被擋下 |
| 前端截圖驗證 | Playwright（Chromium＋SwiftShader WebGL 2.0） | 三種模式都有畫面、零件選取、步驟切換、離線開啟（無網路請求） |
| 輸出檢查 | pytest 或 node 腳本 | `dist/duck_viewer.html` 是單一檔、沒有外部資源、大小在上限內 |

截圖驗證只能證明「畫面畫得出來」，不能代表實機瀏覽器效能；結果寫進 [`../../docs/validation/`](../../docs/validation/README.md) 時要標明驗證層級。

## 執行

```bash
cd nous_duck/assembly_viewer/pipeline
pip install -r requirements-dev.txt
python -m pytest ../tests/pipeline -v
```

沒有安裝 MuJoCo 時，MuJoCo 交叉驗證那一項會跳過，其他照常執行。CI（`.github/workflows/nous-duck-ci.yml` 的 `viewer-pipeline`）會安裝 MuJoCo 並跑完整的 72 項。
