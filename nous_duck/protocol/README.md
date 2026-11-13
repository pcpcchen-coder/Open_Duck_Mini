> [繁體中文](README.md) | [English](README.en.md)

# ② duck-link 協定（protocol）

狀態：**規劃中**（尚無 schema）。

## 職責

duck-link 是鴨子（Pi Zero 2 W）與 Nous（Mac mini）之間**唯一**的介面。兩邊不共用程式碼，只共用這裡的版本化 JSON Schema；Mac 端（TypeScript）與鴨子端（Python）都用同一份 schema 驗證收到與送出的訊息。

## 預計內容

| 路徑 | 內容 | 狀態 |
|---|---|---|
| `schemas/command.schema.json` | Nous → 鴨子：意圖指令（walk、stop、look、gesture、antennas、express），含 `request_id`、`ttl_ms` | 規劃中 |
| `schemas/state.schema.json` | 鴨子 → Nous：狀態快照（模式、電池電壓、姿態、溫度摘要、可用能力、時間戳） | 規劃中 |
| `schemas/event.schema.json` | 鴨子 → Nous：事件（fell、picked_up、battery_low、overheat、motor_error、link_lost／link_restored、estop）與指令的 ack | 規劃中 |
| `schemas/mission.schema.json` | 長時間任務：開始（go_to、find_person、return_home）、取消、進度、完成、失敗（原因代碼）（[ADR-0001 §7.2](../docs/adr/ADR-0001-duck-role-in-nous.md#72-長時間任務mission)） | 規劃中 |
| `schemas/privacy_policy.schema.json` | 隱私設定文件（全域、房間、家人、模式、時段；只含 ID、版本化），由 Nous 同步到鴨子（[ADR-0006](../docs/adr/ADR-0006-privacy-settings.md)） | 規劃中 |
| `examples/` | 每個 schema 的合法與不合法範例，供兩端測試共用 | 規劃中 |

R-001（2026-11-12）後，`state` 還要加入：所在房間／地點、位姿與定位不確定度、地圖版本、充電狀態與電量估算；`event` 加入 `mission_*`、`lost`、`door_closed`、`docked`／`undocked`、`wake_detected`（含聲源方向）。

**語音與影像不走 duck-link 的 JSON 訊息**：語音串流走另外的媒體通道（沿用 AIOS 終端的即時語音路徑或之後決定的方式，見 [ADR-0003 §2.1](../docs/adr/ADR-0003-mobile-terminal-wake-and-find.md#21-終端軟體兩條路線先做可行性-spike)）；原始影像不離開鴨子，只送臉部特徵（[ADR-0003 §6](../docs/adr/ADR-0003-mobile-terminal-wake-and-find.md#6-隱私)）。

## 設計原則

1. **版本化**：每則訊息帶 `protocol_version`（semver）。不相容的變更升主版本；兩端遇到不支援的主版本要拒絕並回報，不猜測。
2. **只傳意圖**：指令是速度＋時長、目標姿態、手勢名稱，不是關節角度串流。
3. **有時效**：會產生動作的指令必須有 `ttl_ms`；鴨子端逾時自動停止（deadman）。
4. **可確認**：每個指令有 `request_id`，鴨子回 ack（accepted／rejected＋原因代碼，以及夾限後的實際值）。Mac 端依 ack 與 state 對應到 AIOS `ToolResult` 的 `confirmed`／`refused`／`unknown`。
5. **原因代碼是固定列舉**，不放自由文字或使用者內容。
6. **安全以鴨子為準**：schema 允許的範圍不等於鴨子會執行的範圍；鴨子端 safety 可以再夾限或拒絕。

## 輸入輸出

- 輸入：架構決策（[ADR-0001](../docs/adr/ADR-0001-duck-role-in-nous.md)）、上游 runtime 的指令向量定義（[`architecture.md` §4](../docs/architecture.md#4-與上游-runtime-的接點)）。
- 輸出：給 `robot/nous_link/`（Python）與 `nous_adapter/`（TypeScript）使用的 schema 與範例。

## 依賴（預計）

- JSON Schema draft 2020-12。
- 驗證器：Python 端與 TypeScript 端各選一個（待定，需鎖版本）。

## 待決

- 傳輸層（WebSocket／其他），見 [`architecture.md` §6](../docs/architecture.md#6-傳輸待決)。傳輸方式不影響 schema 本身。
- 各欄位上限與心跳間隔（需模擬與實機數據）。
