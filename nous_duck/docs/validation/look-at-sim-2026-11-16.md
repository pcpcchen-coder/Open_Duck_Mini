# V3「說話時看著對方」控制器與模擬（2026-11-16）

- 分支：`claude/duck-binocular-vision-planning-3mb8mb`
- 對象：[`robot/behaviors/look_at.py`](../../robot/behaviors/look_at.py)（控制器）、[`sim/look_at_sim/`](../../sim/look_at_sim/)（模擬）
- 規劃：[雙目視覺規劃](../stereo_vision_plan.md) §3.3 P2、§7 V3
- **驗證層級：單元測試＋MuJoCo 模擬**
- **模擬的範圍**：上游 `robot.xml`（唯讀）**固定機身**，只有頭頸關節在動；人臉偵測是**依幾何投影產生的合成資料**（fixture），不是真的影像或偵測器；轉身是**運動學近似**（反向旋轉場景裡的人），沒有跑步態策略
- **沒有做的**：人臉偵測器、真實影像、站立平衡（步態策略）、身體板與感知板之間的連線、實機

## 指令

雲端容器，Python 3.13；依賴鎖在 [`robot/requirements-dev.txt`](../../robot/requirements-dev.txt)、[`sim/requirements-dev.txt`](../../sim/requirements-dev.txt)（mujoco 4.0.1、numpy 2.5.4、pytest 9.2.0）。

```bash
python -m pytest nous_duck/robot/tests -v
```

```bash
python -m pytest nous_duck/sim/tests -v
```

```bash
cd nous_duck/sim
python -m look_at_sim
```

結果：robot 單元測試 **15 passed**；sim 測試 **10 passed**（約 6 秒）。CI 的 `look-at` job 跑同兩組測試。

## 從上游確認的事

| 項目 | 結果 | 怎麼確認的 |
|---|---|---|
| 頭部指令的入口 | 上游 runtime 7 維指令的後 4 維（neck_pitch、head_pitch、head_yaw、head_roll）是**加在策略輸出的頭部目標上的偏移**，而且整個指令向量是**策略觀測的一部分** | Open_Duck_Mini_Runtime `v2` `376de65`：`scripts/v2_rl_walk_mujoco.py`（`head_motor_targets = last_commands[3:] + motor_targets[5:9]`；`obs` 含 `cmds`） |
| 頭部指令範圍 | neck_pitch −0.34～1.1、head_pitch −0.78～0.3、head_yaw ±0.5、head_roll ±0.5 rad | 同上 `xbox_controller.py`。這是策略訓練時看過的範圍，控制器不超出；neck_pitch 上限先保守取 0.6 |
| 正負號 | neck_pitch、head_pitch 正值＝抬頭；head_yaw 正值＝往左；視線俯仰 ≈ neck_pitch＋head_pitch | MuJoCo 順向運動學（`test_joint_signs_positive_pitch_looks_up_positive_yaw_looks_left`） |
| 抬脖子會讓頭往後移 | neck_pitch 1.1 時鏡頭往後約 16 cm | MuJoCo 順向運動學（本次手動算，鏡頭位置用下面的假設） |
| 鏡頭高度 | 0.372 m | home 站姿＋鏡頭裝在頭殼正面中間（`head` body 座標 (0.095, 0, −0.03) m，**假設值**，頭殼還沒設計） |

## 模擬中發現的問題

1. **上游 `robot.xml` 的自身碰撞**：頸部與軀幹網格的凸包互相穿透，固定機身時把頸部推開約 0.12 rad（約 7°）。這是模型的碰撞外形問題，不是舵機或控制器的行為；模擬改成關掉碰撞（機身固定、沒有地板，不需要碰撞）。
2. **平視時看不到站著的人**（雙目視覺規劃 §1.2 的推算在模擬中重現）：第一版控制器沒看到臉時回到平視，1.5 m 外站著的大人一直在畫面上緣之外，永遠找不到。改成：對話中沒看到臉時視線抬高 0.4 rad，並在 0.4 與 0.9 rad 之間上下找。
3. **舵機下垂造成固定誤差**：用回讀角度換算人的方向時，如果指令不補償實際角度與指令的差（重力下垂），這個差會一直留著。改成用回讀估計這個差並從指令扣掉（單元測試 `test_compensates_servo_sag_with_readback`：下垂 0.1 rad 時仍對準到 2.5° 內）。
4. **臉比較大就換人**：第一版在已經看著 B 時，A 的臉比較大就會換過去。改成只有說話者方向指向別人時才換人；說話的人在視野外時，持續 1 s 後轉向說話者方向找。

