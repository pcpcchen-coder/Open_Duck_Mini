# C 線進度：模擬與導航

分支：`claude/duck-c-sim-nav-2e1cfa`。目錄：`nous_duck/sim/`、`nous_duck/robot/navigation/`。
這條線**完全在 Mac 上以模擬完成**，沒有碰 Pi 與實體鴨子。下面所有數字都是**模擬值**。

| Step | 內容 | 狀態 | 驗證層級 |
|---|---|---|---|
| C1 | MuJoCo 全身走路模擬 | 完成 | 模擬（＋單元測試） |
| C2 | 走、停、轉的量測 | 完成 | 模擬 |
| C3 | 地圖格式與合成的家 | 未開始 | |
| C4 | 定位：AprilTag＋里程融合 | 未開始 | |
| C5 | 路徑規劃與 `go_to` 任務 | 未開始 | |
| C6 | 回充 `return_home` | 未開始 | |
| C7 | 禁區、門、迷路的保護 | 未開始 | |

## 怎麼執行

```bash
cd nous_duck/sim
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m pytest tests -q              # 預設測試組
.venv/bin/python -m pytest tests -q --runslow    # 連長時間的模擬測試一起跑
.venv/bin/python -m walk_sim --vx 0.15 --duration 10 --png --out walk_sim_out
.venv/bin/python -m walk_sim.measure --out ../docs/validation/data/walk-measure-2026-11-25.json
```

## C1 全身走路模擬（完成，模擬）

- `sim/walk_sim/model.py`：用 `mujoco.MjSpec` 讀上游 `robot.xml`（不改原檔），在記憶體裡補上浮動機身、IMU、
  舵機參數、鞋底碰撞、地板。參數來源寫在檔頭（Open_Duck_Playground `b9be205`，只取數值）。
- `sim/walk_sim/sim.py`：`WalkSim`，50 Hz，跑上游 `BEST_WALK_ONNX_2.onnx`。101 維觀測的組法對照
  runtime `376de65` 的 `v2_rl_walk_mujoco.py` 與 Playground 的 `mujoco_infer.py`，表格在檔頭。
- `python -m walk_sim`：無頭執行，輸出軌跡 CSV、截圖或短 GIF。
- 對照檢查：同一個控制迴圈換成 Playground 自己的場景 XML（唯讀、不進 repo），行為一致
  （站立、前進速度、起步門檻都相同量級），所以下面的現象來自策略本身，不是模型組錯。

結果：站得住（5 秒位移 < 3 cm）、指令 0.15 m/s 走直線實際約 0.115 m/s、8 秒不跌倒。

## C2 量測（完成，模擬）

完整數字在 `docs/validation/data/walk-measure-2026-11-25.json`，整理在驗證紀錄。重點：

1. **策略有起步門檻**：從站立開始，前進要指令 ≥ 0.10 m/s、後退要 ≤ −0.12 m/s、原地轉要 |yaw| ≥ 0.6 rad/s
   （+0.3 會起步、−0.3 不會），純側移只有 +0.2 m/s 會起步。低於門檻時鴨子留在原地、兩腳著地。
   前後速度達門檻時，同時加任何轉向都會起步（36 種組合 × 9 個相位全部起步）。
2. **實際速度比指令慢**：前進約 0.72～0.79 倍、後退約 0.35 倍、轉向約 0.6～0.9 倍。
3. **速度指令為 0 時不踏步**（模擬）：兩腳一直著地。ADR-0009 §2.5 假設的「原地踏步」在模擬裡沒有出現。
4. 起步到 90% 速度約 1.5 s／0.18 m；指令歸零後 0.5～0.7 s 內兩腳著地，滑行 2～4 cm。
5. 原地轉 90°：yaw 1.0 約 2.1 s、位移 5～10 cm；180° 約 4 s。
6. **頭部指令會影響步態**（runtime 的接法）：走路時 head_yaw ≥ 0.8 rad 或 head_pitch 大角度會讓步態停下來；
   neck_pitch ≥ 0.9 rad、head_yaw ≤ −1.0 rad 在模擬裡會跌倒。導航因此規定「走路時頭回正，停下才轉頭」。
7. ADR-0009 的加速度限制下穩定；40 個種子 × 60 秒隨機指令 × 6 種條件（含機身加 0.2／0.4 kg、摩擦 0.3），跌倒 0 次。
8. 里程：指令積分走約 4 m 後終點誤差 0.19～0.53 m、航向差 5～16°；步數估計在摩擦或舵機增益改變時誤差 0.6～0.9 m。

## 沒做的

- 沒有背隙關節的模型（Playground 訓練時可選）；用 Playground 的背隙場景對照過，起步門檻現象相同。
- 沒有對照實機（實機還不能走）。

## 需要你處理

- 實機能走之後，要重量一次 C2 的表（特別是起步門檻、速度比例、速度為 0 時是否踏步、頭部角度的安全範圍）。
  模擬裡頭部大角度會跌倒這件事，**在實機驗證前不要讓頭部在走路時轉到大角度**。
