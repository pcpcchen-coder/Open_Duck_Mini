# assembly_viewer/tests

狀態：**規劃中**。

## 預計內容

| 類型 | 工具 | 驗證什麼 |
|---|---|---|
| pipeline 單元測試 | pytest | 運動樹世界座標、14 顆舵機 ID 對應與上游一致、網格數量、量化誤差上限、BOM／步驟引用完整 |
| 前端截圖驗證 | Playwright（Chromium＋SwiftShader WebGL 2.0） | 三種模式都有畫面、零件選取、步驟切換、離線開啟（無網路請求） |
| 輸出檢查 | pytest 或 node 腳本 | `dist/duck_viewer.html` 是單一檔、沒有外部資源、大小在上限內 |

截圖驗證只能證明「畫面畫得出來」，不能代表實機瀏覽器效能；結果寫進 [`../../docs/validation/`](../../docs/validation/README.md) 時要標明驗證層級。
