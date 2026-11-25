> [繁體中文](README.md) | [English](README.en.md)

# ② duck-link 協定（protocol）

狀態：**v0 草案可用**（2026-11-25）：[`schemas/duck-link.v0.schema.json`](schemas/duck-link.v0.schema.json)、合法與不合法範例、schema 測試（層級：單元測試）。欄位仍可能變動；隱私設定文件的 schema 還是規劃中。兩端實作見[夥伴功能分步進度](../docs/companion/steps.md)。

## v0 內容（2026-11-25）

| 路徑 | 內容 |
|---|---|
| [`schemas/duck-link.v0.schema.json`](schemas/duck-link.v0.schema.json) | 單一檔案，六種訊息：`hello`、`heartbeat`、`command`、`ack`、`state`、`event`；`protocol_version` 固定 `"0.1"` |
| [`examples/valid.jsonl`](examples/valid.jsonl)、[`examples/invalid.jsonl`](examples/invalid.jsonl) | 每行一則訊息；兩端測試共用 |
| [`tests/test_schema.py`](tests/test_schema.py) | 合法範例全部通過、不合法範例全部被拒；確認協定裡沒有關扭力、重開機、寫偏移這類操作 |

```bash
uv run --no-project --with jsonschema --with pytest python -m pytest nous_duck/protocol/tests -q
```

v0 的重點：

- **傳輸**：WebSocket 文字框，一框一則 JSON。鴨子是 client，連自己的 `127.0.0.1:<port>/duck-link`，由 SSH 通道接到 Mac 的 loopback（[ADR-0009](../docs/adr/ADR-0009-duck-link-transport-and-command-bridge.md) §2.1）。
- **租約**：Nous 每 500 ms 送 `heartbeat`；鴨子 1.5 s 沒收到就停下動作、送 `link_lost`。
- **指令**（`action`）：`status`、`stop`、`resume`、`walk`、`look`、`track`、`gesture`、`express`、`antennas`、`sound`、`presence`、`where`、`places`、`mission_status`、`go_to`、`find_person`、`return_home`、`follow_me`、`wait_here`、`cancel_mission`。
- **`presence`**：Nous 語音工作階段的真實狀態（`idle`／`wake`／`listening`／`thinking`／`speaking`／`working`／`error`／`sleeping`），鴨子依此做眼睛、頭、天線的動作。
- **`track`**：視覺或聲音連動的頭部（可選身體）跟隨，在鴨子本機計算；Nous 只開關。
- **`capabilities`**：每項能力回報 `available`／`degraded`／`unsupported`／`mock`。硬體沒裝或沒驗證過，不能回 `available`。
- 模擬或 mock 的一端，`hello` 與 `state` 必須帶 `mock: true`。

以下「預計內容」是 2026-11-12 的原規劃，保留當紀錄；v0 把 command／state／event／mission 合成一個檔案。

## 職責

duck-link 是鴨子（Pi Zero 2 W）與 Nous（Mac mini）之間**唯一**的介面。兩邊不共用程式碼，只共用這裡的版本化 JSON Schema；Mac 端（TypeScript）與鴨子端（Python）都用同一份 schema 驗證收到與送出的訊息。

## 預計內容

| 路徑 | 內容 | 狀態 |
|---|---|---|
| `schemas/command.schema.json` | Nous → 鴨子：意圖指令（walk、stop、look、gesture、antennas、express），含 `request_id`、`ttl_ms` | 規劃中 |
| `schemas/state.schema.json` | 鴨子 → Nous：狀態快照（模式、電池電壓、姿態、溫度摘要、可用能力、時間戳） | 規劃中 |
| `schemas/event.schema.json` | 鴨子 → Nous：事件（fell、picked_up、battery_low、overheat、motor_error、link_lost／link_restored、estop）與指令的 ack | 規劃中 |
| `schemas/mission.schema.json` | 長時間任務：開始（go_to、find_person、return_home、follow）、取消、進度、完成、失敗（原因代碼）（[ADR-0001 §7.2](../docs/adr/ADR-0001-duck-role-in-nous.md#72-長時間任務mission)） | 規劃中 |
| `schemas/privacy_policy.schema.json` | 隱私設定文件（全域、房間、家人、模式、時段；只含 ID、版本化），由 Nous 同步到鴨子（[ADR-0006](../docs/adr/ADR-0006-privacy-settings.md)） | 規劃中 |
| `examples/` | 每個 schema 的合法與不合法範例，供兩端測試共用 | 規劃中 |

R-001（2026-11-12）後，`state` 還要加入：所在房間／地點、位姿與定位不確定度、地圖版本、充電狀態與電量估算；`event` 加入 `mission_*`、`lost`、`door_closed`、`docked`／`undocked`、`wake_detected`（含聲源方向）。

R-002（2026-11-19，「跟著我來／在這等我」）後，草案再加入：mission 類型 `follow`（進度帶 `phase`）、指令 `wait_here`、事件 `follow_target_acquired`、`follow_reacquired`、`follow_falling_behind`、`follow_target_lost`、`follow_blocked`、`wait_started`、`wait_timeout`；這些訊息不帶影像或外觀特徵（[ADR-0007 §9.3](../docs/adr/ADR-0007-follow-me-and-wait-here.md#93-duck-link-新增草案正式定義放-protocol先改-schema-再改兩端)）。

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
