> [繁體中文](README.md) | [English](README.en.md)

# ② duck-link protocol

Status: **v0 draft usable** (2026-11-25): [`schemas/duck-link.v0.schema.json`](schemas/duck-link.v0.schema.json), valid and invalid examples, and schema tests (level: unit tests). Fields may still change; the privacy policy schema is still planned. For the implementations on both ends see the [companion step tracker](../docs/companion/steps.md) (Traditional Chinese).

## v0 contents (2026-11-25)

| Path | Contents |
|---|---|
| [`schemas/duck-link.v0.schema.json`](schemas/duck-link.v0.schema.json) | One file, six message types: `hello`, `heartbeat`, `command`, `ack`, `state`, `event`; `protocol_version` is fixed at `"0.1"` |
| [`examples/valid.jsonl`](examples/valid.jsonl), [`examples/invalid.jsonl`](examples/invalid.jsonl) | One message per line; shared by the tests on both ends |
| [`tests/test_schema.py`](tests/test_schema.py) | Every valid example passes and every invalid example is rejected; confirms the protocol has no torque-off, reboot, or offset-writing operations |

```bash
uv run --no-project --with jsonschema --with pytest python -m pytest nous_duck/protocol/tests -q
```

Key points of v0:

- **Transport**: WebSocket text frames, one JSON message per frame. The duck is the client and connects to its own `127.0.0.1:<port>/duck-link`, which an SSH tunnel carries to the Mac's loopback ([ADR-0009](../docs/adr/ADR-0009-duck-link-transport-and-command-bridge.md) §2.1).
- **Lease**: Nous sends a `heartbeat` every 500 ms; after 1.5 s without one the duck stops moving and sends `link_lost`.
- **Commands** (`action`): `status`, `stop`, `resume`, `walk`, `look`, `track`, `gesture`, `express`, `antennas`, `sound`, `presence`, `where`, `places`, `mission_status`, `go_to`, `find_person`, `return_home`, `follow_me`, `wait_here`, `cancel_mission`.
- **`presence`**: the real state of the Nous voice session (`idle` / `wake` / `listening` / `thinking` / `speaking` / `working` / `error` / `sleeping`); the duck acts it out with its eyes, head, and antennas.
- **`track`**: vision- or sound-linked head (optionally body) following, computed on the duck; Nous only switches it on and off.
- **`capabilities`**: each capability reports `available` / `degraded` / `unsupported` / `mock`. Hardware that is absent or unverified must not be reported as `available`.
- A simulated or mock end must set `mock: true` in `hello` and `state`.

The "planned contents" below are the original 2026-11-12 plan, kept as a record; v0 merges command / state / event / mission into one file.

## Responsibility

duck-link is the **only** interface between the duck (Pi Zero 2 W) and Nous (Mac mini). The two sides share no code. They share only the versioned JSON Schemas here. The Mac side (TypeScript) and the duck side (Python) validate every message they send and receive against the same schemas.

## Planned contents

| Path | Contents | Status |
|---|---|---|
| `schemas/command.schema.json` | Nous → duck: intent commands (walk, stop, look, gesture, antennas, express), with `request_id` and `ttl_ms` | Planned |
| `schemas/state.schema.json` | Duck → Nous: state snapshot (mode, battery voltage, posture, temperature summary, available capabilities, timestamp) | Planned |
| `schemas/event.schema.json` | Duck → Nous: events (fell, picked_up, battery_low, overheat, motor_error, link_lost / link_restored, estop) and command acks | Planned |
| `schemas/mission.schema.json` | Long-running missions: start (go_to, find_person, return_home, follow), cancel, progress, done, failed (reason codes) ([ADR-0001 §7.2](../docs/adr/ADR-0001-duck-role-in-nous.md#72-長時間任務mission), Traditional Chinese only) | Planned |
| `schemas/privacy_policy.schema.json` | Privacy settings document (global, rooms, family members, modes, time windows; IDs only, versioned), synced from Nous to the duck ([ADR-0006](../docs/adr/ADR-0006-privacy-settings.md), Traditional Chinese only) | Planned |
| `examples/` | Valid and invalid examples for each schema, shared by the tests on both sides | Planned |

After R-001 (2026-11-12), `state` must also carry: current room / place, pose and localization uncertainty, map version, charging status and battery estimate. `event` adds `mission_*`, `lost`, `door_closed`, `docked` / `undocked`, and `wake_detected` (with sound direction).

After R-002 (2026-11-19, "follow me / wait here"), the draft also adds: mission type `follow` (progress carries a `phase`), the `wait_here` command, and the events `follow_target_acquired`, `follow_reacquired`, `follow_falling_behind`, `follow_target_lost`, `follow_blocked`, `wait_started`, and `wait_timeout`. None of these messages carry images or appearance features ([ADR-0007 §9.3](../docs/adr/ADR-0007-follow-me-and-wait-here.md#93-duck-link-新增草案正式定義放-protocol先改-schema-再改兩端), Traditional Chinese only).

**Audio and video do not travel as duck-link JSON messages.** The audio stream uses a separate media channel (the AIOS terminal's realtime voice path, or a method decided later; see [ADR-0003 §2.1](../docs/adr/ADR-0003-mobile-terminal-wake-and-find.md#21-終端軟體兩條路線先做可行性-spike), Traditional Chinese only). Raw images never leave the duck; only face features are sent ([ADR-0003 §6](../docs/adr/ADR-0003-mobile-terminal-wake-and-find.md#6-隱私), Traditional Chinese only).

## Design principles

1. **Versioned**: every message carries `protocol_version` (semver). Incompatible changes bump the major version. Either side rejects and reports an unsupported major version instead of guessing.
2. **Intents only**: commands are velocity plus duration, target poses, and gesture names, not streams of joint angles.
3. **Time-limited**: every command that causes motion must carry `ttl_ms`. The duck stops by itself when it expires (deadman).
4. **Acknowledged**: every command has a `request_id`. The duck replies with an ack (accepted / rejected plus a reason code, and the actual values after clamping). The Mac side maps the ack and state to the AIOS `ToolResult` statuses `confirmed` / `refused` / `unknown`.
5. **Reason codes are a fixed enumeration**, never free text or user content.
6. **The duck decides safety**: the range a schema allows is not the range the duck will execute. The duck's safety layer may clamp or reject further.

## Inputs and outputs

- Inputs: the architecture decision ([ADR-0001](../docs/adr/ADR-0001-duck-role-in-nous.md), Traditional Chinese only) and the command vector of the upstream runtime ([`architecture.md` §4](../docs/architecture.md#4-與上游-runtime-的接點), Traditional Chinese only).
- Outputs: schemas and examples used by `robot/nous_link/` (Python) and `nous_adapter/` (TypeScript).

## Dependencies (planned)

- JSON Schema draft 2020-12.
- Validators: one each for Python and TypeScript (to be chosen, with pinned versions).

## Open questions

- Transport (WebSocket or other). See [`architecture.md` §6](../docs/architecture.md#6-傳輸待決). The transport does not change the schemas.
- Field limits and heartbeat interval (need simulation and hardware data).
