# duckd 的原地蹲低／起立（`--legs`）（2026-11-28）

- 分支：`claude/duck-posture-duckd`（疊在 `claude/duck-sit-stand`／PR #66 上）
- **驗證層級：單元測試（mock 身體、舵機控制台的模擬匯流排）＋MuJoCo 模擬＋開發機上的 mock 端到端**。**沒有實機**：腿沒有出力過，也沒有部署到 Pi。
- 設計：[ADR-0020 草案](../adr/ADR-0020-crouch-and-stand.md)；姿勢怎麼選：[模擬紀錄](posture-crouch-sim-2026-11-28.md)

```bash
cd nous_duck/robot/duckd && .venv/bin/python -m pytest tests -q          # 190 通過、3 跳過，約 75 秒（含 test_posture.py 18 項）
cd nous_duck/sim && .venv/bin/python -m pytest tests -q                   # 55 通過、3 跳過，約 10 秒（含 duckd 引擎進 MuJoCo 的 2 項）
```

## 1. 做了什麼

| 項目 | 內容 |
|---|---|
| `duckd/posture.py` | 站姿 ↔ 蹲姿一條路徑；smoothstep；時間軸每拍最多前進 0.03 秒；收手停在原地；跟隨誤差 > 20° 持續 0.5 秒自動停住；腿不在路徑上（> 6°）拒絕 |
| `duckd/postures/postures.json` | 由 `python -m posture_sim.poses` 產生（只有腿；頭不補償） |
| `head_real.py` | `legs=True` 時白名單加腿部 10 顆；`engage_legs()` 先寫目前位置再開扭力；`release()` 不關腿的扭力 |
| `body.py` | `MockBody(legs=True)`；`BodyReading` 加 `legs_engaged`、`legs`、`legs_torque` |
| `core.py` | `engage_legs`、`posture_command`、`posture_stop`、每拍的 `_posture_step`；緊急停止、釋放、block、腿沒出力時停住 |
| `localctl.py`、`ctl.py` | `engage-legs`、`posture crouch|stand [--duration]`、`posture-stop`；`status` 多了 `posture` |
| `__main__.py` | `--legs`（預設關；部署的 systemd 服務沒加） |

duck-link 沒有改：`state` 沒有新欄位（測試 `test_engage_legs_required_and_not_on_duck_link` 檢查）。

## 2. 單元測試（`tests/test_posture.py`，18 項）

- 姿勢檔只有腿、都在 robot.xml 內縮 2° 內、左右對稱、膝蓋 < 88°。
- 引擎：每拍目標都在路徑上而且單調；任何關節的速度 < 30°/s（Controller 的限速）；卡 1 秒那一拍只前進 0.03 秒；`duration_s` 0.5 夾到 3 秒；不在路徑上拒絕、回傳 None 不送腿部目標；收手後停在原地、只接受 `stand`、回站姿用 6 秒全程的速度；腿完全不動時 0.5 秒後自動停住（`tracking_error`）。
- 核心（MockBody）：沒 `engage-legs` 前拒絕；蹲下、站起完整走完，事件依序 `legs_engaged → start → done → start → done`；緊急停止時停住、之後拒絕；過熱 block 時停住，之後不能蹲、可以慢慢回站姿（途中不再因 block 停），站好後 block 還在就不接受新的蹲低；釋放時停住並放開腿；沒 `--legs` 時全部拒絕。
- 本機指令：`engage-legs`、`posture`（`duration_s` 不是數字時拒絕）、`posture-stop`、`status.posture`。
- 實機後端（模擬匯流排）：`engage` 之後、`engage_legs` 之前，就算上層送了腿部目標，也**沒有任何一次寫入碰到腿部 ID**；`engage_legs` 後 10 顆出力、角度＝站姿；`release` 後腿的扭力還在；沒 `--legs` 時 `engage_legs` 丟例外、腿部 ID 一次都沒寫；`--legs` 時緊急停止讓 14 顆都放鬆。

## 3. 把 duckd 的引擎接進 MuJoCo（`sim/tests/test_posture_sim.py`）

`posture_sim.sim.run_controller` 每 20 ms 呼叫一次 duckd 的 `PostureMotion.step()`，把它的腿部目標送進模擬（頭維持站姿），實際角度回傳給引擎做跟隨誤差判斷：

| 情境 | 結果 |
|---|---|
| 0.5 秒開始蹲、5 秒開始站，跑 9 秒 | 站回來；機身下降 3～4 cm；重心餘裕 > 2.5 cm；腳滑 < 1 cm；力矩 < 1 N·m；沒有觸發跟隨誤差 |
| 蹲到 1.2 秒時控制器晚 1 秒、2 秒收手、4 秒慢慢站 | 站回來；力矩 < 1 N·m；重心餘裕 > 2.5 cm |

另外檢查 `postures.json` 和 `posture_sim/poses.py` 一致。

## 4. 開發機上的 mock 端到端

`python -m duckd --body mock --legs --engage`（連不到 hub 也照跑），再用 `duckd.ctl` 下指令：

```
--- crouch before legs      False legs are not engaged (duckd-ctl engage-legs)
--- engage-legs             True standing
--- crouch                  True moving
（1.5 秒後）                 moving 0.529
（再 2 秒）                  crouched 1.0 {'hz': 50.1, 'overruns': 0}
--- stand，1 秒後 stop       holding_partial 0.714
--- crouch after abort      False after an abort only 'stand' is allowed
--- stand                   True（recovering）
```

## 5. 限制

- **沒有實機**。實機的步驟在 ADR-0020 §3：先 I2C 降速、足底開關按壓測試，再架高、再著地扶著。
- `--legs` 時 Controller 每拍要讀 14 顆的位置（頭部模式只讀 4 顆），匯流排時間變長；對控制迴圈 overrun 的影響沒有在 Pi 上量過。
- 頭不補償（head_pitch 上限 0.3 rad），蹲低時臉朝下約 28°。
- 沒有 IMU 跌倒判斷。
- 模擬裡頭維持站姿、kp 13.37 N·m/rad；實機的舵機 kp 32（單位不同，沒有換算過）。
