# 雲端開發環境調查（Claude Code 雲端容器）

調查期間：2026-11-11～2026-11-12（前一個雲端對話完成主要調查；本次建立架構時重新確認標 ✅ 的項目）。

這些結論只描述 Claude Code 雲端容器的網路與工具，不代表使用者本機或 Pi Zero 2 W 的環境。環境的網路政策可能變動，失敗時先重新確認。

## 網路

| 目標 | 結果 | 用途與備註 |
|---|---|---|
| `git clone` / `git fetch` GitHub | 可用 ✅ | 本次 `git fetch upstream v2`、`git clone` AIOS 皆成功 |
| `raw.githubusercontent.com` | 可用 | 讀單一檔案 |
| `codeload.github.com` | **403** | GitHub「Download ZIP」與 tarball 走這裡，改用 `git clone` |
| GitHub 附件圖片（`github.com/user-attachments/...`） | **403** | README 裡貼的圖片拿不到；改用 repo 內檔案 |
| jsDelivr（`cdn.jsdelivr.net`） | 可用 | 可取得 npm 套件（例如 three.js）或 GitHub 檔案 |
| Google Sheets CSV 匯出 | 可用 ✅ | 上游 BOM 已存成 [`upstream_bom.csv`](upstream_bom.csv) |
| ChatGPT 分享頁 | 可用 ✅ | 需加瀏覽器 User-Agent；資料在 `streamController.enqueue(...)` 裡 |

## 瀏覽器與 3D

- 容器內建 Chromium 與對應的 Playwright（`require('playwright')` 可直接用，不要再 `playwright install`）。
- WebGL 2.0 可用，由 SwiftShader 軟體算圖：能截圖驗證 three.js 畫面，但效能遠低於實體 GPU，**不能拿來量測實機 FPS**。
- 檢視器是單一 HTML、所有資源內嵌，所以測試時可以用 `file://` 或本機靜態伺服器開啟。

## CAD 與資料

- 上游 MuJoCo 模型：`mini_bdx/robots/open_duck_mini_v2/robot.xml`，網格是同目錄的 STL；共 16 個關節（14 個主舵機關節加 2 個天線）。
- 列印檔：`print/` 底下 36 種 STL（另有 `print/mods/`）。
- CAD 沒有：足底開關、喇叭、LED、5V 穩壓器、線材、螺絲；眼燈與喇叭相關 7 件只有列印檔、沒有擺放位置。

## 對開發的影響

1. 依賴一律用 `git clone` 或套件管理器（pip、npm）取得，不用 GitHub ZIP。
2. 組裝圖片只能用 repo 內的檔案（例如上游 `docs/` 的接線圖），不能引用 user-attachments 圖片。
3. 3D 畫面的自動驗證用 Playwright 截圖；效能數字只能在實機量。
