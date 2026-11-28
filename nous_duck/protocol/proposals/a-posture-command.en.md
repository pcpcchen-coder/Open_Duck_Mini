# Proposal (line A): `posture` command (crouch / stand)

[中文](a-posture-command.md)

- Source: line A, 2026-11-28; design in [ADR-0020 draft](../../docs/adr/ADR-0020-crouch-and-stand.md) (Chinese)
- Status: **proposal**; the schema is unchanged. Until the schema is bumped, duckd only offers a local command (`duckd-ctl posture crouch|stand`) and duck-link does not accept posture motions.
- Basis: simulation only ([validation record](../../docs/validation/posture-crouch-sim-2026-11-28.md), Chinese); the legs have not moved on the real robot yet.

## 1. Command

```json
{"type": "command", "action": "posture", "params": {"target": "crouch", "duration_s": 3}}
```

| Field | Type | Meaning |
|---|---|---|
| `target` | `"crouch"` / `"stand"` | Required. `crouch` = crouch in place (the first version of "sit down"); `stand` = return to the standing pose |
| `duration_s` | number, 3–10 | Optional, default 3. The duck never moves faster than 3 s |

- `ack.status`: when `accepted`, `applied` carries the actual `target` and `duration_s`.
- Rejected, always with `reason` values that v0 already has: legs not engaged (`unsupported`), low voltage (`low_battery`), overheating (`overheat`), emergency stop active (`estop_latched`), already fallen (`fallen`), another posture motion or a `gesture` in progress (the workaround from [a-duckd-gaps](a-duckd-gaps.md) §1: `invalid` with `detail` starting with `busy: `), or already in that posture (`invalid`).
- Effect: `reversible_write` (`stand` restores the original state). It is `confirmed` only when `posture_done` has `completed: true` and the read-back `state.posture` matches.

## 2. State

Add one field to `state`:

| Field | Values |
|---|---|
| `posture` | `standing`, `crouched`, `moving`, `holding_partial` (stopped midway after an abort), `unknown` (legs not engaged) |

## 3. Event

```json
{"type": "event", "event": "posture_done", "data": {"target": "crouch", "completed": false, "reason": "stop", "posture": "holding_partial"}}
```

- `completed`: `true` / `false`.
- `reason` (when `completed: false`; event `reason` is a free-form name in v0): one of `stop`, `link_lost`, `low_battery`, `overheat`, `fallen`, `estop`, using the same words as the ack enum.
- `posture`: the posture when the event is sent (as in §2).

## 4. For the integration line to decide

1. The only additions are: `posture` in the `action` enum, `posture` in `state`, and `posture_done` in the event enum. Existing `reason` values are enough.
2. During a posture motion, `stop` means "hold where you are", not "go limp" (in simulation, going limp makes the duck fall forward). Nous-side descriptions must say so.
3. Whether `walk` is allowed while crouched: we recommend **rejecting** it; `stand` first.
