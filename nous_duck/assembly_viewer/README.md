# ① 3D 組裝檢視器（assembly_viewer）

狀態：**規劃中**（第一個交付；尚無程式）。

## 職責

產生一個**可離線開啟的單一 HTML**，讓使用者組裝鴨子時對照：

1. 整隻 Open Duck Mini v2 的 3D 模型（原版 100% 尺寸）。
2. **BOM 爆炸檢視**：每個元件都能單獨查看，包含列印件、14 顆 STS3215、天線舵機、所有電子元件（Pi Zero 2 W、驅動板、IMU、電池、BMS、充電板、開關、接頭）與線材。
3. **逐步組裝指引**：每一步的零件、操作、驗收項目，以及上游文件的參考圖。

## 架構

```text
上游（唯讀）                          pipeline/（Python）                web/（TypeScript + three.js）
mini_bdx/robots/open_duck_mini_v2/  ─►  解析運動樹、算世界座標、     ─►  載入場景 JSON 與網格
  robot.xml、*.stl                       對應舵機 ID、量化壓縮網格         組裝／爆炸／透視模式
print/*.stl（CAD 沒有的件）          ─►  scene.json + meshes.bin           BOM 清單、步驟面板
data/（bom.yaml、steps.yaml、名稱）  ─►  驗證 BOM 與步驟引用            ─►  dist/duck_viewer.html（單一檔）
```

| 子目錄 | 內容 | 狀態 |
|---|---|---|
| [`pipeline/`](pipeline/README.md) | Python：讀 `robot.xml` 與 STL，產生場景 JSON 與壓縮網格 | 規劃中 |
| [`data/`](data/README.md) | `bom.yaml`、`steps.yaml`、零件中英名稱 | 規劃中 |
| [`web/`](web/README.md) | TypeScript＋three.js 前端，打包成單一 HTML | 規劃中 |
| [`tests/`](tests/README.md) | pipeline 單元測試、Playwright 截圖驗證 | 規劃中 |
| `dist/` | 建置輸出（gitignore，不進版控） | — |

## 輸入

- 上游 `mini_bdx/robots/open_duck_mini_v2/robot.xml` 與同目錄 STL（唯讀）。
- 上游 `print/*.stl`：CAD 沒有擺放位置的 7 件（眼燈、喇叭相關）。
- 上游 `docs/` 的接線圖與組裝說明（`assembly_guide.md`、`open_duck_mini_v2_wiring_diagram.png`）。
- `data/` 的 BOM 與步驟定義。

## 輸出

- `dist/duck_viewer.html`：單一檔、所有資源（JS、網格、圖片）內嵌、不連網。

## 依賴（預計）

- Python 3.10+：numpy、scipy（匈牙利演算法 `linear_sum_assignment`）、PyYAML；版本會在 `pipeline/` 鎖定。
- Node.js：TypeScript、three.js（鎖版本）、打包工具（待選，需能輸出單一 HTML）。
- 測試：pytest、Playwright（雲端容器內建 Chromium，WebGL 2.0 經 SwiftShader）。

## 設計參考與誠實標示

- ChatGPT 做過一版（作法見 [`../docs/handoff/handoff_summary.md` §6](../docs/handoff/handoff_summary.md#6-第一個軟體交付離線-3d-組裝檢視器)，原始程式碼在對話紀錄裡），**只當參考**，本 repo 會重新實作並驗證。
- CAD 沒有的零件（足底開關、喇叭、LED、5V 穩壓器、線材、螺絲）與 CAD 沒有擺放位置的 7 件列印件，在畫面上必須標「示意」，並說明位置僅供參考。
- 舵機 ID 對應必須和上游 `docs/configure_motors.md` 一致（右腿 10–14、左腿 20–24、頸頭 30–33），並有測試鎖住。

## 建議的實作批次

1. **pipeline**：運動樹解析、世界座標、14 組舵機對應、網格量化；單元測試（舵機 ID 對應、網格數量、座標範圍）。
2. **data**：BOM 與 14 步組裝步驟（以上游 BOM 與組裝說明為準）。
3. **web**：three.js 三種模式、BOM 連動、步驟面板、單一 HTML 打包。
4. **tests**：Playwright 截圖驗證與檔案大小檢查。
