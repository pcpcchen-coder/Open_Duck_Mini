# assembly_viewer/web

狀態：**規劃中**。

## 職責

TypeScript＋three.js 前端，打包成**單一 HTML**（所有 JS、網格、圖片內嵌），離線可用。

## 預計功能

- 三種檢視模式：組裝（原位）、爆炸（滑桿控制位移）、透視（外殼半透明）。
- 點 3D 零件或 BOM 項互相連動選取；單獨查看；BOM 搜尋（例如輸入 `ID 24` 找到左腳踝舵機）。
- 組裝步驟面板：上一步／下一步、該步零件高亮、完成狀態存在 localStorage（讀取失敗時仍可正常使用）。
- 示意零件有明顯標示。
- 介面預設繁體中文，可切換英文。

## 輸入輸出

- 輸入：pipeline 產生的 `scene.json` 與網格資料、`data/` 的 BOM 與步驟。
- 輸出：`../dist/duck_viewer.html`。

## 依賴（預計）

TypeScript、three.js（鎖版本）、能輸出單一 HTML 的打包工具（待選）。
