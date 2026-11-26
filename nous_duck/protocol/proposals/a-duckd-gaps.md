# 提案（A 線）：duckd 實作時遇到的協定缺口

- 來源：A 線（`robot/duckd/`），2026-11-25
- 狀態：**提案**，schema 沒有動。duckd 目前都用現有欄位繞過（下面寫了怎麼繞）。要不要改由整合線決定；改的話先改 schema 並升版，再改兩端。

## 1. `reason` 加 `busy`

- **現況**：動作（gesture）進行中又收到另一個動作，ADR-0015 §2.4 要回「忙」。`reason` 列舉裡只有 `busy_mission`，語意不對。
- **目前繞法**：`status: rejected`、`reason: invalid`、`detail` 以 `busy: ` 開頭（例如 `busy: gesture shake in progress`）。
- **建議**：`reason` 加 `busy`。Nous 端可以據此決定「等一下再試」而不是當成參數錯誤。

## 2. `state.mode` 加「未接手」

- **現況**：duckd 啟動後不碰硬體，要本機 `engage` 才接手頭部。這時 duckd 不知道舵機有沒有出力（可能有別的程式讓整隻鴨子維持站姿）。列舉裡最接近的是 `limp`，但 `limp` 讀起來像「全身放鬆」。
- **目前繞法**：回 `mode: limp`、`control_source: none`，並且 `capabilities.head` 是 `unsupported`（`reason` 寫 `servo bus not engaged`）。Nous 端請用 `capabilities` 判斷，不要把 `limp` 講成「鴨子癱著」。
- **建議**：`mode` 加 `detached`（duckd 沒有接手任何致動器，實際扭力狀態未知）。

## 3. 動作被中斷的事件

- **現況**：ADR-0015 §2.5 草案有 `gesture_interrupted`，v0 的事件列舉只有 `gesture_done`。
- **目前繞法**：一律送 `gesture_done`；`data.completed` 是 `true`／`false`，被中斷時 `reason` 是 `stop`、`interrupted`（被 `look` 或釋放蓋過）、`link_lost`、`estop` 之一。`data.clamped` 表示播放時有沒有被仲裁器夾限。
- **建議**：維持一個事件也可以，但請把 `data.completed`、`data.clamped` 與 `reason` 的值寫進 schema 說明；或另加 `gesture_interrupted`。

## 4. `hello` 的動作清單沒有說明文字

- **現況**：ADR-0015 §2.5 說鴨子回報動作的 `id`、`description`、`duration_s`；v0 的 `hello.gestures` 只是名稱陣列。
- **目前繞法**：只送名稱。`gesture` 的 `ack.applied` 會帶 `duration_s`。
- **建議**：之後加一個可選的 `gesture_info`（名稱 → `{duration_s, description}`），讓 Nous 的工具說明可以動態產生。

## 5. `ttl_ms` 對各種指令的意義

- **現況**：schema 的說明是「動作指令到期就停」，沒有分指令。
- **duckd 的解讀**寫在 [ADR-0014 §2.4](../../docs/adr/ADR-0014-duckd-head-direct-and-single-process.md)：`walk`、`look` 到期就停；`gesture` 只管能不能開始；`presence`、`track`、`express` 跟著租約。
- **建議**：把這張表寫進 `protocol/README.md`，兩端才不會各自解讀。特別是 `look`：Nous 端給的 `ttl_ms` 要比「到達目標需要的時間」長（`ack.applied.duration_s` 會回報預估時間），否則頭會停在半路。

## 6. `state.link.rtt_ms`

- **現況**：往返時間只有送 heartbeat 的一方（Nous）量得到。
- **目前繞法**：duckd 一律回 `null`。
- **建議**：把這個欄位改成由 Nous 端自己記，或讓 heartbeat 帶上一次量到的 `rtt_ms` 給鴨子顯示。

## 7. `capability_changed` 事件的 `data`

- duckd 在接手／釋放頭部時送 `capability_changed`，`data` 是 `{"capability": "head", "status": "..."}`。schema 沒有規定 `data` 的形狀；建議寫明。

## 8. 追蹤的細節（2026-11-26，`track sound`）

- **現況**：`state.tracking` 只有 `none`／`face`／`sound`。聽聲轉頭時「聲源在頭轉不到的地方、已經轉到極限」沒有欄位可放。
- **目前繞法**：每次轉向送 `tracking_acquired`，`data` 是 `{"target":"sound","mock":…,"bearing_rad":…,"head_yaw_rad":…,"at_limit":true|false}`；安靜 8 s 回正時送 `tracking_lost`、`reason: quiet`、`data.recentered: true`（追蹤沒有結束，只是回正）。
- **建議**：`state` 加可選的 `tracking_detail`（`bearing_rad`、`at_limit`、`source_ok`），並把「回正」和「追丟」分成兩個事件。

## 9. `wake_word` 事件的 `data`（2026-11-27）

- **現況**：schema 沒有規定 `event.data` 的形狀。duckd 轉送本機喚醒時送的是
  `{"keyword_id":"HELLO_YAZI","doa_deg":11.5,"doa_frame":"body","doa_source":"duck_doa","mock":false}`。
  `doa_deg` 往鴨子的左邊為正、0＝正前方，不知道是 `null`；`doa_frame` 是 `body` 或 `head`（頭沒接手、麥克風又在頭上時只能給相對頭部的值）；
  `doa_source` 是 `duck_doa` 或 `wake_service`；方位來源是合成的會多一個 `doa_mock: true`。
- **建議**：把這幾欄寫進 schema（`wake_word` 的 `data` 至少要有 `keyword_id` 與 `mock`），並寫明方位的正負與座標。
- **另外**：連不上 Nous 時 duckd 直接丟掉喚醒、不補送。協定沒有說事件能不能晚送；建議寫明「`wake_word` 不補送」，或讓事件帶發生時間由 Nous 決定要不要理。

