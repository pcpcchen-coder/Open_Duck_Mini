# 質量預算（mass_budget）

狀態：**全部是估計值**。到 2026-11-26 為止，沒有任何一件加裝件秤過，Pi 4 在機身裡的位置也還沒決定（[ADR-0008 §5.1](../../docs/adr/ADR-0008-single-board-pi4.md#5-待決)）。

這裡記錄「相對於上游 CAD 模型」要加上或拿掉哪些元件，給 [`walk_sim/mass.py`](../walk_sim/mass.py) 合進模型的慣量，用來在模擬裡檢查加裝後的步態（[ADR-0005 §2.4](../../docs/adr/ADR-0005-compute-and-sensor-upgrade.md#24-重量與步態策略)）。

| 檔案 | 內容 |
|---|---|
| [`p2_single_pi4.json`](p2_single_pi4.json) | 單板 Pi 4（ADR-0008）＋ADR-0005 的加裝件：拿掉頭裡的 Pi Zero 2 W；機身加 Pi 4、散熱片、UBEC、喇叭、背後觸點板、線材；頭上加 XVF3800 標準版（頭頂）、AR0144、紅外線補光燈、兩片 GC9A01、線材、新頭殼的重量差。第 2 版（2026-11-26）：麥克風依 2026-11-16 的決定改成標準版、裝在頭頂 |

## 欄位

| 欄位 | 意思 |
|---|---|
| `action` | `add`＝加上去；`remove`＝從上游模型拿掉（例如頭裡的 Pi Zero 2 W） |
| `body` | 元件固定在哪個 body 上，隨它一起動（`trunk_assembly`＝機身、`head_assembly`＝頭） |
| `mass_g` | `low`、`nominal`、`high` 三個值（g）。模擬分別跑「全取下限」「估計值」「全取上限」；拿掉的元件在「上限」情境取 `low`，讓上限情境一定最重 |
| `pos_base_m` | 元件質心在**起始姿勢時的 base 座標**（x 向前、y 向左、z 向上，m） |
| `size_base_m` | 元件外形的長方體邊長（base 座標的 x、y、z），只用來算元件自己的轉動慣量 |
| `source.kind` | `measured`（秤過）、`datasheet`（原廠規格）、`retailer`（零售標示）、`repo_estimate`（本 repo 的切片估算）、`guess`（粗估） |
| `placements` | 位置的替代方案，例如 Pi 4 放在機身前、中、後、下方 |

上游模型裡**已經有**的電子零件不用再加：機身的電池芯、BMS、BNO055、舵機驅動板、電源開關、USB-C 充電板，頭裡的 Pi Zero 2 W、天線舵機（SG90）。上游 CAD **沒有** 5 V 穩壓器、喇叭、足底開關、線材（[交接摘要 §5](../../docs/handoff/handoff_summary.md#5-cad-的缺口)），所以 UBEC 和喇叭算成加上去。

## 秤過之後怎麼更新

1. 把 `mass_g` 的三個值都改成秤到的數字（或留一點誤差），`source.kind` 改成 `measured`，`note` 寫秤法與日期。
2. 量出實際安裝位置，改 `pos_base_m`。
3. 改 `version`、`date`，重跑：

```bash
cd nous_duck/sim
.venv/bin/python -m walk_sim.mass_compare --out ../docs/validation/data/mass-model-<日期>.json
```

4. 在 `docs/validation/` 寫一份新的驗證紀錄。`tests/test_mass_model.py` 裡「沒有任何元件秤過」的檢查要一起改。
