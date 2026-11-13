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
| `examples/` | Valid and invalid examples for each schema, shared by the tests on both sides | Planned |

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
