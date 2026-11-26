> [繁體中文](b-nous-readback-and-semantics.md) | [English](b-nous-readback-and-semantics.en.md)

# 協定提案（B 線）：回讀欄位與幾個語意要講清楚

狀態：**提案**，沒有改 schema。日期：2026-11-25。提出者：B 線（Nous 端，`nous_adapter/`）。

來源：實作 DuckAdapter 時遇到的缺口，以及 2026-11-25 用本 repo 的 hub＋DuckAdapter（TypeScript）對 A 線的 `duckd`（Python，mock 身體）跑端到端時看到的差異（紀錄見 [`docs/validation/nous-adapter-2026-11-25.md`](../../docs/validation/nous-adapter-2026-11-25.md)）。兩個實作照 v0 的 schema 互通沒有問題（雙向 0 則不合格訊息）；以下是 schema 沒有規定、兩邊各自解讀的地方。

每一項都寫了「現在怎麼繞過」，所以這份提案不擋任何人；由整合線決定要不要收進 v0 或下一版。

## 1. state 缺少可以回讀的欄位

Nous 端的規則是「ack accepted 且 state 回讀符合才算 `confirmed`」。以下指令在 v0 的 state 裡沒有對應的欄位：

| 指令 | 缺什麼 | 現在怎麼繞過 | 建議加的欄位（state） |
|---|---|---|---|
| `look` | `state.head` 是實際關節角度，沒有**目標**。剛接受時頭還沒到，分不出「還在轉」和「沒有動」 | 等到實際角度進入目標 ±0.06 rad 算到位；逾時但比送出前接近目標算「已開始」 | `head_target`：`{neck_pitch, head_pitch, head_yaw, head_roll}`（夾限後的目標） |
| `gesture` | 沒有「正在做哪個動作」 | 看到 `gesture_done`（帶 `request_id`）或 ack 之後的 state 的 `control_source` 是 `duck_link` 就算開始——後者是很弱的證據 | `activity`：`{kind: "gesture" | "walk" | "look" | "idle", name?, request_id?}` |
| `antennas` | 完全沒有天線的欄位 | 接受了也只回 `unconfirmed` | `antennas`：`{left, right, pattern?}` |
| `sound` | 沒有「正在播／播完」 | 接受了也只回 `unconfirmed`（Nous 端目前不把 `sound` 給模型） | 事件 `sound_done`（帶 `request_id`），或併入 `activity` |
| `wait_here` | 靠 `mode: "waiting"`，這個有 | — | — |

## 2. `gesture_done` 不代表做完

端到端時看到 `gesture_done` 帶 `reason: "stop"`（動作被下一個指令打斷）。schema 只說事件可以帶 `reason`，沒有說 `gesture_done`、`walk_done` 的 `reason` 有哪些值。

- 現在怎麼繞過：Nous 端只把 `gesture_done` 當成「這個動作確實開始過」的證據，不當成「做完」。
- 建議：在 schema 的說明列出這兩個事件的 `reason` 列舉（例如 `completed`、`stop`、`preempted`、`lease_lost`、`fault`），並規定正常做完時 `reason` 省略或為 `completed`。

## 3. 讀取類指令在「沒有資料」時回什麼

`mission_status` 在沒有任務時：`duckd` 回 `rejected`＋`no_mission`；本 repo 的 TypeScript mock 鴨子回 `accepted`＋`data.mission = null`。兩種都合 schema。

- 現在怎麼繞過：DuckAdapter 兩種都當成「讀到了：沒有任務」（`confirmed`）。帶了 `mission_id` 而鴨子回 `no_mission` 才是 `refused`。
- 建議：規定讀取類（`status`、`where`、`places`、`mission_status`）只要能力存在就回 `accepted`，「沒有」用 `data` 表達；`rejected` 留給真的不能回答的情況（`unsupported`、`not_localized`…）。
- 另外，這四個指令的 `ack.data` 形狀 v0 沒有定義。建議至少定：`where` → `{place, localized, uncertainty_m, on_dock}`（和 `state.location` 相同）；`places` → `{places: [{id, kind}], map_version}`；`mission_status` → `{mission: <同 state.mission> | null}`。

## 4. `ttl_ms` 對哪些指令有「到期就停」的效果

schema 寫「motion commands stop when it expires without renewal」。哪些算 motion command 沒有列出。