## 結果（附舵機回讀，3 個亂數種子）

假設：影像 10 fps、偵測延遲 0.1 s、人臉中心雜訊 2 px（標準差）、說話者方向雜訊 10°（標準差）、臉寬 15 cm、臉寬小於 15 px 就偵測不到、轉身一階延遲 0.3 s。「看準所需時間」是誤差第一次小於 5° 並持續 1 s 的時間（`two_people_switch` 從 5 s 換人時起算）。誤差是鏡頭光軸與該看的人的臉的夾角。

| 情境 | 種子 | 看準所需時間 | 最後 2 s 誤差（中位／最大） | 人在畫面內（最後 2 s） | 頭頸最大角速度 | 身體轉角 | 換人次數 | 仰角不夠 | 最後狀態 |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| `adult_1p5m` | 0 | 1.9 s | 0.5° ／ 0.5° | 100% | 1.03 rad/s | 0° | 0 | 否 | tracking |
| `adult_1p5m` | 1 | 2.0 s | 0.7° ／ 0.7° | 100% | 1.03 rad/s | 0° | 0 | 否 | tracking |
| `adult_1p5m` | 2 | 1.9 s | 0.6° ／ 0.6° | 100% | 1.03 rad/s | 0° | 0 | 否 | tracking |
| `child_1m` | 0 | 1.6 s | 0.9° ／ 0.9° | 100% | 1.03 rad/s | 0° | 0 | 否 | tracking |
| `child_1m` | 1 | 1.7 s | 1.0° ／ 1.0° | 100% | 1.03 rad/s | 0° | 0 | 否 | tracking |
| `child_1m` | 2 | 1.7 s | 0.9° ／ 0.9° | 100% | 1.03 rad/s | 0° | 0 | 否 | tracking |
| `adult_too_close_0p7m` | 0 | 2.2 s | 4.3° ／ 4.3° | 100% | 1.30 rad/s | 0° | 0 | 是 | tracking |
| `adult_too_close_0p7m` | 1 | 2.2 s | 4.3° ／ 4.3° | 100% | 1.30 rad/s | 0° | 0 | 是 | tracking |
| `adult_too_close_0p7m` | 2 | 2.2 s | 4.3° ／ 4.3° | 100% | 1.30 rad/s | 0° | 0 | 是 | tracking |
| `walk_across_2m` | 0 | 4.2 s | 1.0° ／ 5.4° | 100% | 1.43 rad/s | -30° | 0 | 否 | tracking |
| `walk_across_2m` | 1 | 5.0 s | 3.7° ／ 5.6° | 100% | 1.44 rad/s | -33° | 0 | 否 | tracking |
| `walk_across_2m` | 2 | 5.1 s | 3.0° ／ 5.9° | 100% | 1.44 rad/s | -34° | 0 | 否 | tracking |
| `called_from_side` | 0 | 3.9 s | 2.5° ／ 2.5° | 100% | 1.86 rad/s | 88° | 0 | 否 | tracking |
| `called_from_side` | 1 | 3.9 s | 2.5° ／ 2.5° | 100% | 1.86 rad/s | 88° | 0 | 否 | tracking |
| `called_from_side` | 2 | 3.9 s | 2.5° ／ 2.6° | 100% | 1.86 rad/s | 88° | 0 | 否 | tracking |
| `two_people_switch` | 0 | 2.2 s | 2.7° ／ 2.7° | 100% | 1.63 rad/s | 18° | 2 | 否 | tracking |
| `two_people_switch` | 1 | 1.7 s | 2.6° ／ 2.6° | 100% | 1.77 rad/s | 18° | 2 | 否 | tracking |
| `two_people_switch` | 2 | 2.2 s | 2.8° ／ 2.8° | 100% | 1.95 rad/s | 18° | 2 | 否 | tracking |
| `leaves_view` | 0 | 1.9 s | — ／ — | 0% | 1.29 rad/s | 0° | 0 | 否 | idle |
| `leaves_view` | 1 | 1.9 s | — ／ — | 0% | 1.29 rad/s | 0° | 0 | 否 | idle |
| `leaves_view` | 2 | 1.9 s | — ／ — | 0% | 1.29 rad/s | 0° | 0 | 否 | idle |

