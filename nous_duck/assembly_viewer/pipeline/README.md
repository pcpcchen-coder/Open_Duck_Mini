# assembly_viewer/pipeline

狀態：**規劃中**。

## 職責

把上游 CAD 轉成前端可直接使用的場景資料。

1. 解析 `mini_bdx/robots/open_duck_mini_v2/robot.xml` 的 body 樹，累積每個 body 的 `pos`／`quat`，算出每個 geom（STL）的世界座標與旋轉；轉成 three.js 的 Y-up 座標系。
2. 讀 STL（binary），量化頂點（預計 int16＋每個網格的縮放與位移），相同網格只存一份、以實例引用。
3. 舵機對應：把 `wj-*`／`*palonier` 網格依位置分成 14 組，以舵盤中心到關節位置的距離做匈牙利演算法配對，對到 14 個關節與 ID；結果必須與上游 `docs/configure_motors.md` 的 ID 表一致，不一致就失敗。
4. 加入 CAD 沒有的零件（示意），標記 `schematic: true`。
5. 計算爆炸向量（每個零件相對組裝中心或所屬子組件的位移方向）。
6. 驗證 `data/bom.yaml`、`data/steps.yaml` 引用的零件都存在。

## 輸入

- 上游 `robot.xml`、STL（唯讀）；上游 `print/*.stl`。
- `../data/*.yaml`。

## 輸出（寫到 `../dist/` 或建置暫存目錄，不進版控）

- `scene.json`：零件清單（ID、名稱、網格引用、世界變換、所屬步驟、BOM 項、是否示意、爆炸向量）。
- `meshes.bin`（或內嵌用的壓縮資料）：量化後的網格。

## 依賴（預計）

Python 3.10+、numpy、scipy、PyYAML（版本鎖定於之後新增的 requirements 檔）。

## 參考

ChatGPT 版的 `model.py` 片段保留在 [`../../docs/handoff/chatgpt_conversation_2026-11.md`](../../docs/handoff/chatgpt_conversation_2026-11.md)（搜尋 `linear_sum_assignment`）；只當參考，需重新核對。
