> [繁體中文](README.md) | [English](README.en.md)

# ④ Nous adapter (nous_adapter)

Status (2026-11-26): **the code is complete and verified up to "unit/integration tests" and "end-to-end against duckd's simulated body". D1, D2 and D4a have been moved into the AIOS branch `claude/duck-link` and a PR has been opened (flag off by default, not merged yet); it has not been tried with real voice yet, and no command has been issued to the real duck yet.**

This directory holds code that **will later be moved back into AIOS**: it lets Nous use the duck through duck-link. Right now it can run standalone (without AIOS), for development and hands-on testing.

| Component | What it does | Status | Verification level |
|---|---|---|---|
| duck-link hub ([`hub/`](hub/duck-link-hub.ts)) | A WebSocket server on the Mac at local `127.0.0.1:8791/duck-link`; `hello`, a heartbeat every 500 ms with round-trip time, pairing of commands with `ack`, the latest `state`, forwarding of `event`; messages in both directions are validated against the duck-link v0 schema | Complete | Integration tests (mock duck); end-to-end against duckd mock; tunnel measured in practice (Mac ↔ Pi, without touching hardware) |
| DuckAdapter ([`adapters/`](adapters/duck.ts)) | AIOS `IntegrationAdapter`, `service = "duck"`, 17 `app.duck.*` tools | Complete | Integration tests (mock duck); end-to-end against duckd mock |
| DuckTerminal ([`terminal/`](terminal/duck-terminal.ts)) | The entry point for duck events; the source interface and throttling for `presence` | Complete (AIOS's real events are not wired up yet; there is only the dev-only manual source) | Unit/integration tests (mock duck) |
| `duckctl` ([`cli/`](cli/duckctl.ts)) | Issues `app.duck.*` from the terminal, without going through AIOS | Complete | Integration tests; tried by hand (against the mock) |
| Voice media channel ([`hub/duck-voice-hub.ts`](hub/duck-voice-hub.ts)) | `/duck-voice`: uplink voice after the duck's local wake, downlink of Nous's reply, start / end / follow-up listening / interruption; `speaking` in `presence` goes by the playback the duck reports. **There is no speech model**: the backend is only "none" or the echo (replay) backend marked mock ([`docs/duck-voice.md`](docs/duck-voice.en.md)) | Channel complete; real conversation requires changing AIOS (waiting for the user's decision on the route) | Integration tests (simulated audio end, synthetic audio); a local interoperability check with line D's state machine |
| mock duck ([`mock/`](mock/mock-duck.ts)) | A **simulated** duck, for tests and trying things out only; `hello` and `state` carry `mock: true` | Complete | — |
| Dev-only text command ([`cli/text-command.ts`](cli/text-command.ts)) | `duckctl say-command "往左看"` ("look left"): fixed keyword rules map one sentence of text to one tool. **It is not Nous, not speech recognition, and not a language model** | Complete | Unit/integration tests (mock duck) |
| Moving into AIOS | The `/duck-link` endpoint (D1), registering the adapter (D2, 6 tools in the first stage), session events → `presence` (D4a) | **Implemented on the AIOS branch `claude/duck-link`, PR awaiting review** (the user agreed on 2026-11-26; see [`docs/aios-integration-plan.md` §0](docs/aios-integration-plan.en.md#0-2026-11-26-update-d1-d2-and-d4a-implemented-on-an-aios-branch)) | AIOS's fixture tests (122) plus a local check against duckd's simulated body; no real hardware, no real voice |

What has not been done and what cannot be claimed:

- **It cannot yet be claimed that "the duck can be commanded by voice".** The AIOS-side code is on a branch, with the flag off by default, and not merged yet; nobody has tried it with real realtime voice. The steps for trying it are in §5 of `docs/validation/duck-link-2026-11-26.md` on the AIOS branch (starting a separate development instance, without affecting the running Nous), to be started by the user themselves.
- **No command has been issued to the real duck.** All tool results come from a mock (the TypeScript mock here, or the mock body of line A's duckd). The real-hardware steps are written under "Against the real duck" below.
- `presence` currently has only the **dev-only manual source** (`duckctl presence`), not events from a Nous voice session.
- Voice is not here: for how Nous's voice reaches the duck see [`docs/voice-path.md`](docs/voice-path.en.md) (design, not implemented).

## Try it yourself (no duck needed)

Requires Node.js 22.12 or later.

```bash
cd nous_duck/nous_adapter
npm ci
```

Open three terminal tabs:

```bash
# Tab 1: hub (listens only on local 127.0.0.1:8791, waiting for the duck to connect in)
bin/duckctl hub
```

```bash
# Tab 2: simulated duck (use when there is no real duck; all output is marked "模擬" (simulated))
bin/duckctl mock-duck
```

```bash
# Tab 3: issue commands
bin/duckctl link                      # connection, round-trip time, whether the other end is simulated
bin/duckctl status                    # mode, head angles, capability list
bin/duckctl look --yaw 0.2            # turn the head to 0.2 rad (positive = to the left)
bin/duckctl look --yaw 10 --deg       # use degrees
bin/duckctl gesture nod               # nod
bin/duckctl express happy             # eye expression
bin/duckctl presence speaking --level 0.4   # manually send interaction state (dev-only, not a Nous event)
bin/duckctl go_to brother_room        # mission: confirmed only means "has set off"
bin/duckctl say-command "往左看"      # dev-only: text → tool (fixed rules, not Nous; not sent if not recognised)
bin/duckctl events --follow           # watch the events the duck reports
bin/duckctl hub --voice echo          # (replaces the hub above) voice channel connected to the simulated echo (replay) backend
bin/duckctl mock-voice                # simulated duck audio end: sends one "wake" and a synthetic tone; opens no microphone, makes no sound
bin/duckctl voice                     # the voice channel's status and the statistics of the last conversation
bin/duckctl help                      # full usage
```

Each command prints the `ToolResult` (the same as what Nous will get later) and the read-back state:

```text
app.duck.look {"head_yaw":-0.9} → confirmed ✔
  （模擬）頭已經轉到位。（數值超出鴨子的限制，已由鴨子夾限，實際值見 applied）
  ⚠ 對面是模擬的鴨子（mock），不是實機。
  結果：{"applied":{"head_yaw":-0.5,"duration_s":0.5},"clamped":true,"rtt_ms":0,"reached":true,"connected":true}
  回讀的狀態：{"mode":"standing", …,"head":{"head_yaw":-0.5, …}, …}
```

How to read the result:

| Status | Meaning |
|---|---|
| `confirmed` | The duck accepted it, and the state (or event) read back afterwards matches. For motions and missions it only means "**accepted and started**", not finished, arrived or found |
| `unconfirmed` | The duck accepted it, but no matching state was read (or the protocol has no field that can be read back, for example the antennas) |
| `unknown` | Sent, but the duck did not reply or the connection dropped. **It must not be treated as not executed**; go and take a look at the duck |
| `refused` | Not executed: the duck rejected it (`data.duck_reason` is the duck's reason code), or the arguments are wrong, or the duck itself reports that it does not have this capability (`unsupported`) |
| `failed` | Not sent (for example the duck is not connected) |

Exit codes of `duckctl`: 0 = `confirmed`; 2 = `unconfirmed`／`unknown`; 1 = `refused`／`failed`; 3 = cannot reach the hub.

## Against the real duck (left for the integration line or the user to run)

Precondition: the duck-side `duckd` ([`../robot/duckd/`](../robot/README.md), line A) has been deployed to the Pi and can be started. **Line B has not started duckd on the Pi and has not issued any command to the real hardware.**

```bash
cd nous_duck/nous_adapter
scripts/duck-link-dev.sh hub-start        # Mac: hub runs in the background
scripts/duck-link-dev.sh tunnel-start     # SSH tunnel Mac → Pi (default host duck-pi4)
scripts/duck-link-dev.sh status           # shows "已連線" (connected) once the duck has connected
```

The tunnel is `ssh -N -R 127.0.0.1:8791:127.0.0.1:8791 duck-pi4`: initiated by the Mac, the Pi's `127.0.0.1:8791` is connected to the Mac's `127.0.0.1:8791`; both sides bind only loopback. The script changes no system settings and installs no persistent service; it has to be run again after the Mac reboots.

After duckd is started on the duck side (the command is as given in line A's documentation):

```bash
bin/duckctl link          # confirm the other end is "not" simulated, and look at the round-trip time
bin/duckctl status        # look at capabilities: whether head is available or degraded; the others should be unsupported
bin/duckctl look --yaw 5 --deg --time 1.5    # small angle, turn slowly; see whether the real head moves and whether the read-back angle is right
bin/duckctl look --yaw 0 --time 1.5          # back to centre
bin/duckctl stop
```

Notes:

- First look at the `duck` line shown by `duckctl link`: if it has "⚠ 模擬", it is still connected to the mock.
- Night-time rules ([overall design §5](../docs/companion/README.md#5-安全與夜間規則)): when unattended, only small, slow head motions; no walking, no sound. `walk` is not sent when the duck reports `walk: unsupported`.
- To check only the tunnel without starting duckd: `ssh duck-pi4 python3 - < scripts/tunnel-probe.py` (a probe program that does not touch hardware; it answers heartbeats for a few seconds under a "not a duck" identity).
- To finish: `scripts/duck-link-dev.sh tunnel-stop`, `scripts/duck-link-dev.sh hub-stop`.

## Tests

```bash
cd nous_duck/nous_adapter
npm ci
npm run typecheck
npm test
```

Results on 2026-11-26: 171 passed (`validator` 33, `hub` 25, `duck-adapter` 51, `terminal` 18, `cli` 18, `duck-voice` 26), about 6 seconds. The tests connect only to ephemeral local ports, do not touch 8791, and do not connect to the running Nous. The test tooling is the same as AIOS's: vitest 5.0.3, tsx 4.23.15, TypeScript 7.0.2.

End-to-end check against line A's duckd (mock body):

```bash
# Tab 1 (in line A's robot/duckd directory): python -m duckd --body mock --engage --url ws://127.0.0.1:18792/duck-link
# Tab 2:
npx tsx scripts/e2e-duckd.ts --port 18792
```

For the record and numbers see [`../docs/validation/nous-adapter-2026-11-25.md`](../docs/validation/nous-adapter-2026-11-25.md).

## Tool list

Each tool's `effect`, parameters and description are as defined in [`adapters/duck.ts`](adapters/duck.ts) (`bin/duckctl tools` prints them).

| Tool ID | effect | What `confirmed` means | Duck capabilities required |
|---|---|---|---|
| `app.duck.status` | read | The duck returned its current state | — |
| `app.duck.walk` | reversible_write | state shows walking has started (not that it has finished) | `walk` |
| `app.duck.stop` | reversible_write | state shows it has stopped and has no mission | — (sent at any time) |
| `app.duck.look` | reversible_write | The head reached the target (`data.reached: true`), or has started turning (`false`) | `head` |
| `app.duck.gesture` | reversible_write | The gesture has started (a `gesture_done` event, or state shows control by duck-link) | `head` |
| `app.duck.antennas` | reversible_write | **Currently never `confirmed`**: the v0 state has no antenna position to read back, so at most `unconfirmed` | `antennas` |
| `app.duck.express` | reversible_write | state shows the expression has changed | `eyes` |
| `app.duck.track` | reversible_write | state shows the tracking setting has taken effect (not that a person has already been seen) | `head` + `tracking_face` or `tracking_sound` |
| `app.duck.where` | read | The duck returned its location | `navigation` |
| `app.duck.places` | read | The duck returned the list of places | `navigation` |
| `app.duck.mission_status` | read | The duck returned the mission status (no mission is also a successful read) | — |
| `app.duck.go_to` | reversible_write | The mission has started (**has set off, not arrived**), `data.mission_id` | `navigation`, `walk` |
| `app.duck.find_person` | reversible_write | The search has started (not found) | `navigation`, `walk`, `camera` |
| `app.duck.return_home` | reversible_write | Has started returning to the charging dock (not already charging) | `navigation`, `walk`, `dock` |
| `app.duck.cancel_mission` | reversible_write | state shows no mission in progress | — |
| `app.duck.follow_me` | reversible_write | Has started looking for you (not already following) | `walk`, `camera` |
| `app.duck.wait_here` | reversible_write | state shows `mode: waiting` | — |

**Only 6 are enabled in the first stage** (`DUCK_STAGE1_TOOLS`, decided by the user on 2026-11-26): `status`, `stop`, `look`, `gesture`, `express`, `track`. The definitions of the other 11 are all there, but with `enabled: false` and hidden from the human-readable catalogue; AIOS's Dispatcher returns `refused`／`disabled` for them. `duckctl` is the development entry point and has all 17 enabled (`enableAllTools`).

When the duck reports a capability as `unsupported`, the corresponding tool is not sent and returns `refused` directly (`data.duck_reason: "unsupported"`, `data.capability`). With the duck's current hardware (only head servos and a speaker), the only ones that will move anything on the real duck are `status`, `stop`, `look` and `gesture`.

duck-link commands not given to the model, and why:

| Command | Reason | Who may issue it |
|---|---|---|
| `presence` | It has to be driven by the **real events** of the voice session; giving it to the model amounts to letting it "act out" listening or speaking | DuckTerminal (`PresenceDriver`); during development `duckctl presence` |
| `sound` | Local prompt tones are the terminal's feedback, not the model's decision | Later, by DuckTerminal |
| `resume` | Once the pause is lifted, `walk` will be accepted, which is more like something done only when a person is present. **Whether to give it to the model is for the user to decide** (not given by default) | `duckctl resume` |

`track` is given to the model: the user will say "look at me" or "stop looking at me all the time", and Nous is only the switch; the tracking is computed locally on the duck.

Operations deliberately not provided ([ADR-0001 §4, §7.3](../docs/adr/ADR-0001-duck-role-in-nous.md#4-appduck-工具清單草案)): turning torque off, rebooting, writing servo settings, releasing the emergency stop, streaming joint angles, mapping and changing no-go zones, obtaining images or recordings, loosening privacy settings. The duck-link v0 schema does not contain these operations, and the hub cannot send a command that does not conform to the schema (there are tests).

Tools not done yet: `app.duck.announce` (whether to do it depends on the voice path, see [`docs/voice-path.md`](docs/voice-path.en.md)), `app.duck.privacy_tighten` (waiting for the privacy settings schema of [ADR-0006](../docs/adr/ADR-0006-privacy-settings.md)).

## Directory

| Path | Contents |
|---|---|
| `hub/duck-link-hub.ts` | duck-link hub and the `DuckLink` interface; `start()` runs standalone, `attach(server)` attaches to an existing http server (the way the AIOS core connects it) |
| `adapters/duck.ts` | Tool definitions and `DuckAdapter` |
| `adapters/duck-exec.ts` | The shared flow: one command → ack → read-back → `ToolResult` |
| `adapters/duck-text.ts` | Fixed sentences for results (Chinese and English) |
| `terminal/duck-terminal.ts` | Event entry point (classification, mission records, sink) |
| `terminal/presence.ts` | `PresenceDriver`: voice session events → `presence`, debouncing and throttling |
| `terminal/manual-presence-source.ts` | The **dev-only** manual presence source |
| `shared/aios-integrations.ts`, `aios-schema.ts`, `aios-contracts.ts` | Minimal re-declaration of the AIOS contracts, one file per AIOS module (source commit noted; the AIOS side imports the original files directly and does not need these three files) |
| `cli/text-command.ts` | The **dev-only** text command rules (not Nous) |
| `shared/duck-link.ts`, `shared/capabilities.ts` | duck-link message types; command → capability mapping |
| `shared/validator.ts` | Validates against `../protocol/schemas/duck-link.v0.schema.json` (Ajv 8.20.0) |
| `mock/mock-duck.ts` | The **simulated** duck |
| `cli/` | `duckctl`, the hub process, the control channel (UNIX socket), a minimal dev-only Dispatcher |
| `scripts/duck-link-dev.sh` | Starts／stops the hub and the SSH tunnel in the background |
| `scripts/tunnel-probe.py` | Tunnel probe that runs on the Pi (does not touch hardware) |
| `scripts/e2e-duckd.ts` | End-to-end check against line A's duckd |
| `tests/` | vitest tests |
| `docs/aios-integration-plan.md` | The plan for moving into AIOS (file and function level) |
| `docs/voice-path.md` | Voice path design |
| `docs/voice-test.md` | Step-by-step voice test for the user to follow (telling the duck by voice to turn its head, nod and shake its head; the channel test with wake word + microphone + speaker) |
| `docs/duck-voice.md` | The Nous side of the voice media channel `/duck-voice`: wire format, rules, the voice backend interface, what is still missing |
| `hub/duck-voice-hub.ts`, `shared/duck-voice.ts` | The Nous side of the voice media channel (turn-based; audio only in memory) |
| `mock/echo-voice-backend.ts`, `mock/mock-duck-voice.ts` | The **simulated** echo (replay) backend (not a speech model) and the simulated duck audio end (synthetic audio) |

## AIOS conventions followed

- TypeScript, no framework; relative imports with the `.ts` extension; configuration the same as AIOS's `tsconfig.json` (minus the browser libs).
- Contracts: `IntegrationAdapter`, `ToolDefinition` and `ExecutionContext` from AIOS `prototype/ambient-shell/server/integrations/contracts.ts`, and `ToolResult` from `shared/integrations.ts` (`ok` is true only for `confirmed`). Commit consulted: `c85307861f7562803fb3776407493da49cdc8a83`.
- Tool ID `app.duck.<action>`; name sent to the model `app__duck__<action>`; every tool declares `effect`, `timeoutMs` (100 ms–60 s) and `supportedRoutes` (`api_key`, `live`); the parameter schema uses only the subset AIOS supports (flat object, scalars).
- Tool descriptions have a Chinese `description` and an English `descriptionEn`; results use fixed sentences, with the English listed separately.
- When the other end is a simulated duck, `adapter.mock` is true, every result's message starts with "（模擬）", and `data.mock` is true.
- Documentation is bilingual, Chinese and English (AIOS `docs/BILINGUAL.md`).

## Dependencies

Pinned in `package.json` and `package-lock.json`: `ws` 8.22.0, `ajv` 8.20.0; for development `typescript` 7.0.2, `tsx` 4.23.15, `vitest` 5.0.3, `vite` 8.3.4, `@types/node` 25.9.9, `@types/ws` 8.18.1. Except for `ajv`, the versions are all the same as AIOS's. `.npmrc` sets `legacy-peer-deps=true` (npm 10.9 crashes when resolving vitest 5's peer dependencies; AIOS is set the same way).

## Inputs and outputs

- Inputs: tool calls (later from the Nous Agent, now from `duckctl`); `ack`, `state` and `event` received over duck-link; voice session events (later from AIOS, now only the dev-only manual source).
- Outputs: duck-link `command`; AIOS `ToolResult`; tidied duck events (`TerminalEvent`).
- Protocol: [`../protocol/`](../protocol/README.en.md). Gaps and ambiguities found during implementation are written in [`../protocol/proposals/b-nous-readback-and-semantics.md`](../protocol/proposals/b-nous-readback-and-semantics.en.md); the schema was not changed.
