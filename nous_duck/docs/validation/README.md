# 驗證紀錄

實機與測試紀錄。每一份紀錄寫清楚：

- 日期、分支與 commit
- **驗證層級**：單元測試／模擬（MuJoCo）／無頭瀏覽器（Playwright＋SwiftShader）／實機
- 執行的指令、環境（雲端容器、Mac mini、Pi Zero 2 W）
- 結果與原始數字（數字怎麼算出來的也要寫）
- 限制：哪些沒驗證、哪些是 mock 或示意

檔名格式：`<主題>-YYYY-MM-DD.md`，例如 `assembly-viewer-pipeline-2026-11-13.md`。

## 紀錄

| 日期 | 紀錄 | 層級 |
|---|---|---|
| 2026-11-13 | [組裝檢視器 pipeline](viewer-pipeline-2026-11-13.md) | 單元測試、MuJoCo 交叉驗證、無頭瀏覽器目視檢查 |
| 2026-11-13 | [組裝檢視器 BOM 與組裝步驟](viewer-bom-steps-2026-11-13.md) | 單元測試、無頭瀏覽器目視檢查 |