情境說明：

- `adult_1p5m`（6 s）：大人站在前方 1.5 m、偏左 0.3 m（臉 1.6 m）
- `child_1m`（6 s）：小孩站在前方 1.0 m、偏右 0.2 m（臉 1.0 m）
- `adult_too_close_0p7m`（6 s）：大人站在前方 0.7 m（臉 1.6 m）：需要的仰角超出頭部範圍
- `walk_across_2m`（11 s）：大人在前方 2 m 由左往右走過（0.4 m/s，左 1.5 m → 右 1.5 m）
- `called_from_side`（10 s）：坐著的大人在左側 90°、1.5 m（臉 1.2 m），一開始不在畫面內；0.5 s 時開口（只有說話者方向）
- `two_people_switch`（12 s）：A（右 0.6 m、臉 1.6 m）與 B（左 0.7 m、臉 1.2 m）都在 2 m 前方；A 先說話，5 s 起換 B 說話
- `leaves_view`（14 s）：大人在前方 1.5 m，3 s 時離開（不再出現）

說明：

- `adult_too_close_0p7m`：需要約 60° 仰角，超出頭部範圍（視線最高約 52°），控制器回報「仰角不夠」，臉仍在畫面內（誤差 4.3°）。行為層可以據此後退一點；這一批沒有做後退。
- `two_people_switch` 換人 2 次：A 開口（0.5 s）之前，鴨子可能先看到 B；A 開口後換到 A，5 s 起 B 開口再換到 B。
- 頭頸最大角速度 1.0～2.0 rad/s。STS3215 的速度上限要查規格並實測，這裡只表示指令沒有要求突然的大跳動。

## 結果（不附舵機回讀，種子 0）

拿不到舵機回讀時，控制器用自己的指令值當作拍攝當下的視線。仍然能追，但沒辦法補償下垂，固定誤差約 2～3°：

| 情境 | 種子 | 看準所需時間 | 最後 2 s 誤差（中位／最大） | 人在畫面內（最後 2 s） | 頭頸最大角速度 | 身體轉角 | 換人次數 | 仰角不夠 | 最後狀態 |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| `adult_1p5m` | 0 | 1.6 s | 2.9° ／ 2.9° | 100% | 1.03 rad/s | 0° | 0 | 否 | tracking |
| `child_1m` | 0 | 1.4 s | 2.7° ／ 2.7° | 100% | 1.03 rad/s | 0° | 0 | 否 | tracking |
| `adult_too_close_0p7m` | 0 | 2.2 s | 4.3° ／ 4.3° | 100% | 1.30 rad/s | 0° | 0 | 是 | tracking |
| `walk_across_2m` | 0 | 5.1 s | 2.2° ／ 5.4° | 100% | 1.48 rad/s | -37° | 0 | 否 | tracking |
| `called_from_side` | 0 | 3.7 s | 2.2° ／ 2.2° | 100% | 1.86 rad/s | 87° | 0 | 是 | tracking |
| `two_people_switch` | 0 | 2.0 s | 1.8° ／ 1.8° | 100% | 1.79 rad/s | 16° | 2 | 否 | tracking |
| `leaves_view` | 0 | 1.6 s | — ／ — | 0% | 1.29 rad/s | 0° | 0 | 否 | idle |

## 限制

- **沒有驗證站立平衡**。頭部指令是策略觀測的一部分，策略「應該」會處理，但抬脖子讓頭往後移；neck_pitch 上限 0.6 rad 是保守值，要在跑步態策略的模擬（P2）與實機確認後才能放寬。
- 合成偵測：沒有漏偵測以外的錯誤（誤偵測、側臉、遮擋、背光），也沒有模擬雙目延遲的真實分布。
- 轉身用運動學近似；真的轉身靠步態，會晃、會打滑，速度與延遲要實測。上游 ang_vel 的正負號**還沒在實機確認**。
- 鏡頭位置、各項門檻與時間常數都是初始值；鏡頭到貨、頭殼設計後要重新跑。
- 這些都是模擬結果，**不代表實機能做到**。
