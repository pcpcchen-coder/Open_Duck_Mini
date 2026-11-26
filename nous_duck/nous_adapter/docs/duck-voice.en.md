> [繁體中文](duck-voice.md) | [English](duck-voice.en.md)

# duck-voice: the voice media channel (Nous side)

Status (2026-11-26): **the Nous side of the channel is built and tested; real conversation does not work yet.** There is only an "echo" (replay) backend here, marked mock (it plays back the sound it heard; it is not a speech model). Connecting it to Nous's realtime voice requires changing AIOS, and is waiting for the user's decision on which route to take (§7).

Verification level: unit/integration tests (against a simulated duck audio end, with synthetic audio), plus one local interoperability check of "line D's real duck-side state machine `session.py` against this hub" (synthetic audio, no microphone and no speaker). **No real person's voice has gone through this channel, and there has been no real hardware.**

- The authoritative source for the wire format is the duck-side (line D) implementation: `robot/audio/duck_audio/session.py` (the state machine) and `voice_service.py` (the service). Line D's interface draft file `protocol/proposals/d-duck-voice-media-channel.md` had not yet entered the repo when this document was written; where the two differ, the duck-side code prevails.
- This document explains how the Nous side (`nous_adapter/`) implements it, and the rules the Nous side adds on its own.
- Related: [ADR-0010](../../docs/adr/ADR-0010-duck-voice.md) (the voice chain), [ADR-0003 §6](../../docs/adr/ADR-0003-mobile-terminal-wake-and-find.md) (the privacy red lines), [`voice-path.md`](voice-path.en.md) (route comparison).

## 1. Why a separate channel

`/duck-link` is the JSON control plane (commands, state, events); voice and video do not go over it ([`protocol/README`](../../protocol/README.en.md)). Voice needs binary, low latency, and capture and playback are the responsibility of the duck's audio process (line D), not duckd (line A). So:

| | `/duck-link` | `/duck-voice` |
|---|---|---|
| Content | Commands, ack, state, event | Voice PCM and turn control |
| Process on the duck side | duckd (the body) | The audio service (microphone, wake word, speaker) |
| Nous side | `hub/duck-link-hub.ts` | `hub/duck-voice-hub.ts` |
| Port and gatekeeping | The same port (8791 in development), the same SSH tunnel, the same gatekeeping: bound to loopback only, `Host` check, anything carrying `Origin` is rejected | Same as left |

The two channels do not depend on each other: with the audio service not running, the body can still be used; and the other way round as well.

## 2. Wire format (the duck side prevails)

Turn-based, half-duplex. One "turn" = the duck listens for a stretch, Nous replies with a stretch.

- Text frames = JSON control messages. Binary frames = PCM, **with no header**.
- Uplink (duck → Nous): s16le, mono, 16 kHz, 20 ms per frame (640 bytes). Sent only during the stretch in which the duck is "listening".
- Downlink (Nous → duck): s16le, mono, 24 kHz. On the Nous side each frame is at most 100 ms (4 800 bytes).

Duck → Nous:

| Message | Fields | Meaning |
|---|---|---|
| `hello` | `v: 0`, `uplink`, `downlink` (may additionally carry `software`, `mock`) | The first message after connecting |
| `turn_start` | `turn_id`, `trigger` (`wake_word` / `follow_up`), `keyword_id`, `doa_deg` | Start listening for a turn; uplink audio follows. `wake_word` = the wake word was detected locally; `follow_up` = follow-up listening as told by Nous's `listen` |
| `turn_end` | `turn_id`, `reason` (`remote` / `silence` / `max_duration` / `no_speech` / `cancelled`) | Stop the uplink |
| `playback` | `turn_id`, `state` (`started` / `finished` / `flushed` / `refused`), `reason` | Sound has really started coming out / playback finished / it was flushed / the local gate does not allow playback |

Nous → duck:

