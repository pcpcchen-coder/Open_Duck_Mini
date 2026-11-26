> [繁體中文](d-duck-voice-media-channel.md) | [English](d-duck-voice-media-channel.en.md)

# Protocol proposal (line D): duck-voice v0 — the voice media channel between the duck and Nous

- Proposed by: line D (duck-side audio), 2026-11-26. **The duck-link schema is not changed.**
- Status: **not adopted (experimental)**. On 2026-11-26 the user decided that voice conversation takes "route 2": Chromium on the duck's Pi opens the Nous page and does the capture and playback, so nothing goes through this channel. This interface and both implementations (duck side `voice_service.py --mode native`, line B's hub in `nous_adapter`) were run against each other and are kept as an experiment record; **this is not a capability the duck has**. For route 2's wake event and microphone sharing see [`docs/validation/voice-duck-side-2026-11-26.md`](../../docs/validation/voice-duck-side-2026-11-26.md) (Traditional Chinese).
- Duck-side implementation: [`robot/audio/duck_audio/voice_service.py`](../../robot/audio/duck_audio/voice_service.py), [`session.py`](../../robot/audio/duck_audio/session.py); simulated Nous end (mock, for tests): [`mock_nous.py`](../../robot/audio/duck_audio/mock_nous.py).
- Related: [ADR-0010](../../docs/adr/ADR-0010-duck-voice.md) (voice chain), [ADR-0003](../../docs/adr/ADR-0003-mobile-terminal-wake-and-find.md) §6 (red lines), [voice path](../../nous_adapter/docs/voice-path.en.md).

## 1. Why it is needed

AIOS realtime voice is "the browser page talks WebRTC straight to the cloud model"; the core never touches audio (voice-path §1). When the duck captures and plays with a native program (route B in ADR-0003), the Nous side needs an endpoint that can receive and send PCM. This document defines how that endpoint and the duck talk. The control plane (`wake_word` event, `presence`) stays on duck-link; this channel only carries audio and the opening and closing of a turn.

## 2. Transport

- The duck is the WebSocket **client** and connects to `ws://127.0.0.1:<port>/duck-voice` (default port 8791, the same SSH tunnel as duck-link). The duck side **accepts only loopback `ws://` URLs** and refuses anything else.
- Text frames are JSON control messages; binary frames are PCM.
- Uplink (duck → Nous): 16000 Hz, s16le, mono, 20 ms per frame (320 samples, 640 bytes). The source is the XVF3800 processed channel (echo cancellation, beamforming, noise suppression, automatic gain).
- Downlink (Nous → duck): 24000 Hz, s16le, mono, frames of any length (20–100 ms suggested). It is Nous's **original voice**; voice changing, the volume cap and limiting all happen on the duck.
- A disconnect on either side ends the turn: the duck stops capturing, drops audio not yet played and goes back to listening for the wake word only. The duck reconnects automatically (starting at 1 s, at most 15 s).

## 3. Messages

Duck → Nous:

| type | fields | when |
|---|---|---|
| `hello` | `v:0`, `uplink:{rate,format,channels,frame_ms}`, `downlink:{rate,format,channels}` | first message after connecting |
| `turn_start` | `turn_id` (integer, increasing), `trigger:"wake_word"\|"follow_up"`, `keyword_id` (for example `"HEY_YAZI"`; manual testing uses `"MANUAL"`), `doa_deg` (always `null` in v0) | a turn begins; uplink PCM only follows this |
| `turn_end` | `turn_id`, `reason:"remote"\|"silence"\|"no_speech"\|"max_duration"\|"cancelled"` | the uplink is closed; no more PCM for this turn |
| `playback` | `turn_id`, `state:"started"\|"finished"\|"flushed"\|"refused"`, `reason` (only with `refused`) | the speaker **actually** started, finished, was flushed, or the local gate refused |

Nous → duck:

| type | fields | what the duck does |
|---|---|---|
| `hello_ack` | `v`, (the mock adds `mock:true`) | not checked at present |
| `listen_stop` | `turn_id` | Nous decided the person finished: close the uplink, send `turn_end{reason:"remote"}`, wait for the reply |
| `speak_start` | `turn_id` | start playing this turn's reply; if still capturing, close the uplink first |
| (binary) | PCM | accepted only after `speak_start` and before `speak_end` / `flush`; dropped otherwise |
| `speak_end` | `turn_id` | no more audio; `playback{finished}` follows when playback really ends |
| `flush` | — | stop at once and drop audio not yet played (for interruption); replies `playback{flushed}` |
| `listen` | — | listen for one more turn without the wake word (continued conversation). **Accepted only right after a reply finished playing or while waiting for a reply**; ignored while idle |
| `session_end` | — | end the turn and return to idle |

Messages with a mismatched `turn_id`, an unknown `type`, or arriving at the wrong time are ignored by the duck.

## 4. Who opens and who closes

- **Open**: only the duck can open the uplink — its local wake word, or a `listen` from Nous right after a reply. Nous cannot remotely open the microphone while the duck is idle.
- **Audio before the wake word is not sent**: the uplink starts after the wake word is detected, with no pre-roll (ADR-0003 §6). So the first utterance Nous receives does not contain the wake word.
- **Close**: normally Nous sends `listen_stop` (it has the model's voice activity detection). The duck also has local safeguards, all exposed as settings: 8 s with no speech after waking (`no_speech`), 1.5 s of quiet after speech (`silence`), 30 s maximum per turn (`max_duration`), 15 s waiting for a reply.
- **Cue sound**: after waking, the duck plays its local `listen_on` first and starts the uplink only when it has finished.
- **Interruption**: v0 is half duplex — while the duck plays a reply it sends no uplink and does not listen for the wake word (the setting `audio.barge_in` enables "interrupt with the wake word during playback"; it is off by default and has not been verified with a human voice). To stop playback, Nous sends `flush`.
- **When Nous is not connected**: waking does not open the uplink; the duck only plays a cue sound.

## 5. What line B needs to confirm or decide

1. Who implements this endpoint on the Nous side (a bridge process in `nous_adapter`, or the AIOS core), and how it reaches the realtime voice model.
2. Whether the downlink can be 24 kHz s16le mono; whether a 16 kHz uplink is enough (if the model wants 24 kHz, which side resamples).
3. Whether Nous can send `listen_stop`; if not, the duck's own `silence` decision is used.
4. Whether continued conversation (`listen`) is used in v0.
5. Wake events: besides `turn_start` here, should the duck also send a `wake_word` event over duck-link (the duck-side voice service does not connect to duck-link at present; that connection lives in duckd). Suggestion: the Nous side treats `turn_start` as the wake event and does not duplicate it.
6. Port: share 8791 with duck-link (different path) or use another.

## 6. Later

- `doa_deg` (sound direction at wake time): the duck-doa service already reads the XVF3800; two programs reading the USB control interface at once make each other retry, so v0 leaves it out.
- Full duplex and natural interruption: to be decided after echo cancellation has been measured with a human voice.
- Moving this channel into the formal duck-link schema (if both sides think it should be).
