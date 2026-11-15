# ChatGPT 版 3D 組裝檢視器成品（備用）

這是 ChatGPT 在 2026-11-12 做出的 `Open_Duck_Mini_v2_Assembly_Viewer.html` 成品。當初以為只存在 ChatGPT 的沙箱、拿不到；使用者在 2026-11-14 上傳了這個檔案，**原封不動**存放在這裡，當作備用。

> ⚠️ **這是 ChatGPT 的產出，不是本 repo 的實作，內容沒有經過本 repo 驗證。** 它的產生程式見 [`../chatgpt_viewer_src/`](../chatgpt_viewer_src/README.md)。本 repo 自己的檢視器在 [`../../../assembly_viewer/`](../../../assembly_viewer/README.md)。

| 項目 | 內容 |
|---|---|
| 檔案 | [`Open_Duck_Mini_v2_Assembly_Viewer.html`](Open_Duck_Mini_v2_Assembly_Viewer.html)，16,674,219 bytes |
| sha256 | `cfa49ca183e375d743956195abc3a984cd7ce8de54b4fa40a453aea1ec43464e` |
| 對應上游 | `apirrone/Open_Duck_Mini` commit `b23317a`（檔案內的 `DATA.commit`） |
| 內嵌內容 | three.js r160（MIT）、52 個網格（int16 量化＋gzip）、零件與 14 個組裝步驟、BOM 75 類、22 張照片與接線圖 |
| 照片來源 | 看起來是上游組裝指南的照片、CAD 圖與接線圖（機構與電路，沒有人或住家）；由 ChatGPT 的 `photos.py` 下載縮圖 |
| 修改 | 無（與上傳檔案位元組相同） |

## 本 repo 對它做過的檢查（2026-11-14）

**只確認「打得開」，沒有檢查內容是否正確。**

- 用 Playwright Chromium（SwiftShader WebGL）以 `file://` 開啟，**擋掉所有網路請求**：沒有任何對外請求、沒有 JavaScript 錯誤，WebGL 畫布正常建立，3D 模型、14 個步驟與 BOM 都有顯示。截圖：[`headless-offline-2026-11-14.png`](headless-offline-2026-11-14.png)。
- 掃過內嵌資料：沒有個人資料或電子郵件；外部連結只有上游 GitHub 與 three.js 文件。
- 頁面會用瀏覽器的 `localStorage` 記住組裝步驟的完成狀態（只存在自己的瀏覽器）。

## 零件擺放核對（2026-11-15）

用 [`../../../tools/compare_chatgpt_viewer.py`](../../../tools/compare_chatgpt_viewer.py) 逐件和本 repo pipeline 比對（[驗證紀錄](../../validation/viewer-web-2026-11-15.md#1-chatgpt-版的零件擺放核對)）：

- 138 個 CAD 零件實例一對一全部對上，最大頂點誤差 0.0005 mm；兩邊座標只差平移 (0.025, 0, −22.3) mm。
- 14 顆舵機 ID 全部相同。
- **右腿的 180° 有畫對**：膝、踝舵機（13、14）在右腿內側，（23、24）在左腿外側。
- 但它的步驟文字**沒有提醒**右腿要轉 180°、膝踝舵機左外右內；照文字組容易裝成鏡像。

「一致」是指和上游 CAD 一致（兩邊都從上游 `robot.xml` 算），不代表實機確認過。

## 沒有驗證的事

- 組裝步驟內容是否正確。
- ChatGPT 自己說明部分電子板、線束、緊固件是示意。
- 不含 Nous Duck 的改裝（感知板、鏡頭、麥克風、充電座觸點板等）。

![無頭瀏覽器離線開啟](headless-offline-2026-11-14.png)