| Message | Fields | Meaning |
|---|---|---|
| `hello_ack` | `v: 0` (the Nous side additionally carries `software`, and carries `mock: true` when the backend is simulated) | Response to `hello` |
| `listen_stop` | `turn_id` | The user has finished speaking (the backend's judgment); please stop the uplink |
| `speak_start` | `turn_id` | The reply begins; downlink PCM follows |
| `speak_end` | `turn_id` | The PCM of this stretch of reply has all been sent |
| `flush` | — | Empty the playback queue immediately |
| `listen` | — | Please listen for another turn without the wake word (follow-up listening) |
| `session_end` | `reason` (added by the Nous side, see §4) | This conversation is over; go back to standby |

## 3. How one conversation goes

```text
The duck (audio service)                 Nous (duck-voice hub)               Voice backend
  wake word detected locally
  turn_start{1, wake_word} ───────────►  no conversation → open one ───────► start()
  uplink PCM… ────────────────────────►  (backend still opening: held in memory, ≤2 s)
                                         opened → send the held audio ─────► pushAudio…
  uplink PCM… ────────────────────────► ───────────────────────────────────► pushAudio…
                                         ◄── backend: the user has finished speaking
  ◄─────────────── listen_stop{1}
  turn_end{1, remote} ────────────────►
                                         ◄── backend: the reply's audio
  ◄─────────────── speak_start{1}
  ◄─────────────── downlink PCM…
  playback{1, started} ───────────────►  presence → speaking
  ◄─────────────── speak_end{1}
  playback{1, finished} ──────────────►  presence → listening
  ◄─────────────── listen
  turn_start{2, follow_up} ───────────►  (the next turn of the same conversation)
  …nobody speaks for a long while…
  turn_end{2, no_speech} ─────────────►  end: close the backend
  ◄─────────────── session_end{done}     presence → idle
```

## 4. Rules on the Nous side

| Rule | How it is done |
|---|---|
| Who decides to open the microphone | **The duck, locally.** Nous opens a conversation with the backend only when it receives `turn_start(wake_word)`; it sends `listen` only after the reply has finished playing (`playback finished`). Sending `listen` during standby has no effect — the duck-side state machine does not accept it |
| Uplink audio received while not listening | Dropped and counted; 20 consecutive frames close the connection (it means something is wrong with the duck-side gate) |
| While the backend is still opening | Uplink audio is held in memory, for at most 2 seconds; once it is open the audio is handed to the backend, and if it cannot be opened the audio is thrown away |
| No backend, the backend cannot be opened, too frequent | Replies with `session_end`, with `reason` being `no_backend` / `rate_limited`. Conversations started by a wake are limited to 3 per 60 seconds (the same as AIOS) |
| `session_end.reason` | A field added by the Nous side (the duck side currently ignores it): `done`, `no_backend`, `busy`, `rate_limited`, `error`, `max_duration`, `backend_lost`. Later the duck can play different cue sounds depending on the reason |
| Who judges that the user has finished speaking | Either side can: the backend judges first → Nous sends `listen_stop`; the duck judges first → it sends `turn_end(silence / max_duration)`, and Nous passes that on to the backend |
| The duck sends `turn_end(no_speech / cancelled)` | This conversation is over: close the backend, reply with `session_end` |
| The duck sends `playback refused` | The local gate does not allow playback (quiet hours, privacy switch): the conversation ends, and it does not count as an error |
| Interruption (barge-in) | The first version relies on the duck locally: the wake word is heard again while speaking → the duck replies `playback flushed` and starts a new turn, and Nous tells the backend to stop the previous stretch of reply. The duck does not send uplink while it is speaking, so there is no "model-side barge-in detection" |
| Timeouts | No uplink frame received for 2 seconds while listening → end (`error`); the conversation is open but not listening, not speaking, and with no reply on the way for more than 20 seconds → end; the limit for a single conversation is 5 minutes. "Nobody speaks for a long while" is judged by the duck side |
| Whether the connection is alive | WebSocket protocol-level ping, every 2 seconds; with no response at all for 6 seconds the connection is closed |
| Version | `hello.v` is not 0 → the connection is closed, with no attempt at compatibility |
| Only one audio end at a time | A new connection replaces the old one as soon as it completes `hello` |

### Privacy

- Audio only passes through memory. `hub/duck-voice-hub.ts`, `shared/duck-voice.ts` and the echo (replay) backend contain no file-system code at all (a test checks the source code).
- Logs and events contain only counts and times: number of turns, number of frames, number of bytes, duration, end reason. No audio, no text content.
- Audio from before the wake does not leave the duck: that is the duck side's responsibility (line D); the Nous side's counterpart is "frames received while not listening are always dropped".

## 5. Relationship with the control plane

| What happens on the voice channel | The result on the control plane (`/duck-link`) |
|---|---|
| `turn_start(wake_word)`, the conversation is opened | `presence: wake` (at least 600 ms) → `listening` |
| The backend reports that it hears someone speaking | `presence: listening` |
| The user has finished speaking and playback has not started yet | `presence: thinking` |
| `playback started` | `presence: speaking` — **it only counts when sound really comes out** |
| `playback finished` / `flushed` | `presence: listening` |
| The conversation ends | `presence: idle`; when it ends because of an error, `error` first for about 1.5 seconds |

- `presence` is, as before, sent by Nous to duckd over `/duck-link`, and duckd decides how the head and eyes act it out. `speaking` now has a real source.
- Moving along with the volume while speaking: **does not go over the network**. The duck itself measures the sound it is playing (line D already has a volume envelope); `presence` carries only the state, not `speech_level`.
- The direction of the wake (`doa_deg`) is put unchanged into the data of the terminal event `wake_word`; whether to turn toward the sound source is the duck's local business (line A's `track sound`).
- `duckctl events` shows `wake_word` (including whether a conversation was opened this time) and `voice_session_ended` (counts only).

