> [繁體中文](aios-integration-plan.md) | [English](aios-integration-plan.en.md)

# AIOS integration plan: connecting the duck to Nous

Status: **D1, D2 and D4a have been implemented on an AIOS branch and a PR has been opened (2026-11-26; flag off by default, not merged yet, not tried with real voice); D3, D4b and D5–D7 are still a plan.** Date: 2026-11-25, updated 2026-11-26 (§0). Until it is merged and verified in AIOS, nowhere is it claimed that "the duck is integrated into Nous".

- AIOS consulted: `pcpcchen-coder/AIOS` `main`, commit `c85307861f7562803fb3776407493da49cdc8a83` (2026-11-24), `git clone`d into a temporary directory and inspected **read-only**; nothing was run, nothing was modified, and no request was sent to the running Nous.
- Unless noted otherwise, paths are relative to AIOS's `prototype/ambient-shell/`; `file:line` are line numbers at that commit.
- A "fact" is read directly from the code; a "recommendation" or "inference" is this document's judgement and is marked explicitly.
- For the current state of this repo's side see [`../README.md`](../README.en.md); for how voice reaches the duck see also [`voice-path.md`](voice-path.en.md).

## 0. 2026-11-26 update: D1, D2 and D4a implemented on an AIOS branch

On 2026-11-26 the user agreed to open a branch, implement, and open a PR in a **separate clone** of the AIOS repo (not the checkout that is running Nous). The result:

