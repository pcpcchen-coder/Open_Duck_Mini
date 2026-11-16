# assembly_viewer/release

這裡放**建置好的組裝檢視器**，給人直接下載使用，不用自己建置。

| 檔案 | 內容 |
|---|---|
| [`duck_viewer.html`](duck_viewer.html) | Open Duck Mini v2 離線 3D 組裝檢視器，單一 HTML、約 4.3 MB。下載後用瀏覽器直接開，不需要網路 |

## 怎麼開

GitHub 不會在網頁上直接顯示 HTML。到 [`duck_viewer.html`](duck_viewer.html) 頁面按「Download raw file」（下載圖示），存到電腦或 iPad 後用瀏覽器開啟。需要支援 `DecompressionStream` 的瀏覽器（Chrome 80、Firefox 113、Safari 16.4 以後）。

頁面左下角記錄它建置自哪個 commit、哪一天。

## 驗證層級

單元測試與無頭瀏覽器（斷網開啟）；**沒有實機驗證**，組裝步驟也還沒有人照著實際組過。見 [驗證紀錄](../../docs/validation/viewer-web-2026-11-15.md)。畫面只有上游 CAD 裡的零件，足底開關、喇叭、LED、線材、螺絲、熱熔螺母不在畫面中。

## 怎麼更新

這份檔案由 `web/` 建置產生，**不要手改**。改了 pipeline、`data/` 或 `web/src` 之後：

```bash
# 1. 先 commit 原始碼的改動
# 2. 重新產生 pipeline 輸出與 release
cd nous_duck/assembly_viewer/pipeline && python -m viewer_pipeline
cd ../web && npm ci && npm run release
# 3. commit release/duck_viewer.html
```

CI（`viewer-web` job）會用目前的原始碼重新建置，和這份檔案比對（忽略建置日期與 commit；網格比對解壓後的位元組）。內容不一致代表這份過期，CI 會失敗並提示上面的步驟。
