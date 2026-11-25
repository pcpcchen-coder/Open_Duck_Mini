# 協定提案（C 線）：任務事件的原因代碼與資料欄位、被抱起來

- 提出：C 線（模擬與導航），2026-11-26
- 對象：[`schemas/duck-link.v0.schema.json`](../schemas/duck-link.v0.schema.json)。**這份提案沒有改 schema**；導航程式目前只用現有欄位，下面每一項都通過現行 schema 的驗證。
- 背景：[`robot/navigation/README.md`](../../robot/navigation/README.md)、[ADR-0016](../../docs/adr/ADR-0016-navigation-core-and-sim-findings.md)

## 1. `mission_failed` 的 `reason` 要有固定列舉

現況：`event.reason` 是任意的 `name`（`^[a-z0-9_]{1,48}$`），schema 沒有列出任務失敗的原因。導航實際會送出的代碼：

| 代碼 | 意思 | Nous 可以怎麼說 |
|---|---|---|
| `door_closed` | 路上的門關著；鴨子停在門前。`data.door` 是門的 ID | 「房門關著」 |
| `lost` | 找不到標籤、無法定位；鴨子停在原地 | 「我迷路了」 |
| `blocked` | 路被擋住、重新規劃也過不去；或送了指令但腳沒動（`data.detail: gait_did_not_start`） | 「路被擋住了」 |
| `forbidden` | 目的地在禁區邊界內，或估計位置太靠近禁區（`data.zone`、`data.zone_kind`） | 「那裡我不能去」 |
| `timeout` | 任務超過時間上限 | |
| `fell` | 跌倒 | 「我跌倒了」 |
| `cancelled` | 被 `cancel_mission` 取消 | |
| `dock_failed` | 回充對不準或一直沒有充電訊號（`data.detail`、`data.attempts`） | 「我回不了家」 |

提案：

1. schema 加 `mission_fail_reason` 列舉（上表 8 個），並規定 `event == "mission_failed"` 時 `reason` 必填、必須是其中之一。
2. `cancelled` 與 `dock_failed` 是總體設計與 ADR-0002 §5.3 沒列的兩個，請確認名稱。另一個做法是加 `mission_cancelled` 事件，取消就不算「失敗」；我傾向沿用 `mission_failed`＋`cancelled`，少一種事件。

## 2. 任務事件的 `data` 欄位

現況：`event.data` 是任意物件。導航目前放的：

| 事件 | `data` |
|---|---|
| `mission_progress` | `kind`、`phase`、`progress`（0～1）、`near`（最近的地點 ID 或 null）、`uncertainty_m`；回充重試時另有 `detail`、`attempt` |
| `mission_done` | `kind`、`place`；`go_to` 另有 `uncertainty_m`；`return_home` 另有 `charging`、`charging_signal_mock`、`attempts` |
| `mission_failed` | `kind`、`place`、`phase`、`near`，加上 §1 表裡各原因的欄位 |
| `undocked`、`docked` | `place` |
| `charging_started` | `signal`：`electrical` 或 `mock` |

所有事件在模擬或 mock 時都帶 `mock: true`。

提案：在 schema 裡為這幾個事件的 `data` 定義欄位（`additionalProperties: false`），並明文規定 **`data` 不放座標、地圖、影像**，只放地點 ID 與數值（隱私規則）。

## 3. `phase` 的值

`state.mission.phase` 與事件的 `data.phase` 目前是任意 `name`。導航會出現的值：
`undocking`、`planning`、`localizing`、`navigating`、`final_turn`、`dock_approach`、`dock_settle`、`dock_turn`、`dock_settle2`、`dock_back`、`dock_retreat`、`dock_retry`。

提案：不做成列舉（內部階段之後還會改），但在說明裡寫「`phase` 只供顯示與除錯，Nous 不要依它做判斷」。

## 4. `where`、`places`、`mission_status` 的 `ack.data`

現況：`ack.data` 是任意物件。導航回的：

- `where`：`place`、`room`、`localized`、`uncertainty_m`、`on_dock`、`map_version`、`mock`
- `places`：`map_version`、`synthetic_map`、`places: [{place, room, is_dock}]`
- `mission_status`：`mission_id`、`kind`、`place`、`phase`、`progress`、`state`（`active`／`done`／`failed`）、`reason`、`mock`

提案：把這三個形狀寫進 schema。`state.location` 目前沒有 `room` 與 `map_version`，建議加上（ADR-0002 §3.2 要求鴨子與 Nous 用同一版地圖，Nous 需要知道鴨子手上是哪一版）。

## 5. 被抱起來：`picked_up` 要成為身體端的義務

現況：事件列舉裡有 `picked_up`，但沒有說誰偵測、之後會怎樣。

模擬的結論（[驗證紀錄 §8](../../docs/validation/sim-nav-2026-11-25.md#8-c7安全規則)）：鴨子被抱到別處放下後，如果身體端沒有告訴導航，導航會照舊的位置估計繼續走，直到標籤對不上為止。有通知時，導航立刻丟掉定位、原地找標籤。

提案：

1. 這主要是鴨子內部的介面（duckd → 導航的 `SensorFrame.lifted`），不一定要改 schema；但請在協定說明裡寫明：**身體端偵測到被抱起來（兩腳離地＋IMU）時必須送 `picked_up`，進行中的任務會暫停並重新定位**。
2. `state.location.localized` 在被抱起來之後要變成 `false`，直到重新看到標籤（導航已經這樣做）。
3. 可以考慮加 `put_down` 事件，讓 Nous 知道鴨子重新站在地上了；非必要。

## 6. 能力回報

`capabilities.navigation` 與 `capabilities.dock` 在模擬裡回 `mock`。實機上在鏡頭、標籤、充電座都驗證過之前，應該回 `unsupported`（不是 `degraded`）；這一點現行 schema 已經能表達，只是提醒 A 線。
