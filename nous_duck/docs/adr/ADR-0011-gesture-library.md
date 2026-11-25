# ADR-0011：動作庫——先用現有步態策略編排具名動作，動態動作另開訓練批次

- 狀態：**草案（Proposed）**
- 日期：2026-11-15
- 相關：[ADR-0009 草案](https://github.com/pcpcchen-coder/Open_Duck_Mini/pull/9)（duck-link 傳輸與指令橋接，尚未合併）、[ADR-0001](ADR-0001-duck-role-in-nous.md)（§4 `app.duck.gesture`、`look`、`antennas`、`express`）、[ADR-0005](ADR-0005-compute-and-sensor-upgrade.md)（§2.4 重量與步態策略）、[ADR-0006](ADR-0006-privacy-settings.md)（§4.2 眼燈優先順序）、[`../architecture.md`](../architecture.md) §4、[`../../robot/README.md`](../../robot/README.md)、[`../../sim/README.md`](../../sim/README.md)

本 ADR 的依據是**閱讀上游程式碼**，沒有在模擬或實機上跑過。查閱版本：Open_Duck_Mini_Runtime `v2` commit `376de65`（2026-09-07）、Open_Duck_Playground `main` commit `b9be205`（2025-08-05）。根目錄的 `BEST_WALK_ONNX*.onnx` 是用哪個版本的 Playground 訓練的，目前不知道。

## 1. 背景

使用者想教鴨子新動作，例如點頭、搖頭、東張西望、天線擺動。要決定兩件事：哪些動作不用訓練就能做？這些動作在鴨子上要怎麼定義、執行，又要怎麼開放給 Nous？

ADR-0001 已經列出 `app.duck.gesture`（執行鴨子端白名單內的預錄動作），但沒有定義「預錄動作」是什麼、能做到什麼程度。

### 1.1 上游程式碼的事實

| 事實 | 出處 |
|---|---|
| 步態策略每 20 ms 讀一個 7 維指令：`[lin_vel_x, lin_vel_y, ang_vel, neck_pitch, head_pitch, head_yaw, head_roll]` | runtime `scripts/v2_rl_walk_mujoco.py:152-170`（`last_commands` 放進觀測值） |
| 實機上，頭部 4 軸的目標角度＝**指令值＋策略輸出**（`head_motor_targets = last_commands[3:] + motor_targets[5:9]`） | runtime `scripts/v2_rl_walk_mujoco.py:310` |
| **訓練時，頭部指令只是觀測值**：把頭部關節設成指令值的那一行被註解掉了（`# motor_targets.at[5:9].set(state.info["command"][3:])`），也沒有任何獎勵項追蹤頭部指令 | Playground `open_duck_mini_v2/joystick.py:419`、`:634-666` |
| 訓練時的指令範圍：前後 ±0.15 m/s、左右 ±0.2 m/s、轉向 ±1.0 rad/s；neck_pitch −0.34～1.1、head_pitch ±0.78、head_yaw ±1.5、head_roll ±0.5 rad | Playground `joystick.py:94-101` |
| 訓練時指令每 500 步（`ctrl_dt` 0.02 s，約 10 s）重新抽一次，期間固定不變；有 10% 的機率 7 維全部為 0 | Playground `joystick.py:456-461`、`:671-725` |
| 上游手把有兩種模式：走路模式只送速度、頭部指令維持 0；頭部模式只送頭部、速度設 0。頭部範圍 head_pitch −0.78～0.3、head_yaw ±0.5、head_roll ±0.5，neck_pitch 固定 0 | runtime `mini_bdx_runtime/xbox_controller.py:15-17`、`:69-118` |
| 暫停（`paused`）時主迴圈在算策略之前就 `continue`，**不送任何馬達目標**，頭部指令也不會生效；天線的設定在暫停判斷之前，暫停時仍會更新 | runtime `scripts/v2_rl_walk_mujoco.py:238-251` |
| 天線是 2 顆 PWM 舵機（Pi Zero GPIO D13／D12），輸入 −1～1，不在步態策略裡 | runtime `mini_bdx_runtime/antennas.py` |
| 眼燈、投影燈、音效各自獨立（GPIO 開關、pygame 播 wav），不在步態策略裡 | runtime `eyes.py`、`projector.py`、`sounds.py` |

### 1.2 這些事實代表什麼

1. **天線、眼燈、投影燈、音效**跟平衡無關，可以自由編排。
2. **速度指令**在訓練範圍內有獎勵追蹤，是策略真正學過的。但訓練時指令約 10 秒才換一次，頻繁切換速度不在訓練分布裡。
3. **頭部**：依這個版本的 Playground，策略沒有學過「頭照指令轉動時要怎麼平衡」。實機上，頭部指令是直接疊加到策略輸出上的。所以頭部動作能不能不摔、能動多快，**不能用「訓練過」來保證**，要在模擬和實機上一個一個驗證。上游手把讓人在站立時動頭，代表作者有這樣用，但這不是我們的驗證。
4. **「站著」有兩種狀態**：策略在跑、速度指令為 0；或是暫停。依 §1.1 暫停那一列，暫停時頭不會動。ADR-0009 草案（[PR #9](https://github.com/pcpcchen-coder/Open_Duck_Mini/pull/9) §2.5）記載「速度為 0 時策略仍會原地踏步」，這點我還沒在模擬裡確認。如果屬實，頭部動作會在原地踏步時進行，平衡條件和完全站定不同。
5. 我們的頭部會重新設計（AR0144 鏡頭與紅外線補光燈裝在頭上，ADR-0005），頭的質量會變。原版上驗證過的頭部動作，換頭之後要重新驗證。

## 2. 決定

### 2.1 動作分三類

| 類別 | 定義 | 要不要訓練 | 初版動作庫 |
|---|---|---|---|
| **A 類：編排** | 只用現有步態策略的 7 維指令，加上天線、音效、眼燈提示，依時間軸編排 | 不用 | **納入** |
| **B 類：開迴路關鍵影格** | 繞過步態策略，直接控制腿部關節（蹲、傾身、抬腳） | 不用，但沒有平衡回饋 | **不納入**。要做的話另寫 ADR，處理「策略交出與接回控制權」和驗證方式 |
| **C 類：訓練新策略** | 動到全身平衡的動態動作（舞步、踢、跳、坐下站起、跌倒後起身、新步態） | 要 | **不納入**。每個動作一個批次（參考動作 → Playground 環境與獎勵 → GPU 訓練 → 模擬 → 實機）；策略之間怎麼切換要另寫 ADR |

### 2.2 動作定義檔

- A 類動作寫成 JSON 定義檔，放在 `robot/behaviors/library/<id>.json`；定義檔的格式用 JSON Schema 描述，放在 `robot/behaviors/`。這是**鴨子本機的格式**，不屬於 duck-link 協定，Nous 看不到內容，只看得到名稱和摘要（§2.5）。選 JSON 是因為和 duck-link 一樣用 JSON Schema 驗證，不多加依賴。
- 每個動作由幾條**軌**組成，每條軌是一串關鍵影格 `[t（秒）, 值]`，播放時以 50 Hz 插值：

| 軌 | 對應 | 值的單位 |
|---|---|---|
| `vel` | 指令 0–2（lin_vel_x、lin_vel_y、ang_vel） | m/s、rad/s |
| `head` | 指令 3–6（neck_pitch、head_pitch、head_yaw、head_roll） | rad |
| `antennas` | 左、右天線 | −1～1 |
| `cues` | 在某個時間點發出的音效或眼燈提示（交給感知板執行，見 §2.4） | 列舉名稱 |

- 必填欄位（草案）：`id`（小寫英數加底線，例如 `nod`）、`version`、`category`（初版只能是 `"A"`）、`description`（繁體中文）、`tracks`、`interpolation`（`linear` 或 `min_jerk`）、`requires`（需要的硬體，例如 `antennas`、`speaker`、`eyes_rgb`）、`allowed_modes`（`standing`＝策略在跑、速度指令為 0；`paused`＝暫停。含 `head` 軌的動作只能用 `standing`，因為暫停時頭不會動；只有 `antennas`、`cues` 的動作兩種都可以）、`verification`（見 §2.6）。
- 範例（**示意**，角度和時間都是還沒驗證的佔位值，不能拿來上機）：

```json
{
  "id": "nod",
  "version": 1,
  "category": "A",
  "description": "點頭兩下",
  "interpolation": "min_jerk",
  "allowed_modes": ["standing"],
  "requires": [],
  "tracks": {
    "head": {
      "head_pitch": [[0.0, 0.0], [0.4, -0.3], [0.8, 0.0], [1.2, -0.3], [1.6, 0.0]]
    }
  },
  "verification": { "level": "none", "hardware_profile": null, "record": null }
}
```

### 2.3 允許範圍（初版）

初版取**訓練範圍和上游手把範圍的交集**，也就是比較保守的那一邊：

| 指令 | 訓練範圍 | 上游手把 | 初版允許 |
|---|---|---|---|
| lin_vel_x | ±0.15 m/s | ±0.15 | **±0.15** |
| lin_vel_y | ±0.2 m/s | ±0.2 | **±0.2** |
| ang_vel | ±1.0 rad/s | ±1.0 | **±1.0** |
| neck_pitch | −0.34～1.1 rad | 固定 0 | **固定 0** |
| head_pitch | ±0.78 rad | −0.78～0.3 | **−0.78～0.3** |
| head_yaw | ±1.5 rad | ±0.5 | **±0.5** |
| head_roll | ±0.5 rad | ±0.5 | **±0.5** |
| 天線 | （不在策略裡） | — | **−1～1**；實際機構會不會干涉，組裝後確認 |

另外的規則：

1. **頭部軌和速度軌不能同時非零**，跟上游手把的兩種模式一樣。初版動作庫只做速度指令為 0 的動作（`vel` 全為 0），原地轉向也先不做。有速度的動作等 P4 有避障和禁區之後再評估，而且要和 `app.duck.walk` 受一樣的上限與檢查。
2. **頭部角速度、角加速度上限**，以及**速度指令的變化率上限**，要在模擬中量出初始值，寫進 `robot/config/`，並在 `docs/validation/` 留紀錄。這些數字還沒量之前，載入器拒絕任何含頭部軌的動作上實機，只能在模擬中跑。
3. 放寬任何一項範圍（例如 neck_pitch、或 head_yaw 放寬到 ±1.5）都要有模擬加實機的紀錄。

### 2.4 執行與安全

1. **在身體板執行**：`robot/behaviors` 的播放器以 50 Hz 產生 7 維指令和天線位置，經 `robot/safety` 再交給上游 runtime。這和 [`architecture.md` §4](../architecture.md#4-與上游-runtime-的接點) 規劃的包裝指令來源是同一個接點。如果 ADR-0009 草案採用，播放器就是它的 `CommandArbiter` 的一個指令來源，和手把、duck-link 意圖一起仲裁；動作的頭部範圍比 ADR-0009 草案的夾限更嚴（neck_pitch 固定 0）。
2. **載入時檢查，不偷偷夾限**：定義檔任何一個關鍵影格超出 §2.3 的範圍，或插值後超出速率上限，整個動作拒絕載入並記錄原因，不會悄悄截斷之後照做。safety 在執行時仍會夾限，作為最後一道關卡。
3. **永遠可以中斷**：`stop`、緊急停止、跌倒、低電壓、斷線，都會立刻中斷動作。中斷後頭部依速率上限回到中立姿勢，天線回到 0。
4. **一次只做一個動作**：動作進行中又收到新動作，回 `refused`（`busy`），Nous 要先 `stop`。
5. **任務進行中不做頭部動作**：鏡頭裝在頭上，導航和找人需要頭部穩定。任務（mission）進行中，含 `head` 軌的動作回 `refused`（`busy_mission`）；只動天線或只有 `cues` 的動作可以做。
6. **音效與眼燈交給感知板**：依 ADR-0005 與 ADR-0006，喇叭和 RGB 眼燈由 Pi 4 驅動。身體板在時間點送出提示，由感知板執行。眼燈提示**永遠不能蓋掉「鏡頭開著」的青色**（ADR-0006 §4.2 的優先順序）；音效遵守夜間與隱私模式的音量設定。同步誤差容許值待定。
7. 硬體不存在（例如還沒裝 RGB 眼燈）時，`requires` 不符的動作不列給 Nous，呼叫時回 `refused`（`hardware_missing`）。

### 2.5 對 Nous 的介面

- 沿用 ADR-0001 的 `app.duck.gesture`（`reversible_write`），參數 `name` 是鴨子回報清單裡的名稱。`look`、`antennas` 保留，用在單一目標姿態；`gesture` 用在有時間軸的組合動作。
- 鴨子的 `state` 回報可用動作清單：`id`、`description`、`duration_s`、`allowed_modes`，以及動作庫版本。
- 結果語意：ack accepted 且 state 顯示動作正在執行 → `confirmed`，意思是**已開始**，不是已做完。做完或被中斷以事件回報（草案：`gesture_done`、`gesture_interrupted`＋原因代碼）。
- 原因代碼草案：`unknown_gesture`、`busy`、`busy_mission`、`mode_not_allowed`、`hardware_missing`、`safety_refused`。
- **新增或修改動作定義不開放給模型**，比照 ADR-0001 §4「更新 ONNX 策略」，走 `robot/deploy/` 的人工部署流程。
- 上面的欄位和代碼寫進 `protocol/schemas` 的時間點是 P3（duck-link 第一批）。本 ADR 不先寫 schema。

### 2.6 驗證等級綁定硬體版本

- 每個動作的 `verification.level` 是 `none`、`sim`、`real` 其中之一，同時記錄驗證時的 `hardware_profile`（機身設定的識別，例如「原版頭」或「AR0144 頭 v1」）和驗證紀錄的路徑。
- **鴨子只把 `real`、而且 `hardware_profile` 符合目前機身的動作列給 Nous。** `none` 和 `sim` 的動作只能在本機用 CLI 執行，旁邊要有人。
- 硬體一改（例如換上新的頭），受影響動作的驗證等級自動退回 `sim`，要重新驗證。

### 2.7 初版動作清單（草案）

名稱和幅度都還可以改，一開始全部是 `verification: none`：

| id | 說明 | 用到的軌 |
|---|---|---|
| `nod` | 點頭 | head（head_pitch） |
| `shake` | 搖頭 | head（head_yaw） |
| `tilt` | 歪頭 | head（head_roll） |
| `look_around` | 慢慢東張西望 | head（head_yaw、head_pitch） |
| `antenna_wiggle` | 天線擺動 | antennas |
| `antenna_perk` | 天線豎起（「聽到了」） | antennas |
| `happy` | 天線擺動＋歪頭＋開心音效 | antennas、head、cues（需要 `speaker`） |

## 3. 理由

- A 類不用 GPU、不用訓練，就能涵蓋大部分表情和互動需求，是最便宜的起點。
- §1.1 的程式碼顯示頭部動作不在訓練的獎勵裡，所以初版不擴大範圍：取保守範圍、只在站著時動頭、速率上限要先量。動作庫仍然可以先做，靠驗證流程把關，而不是假設「策略會處理」。
- 動作定義留在鴨子本機、Nous 只送名稱，符合 ADR-0001「Nous 只下意圖」和「安全以鴨子為準」。模型不能自己發明關節軌跡。
- 載入時拒絕超出範圍的動作，而不是執行時偷偷截斷，避免「定義檔寫的」和「實際做的」不一致，卻沒有人知道。
- 驗證綁定硬體版本，是因為頭部重新設計是已知、一定會發生的變更（ADR-0005）。
- B 類繞過步態策略，沒有平衡回饋，又要處理控制權交接，風險和 A 類不在同一個等級，所以分開決定。
- C 類需要參考動作、獎勵設計和 GPU，而且一個動作一個策略要能切換，工作量大，所以等有明確想要的動作時再一個一個開批次。

## 4. 後果

- `robot/behaviors/` 要實作：定義檔 JSON Schema、載入器與檢查器、50 Hz 插值播放器、中斷處理、送給感知板的提示。檢查器、插值、中斷、拒絕規則都可以在雲端寫單元測試，驗證層級標「單元測試」。
- `sim/` 需要一個測試工具：在 MuJoCo 裡用上游 ONNX 策略播放動作，記錄是否跌倒、腳是否滑動、軀幹姿態變化，用來量 §2.3 的速率上限。這依賴 `sim/` 的第一批（載入上游模型和策略跑平地行走）。
- 實機驗證要等 P1（原版能走）。開放給 Nous 要等 P3。
- `protocol/` 在 P3 加入動作清單、`gesture_*` 事件和原因代碼；`nous_adapter/` 的 `gesture` 工具參數改成依鴨子回報的清單動態產生。
- P2 換頭之後，含頭部軌的動作要重新驗證。
- 不改任何上游檔案；上游程式只當作參考與執行環境。

### 4.1 建議的批次順序

1. `sim/` 第一批：載入上游模型與 ONNX 策略，跑平地行走與站立（模擬層級）。
2. `robot/behaviors/` 第一批：定義檔 schema、載入器與檢查器、播放器，以及單元測試（不需要硬體）。
3. 在模擬中播放初版動作，量出速率上限，寫進 `docs/validation/`。
4. P1 之後在實機上逐一驗證，有人在旁邊扶著。

## 5. 待決

1. 頭部角速度、角加速度上限，速度指令變化率上限（模擬量測後決定）。
2. 是否放寬 neck_pitch，或把 head_yaw 放寬到訓練範圍 ±1.5（需要模擬加實機紀錄）。
3. 根目錄 `BEST_WALK_ONNX*.onnx` 與 runtime 實際採用的策略，是用哪個版本的 Playground 訓練的？如果訓練時頭部指令有作用，§1.2 第 3 點的結論可以放寬。
4. 要不要做 B 類動作（另寫 ADR）。
5. 第一個 C 類動作要做哪一個（例如跌倒後自己起身），以及多策略切換的方式（另寫 ADR）。
6. 音效、眼燈提示和動作之間的同步誤差容許值。
7. 初版動作的名稱、幅度和節奏（使用者的偏好）。
8. 暫停狀態下要不要開一條「只動頭」的路徑（繞過步態迴圈直接送頭部目標）。這會碰到 B 類的問題（策略沒有在控制），要另外評估。
9. 速度為 0 時策略是否原地踏步（§1.2 第 4 點），要在模擬中確認。
10. 鴨子要不要在待機時自己做小動作（例如偶爾東張西望），還是只在 Nous 要求時才動。
