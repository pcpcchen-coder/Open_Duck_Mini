# 提案（A 線）：姿勢指令 `posture`（蹲低／站起）

[English](a-posture-command.en.md)

- 來源：A 線，2026-11-28；設計見 [ADR-0020 草案](../../docs/adr/ADR-0020-crouch-and-stand.md)
- 狀態：**提案**，schema 沒有動。schema 升版之前，duckd 只開放本機指令（`duckd-ctl posture crouch|stand`），duck-link 不接受姿勢動作。
- 依據：只有模擬（[驗證紀錄](../../docs/validation/posture-crouch-sim-2026-11-28.md)）；腿還沒在實機上動過。

## 1. 指令

```json
{"type": "command", "action": "posture", "params": {"target": "crouch", "duration_s": 3}}
```

| 欄位 | 型別 | 說明 |
|---|---|---|
| `target` | `"crouch"`／`"stand"` | 必填。`crouch`＝原地蹲低（第一版的「坐下」）；`stand`＝回到站姿 |
| `duration_s` | number，3～10 | 選填，預設 3。鴨子不會比 3 秒快 |

- `ack.status`：`accepted` 時 `applied` 帶實際的 `target` 與 `duration_s`。
- 拒絕的情況，都用 v0 已有的 `reason`：腿沒有接手（`unsupported`）、低電壓（`low_battery`）、過熱（`overheat`）、緊急停止中（`estop_latched`）、已經倒了（`fallen`）、另一個姿勢動作或 `gesture` 進行中（沿用 [a-duckd-gaps](a-duckd-gaps.md) §1 的繞法：`invalid`＋`detail` 以 `busy: ` 開頭）、已經在那個姿勢（`invalid`）。
- effect：`reversible_write`（`stand` 可以回到原狀）。只有 `posture_done` 的 `completed: true` 而且 `state.posture` 回讀一致，才算 `confirmed`。

## 2. 狀態

`state` 加一個欄位：

| 欄位 | 值 |
|---|---|
| `posture` | `standing`、`crouched`、`moving`、`holding_partial`（收手後停在中間）、`unknown`（腿沒有接手） |

## 3. 事件

```json
{"type": "event", "event": "posture_done", "data": {"target": "crouch", "completed": false, "reason": "stop", "posture": "holding_partial"}}
```

- `completed`：`true`／`false`。
- `reason`（`completed: false` 時；事件的 `reason` 在 v0 是自由名稱）：`stop`、`link_lost`、`low_battery`、`overheat`、`fallen`、`estop` 之一，和 ack 的列舉用同樣的字。
- `posture`：事件當下的姿勢（同 §2）。

## 4. 要整合線決定的

1. 要新增的只有：`action` 列舉加 `posture`、`state` 加 `posture`、事件列舉加 `posture_done`。`reason` 用現有的值就夠。
2. `stop` 在姿勢動作中的意思是「停在原地」，不是「放鬆」（模擬裡放鬆會往前倒）。Nous 端的說明文字要照這個寫。
3. 蹲著時能不能 `walk`：建議**拒絕**，先 `stand`。
