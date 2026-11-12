# ⑤ MuJoCo 模擬（sim）

狀態：**規劃中**（尚無程式）。

## 職責

在沒有實機或實機有風險時，用 MuJoCo 驗證：

- `robot/behaviors` 的意圖轉換與 `robot/safety` 的上限、TTL、斷線處理。
- duck-link 端到端：mock Nous → `robot/nous_link` → 模擬中的鴨子 → state／event 回報。
- 決定 safety 門檻（跌倒判定、TTL、心跳）的初始值；最終值仍要實機確認。

R-001（2026-11-12）後新增：

- **加裝後的質量模型**：在本目錄複製上游 MJCF，加入感知板、鏡頭、麥克風、喇叭、充電觸點的質量與位置，測試原步態策略是否仍穩定；不穩定就用上游訓練流程重新訓練（[ADR-0005 §2.4](../docs/adr/ADR-0005-compute-and-sensor-upgrade.md#24-重量與步態策略)）。
- **導航場景**：牆、門、家具、AprilTag 貼圖、模擬雙目鏡頭，用來測試定位與導航（[ADR-0002](../docs/adr/ADR-0002-indoor-localization-and-navigation.md)）與回充對位（[ADR-0004](../docs/adr/ADR-0004-docking-and-charging.md)）。

## 輸入

- 上游模型 `mini_bdx/robots/open_duck_mini_v2/`（`robot.xml`、`scene.xml` 等，唯讀）。
- 上游步態策略（例如根目錄的 `BEST_WALK_ONNX*.onnx`，或 runtime 使用的策略；以實際採用的為準）。

## 輸出

- 模擬腳本與場景設定（放本目錄，不改上游模型檔；需要修改時複製到本目錄並註明來源 commit）。
- 量測結果寫進 `../docs/validation/`，標明「模擬」層級。

## 依賴（預計）

MuJoCo（Python 綁定）、onnxruntime；版本待鎖定。上游 `v2_rl_walk_mujoco.py` 可作為參考。

## 限制

模擬結果不等於實機：舵機背隙、摩擦、電壓變化、足底材質都會不同。
