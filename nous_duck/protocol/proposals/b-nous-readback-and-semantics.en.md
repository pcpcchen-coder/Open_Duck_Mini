> [繁體中文](b-nous-readback-and-semantics.md) | [English](b-nous-readback-and-semantics.en.md)

# Protocol proposal (line B): read-back fields and a few semantics that need to be spelled out

Status: **proposal**; the schema has not been changed. Date: 2026-11-25. Proposed by: line B (the Nous side, `nous_adapter/`).

Source: gaps hit while implementing DuckAdapter, plus the differences seen on 2026-11-25 when running end-to-end with this repo's hub + DuckAdapter (TypeScript) against line A's `duckd` (Python, mock body) (record in [`docs/validation/nous-adapter-2026-11-25.md`](../../docs/validation/nous-adapter-2026-11-25.md)). The two implementations interoperate under the v0 schema without problems (0 invalid messages in either direction); what follows are the places the schema does not specify and each side interprets on its own.

Every item states "how it is worked around today", so this proposal does not block anyone; the integration line decides whether to take it into v0 or the next version.

## 1. state lacks fields that can be read back

The rule on the Nous side is "only ack accepted plus a matching state read-back counts as `confirmed`". The following commands have no corresponding field in the v0 state:

| Command | What is missing | How it is worked around today | Suggested field to add (state) |
|---|---|---|---|
| `look` | `state.head` is the actual joint angles; there is no **target**. Right after acceptance the head has not arrived yet, so "still turning" cannot be told apart from "did not move" | Wait until the actual angle is within ±0.06 rad of the target and count that as reached; on timeout, if it is closer to the target than before sending, count it as "started" | `head_target`: `{neck_pitch, head_pitch, head_yaw, head_roll}` (the target after clamping) |
| `gesture` | There is no "which gesture is being performed" | Seeing `gesture_done` (with `request_id`), or a state after the ack whose `control_source` is `duck_link`, counts as started — the latter is very weak evidence | `activity`: `{kind: "gesture" | "walk" | "look" | "idle", name?, request_id?}` |
| `antennas` | There is no antenna field at all | Even when accepted, only `unconfirmed` is returned | `antennas`: `{left, right, pattern?}` |
| `sound` | There is no "playing / finished playing" | Even when accepted, only `unconfirmed` is returned (the Nous side currently does not give `sound` to the model) | Event `sound_done` (with `request_id`), or merge into `activity` |
| `wait_here` | Relies on `mode: "waiting"`, which exists | — | — |

## 2. `gesture_done` does not mean it finished

During end-to-end, `gesture_done` was seen with `reason: "stop"` (the gesture was interrupted by the next command). The schema only says events may carry `reason`; it does not say which values `reason` can take for `gesture_done` and `walk_done`.

- How it is worked around today: the Nous side treats `gesture_done` only as evidence that "this gesture did start", not as "finished".
- Recommendation: list the `reason` enum for these two events in the schema's description (for example `completed`, `stop`, `preempted`, `lease_lost`, `fault`), and specify that on normal completion `reason` is omitted or is `completed`.

## 3. What read commands return when there is "no data"

`mission_status` when there is no mission: `duckd` returns `rejected` + `no_mission`; this repo's TypeScript mock duck returns `accepted` + `data.mission = null`. Both conform to the schema.

- How it is worked around today: DuckAdapter treats both as "read: no mission" (`confirmed`). Only when a `mission_id` was given and the duck returns `no_mission` is it `refused`.
- Recommendation: specify that read commands (`status`, `where`, `places`, `mission_status`) return `accepted` whenever the capability exists, and express "none" through `data`; keep `rejected` for cases that truly cannot be answered (`unsupported`, `not_localized`…).
- In addition, v0 does not define the shape of `ack.data` for these four commands. Recommendation: define at least: `where` → `{place, localized, uncertainty_m, on_dock}` (same as `state.location`); `places` → `{places: [{id, kind}], map_version}`; `mission_status` → `{mission: <same as state.mission> | null}`.

## 4. For which commands `ttl_ms` has a "stop on expiry" effect

The schema says "motion commands stop when it expires without renewal". Which commands count as motion commands is not listed.

