# assembly_viewer/tests

狀態：**已完成**（2026-11-15）。pipeline 與步驟資料單元測試 63 項（`tests/pipeline/`）、前端輸出檢查（`web/check_output.mjs`）、無頭瀏覽器檢查（`tests/web/check_viewer.cjs`）。

## 內容

| 類型 | 工具 | 驗證什麼 |
|---|---|---|
| pipeline 單元測試 | pytest | 運動樹（含與 MuJoCo 逐一比對）、14 顆舵機 ID 對應與上游一致、左右位置、列印件數量對照上游清單、網格從 `meshes.bin` 解回的誤差、爆炸向量、建置可重現 |
| 步驟資料（`test_steps.py`） | pytest | 每個零件剛好裝一次、各步裝的舵機、來源連結與錨點存在、8 種資料錯誤會讓建置失敗、步驟警語引用的幾何事實（膝踝舵機左外右內、右腿側板轉 180°、頸部舵盤偏 16.6 mm） |
| 無頭瀏覽器檢查（`web/check_viewer.cjs`） | Playwright（Chromium＋SwiftShader WebGL 2.0） | 斷網開啟、沒有錯誤、15 步都有畫面、整機＋爆炸＋透視、搜尋 `ID 24` 與資訊卡、點模型選取、進度重新整理後仍在、手機寬度沒有水平捲動；截圖存到 `dist/screens/` |
| 輸出檢查（`../web/check_output.mjs`） | Node.js | `dist/duck_viewer.html` 是單一檔、沒有外部資源、大小在 16 MB 內 |
| release 一致性（`../web/check_release.mjs`） | Node.js | 進版控的 `release/duck_viewer.html` 和目前原始碼建置的結果相同（忽略建置日期與 commit） |

截圖驗證只能證明「畫面畫得出來」，不能代表實機瀏覽器效能；結果寫進 [`../../docs/validation/`](../../docs/validation/README.md) 時要標明驗證層級。

## 執行

```bash
cd nous_duck/assembly_viewer/pipeline
pip install -r requirements-dev.txt
python -m viewer_pipeline
python -m pytest ../tests/pipeline -v

# 前端（需要先跑上面的 pipeline）
cd ../web && npm ci && npm run build && npm run check
cd ../../..
node nous_duck/assembly_viewer/tests/web/check_viewer.cjs   # 需要 Playwright＋Chromium
```

沒有安裝 MuJoCo 時，MuJoCo 交叉驗證那一項會跳過，其他照常執行。CI（`.github/workflows/nous-duck-ci.yml`）的 `viewer-pipeline` 會安裝 MuJoCo 跑完整的 63 項；`viewer-web` 會建置前端、做輸出檢查，並安裝 Playwright 跑無頭瀏覽器檢查。

`check_viewer.cjs` 只能證明「斷網打得開、畫得出來、互動有反應」，不代表實機瀏覽器效能，也不代表組裝步驟正確。
