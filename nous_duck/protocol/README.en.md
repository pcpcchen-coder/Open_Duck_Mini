> [繁體中文](README.md) | [English](README.en.md)

# ② duck-link protocol

Status: **Planned** (no schemas yet).

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

After R-001 (2026-11-12), `state` must also carry: current room / place, pose and localization uncertainty, map version, charging status and battery estimate. `event` adds `mission_*`, `lost`, `door_closed`, `docked` / `undocked`, and `wake_detected` (with sound direction). [ADR-0009](../docs/adr/ADR-0009-docked-interaction.md) (2026-11-26, draft; Traditional Chinese only) adds: `docked` sub-states in `state` (`docked_idle` / `docked_engaged` / `docked_quiet`) with charging details (charging, full, unstable contact); the `dock_contact_unstable` event and reason codes for `undocked` (for example `contact_lost`); and `clamped` in the ack (a head target clamped to the docked range).

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
