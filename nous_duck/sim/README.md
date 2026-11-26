# ⑤ MuJoCo 模擬（sim）

狀態：**三個模擬可用**（都只在開發機上跑，結果是模擬值，不是實機）：[`look_at_sim/`](look_at_sim/)（2026-11-16，[驗證紀錄](../docs/validation/look-at-sim-2026-11-16.md)）、[`walk_sim/`](walk_sim/) 全身走路與 [`nav_sim/`](nav_sim/) 家中導航（2026-11-25，[驗證紀錄](../docs/validation/sim-nav-2026-11-25.md)）。加裝後的質量模型（2026-11-26，[驗證紀錄](../docs/validation/mass-model-2026-11-26.md)）可用，但重量是估計值；duck-link 端到端模擬仍是規劃中。

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

## 已有的模擬

| 路徑 | 內容 | 狀態 |
|---|---|---|
| [`look_at_sim/`](look_at_sim/) | `robot/behaviors/look_at.py` 的模擬：上游 `robot.xml` **固定機身**（只動頭頸）、依幾何投影產生的**合成人臉偵測**（fixture）、轉身用運動學近似；7 個情境 | 可用；**不驗證平衡**（沒跑步態策略） |
| [`walk_sim/`](walk_sim/) | **全身走路**：用 `MjSpec` 由上游 `robot.xml` 組出浮動機身模型（不改原檔），跑上游步態策略 `BEST_WALK_ONNX_2.onnx`，50 Hz、7 維指令。觀測向量與動作的組法、參數來源寫在 `model.py` 與 `sim.py` 檔頭 | 可用；跟 Playground 自己的場景交叉檢查過；**沒有對照實機** |
| [`walk_sim/measure.py`](walk_sim/measure.py) | 走、停、轉的量測：指令 vs 實際速度、起步門檻、起步與停下、轉身、頭部指令的影響、加速度限制、多種子跌倒率、里程誤差；另外產生導航用的步態反應表 | 可用（模擬值） |
| [`walk_sim/mass.py`](walk_sim/mass.py)、[`walk_sim/mass_compare.py`](walk_sim/mass_compare.py) | **加裝後的質量模型**：依 [`mass_budget/`](mass_budget/README.md) 的質量預算，把元件合進上游模型的 body 慣量（可加可減：拿掉頭裡的 Pi Zero 2 W、機身加 Pi 4 等），再比較上游模型與加裝後的站立、走路、起步門檻、頭部大角度、跌倒率與加重餘裕 | 可用（模擬值）；**重量與位置都是估計，沒有秤過**（2026-11-26，[驗證紀錄](../docs/validation/mass-model-2026-11-26.md)） |
| [`nav_sim/`](nav_sim/) | 把導航核心 [`robot/navigation/duck_nav`](../robot/navigation/README.md) 接上全身走路模擬：依地圖蓋牆、家具、充電座與貼了 tag36h11 貼圖的標籤；標籤觀測、障礙點、充電訊號是 **mock** | 可用；充電座的 V 形導引與電氣行為**沒有模擬** |
| [`nav_sim/tagcheck.py`](nav_sim/tagcheck.py) | 頭上相機算圖＋OpenCV 的 tag36h11 偵測器，對照 mock 的標籤觀測 | 可用；算圖沒有畸變、模糊、雜訊 |

```bash
cd nous_duck/sim
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m pytest tests -q              # 29 通過、2 跳過，約 8 秒
.venv/bin/python -m pytest tests -q --runslow    # 31 通過，約 1 分鐘
.venv/bin/python -m look_at_sim                  # look_at 的結果表

# 全身走路：軌跡 CSV、截圖、短 GIF
.venv/bin/python -m walk_sim --vx 0.15 --duration 10 --png --out walk_sim_out
.venv/bin/python -m walk_sim --script "2:0,0,0;8:0.15,0,0;4:0,0,1.0;3:0,0,0" --gif --out walk_sim_out
.venv/bin/python -m walk_sim.measure --out ../docs/validation/data/walk-measure-2026-11-25.json   # 約 3 分鐘

# 加裝後的質量模型（質量預算在 mass_budget/）
.venv/bin/python -m walk_sim.mass_compare --out ../docs/validation/data/mass-model-2026-11-26.json  # 4 核約 18 分鐘

# 端到端：充電座 → 房間 → return_home，輸出軌跡圖 trips.png 與 summary.json
.venv/bin/python -m nav_sim.demo --trips 10 --seed 100 --out nav_demo_out --topview
.venv/bin/python -m nav_sim.tagcheck
```

無頭執行；截圖、GIF 與 `tagcheck` 需要離螢幕 OpenGL（macOS 直接可用，Linux 設 `MUJOCO_GL=egl`）。

### 模擬裡的發現（細節在驗證紀錄）

- 上游策略有**起步門檻**：從站立開始，前進指令要 ≥ 0.10 m/s、後退要 ≤ −0.12 m/s，否則鴨子留在原地；實際速度約是指令的 0.75 倍（後退 0.35 倍）。
- 速度指令為 0 時**不踏步**，兩腳一直著地。
- 走路時大角度的頭部指令會讓步態停下來，部分角度會跌倒。
- 端到端 60 趟（合成的家）全部成功、沒有跌倒；回充第一次就對準的有 50 趟。

## 依賴

`requirements.txt` 鎖定 mujoco 4.0.1、numpy 2.5.4（與 `hardware/dock/cad` 相同；numpy 2.5.4 需要 **Python 3.12**）、onnxruntime 1.32.0、pillow、matplotlib、opencv-contrib-python-headless。`sim/` 只在開發機上跑，不上鴨子。

## 限制

模擬結果不等於實機：舵機背隙、摩擦、電壓變化、足底材質都會不同；Pi 4 等加裝件已用**估計重量**放進模型（[`mass_budget/`](mass_budget/README.md)），還沒秤過實物。差距的清單見[驗證紀錄 §9](../docs/validation/sim-nav-2026-11-25.md#9-模擬與實機的差距)。
