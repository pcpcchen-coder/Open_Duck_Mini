> [繁體中文](README.md) | [English](README.en.md)

# ④ Nous adapter (nous_adapter)

Status: **Planned** (no code yet).

## Responsibility

This directory holds code that **will move back into AIOS**: it lets Nous use the duck through duck-link. According to [ADR-0001](../docs/adr/ADR-0001-duck-role-in-nous.md) (Traditional Chinese only), the duck has two roles in Nous:

1. **DuckAdapter** (body adapter): an AIOS `IntegrationAdapter` with `service = "duck"` that offers `app.duck.*` tools to the Nous agent.
2. **DuckTerminal** (terminal): sends the duck's events into Nous and sends Nous's expression output to the duck.

## Subdirectories

| Path | Contents | Status |
|---|---|---|
| `adapters/` | `duck.ts`: DuckAdapter (tool definitions, `health()`, `execute()`, mapping acks and state to `ToolResult`) | Planned |
| `shared/` | duck-link message types (generated from or checked against `protocol/schemas`), plus types minimally redeclared from the AIOS contract (with the source commit noted) | Planned |
| `terminal/` | DuckTerminal: event intake and expression output | Planned |
| `tests/` | Tests of tool definitions, result mapping, timeouts, and disconnects against a **mock duck** (must be labelled mock) | Planned |

## AIOS conventions to follow

- TypeScript, in the style of AIOS `prototype/ambient-shell` (no framework).
- Contract: `IntegrationAdapter`, `ToolDefinition`, and `ExecutionContext` from AIOS `prototype/ambient-shell/server/integrations/contracts.ts`. Results use `ToolResult` from `shared/integrations.ts` (`ok` is true only for `confirmed`).
- Tool IDs: `app.<service>.<action>`, here `app.duck.<action>`. Service and action are lowercase alphanumerics, optionally split by single underscores. The function name sent to the model is `app__duck__<action>`.
- Each tool declares `effect` (`read` / `reversible_write` / `external_commit`), `timeoutMs` (100 ms to 60 s), and `supportedRoutes`.
- A mock adapter sets `mock` to `true`, and every status and result it returns is labelled mock.
- Documentation is bilingual (AIOS `docs/BILINGUAL.md`). Tool descriptions provide `description` (Chinese) and `descriptionEn`.

## Tool list (draft)

| Tool ID | effect |
|---|---|
| `app.duck.status` | read |
| `app.duck.walk` | reversible_write |
| `app.duck.stop` | reversible_write |
| `app.duck.look` | reversible_write |
| `app.duck.gesture` | reversible_write |
| `app.duck.antennas` | reversible_write |
| `app.duck.express` | reversible_write (`unsupported` when the expression hardware is absent) |

Parameters, confirmation rules, and the operations deliberately not offered are in [ADR-0001 §4](../docs/adr/ADR-0001-duck-role-in-nous.md#4-appduck-工具清單草案) (Traditional Chinese only).

## Inputs and outputs

- Inputs: tool calls from the Nous agent; acks, state, and events received over duck-link.
- Outputs: duck-link commands; AIOS `ToolResult`s; duck events delivered into Nous.

## Dependencies

- `../protocol/schemas` (planned).
- The AIOS integration-layer contract (AIL-1). This directory does not copy large parts of AIOS code.

## Moving back into AIOS (planned)

Open a separate batch in the AIOS repository: put `adapters/duck.ts` under `prototype/ambient-shell/server/integrations/adapters/`, add it to the reviewed adapter list, and enable it with `NOUS_AIL_SERVICES`. Until that is done and verified in AIOS, no document may claim the integration exists.