- What the Nous side does today: `ttl_ms` for `walk` is set to `duration_s` + 0.5 s, and for `look` to `duration_s` + 1 s (so that the motion is not cut short by the ttl); mission commands (`go_to` etc.) use 5 s, and `track`／`presence`／`express` use 2–3 s, on the assumption that they **do not** stop because the ttl expires.
- Recommendation: state explicitly in the schema's description: only `walk` (and `look`?) stops when the ttl expires; for missions, `track`, `presence`, `express` and `antennas`, the ttl only means "drop it if processing starts too late". The lifetime of missions and `track` is determined by the connection lease and their own timeout parameters.

## 5. "Accepted at any time" for `wait_here` and `stop`

ADR-0001 §7.3 says `wait_here` is "accepted at any time". During end-to-end, `duckd` (the head-only mock) returned `rejected: unsupported` for `wait_here`.

- This is not a duckd error: v0 does not specify which commands are exempt from capability limits, and `capabilities` has no key corresponding to `wait_here`.
- How it is worked around today: for `stop`, `wait_here`, `cancel_mission`, `mission_status` and `status`, the Nous side does not do the "do not send if the capability is unsupported" pre-check; it always sends and lets the duck decide; if the duck rejects, it truthfully returns `refused`.
- Recommendation: specify that `stop` is always `accepted` (even when already stopped); for `wait_here` on a duck that cannot walk, either `accepted` (it is already staying in place, `mode` becomes `waiting`), or state explicitly that `unsupported` may be returned. Pick one of the two and write it into the description.

## 6. The command → capability mapping table

Before sending, the Nous side looks at `capabilities`: if a required capability is `unsupported`, it does not send and reports that directly. This mapping table currently exists only in the Nous-side code (`nous_adapter/shared/capabilities.ts`), and the duck side has its own copy; when the two copies disagree, the result is "Nous did not send" or "sent and rejected" — both safe, but with different messages.

| Command | Capabilities the Nous side currently considers required |
|---|---|
| `walk` | `walk` |
| `look`, `gesture` | `head` |
| `antennas` | `antennas` |
| `express` | `eyes` |
| `sound` | `speaker` |
| `track face` ／ `track sound` | `head` + `tracking_face` ／ `head` + `tracking_sound` |
| `where`, `places` | `navigation` |
| `go_to` | `navigation`, `walk` |
| `find_person` | `navigation`, `walk`, `camera` |
| `return_home` | `navigation`, `walk`, `dock` |
| `follow_me` | `walk`, `camera` |

Recommendation: put this table into `protocol/` (the README or a small JSON) and have both ends read it from there.

## 7. Connection setup order and replacement rules

The schema only says hello is "the first message from each side after the WebSocket opens". What this repo's hub does (`duckd` interoperates with it without problems):

- The hub sends its own hello immediately when the connection is established, without waiting for the duck.
- The duck's first message must be a valid `hello` (`role: "duck"`), otherwise the connection is closed (code 4003); it is also closed if there is no hello within 3 seconds.
- The hub starts sending heartbeat only after receiving the duck's hello.
- `protocol_version` is not `"0.1"` → close (code 4002), with no attempt at compatibility.
- Only one duck connection at a time; a new connection replaces the old one after completing hello (the old one is closed with code 4001).
- The hub has received no message of any kind from the duck for more than 3 seconds → close (code 4000).

Recommendation: write the order, timeouts and close codes into `protocol/README`.

## 8. Who issues `resume`

`resume` is in the v0 command list, and ADR-0009 §2.5 says "before the first walk, an explicit resume from the local side or from Nous is required". The Nous side currently has **not** made it a model tool (once the pause is lifted, `walk` will be accepted, which is more like something done only when "a person is present"); it is kept only in the dev CLI (`duckctl resume`).

Whether to give the model `app.duck.resume` is the user's decision, not a protocol question; it is recorded here because it affects "whether Nous can make the duck start walking by itself".

## 9. Reason codes for `mission_failed`

`event.reason` is a free-form name (`^[a-z0-9_]{1,48}$`), with no enum. To tell the user why something failed, Nous needs a fixed list so that it can map to fixed sentences (the AIOS convention is fixed reason codes and fixed text).

Recommendation: enumerate the mission failure reasons (for example `door_closed`, `blocked`, `lost`, `cancelled`, `stopped`, `fell`, `link_lost`, `low_battery`, `timeout`, `person_not_found`, `dock_not_found`, `no_charge`), with line C (navigation) confirming which ones will actually be used.
