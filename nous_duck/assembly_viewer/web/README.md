# assembly_viewer/web

狀態：**第一版已實作**（2026-11-15）。驗證層級：無頭瀏覽器（斷網開啟），見[驗證紀錄](../../docs/validation/viewer-web-2026-11-15.md)。沒有實機驗證。

## 職責

TypeScript＋three.js 前端。把 pipeline 的輸出和前端程式打包成**單一 HTML**（程式、樣式、網格、資料全部內嵌），離線可開。

## 使用方式

```bash
# 1. 先產生 pipeline 輸出（scene.json、meshes.bin、steps.json）
cd nous_duck/assembly_viewer/pipeline
pip install -r requirements.txt
python -m viewer_pipeline

# 2. 打包
cd ../web
npm ci
npm run typecheck
npm run build      # → ../dist/duck_viewer.html（不進版控）
npm run check      # 檢查是單一檔、沒有外部資源、大小在 16 MB 內
```

打包好的 `duck_viewer.html` 直接用瀏覽器開（雙擊或拖進瀏覽器），不需要網路。

## 功能

| 功能 | 說明 |
|---|---|
| 依步驟 | 15 步組裝順序。已裝的零件正常顯示、這一步裝上的橘色、要注意的藍色、後面步驟的隱藏（可改成淡淡顯示）。鏡頭自動對準這一步的零件 |
| 整機 | 顯示全部零件 |
| 爆炸 | 滑桿 0～200%，沿 pipeline 算的爆炸向量移開 |
| 透視外殼 | 機身與頭殼、腿側蓋變半透明 |
| 舵機 ID 標籤 | 藍色是鴨子的左邊、紅色是右邊、黑色是中線；地面標示「鴨子的左邊／右邊」與「前」 |
| 視角 | 斜前、正面、左側、右側、背面、俯視；拖曳旋轉、滾輪縮放、右鍵平移 |
| 零件清單 | 依類別分組（舵機每顆一列、其他零件同網格合併）；搜尋 `ID 24`、`膝`、`foot_top` |
| 零件資訊 | 點模型或清單：名稱、類別、數量、列印檔、舵機 ID 與關節、裝在第幾步；推定或推得位置的零件會註明 |
| 單獨顯示 | 只顯示選取的零件 |
| 進度 | 每步可勾「完成」，存在這個瀏覽器的 localStorage；不能存時頁面會提示，其他功能照常 |
| 鍵盤 | ←／→ 切換步驟，Esc 取消選取 |
| 主題 | 跟隨系統的淺色／深色 |

## 檔案

| 檔案 | 內容 |
|---|---|
| `src/index.html` | 頁面骨架與內嵌位置的標記 |
| `src/style.css` | 樣式（淺色／深色 token、桌面三欄、手機分頁） |
| `src/types.ts` | `scene.json`、`steps.json` 的型別 |
| `src/data.ts` | 讀內嵌資料、解壓網格（`DecompressionStream`）、依量化格式還原頂點 |
| `src/viewer.ts` | three.js 場景：零件、步驟著色、爆炸、透視、點選、標籤、鏡頭 |
| `src/main.ts` | 介面：步驟面板、零件清單與搜尋、資訊卡、檢視控制 |
| `build.mjs` | esbuild 打包程式與樣式，把資料與 gzip＋base64 的網格填進範本 |
| `check_output.mjs` | 輸出檢查 |

依賴（鎖在 `package-lock.json`）：`three@0.186.1`；建置用 `esbuild@0.28.2`、`typescript@6.0.3`、`@types/three@0.186.0`。three.js 的授權聲明由 esbuild 保留在輸出檔尾端。

## 誠實標示

- 頁面上方固定提醒：只有上游 CAD 裡的零件，足底開關、喇叭、LED、線材、螺絲、熱熔螺母不在畫面中；組裝步驟未經實機驗證。
- CAD 沒有擺放位置的 7 件（表情套件）在清單標「推得位置」，資訊卡說明是借頭殼座標推得的。
- 依接線圖推定的兩片電路板標「推定」並顯示依據；天線註明上游沒有說明來源。

## 限制與下一步

- 還沒有 BOM（採購用的完整清單）與 CAD 以外零件的示意形狀；要等 `data/bom.yaml`。
- 沒有內嵌上游組裝照片（照片在 GitHub 附件，雲端環境拿不到），步驟只放上游文件連結。
- 只有零位姿態；沒有英文介面切換。
- 檔案約 4.3 MB，最大的是 STS3215 下殼網格；要再縮小可以考慮簡化舵機網格。