- Branch `claude/duck-link` (based on AIOS main `c853078`; on 2026-11-26 `origin/main` was confirmed to still be this commit), PR: [pcpcchen-coder/AIOS#156](https://github.com/pcpcchen-coder/AIOS/pull/156). **Not merged**; the running Nous was not restarted, switched or changed.
- Flag `NOUS_DUCK` (off by default). When it is off there is no endpoint, no adapter and no observer; AIOS's own full check (`node scripts/verify-aios.mjs`) passes.
- Verification level: AIOS's fixture tests (5 new test files, 122 tests, with a fake duck marked mock on the other end) plus one local check of "the AIOS branch's hub and Dispatcher against duckd's simulated body" (0 messages not conforming to the schema in either direction). **No real hardware, no real voice.** The details are in `docs/validation/duck-link-2026-11-26.md` on the AIOS branch.
- How the user can try it (starting a separate development instance: a different port and configuration directory, without affecting the running Nous) is written in §5 of the same document. Those steps connect to the cloud model and make sound; they have **not been run by anyone**, and the user has to start them themselves.

Where what was actually done differs from the plan in §3–§6 of this document:

| Plan | Actual | Reason |
|---|---|---|
| The hub goes in `server/duck-link.ts`, the rest scattered in `server/` | Everything is in `server/duck/`: `link.ts` (hub), `schema.ts`, `exec.ts`, `text.ts`, `presence.ts`, `session-bridge.ts`; the adapter is in `server/integrations/adapters/duck.ts`; the types are in `shared/duck-link.ts` and `shared/duck-capabilities.ts` | One folder is easy to find and easy to remove as a whole |
| The schema is read from file with `fs` | A JSON import (`with { type: "json" }`), consistent with the rest of AIOS | No dependence on file paths at run time |
| Register all 17 tools, then decide which to turn on | All 17 are defined, **only 6 are enabled**: `status`, `stop`, `look`, `gesture`, `express`, `track`; the rest have `enabled: false` and `catalog.hidden: true` | The user's decision on 2026-11-26. The ones not enabled do not go into the model's tool table and are not listed in the human-readable command table |
| `presence` is sent by DuckTerminal | The core uses `sendDuckPresence()` directly; DuckTerminal's event entry point (D3) was not moved in this batch | D3 is not in this batch; presence should not depend on whether the adapter is registered |
| D4a's observation point is wired to `PresenceDriver.handle()` | There is one more layer in between, `createPresenceBridge()`: it handles "start was decided but the connection never came up" (back to idle after 60 seconds), two sessions existing at once, and the session ID changing when the path changes; when a delegation starts it switches to working by itself | The core's events are coarser than the page's phase, so there has to be a place to fill in these cases |
| The observation point field is called something like `onSessionChange` | `RealtimeSessionsOptions.onSessionEvent`, with event type `SessionLifecycleEvent` (`started`／`connected`／`delegation`／`ended`); the `createApp` option is `voiceSessionObserver` | `RealtimeSessions` is created inside `createApp` (`server/app.ts:285`), not in `nous.ts` |
| Whether to add Ajv was pending | `ajv` 8.20.0 was added (`package.json` and the lock) | Both ends have to validate against the same schema file; the standalone generator was not tried |

Item-by-item comparison against the AIOS contracts: this repo's `shared/aios-integrations.ts`, `aios-schema.ts` and `aios-contracts.ts` are minimal re-declarations. After the adapter was moved into AIOS as is and its imports were pointed at AIOS's original files, `tsc --noEmit` reported no errors at all — the types used (`ToolResult`, `toolResult`, `IntegrationToolId`, `ToolDefinition`, `AdapterCatalog`, `ExecutionContext`, `HealthReport`, `IntegrationAdapter`, `InputSchema`) are compatible with the real declarations at AIOS `c853078`. What AIOS has and this repo does not declare: `ToolDefinition.legacyName`, `AdapterCatalog.builtin`, the `scalar` of `PropertySchema`, `ToolCapability`, `IntegrationFunctionSpec`, `CAPABILITY_STATUSES`, `fromWireName`, `serviceOf`, and the types of the page state; DuckAdapter uses none of them.

Things discovered only during the move, which the earlier plan did not cover:

- AIOS's English command table (`README.en.md`) is not generated automatically; rows have to be added by hand.
- The baseline file of AIOS's `tests/commands-from-catalog.test.ts` contains local time, and running it directly in Asia/Taipei fails (unrelated to the duck); both regenerating the baseline file and running the tests need `TZ=UTC`.
- AIOS's bilingual check requires the code blocks of the two language versions to be **byte-for-byte identical** (Chinese comments inside code blocks must not be translated).
- The fake adapter dependency used in tests cannot be a Proxy that "throws as soon as it is touched": `DuckAdapter.mock` reads the connection state, and the catalogue and the commands page read it.

## 1. Summary

| Question | Answer |
|---|---|
| Which files change to move DuckAdapter into AIOS | Add 1 adapter file and 1 test file, modify 8 existing files and 2 baseline files (§3) |
| Where the `/duck-link` endpoint goes | A new module `server/duck-link.ts`, created in `server/nous.ts` and attached to the `upgrade` event of the `Server` returned by `createApp` (§4). **AIOS currently has no inbound WebSocket endpoint at all**; this is the first |
| Which real events `presence` is produced from | The core currently knows only the start, connect and end of a session plus some events of the live path; the full listening／thinking／speaking state is **known only to the page**. A core observation point has to be added, then page reporting (§6) |
| How Nous's voice reaches the duck's speaker | The assistant's voice is the WebRTC audio track received by **the browser page that started this conversation**; the core does not handle audio at all. So the only approach that needs no new audio pipeline is route A of ADR-0003: run the Nous page on the duck's Pi 4 ([`voice-path.md`](voice-path.en.md)) |
| How many batches AIOS has to open | 7; for the recommended order see §8; once the first 3 are done, Nous can use voice to tell the duck to do motions |

## 2. Facts found (the parts that affect the design)

### 2.1 Adapter registration and enabling

- Reviewed list: `KNOWN_ADAPTERS` at `server/integrations/index.ts:36-39` (ID → factory). Currently it has `mock`, `home`, `spotify_soloist`, `voice_relay`, `google_calendar`, `weather`, `lg_tv`, `gmail_gog`. The factory signature is `(config: Config["ail"], log, deps: AdapterDeps) => IntegrationAdapter | null`.
- Enabling: `NOUS_AIL=on` plus `NOUS_AIL_SERVICES` (comma-separated adapter IDs), parsed by `parseAil()` at `server/config.ts:292-312`; read only once at startup, and neither the model nor the page can enable tools.
- How modules already created by the core are handed to adapters: `AdapterDeps` (`index.ts:30-34`, currently `home?: HomeBridgePort`, `weather?`). `createIntegrations` is called only once, at `server/nous.ts:321`.
- Registration checks (`registry.ts:32-63`): tool ID format, `serviceOf(id) === adapter.service`, `effect` in the list, `timeoutMs` 100–60 000, `supportedRoutes` non-empty and not containing `page`, parameter schema only a flat object plus scalars (`schema.ts`).
- Effect of `effect` (`policy.ts:38-41`, `dispatcher.ts:105-107`): `read` and `reversible_write` execute directly; `external_commit` needs confirmation, but the confirmation card is not wired to the integration layer, so it is **always refused**. The duck's tools are all `read` or `reversible_write` and are not affected.
- Dispatcher limits (`dispatcher.ts:71-143`, `policy.ts:44`): 30 calls per minute per adapter (all paths combined); a result's `data` over 4 096 bytes is dropped; `message` is truncated to 500 characters; when the adapter throws, a tool with side effects returns `unknown`.
- Name sent to the model: `app__duck__<action>`; the tool tables of the two voice paths are attached at `server/nous.ts:333` (`api_key`) and `:337` (`live`).
- The live path allows at most 2 tool calls per delegation (`maxHostCalls: 2` at `live-tool-caller.ts:61-69`, shared between page tools and integration tools).
- The official checklist for adding an adapter: `docs/development/adding-an-adapter.md`.

### 2.2 How existing adapters are written

- The template for read-back confirmation is `adapters/lg-tv.ts` (file header `:13-14`): read-back present and matching → `confirmed`; sent but cannot be read or does not match → `unconfirmed`; disconnected or no reply after sending → `unknown`; cannot connect, not sent → `failed`. This repo's DuckAdapter uses the same semantics.
- **No adapter holds a long-lived connection**: the LG TV opens one connection per tool call (`server/lgtv/ssap.ts:6`); Spotify Soloist opens one per health check; home appliances are one HTTP request each time. The duck would be the first adapter "backed by a long-lived connection that the device itself initiates inbound". The closest approach is `HomeBridgePort` in `adapters/home.ts`: the adapter gets only an interface, the real object is created by the core and passed in through `AdapterDeps`, and tests pass a fake.
- Marking of mock: for an adapter with `mock: true`, tools have to be marked `catalog.hidden` (`catalog.ts:148`); `mock: "config"` (for example `voice_relay`) means it depends on configuration, and the adapter's `mock` is determined by the actual output end (`voice-relay.ts:95`). DuckAdapter uses `"config"`: whether the other end is a real duck or simulated depends on the `hello.mock` of the end that connects in.
- Tests: all in `tests/*.test.ts` (vitest 5.0.3, no config file); adapter tests are named `tests/integration-<name>.test.ts`; the LG TV test uses `ws`'s `WebSocketServer` to stand up a fake TV on an ephemeral port, noted as "fixture, not real-hardware verification".

### 2.3 HTTP and WebSocket

- `createApp` (`server/app.ts:278`) is a plain `node:http` server, bound only to `127.0.0.1` (`server/nous.ts:578`), default port 8787.
- **No inbound WebSocket**: `createApp` does not register `upgrade`; the `ws` package is used in the core only as a client (LG TV, OpenAI sideband).
- Guard (`server/http-guard.ts`): `Host` must be `localhost:<port>` or `127.0.0.1:<port>`; **GET checks only Host, not Origin**. There is no token mechanism for local clients.
- Core → page push is SSE (`GET /api/events`).

### 2.4 Terminals (`terminals/rpi4/`)

- A "terminal" is simply **a browser page with `?terminal=<id>`**. The core has no terminal registry, capability description or pairing; voice, wake word, state and the choice of output device are all inside the page.
- Connection: **the Pi initiates** SSH to the Mac, using a local forward (`terminals/rpi4/bin/aios-tunnel:12-25`, `-L 127.0.0.1:$AIOS_PORT:127.0.0.1:$AIOS_PORT`); the Mac has to have "Remote Login" turned on. The Pi's local port must equal the core's port, otherwise it does not pass the Host check.
- Heartbeat: the page does `POST /api/terminal/heartbeat` every 10 seconds; the core treats 25 seconds without one as offline (`server/terminal-presence.ts:21-75`). A code comment explains: after the Pi disappears, the SSH-forwarded TCP connection may still be open on the Mac end, so only the application-layer heartbeat is trusted (`shared/terminal.ts:4-5`).
- Terminal ID: `/^[a-z0-9][a-z0-9-]{0,31}$/`, cannot be `main`; `rpi4` is hard-coded in the kiosk script.
- The only example on the Pi of "a non-browser program reading core state" is `bin/aios-display`: it polls `GET /api/terminal/display` with `curl` every 2 seconds.

### 2.5 Realtime voice sessions

- Both paths are **the browser connecting directly to the cloud model over WebRTC**; the core only relays SDP, and sometimes also holds a WebSocket for control (sideband).
- The full state machine is only in the page: `RealtimePhase = "off" | "connecting" | "listening" | "hearing" | "thinking" | "speaking"` (`src/realtime.ts:32`), passed to the cyberbrain via `onPhase` (`src/main.ts:482`). **The page never reports phase back to the core.**
- What the core knows (on both paths): `POST /api/realtime/start` (with `source`: `user`／`look_to_talk`／`wake_word`, and `page`), connected, `alive` every 15 seconds, `POST /api/realtime/end` and the internal `finish(session, reason)`.
- The live path additionally gets from the sideband (`server/live-route.ts:469-551`): `session.started`, transcripts of the user and the assistant (partial and final), `delegation` (tool work start and end), `error`; whether the two events `speech.started` and `audio.done` are really sent on the live wire is stated in a code comment as **unconfirmed** (`shared/frameless.ts:14-17`).
- api_key path: the core attaches the sideband only when this conversation carries memory rules; otherwise, between connecting and ending, the core sees nothing.
- `RealtimeSessions` (`server/realtime-routes.ts:300`) **has no hook for observation** (`RealtimeSessionsOptions` `:135-169` has no field such as `onSessionChange`).
- Volume of the assistant's voice: the core has none at all. On the live path the page measures the RMS of the assistant's track (`src/live-voice.ts:860-883`, every 50 ms) and only compares it with the threshold `SPEAKING_RMS = 0.02`; the api_key path does not measure the assistant's track.

### 2.6 Audio output and wake

- The assistant's voice is played in **the page that owns this conversation** (`playRemote` at `src/main.ts:815-846`); the output device uses `setSinkId` (`src/audio-devices.ts:105-125`), and the preference is stored in the core's `audio.json`, **one global copy, not per terminal** (`server/app.ts:326`).
- The core never handles raw audio; **there is no path at all that sends the assistant's voice to a non-browser device**.
- The wake word runs in the page (sherpa-onnx 2.0.1 wasm, keywords "Hello Nous" and "Hey Nous"); each page detects with its own microphone. After waking, the page does `POST /api/realtime/start {source: "wake_word"}`, and the core limits this to 3 times per minute.
- `spike/wake/direction/` measures "the wake success rate at different angles", **not** direction-of-arrival estimation; AIOS has no DOA or beamforming code.
- Page capture keeps only channel 1 when the channel count is not 1, 2, 4 or 6 (`spike/wake/direction/logic.ts:31-35`).
- AIOS has no concept of a duck, robot or mobile terminal anywhere (search of the whole repo).

## 3. Batch D2: moving DuckAdapter into AIOS

Files to move (this repo → AIOS):

| This repo (`nous_duck/nous_adapter/`) | AIOS | Notes |
|---|---|---|
| `adapters/duck.ts`, `adapters/duck-exec.ts`, `adapters/duck-text.ts` | `server/integrations/adapters/duck.ts` (can be merged into one file, or put the latter two in `server/duck/`) | Change `import` to AIOS's `../contracts.ts`, `../../../shared/integrations.ts` |
| `shared/aios-contracts.ts` | **Delete** | It is only a minimal re-declaration of AIOS types |
| `shared/duck-link.ts`, `shared/capabilities.ts` | `shared/duck-link.ts` | Pure types and constants; putting them in `shared/` fits AIOS's layering |
| `DUCK_TEXT_EN`, `DUCK_REJECT_TEXT_EN` in `adapters/duck-text.ts` | `server/messages.en.json` | AIOS's English sentences use the original Chinese text as the key |
| `mock/mock-duck.ts` | `tests/fixtures/mock-duck.ts` | For tests only |
| `tests/duck-adapter.test.ts` | `tests/integration-duck.test.ts` | Named after `integration-lg-tv.test.ts` |

Places to change in existing AIOS files (per `docs/development/adding-an-adapter.md`):

1. `server/integrations/index.ts`: add `duck?: DuckLink` to `AdapterDeps`; add `duck: (_config, _log, deps) => (deps.duck ? new DuckAdapter(deps.duck) : null)` to `KNOWN_ADAPTERS` (not registered if the hub is not enabled).
2. `server/nous.ts:321`: pass the hub in the deps of `createIntegrations(...)` (the hub has to be created before this line, see §4).
3. `server/integrations/catalog.ts:24-35`: add `DUCK_CATALOG` to `ADAPTER_CATALOGS`.
4. `server/messages.en.json`: English for the service name "鴨子", each tool's `summary`, example utterances and `needs` (`checkCatalog()` checks this, `catalog.ts:130-133`).
5. `tests/fixtures/model-tools.ts:34-48`: add a DuckAdapter instance to `modelToolAdapters()`.
6. `tests/fixtures/model-tools.baseline.json`: regenerate (`npx tsx scripts/write-model-tools-baseline.ts --model-tools`) — the tools the model sees have changed.
7. `tests/fixtures/commands-page.baseline.json` and the commands table: regenerate (`--commands`, `npm run docs:commands`).
8. `tests/capability-catalog.test.ts:81`: the integration tool count is hard-coded as 32 and has to change (adding 17 makes 49; with phased enabling it is the actual number).
9. `.env.example:94-108`: describe `duck` in the AIL block.
10. (Recommendation) `realtimeToolRules()` at `server/realtime.ts:309-336`: add a `DUCK_RULE` section, modelled on `TV_RULE` (`:291`). Content: `confirmed` only means started; mission tools have to wait for events; on `unknown`, ask the user to take a look at the duck; do not retry capabilities the duck does not have.

Checks before delivery (§5 of the same checklist): `npm run catalog -- --check`, `npm run typecheck`, `npx vitest run tests/capability-catalog.test.ts tests/commands-from-catalog.test.ts`, and `node scripts/verify-aios.mjs` at the repo root.

Risks and recommendations:

| Risk | Description | Recommendation |
|---|---|---|
| 17 more tools at once | The tool tables of both voice paths get longer (tokens, the chance of the model picking the wrong tool); the live path can call only 2 tools per delegation | **Phased enabling**: in the first phase enable only `status`, `stop`, `look` and `gesture`, for which the duck has hardware now (plus `express` once it arrives); set the rest to `false` in `ToolDefinition.enabled` and enable them when the hardware arrives. This is a recommendation; the user has to decide |
| Rate limit of 30 per minute | `stop` counts too; ADR-0001 wants `stop` to be unlimited | `presence` does not go through the Dispatcher (it goes through DuckTerminal) and does not use quota. Whether `stop` is exempt requires changing `policy.ts` and is AIOS's decision; the duck side additionally has the lease and local safety and does not depend on this |
| `data` limit of 4 096 bytes | Anything over is dropped entirely | This repo's tests have confirmed that every tool's `data` is within the limit (see the validation record); it has to be measured again when fields are added later |
| `ToolResult.reason` is a fixed list | There are no codes for "the duck rejected" or "capability unsupported" | Currently `unavailable`／`invalid_arguments`／`timeout` are used, and the duck's reason goes in `data.duck_reason`. Whether to add new codes to `shared/integrations.ts` is for AIOS to decide |
| Dependency | Schema validation uses Ajv 8.20.0; the AIOS integration layer currently deliberately adds no dependencies (`schema.ts` file header) | Two options: AIOS adds `ajv` (pinned), or use Ajv's standalone mode to compile the schema into plain code at build time, with no runtime dependency. It is **not yet verified** that the standalone output works in AIOS's `tsx` environment |
| `architecture.test.ts` | `server/` may import only `server/` and `shared/` | When moving, put `shared/duck-link.ts` in `shared/` and the hub in `server/`; this does not violate it |

## 4. Batch D1: the `/duck-link` endpoint (duck-link hub into the core)

Files to move: `hub/duck-link-hub.ts` → `server/duck-link.ts`; `shared/validator.ts` → `server/duck-link-schema.ts`; the schema file copied into AIOS (for example `shared/duck-link.v0.schema.json`, with the source repo and commit noted in the file header — the canonical copy of the schema is in this repo's `protocol/schemas/`); `tests/hub.test.ts` → `tests/duck-link.test.ts`.

How to wire it (recommendation):

1. Split `DuckLinkHub` into two parts: "protocol logic" and "attach to an existing `http.Server`". This repo's hub opens its own `http.Server`; after moving into AIOS, change it to `attach(server: Server, hosts: Set<string>)`, with `server.on("upgrade", …)` inside.
2. `server/nous.ts`: **before** line 321 (`createIntegrations`), `const duckLink = config.duck.enabled ? new DuckLinkHub({ log }) : null`, passed into `AdapterDeps`; **after** line 519 (`createApp`), `duckLink?.attach(server, hosts)`.
3. `server/config.ts`: add `NOUS_DUCK=on` (off by default). `upgrade` is attached only when it is on; when `NOUS_AIL_SERVICES` contains `duck` but `NOUS_DUCK` is not on, the factory returns `null` (not registered).
4. Checks the `upgrade` handler has to do itself (the existing guard is not applied to upgrade):
   - The path is exactly `/duck-link`, otherwise 404.
   - `checkRequest("GET", req.headers, hosts)` (Host check, reusing `http-guard.ts`).
   - **Reject if there is an `Origin` header**. `checkRequest` does not check Origin for GET, and browsers do not apply CORS to WebSocket either; without this block, any web page open on the Mac or the Pi could connect in and impersonate the duck. This repo's hub already does this and has tests.
   - A message size limit (this repo uses 64 KiB).
   - Only one duck connection at a time; a new one replaces the old one after completing `hello`.
   - Use the application-layer heartbeat to judge whether the connection is still alive (this repo: close after 3 seconds without any message), not trusting TCP state — the same reason AIOS has for the terminal heartbeat (§2.4).
5. Tunnel: the duck side connects to `ws://127.0.0.1:8787/duck-link` (the local port has to equal the core port to pass the Host check). It can reuse rpi4's Pi-initiated `-L` (the Mac's "Remote Login" has to be on), or the Mac can initiate `ssh -R 127.0.0.1:8787:127.0.0.1:8787` (Remote Login need not be on). **The direction is for the user to decide**; it makes no difference to the duck-side program.

Risks:

| Risk | Description |
|---|---|
| The first inbound WebSocket | AIOS has no precedent, and the guard has to be written by hand; this repo's tests (path, Origin, Host, non-loopback) have to be moved along with it |
| No authentication of the duck's identity | Consistent with the current state of AIOS: the trust boundary is "loopback + SSH". Any program on the Pi that can connect to `127.0.0.1:<port>` can impersonate the duck. Whether to add a shared secret is a new mechanism; AIOS currently has nothing similar (rpi4 pairing is only a draft) |
| The tunnel forwards the whole core along with it | Forwarding the core's port with `-L`／`-R` lets programs on the Pi call all of the core's HTTP APIs (the rpi4 terminal is already like this). To expose only duck-link, the hub can stay on a separate port (the current 8791) — that is the variant "not moved into the core's HTTP server, only into the core process" |
| The core port can change | The Electron build switches ports when the port is taken (`fallbackPort`, `nous.ts:235`), and the duck side's port setting has to follow |

## 5. Batch D3: duck events into Nous (DuckTerminal's event entry point)

Fact: AIOS has no entry point for receiving device events; nor can a mechanism for the core to "proactively start a voice conversation" be confirmed (`server/proactive.ts` holds the settings and sentences of the morning briefing; whether the core can trigger speech was **not verified**).

This repo already has: `terminal/duck-terminal.ts` turns duck-link events into `TerminalEvent` (categories `safety`／`link`／`mission`／`motion`／`wake`／`dock`／`config`, marked `notify` or `info`, whether the source is the duck or the hub, and whether it is simulated) and hands them to `DuckEventSink`. After moving into AIOS a sink has to be implemented. Three steps are recommended, all of them **recommendations**:

1. Record only: write to the core's log, and make whether the duck is connected visible in the integration status (`GET /api/integrations/status`). Minimal, no risk.
2. Display: to the page via SSE (showing "the duck fell over" or "the duck has arrived" next to the cyberbrain). Needs a new kind of SSE event and page text.
3. Continue the conversation: when `mission_done`／`mission_failed` happens, if the conversation that issued the command is still going, let the model know the result and say it. On the live path the core has the sideband and may be able to do this; on the api_key path the conversation is in the page and has to be relayed through the page. **The feasibility of this step was not verified**; a spike has to be done in AIOS.

## 6. Batch D4: the real event source for `presence`

This repo already has: `PresenceDriver` in `terminal/presence.ts`, whose input is `VoiceSessionEvent` (shaped to match the AIOS signals in the table below) and whose output is throttled `presence` commands. The only source today is the **dev-only manual source** (`duckctl presence`).

Which real sources AIOS has for each `presence` state (facts, taken from §2.5):

| `presence` | Sources the core already has | Sources only the page has | Gap |
|---|---|---|---|
| `idle` | No session in progress; after `finish()` | phase `off` | The core has no "state changed" notification |
| `wake` | `RealtimeSessions.start(…, source = "wake_word")` (`realtime-routes.ts:378`) | Wake trigger → prompt tone → conversation starts | The core does not know until `/start`, which is already after the prompt tone |
| `listening` | Connected; live: `session.started`, end of an assistant turn | `listening`／`hearing` | On the api_key path the core sees nothing after connecting |
| `thinking` | live: end of a user turn, delegation start | `thinking` | api_key (without memory) has none |
| `speaking` | live: the assistant transcript is growing (based on text, not on sound) | `speaking` (api_key: `output_audio_buffer.started/stopped`; live: track RMS) | The accurate "started speaking／finished speaking" exists only in the page |
| `working` | Delegation start and end, a background task running, the Dispatcher executing a tool | `brain.working` | The core has it |
| `error` | `finish(session, "connect_failed")`, the reason for `closed` is `connection_lost`／`auth`／`usage_limit`／`error` | The cyberbrain's error | The core has it |
| `sleeping` | No corresponding voice concept (closest: day/night mode, the terminal's screen-off report, the Mac locked or asleep) | — | Has to be defined first |

Recommendation: do it in two steps:

- **D4a (core observation point; coarse, but present on both paths)**: add an `onSessionEvent?` callback to `RealtimeSessionsOptions` (`server/realtime-routes.ts:135-169`), fired in `start()` (with `source`), `call()` (connected), `finish()` (with `reason`) and on the live `LiveCoreEvent` (`delegation`, `closed`). `server/nous.ts` wires it to `PresenceDriver.handle()`. This gives `wake`, `listening` (everything after connecting counts as listening), `working`, `error` and `idle`. There are **no** boundaries for `thinking` and `speaking`.
- **D4b (page reports phase; accurate)**: add `POST /api/realtime/phase {session_id, owner, phase}`, called by the page in `onPhase` (`src/main.ts:482`); the core validates it with the existing `sessionAuth` (`app.ts:877-884`) and forwards it to `PresenceDriver`. This is the only way to get "speaking" on the api_key path (without memory). Report only while the duck is connected, to avoid sending extra requests the rest of the time.

`speech_level` (the volume while speaking) has two possible sources:

1. The page reports the RMS of the assistant's track at 5 Hz or less to the core → hub → the duck. The page and the core both have to change; the api_key path does not measure the assistant's track today and that has to be added.
2. **Compute it on the duck**: when the sound really plays from the duck's speaker (route A), the duck's audio layer itself measures the sound being played, without going through AIOS and with no network latency. **The recommendation is to adopt this one**, with `presence` sending only the state and not the volume. This is a recommendation; the duck-side implementation is in line D (`robot/audio/`).

Risk: every change of `presence` is one duck-link command; `PresenceDriver` already does debouncing (120 ms), minimum hold times for `wake`／`error`, and volume throttling (at most one message per 200 ms, and no message when the change is less than 0.1), and has tests. These values have all **not been tuned on real hardware**.

## 7. Batches D5–D7: audio to the duck, wake, directing to a terminal

Details and reasons are in [`voice-path.md`](voice-path.en.md). The requirements on AIOS are summarised below:

| Batch | Content | What AIOS has to change |
|---|---|---|
| D5 the duck as a page terminal (route A) | The duck's Pi 4 runs Chromium opening `/?terminal=<duck ID>`, and the sound comes out of the duck's speaker | At minimum **AIOS needs no change at all** (the terminal ID is just a URL parameter); a separate copy of the `terminals/rpi4/` package has to be made for the duck (no screen, different terminal ID). The output device preference is one global copy today, and the device IDs on the Pi and the Mac differ, so it may have to become per terminal |
| D6 the duck's own wake word and multi-device arbitration | The duck has its own wake word; when several devices hear it at once, respond only once | Wake keywords have to be configurable per terminal; the core adds arbitration (ADR-0003 §3). Today each page detects on its own and starts a conversation on its own |
| D7 directing a conversation to a specific terminal | Let Nous speak up proactively through the duck (for example "go wake him up") | Today: a conversation belongs to the page that started it, and the sound plays only in that page. A core → specific page "start a conversation" push has to be added. **Feasibility not verified** |

## 8. AIOS batch list and recommended order

| Order | Batch | Content | What is gained when done | Main risks |
|---|---|---|---|---|
| 1 | D1 | `/duck-link` endpoint and hub into the core (`NOUS_DUCK`) | The duck can connect to the Nous core | The first inbound WebSocket, the guard, the tunnel direction |
| 2 | D2 | Register the `duck` adapter (enable the tools that have hardware first) | Use voice to tell the duck to turn its head, nod, stop, and report status | Longer tool tables, baseline files, dependency |
| 3 | D4a | The core's session observation point → `presence` (coarse) | The duck reacts when a Nous conversation starts, ends, and when tools run | `RealtimeSessions` has to be touched |
| 4 | D3 | Duck events into the core (record and display first) | Falls, disconnects and mission results are visible | The feasibility of "continue the conversation" is not verified |
| 5 | D4b | Page reports phase → `presence` (accurate) | The duck does motions following "listening, thinking, speaking" | Both the page and the core have to change |
| 6 | D5 | The duck as a page terminal (a microphone is needed first) | Nous's voice comes out of the duck, and people speak to the duck | Load on the Pi 4, running Chromium without a screen, echo cancellation — all need a spike |
| 7 | D6, D7 | Wake word and arbitration, directing to a terminal | Calling the duck by name, Nous speaking up proactively through the duck | Both are new mechanisms |

Orders 1–3 need no new hardware and can be verified with the current head servos. Every batch has to have its own tests and validation record in AIOS; the corresponding code and tests on this repo's side already exist (see [`../README.md`](../README.en.md)), but "usable inside AIOS" only counts once that side is done.

## 9. Things not yet verified

- Whether the Ajv standalone output works in AIOS's environment.
- Whether the live path's sideband really sends `speech.started` and `audio.done` (AIOS itself also marks this as unconfirmed).
- Whether the core can proactively make a given page start a conversation; whether duck events can be inserted into a conversation in progress.
- How an adapter with `mock: "config"` behaves in `checkCatalog()` and on the commands page (`voice_relay` is the precedent, but the duck's catalog has not actually been run).
- Whether the Nous page can start a conversation without a microphone (presumably not; not verified).