- 現在 Nous 端的作法：`walk` 的 `ttl_ms` 設成 `duration_s`＋0.5 秒、`look` 設成 `duration_s`＋1 秒（免得動作被 ttl 提早切斷）；任務類（`go_to` 等）用 5 秒、`track`／`presence`／`express` 用 2～3 秒，假設它們**不會**因為 ttl 到期而停。
- 建議：在 schema 的說明明列：ttl 到期會停的只有 `walk`（以及 `look`？）；任務、`track`、`presence`、`express`、`antennas` 的 ttl 只代表「太晚開始處理就丟掉」。任務與 `track` 的存活由連線租約與各自的逾時參數決定。

## 5. `wait_here` 與 `stop` 的「任何時候都接受」

ADR-0001 §7.3 寫 `wait_here`「任何時候都接受」。端到端時 `duckd`（只有頭部的 mock）對 `wait_here` 回 `rejected: unsupported`。

- 這不算 duckd 的錯：v0 沒有規定哪些指令不受能力限制，`capabilities` 裡也沒有對應 `wait_here` 的鍵。
- 現在怎麼繞過：Nous 端對 `stop`、`wait_here`、`cancel_mission`、`mission_status`、`status` 不做「能力 unsupported 就不送」的事前檢查，一律送出，由鴨子決定；鴨子拒絕就如實回 `refused`。
- 建議：規定 `stop` 一律 `accepted`（已經停著也是）；`wait_here` 在不能走路的鴨子上要嘛 `accepted`（本來就在原地，`mode` 變 `waiting`），要嘛明確寫可以回 `unsupported`。二選一寫進說明。

## 6. 指令 → 能力的對照表

Nous 端在送出前會看 `capabilities`：需要的能力是 `unsupported` 就不送，直接回報。這張對照表現在只存在 Nous 端的程式裡（`nous_adapter/shared/capabilities.ts`），鴨子端有自己的一份；兩份不一致時，結果是「Nous 沒送」或「送了被拒」，都安全，但訊息不同。

| 指令 | Nous 端現在認為需要的能力 |
|---|---|
| `walk` | `walk` |
| `look`、`gesture` | `head` |
| `antennas` | `antennas` |
| `express` | `eyes` |
| `sound` | `speaker` |
| `track face` ／ `track sound` | `head`＋`tracking_face` ／ `head`＋`tracking_sound` |
| `where`、`places` | `navigation` |
| `go_to` | `navigation`、`walk` |
| `find_person` | `navigation`、`walk`、`camera` |
| `return_home` | `navigation`、`walk`、`dock` |
| `follow_me` | `walk`、`camera` |

建議：把這張表放進 `protocol/`（README 或一個小的 JSON），兩端都從那裡讀。

## 7. 連線建立的順序與取代規則

schema 只說 hello 是「兩邊在 WebSocket 開啟後的第一則訊息」。本 repo 的 hub 的作法（`duckd` 與它互通沒有問題）：

- hub 在連線建立時立刻送自己的 hello，不等鴨子。
- 鴨子的第一則訊息必須是合格的 `hello`（`role: "duck"`），否則關閉（代碼 4003）；3 秒內沒有 hello 也關閉。
- 收到鴨子的 hello 之後 hub 才開始送 heartbeat。
- `protocol_version` 不是 `"0.1"` → 關閉（代碼 4002），不嘗試相容。
- 同一時間只有一條鴨子連線；新的連線完成 hello 後取代舊的（舊的以代碼 4001 關閉）。
- hub 超過 3 秒沒收到鴨子的任何訊息 → 關閉（代碼 4000）。

建議：把順序、逾時與關閉代碼寫進 `protocol/README`。

## 8. `resume` 由誰下

`resume` 在 v0 的指令清單裡，ADR-0009 §2.5 寫「第一個 walk 前需要本機或 Nous 明確 resume」。Nous 端目前**沒有**把它做成模型工具（解除暫停之後 `walk` 就會被接受，比較像「有人在場」才做的事），只留在開發 CLI（`duckctl resume`）。

要不要給模型 `app.duck.resume`，是使用者的決定，不是協定問題；記在這裡是因為它影響「Nous 能不能自己讓鴨子開始走」。

## 9. `mission_failed` 的原因代碼

`event.reason` 是自由的名稱（`^[a-z0-9_]{1,48}$`），沒有列舉。Nous 要把失敗原因說給使用者聽，需要固定清單才能對應固定句（AIOS 的慣例是原因代碼固定、文字固定）。

建議：列舉任務失敗的原因（例如 `door_closed`、`blocked`、`lost`、`cancelled`、`stopped`、`fell`、`link_lost`、`low_battery`、`timeout`、`person_not_found`、`dock_not_found`、`no_charge`），由 C 線（導航）確認實際會用到哪些。