## 6. The voice backend interface

The hub does not know who the backend is. The interface is in `hub/duck-voice-hub.ts`:

```ts
interface VoiceBackend {
  readonly label: string;
  readonly mock: boolean;
  start(info: { sessionId: string; keywordId?: string }, sink: VoiceBackendSink): Promise<VoiceBackendCall>;
}
interface VoiceBackendCall {
  pushAudio(pcm: Buffer): void;        // uplink: s16le / 16 kHz / mono
  endTurn?(): void;                    // the duck judged that the user has finished speaking
  cancelReply?(): void;                // the reply was interrupted
  playback?(state: PlaybackState): void;
  close(reason: string): void | Promise<void>;
}
interface VoiceBackendSink {
  phase(phase: "listening" | "hearing" | "thinking"): void;   // thinking = the user has finished speaking
  audio(pcm: Buffer): void;            // reply: s16le / 24 kHz / mono
  audioEnd(): void;
  interrupt(): void;                   // ask the duck to flush playback
  end(reason: SessionEndReason): void;
}
```

The backends in this repo:

| Backend | What it is | Purpose |
|---|---|---|
| None (default) | Every wake gets `session_end: no_backend` in reply | The honest default: there is no speech model here |
| `echo` (`mock/echo-voice-backend.ts`) | **Simulated**: plays the sound it heard back unchanged after you stop speaking. It does not recognize, does not understand, and does not generate | Lets the two ends first get the channel, start and end, playback reports and follow-up listening working end to end |

## 7. What is still missing before it is a real conversation

The real backend has to connect to Nous's realtime voice, and that requires changing AIOS. The current state of AIOS (consulted read-only at main `265cbee`): in both realtime voice paths the audio is WebRTC between "the browser page ↔ the cloud model"; the core never handles the audio, and there is no mechanism at all for a non-browser device to act as a voice terminal. The two feasible routes:

| | Route 1: a duck voice session on the core side | Route 2: Chromium running on the duck's Pi with the Nous page open |
|---|---|---|
| Approach | The AIOS core connects to the realtime voice model over WebSocket and implements the `VoiceBackend` above; this `/duck-voice` channel is moved into the core as it is | Capture and playback of the conversation are done by the browser on the Pi; AIOS gets a small change so that the duck's wake can tell the page to start a conversation |
| Is this channel used | Yes (all of it) | No (the conversation audio goes through the browser) |
| Line D's native capture, voice changing and gates | All of them are used | The conversation audio does not pass through them |
| AIOS changes | Estimated 500–800 lines including tests, flag off by default | About 100–150 lines plus tests |
| Limitations | Only the path that uses an OpenAI API key and is billed by usage can be used; the first version has no household memory, family greetings, page tools or confirmation cards | The load of the Pi 4 running Chromium at the same time, obtaining the microphone without a screen, and echo cancellation are all not verified |
| Verification status | No actual measurement of any kind; there is no existing code in AIOS for the model's WebSocket mode | No actual measurement of any kind (the last spike only measured the case without a microphone) |

**Which one to take is for the user to decide** (whether there is an OpenAI API key that can be given to the duck, and whether usage-based billing is acceptable). Until the decision and authorization are obtained, there are no changes of any kind to AIOS.

## 8. How to try it (no duck needed, no sound)

```bash
cd nous_duck/nous_adapter
bin/duckctl hub --voice echo        # Tab 1: hub, voice channel connected to the simulated echo (replay) backend
bin/duckctl mock-voice              # Tab 2: the simulated duck audio end sends one "wake" and a synthetic tone
bin/duckctl voice                   # show the channel's status and the statistics of the last conversation
bin/duckctl events                  # wake_word, voice_session_ended
```

`mock-voice` prints the order of the control messages received (`hello_ack → listen_stop → speak_start → speak_end → listen`), the number of downlink frames, and the playback reports. Everything is marked simulated.

For the steps to connect the real duck audio end (line D's `voice_service`), see [`voice-test.md`](voice-test.en.md).

## 9. Things that are not verified

- A real person's voice, a real microphone and speaker, and whether the XVF3800's echo cancellation is good enough for modes other than half-duplex to hold up.
- Latency and jitter when going over Wi-Fi and the SSH tunnel (24 kHz PCM is about 48 kB/s downlink, 16 kHz about 32 kB/s uplink).
- Any real speech model. Whether the timing of turn switching (who judges first that speaking has finished) goes smoothly in a real conversation.
- Long-lived connections, restarts of the audio end, and the load of running at the same time as duckd.
