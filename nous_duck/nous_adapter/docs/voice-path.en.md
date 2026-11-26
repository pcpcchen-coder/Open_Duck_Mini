> [繁體中文](voice-path.md) | [English](voice-path.en.md)

# Voice path: how Nous's voice reaches the duck, and how the duck listens

Status: **on 2026-11-26 the user decided to take route 2 (Chromium on the duck's Pi opens the Nous page); see §8.** The Nous-side changes are in an AIOS PR ([pcpcchen-coder/AIOS#158](https://github.com/pcpcchen-coder/AIOS/pull/158), flag off by default, not merged); **nobody at all has run it with a real microphone, speaker and voice model yet.** Date: 2026-11-25; updated twice on 2026-11-26 (§7, §8). §2–§5 are the comparison made before the decision, kept as a record.

This document lines up the current state of AIOS (facts) against the duck's current hardware and answers four questions: the shortest workable conversation path today, how it changes once the microphone array arrives, what AIOS has to change, and what can be done on the duck side.

- **Fact**: found by read-only inspection of the code at AIOS commit `c85307861f7562803fb3776407493da49cdc8a83`, with `file:line` (relative to `prototype/ambient-shell/`). The full list is in [`aios-integration-plan.md` §2](aios-integration-plan.en.md#2-facts-found-the-parts-that-affect-the-design).
- **Recommendation**: this document's judgement, always marked "recommendation".
- **Unverified**: things that have not actually been run or measured, always marked "unverified". Nothing in this document has been through a listening test — the night-time rules do not allow the speaker to make sound.

Related decisions: [ADR-0003](../../docs/adr/ADR-0003-mobile-terminal-wake-and-find.md) (route A／B), [ADR-0010](../../docs/adr/ADR-0010-duck-voice.md) (voice chain, voice changing, local sound effects).

## 1. The five facts that determine the design

| # | Fact | Source |
|---|---|---|
| 1 | Both realtime voice paths are **a browser page connecting directly to the cloud model over WebRTC**: the microphone is acquired in the page, and the assistant's voice is the remote audio track the page receives. The core only relays SDP, and sometimes also holds a WebSocket for control | `src/realtime.ts`, `src/live-voice.ts`, `server/realtime.ts:558`, `server/live-route.ts:31` |
| 2 | The assistant's voice is played **only in the page that started this conversation** (`new Audio()` + `srcObject`) | `src/main.ts:815-846` |
| 3 | The core **never handles raw audio**, and there is no path at all that sends the assistant's voice to a non-browser device (no PCM／RTP forwarding, no saving TTS to file) | Search of all of `server/`; the only exception is voice-relay calling `say` on the Mac |
| 4 | The output device is chosen with the browser's `setSinkId`; the preference is **one global copy**, not per terminal | `src/audio-devices.ts:105-125`, `server/app.ts:326` |
| 5 | The wake word runs inside the page (sherpa-onnx wasm), each page using its own microphone; the keywords are "Hello Nous" and "Hey Nous" | `shared/wake-runtime.json`, `src/audio/` |

One additional point: ADR-0010 §1 says "realtime voice is the Mac core connecting to the cloud realtime voice model". Per fact 1, what connects to the cloud model is the **page**, and the core does not handle audio. This does not affect ADR-0010's decision (voice changing goes in the Pi's system audio layer); rather, it is the reason for it: the sound only appears on the machine that plays it, so the only place to change the sound is there.

The direct consequence: **to make Nous's voice come out of the duck's speaker without adding an audio pipeline to AIOS, the only approach is to run "the page that owns this conversation" on the duck's Pi 4** — that is, route A of ADR-0003. Route B (a native terminal program) needs the AIOS core to add an entire audio send/receive stack, of which not a single line exists today.

## 2. Now (the duck has only a USB speaker, no microphone)

The duck cannot hear. Conversation can only happen where there is a microphone. Three approaches:

### 2.1 Approach 0: talk at the Mac, the duck does the motions (recommendation: do this first)

```text
Person ──speech──► Mac microphone ──► Nous page on the Mac ⇄ cloud model
                                        │ audio: the Mac's speaker
                                        │ tool calls: app.duck.look／gesture／…
                                        ▼
                         Nous core ── duck-link ──► the duck (head motion, later the eyes)
                         presence (listening／thinking／speaking) ──► the duck moves along
```

- The sound comes out of the **Mac**, not the duck. This has to be stated honestly: at this point it is "Nous is speaking and the duck moves along beside it", not "the duck is speaking".
- Needs AIOS batches D1 (`/duck-link`), D2 (`duck` adapter) and D4a (the coarse `presence` source). **No new hardware is needed.**
- This repo's side is already complete and tested against the mock duck: hub, DuckAdapter, PresenceDriver ([`../README.md`](../README.en.md)).
- The duck-side local sound effects (ADR-0010 §6) can be done first; they do not depend on Nous.

### 2.2 Approach 1: forward the Mac's audio to the duck's speaker (unverified; not recommended as the main route)

The idea: make the duck's Pi an audio output device the Mac can see, and have the Nous page on the Mac select it with the existing "choose audio output device". That way AIOS does not need changing, and the microphone is still the Mac's.

- Possible technologies: AirPlay receiver, Bluetooth speaker mode, network audio (a PipeWire／PulseAudio network sink). **None has been tried.**
- Things to verify:
  - Whether Chromium's `setSinkId` lists that device (fact 4 only shows that it uses the browser's device list; it does not say network devices will appear).
  - Latency. Conversation audio that arrives late makes people think there is no response, and also defeats echo cancellation on the Mac's microphone (the sound comes out of the duck in another room, and the Mac's microphone may pick it up). Protocols like AirPlay usually have deliberate buffering; the actual numbers have **not been measured**.
  - AIOS's rpi4 document says Bluetooth on the Pi is "not yet supported" (`terminals/rpi4/README.en.md:217`); that refers to connecting Bluetooth devices when the Pi acts as a terminal, not to this usage, but it shows that nobody has verified this area.
- The person has to speak to the Mac while the sound comes out of the duck; this does not hold up when the duck is not next to the Mac.
- Conclusion (recommendation): only worth doing as an experiment for "wanting to hear the duck's voice before the microphone arrives"; do not invest in it as the main route.

### 2.3 Approach 2: first plug an off-the-shelf USB microphone into the duck and go straight to route A (the recommended shortest "the duck speaks" path)

AIOS's rpi4 terminal is exactly "Pi 4 + USB microphone + speaker + Chromium". Once the duck's Pi 4 has any USB microphone plugged in (for example the one the rpi4 terminal uses), it meets the same conditions:

```text
Person ──speech──► USB microphone on the duck ──► Chromium on the duck's Pi 4 (Nous page, ?terminal=<duck ID>) ⇄ cloud model
                                                    │ audio: the Pi's audio output → duck_voice (voice changing) → USB speaker
                                                    │ HTTP／SSE through the SSH tunnel → the Nous core on the Mac (tools, memory, settings)
```

- **AIOS can stay completely unchanged**: the terminal ID is just a URL parameter (rule `/^[a-z0-9][a-z0-9-]{0,31}$/`, `shared/terminal.ts:12`).
- The work is on the duck side: a terminal package for the duck (modelled on `terminals/rpi4/`: tunnel, kiosk, start at boot); the differences are that the duck has no screen and the terminal ID is different.
- **Unverified things that need a spike first** (ADR-0003 §2.1 already lists them as a spike):
  - How to run Chromium without a screen (the rpi4 package relies on the desktop session to auto-start; without a screen it needs a virtual display or headless, and whether acquiring the microphone and autoplay work properly in headless mode is **not known**).
  - Whether the Pi 4 (2 GB) has enough CPU and memory to run Chromium, duckd and, later, navigation at the same time.
  - Echo cancellation: an ordinary USB microphone has no hardware AEC, so it can only rely on Chromium's `echoCancellation`; the speaker and microphone are both on the duck's body and very close together, so the result has to be measured.
  - Capture quality under servo noise.
  - The output device preference is one global copy (fact 4): the device ID selected on the Mac does not exist on the Pi. How the rpi4 terminal handles this today has not been fully looked into; it has to be confirmed in the spike.
- In this approach the source of `presence` is right on the duck's own Pi (the page knows the full listening／thinking／speaking state), but the page's CSP is `connect-src 'self'` (`server/page-headers.ts:11`), so it **cannot connect to duckd directly**; it still has to go through the core (batch D4b: page reports phase → core → hub → the duck).

## 3. After the microphone array is connected (ADR-0005: the standard reSpeaker XVF3800, mounted on the head)

Route A stays the same; the capture and playback hardware is swapped:

| Item | Change | Where it is done |
|---|---|---|
| Capture | Replaced by the microphone array, with echo cancellation, beamforming and noise reduction done in hardware | The duck (hardware + system audio layer) |
| Playback | The speaker is driven by the array's output instead, so that the echo-cancellation reference signal is the sound actually played (ADR-0010 §4); whether the array uses its own playback signal as the reference **has to be verified on arrival** | The duck |
| Direction of arrival (DOA) | Read from the array's USB control interface, **not through the page**. The page's capture keeps only channel 1 when the channel count is not 1, 2, 4 or 6 (`spike/wake/direction/logic.ts:31-35`), so the page cannot get direction and should not be relied on for it | The duck (`robot/audio/`), with the result reported in the `data` of the duck-link event `wake_word` |
| Wake word | The duck's wake word defaults to 「Hey 鴨子」 ("Hey Duck") and can be changed (ADR-0003 §3, decided 2026-11-26). Two approaches: (a) keep the page's wake (Chromium on the Pi detects it itself; AIOS's current keywords are only "Hello Nous" and "Hey Nous", and adding 「Hey 鴨子」 requires changing AIOS's wake configuration); (b) the duck detects it natively and locally (`robot/audio/`) | (a) no AIOS change; (b) detection is on the duck, but "starting a conversation after waking" needs AIOS's cooperation (see §4) |
| Multi-device arbitration | When the Mac, rpi4 and the duck hear the same utterance at once, respond only once | AIOS (batch D6) |
| Finding a person | Wake → DOA → turn → find a face (ADR-0003 §4) | Locally on the duck; Nous only issues `find_person` |

AIOS's wake direction spike (`spike/wake/direction/`) measures the wake success rate at different angles, **not** direction-of-arrival estimation; AIOS has no DOA code that can be reused. For how to read DOA, ADR-0003 §4 specifies reusing FamilyRecorder.

## 4. What AIOS has to change and what is done on the duck side

| Capability | Duck side (this repo, `robot/`) | Nous side (this repo, `nous_adapter/`, to be moved into AIOS later) | What the AIOS core／page has to add |
|---|---|---|---|
| Nous uses voice to make the duck do motions | duckd executes and reports | DuckAdapter, hub (**complete, tested against the mock**) | D1, D2 |
| The duck does motions following the conversation state | `presence` choreography | PresenceDriver (**complete, tested against the mock**) | D4a (coarse), D4b (accurate) |
| Nous's voice comes out of the duck | Terminal package, audio output chain, voice changing | — | At minimum no change (route A); the output device preference may have to become per terminal |
| The duck hears people speak | Microphone, echo cancellation | — | Same as above |
| Moving with the volume while speaking | **Recommendation: on the duck, measure the sound it is itself playing** (a monitor in the audio layer), not over the network | `presence` sends only the state | None (if this recommendation is adopted). Otherwise the page has to report volume |
| The duck's own wake word | Local detection (native) or page detection | DuckTerminal forwards the `wake_word` event (the entry point already exists) | D6: wake keywords configurable per terminal, arbitration; after the core receives the duck's wake event, how to start a conversation that belongs to the duck's page — **no such path exists today** |
| Nous speaks up proactively through the duck | Playback | — | D7: directing a conversation to a specific terminal, **feasibility not verified** |
| Voice changing, local sound effects, privacy and volume gates | All on the duck (ADR-0010 §3, §6, §7) | — | None |
| Sound when Nous cannot be reached | Pre-recorded prompts (ADR-0010 §6) | — | None |

## 5. Recommended order

1. **Approach 0**: AIOS batches D1, D2, D4a. With the current hardware it is already possible to see "the duck reacts while talking with Nous, and can be told to turn and nod its head".
2. **The route A spike** (no need to wait for the microphone array): on the duck's Pi 4, plug in a USB microphone, run the Nous page without a screen, and measure CPU, memory, latency and echo. This is the spike ADR-0003 §2.1 requires anyway; the result decides whether to take route A or B. **A person has to be present, and it will make sound**; it cannot be done at night.
3. Spike passes → the duck's terminal package, AIOS batch D4b (accurate `presence`).
4. Microphone array arrives → swap capture and playback, DOA, the duck's own wake word (D6).
5. D7 (directing to a terminal, speaking up proactively) last; decide whether to do it after gaining usage experience with the earlier steps.

If the spike does not pass (the Pi 4 cannot run Chromium, or the microphone cannot be acquired without a screen), the fallback is route B, at the cost of the AIOS core having to add audio send/receive; the workload is large and a separate ADR has to be written.

## 6. Things that need the user's decision or presence

- Whether to plug in a USB microphone first and do the route A spike (recommendation: yes); which one to use.
- Listening tests and volume (it will make sound; daytime, with a person present).
- The duck's terminal ID (the wake word is settled: 「Hey 鴨子」 by default, ADR-0003 §3).
- Whether to spend time trying approach 1 (forwarding the Mac's audio to the duck).

## 7. 2026-11-26 update

In line with the revised ADRs and that day's progress, the sections above are to be read as follows:

| Item | Update |
|---|---|
| Microphone | The user decided to use the **standard** reSpeaker XVF3800 USB 4-Mic Array (USB VID `0x2886`, PID `0x001A`), **mounted on the head** (ADR-0005 §2.3.1). The "Flex version, mounted on the body" originally written in this document is void. When checked on 2026-11-26 it was not yet connected to the Pi |
| DOA | The array is on the head, so the sound-source angle read is **relative to the head**; the head's current rotation angle has to be added to get the direction relative to the body. This part is done by line A locally on the duck (`track sound`), not through Nous |
| Wake word | 「Hey 鴨子」 by default, can be changed (ADR-0003 §3). There is no corresponding implementation on the Nous side yet |
| Approach 0 (talk at the Mac, the duck does the motions) | AIOS batches D1, D2 and D4a **have been implemented on the AIOS branch `claude/duck-link` and a PR has been opened** (flag `NOUS_DUCK` off by default; fixture tests and a local check against duckd's simulated body, no real hardware, no real voice). See [`aios-integration-plan.md` §0](aios-integration-plan.en.md#0-2026-11-26-update-d1-d2-and-d4a-implemented-on-an-aios-branch) |
| The route A spike | For the preparation work (the script for running Chromium without a screen on the Pi, and measurements) see [`../../robot/deploy/pi4/terminal/`](../../robot/deploy/pi4/terminal/) and the [validation record](../../docs/validation/duck-terminal-spike-2026-11-26.md). The step that actually connects to Nous and makes sound is **waiting for you** to be present |
| `speaking` | The presence in this AIOS batch has only `wake`／`thinking`／`listening`／`working`／`error`／`idle`; there is **no `speaking`** (the core does not know the model is speaking). Nodding while speaking has to wait for the page to report phase (D4b), or for the duck itself to measure the sound being played (the recommendation in §4) |

## 8. The 2026-11-26 decision: route 2

The user's decision (2026-11-26, verbatim; English gloss added):

- 「我要路線2」 ("I want route 2") — Chromium on the duck's Raspberry Pi opens the Nous page (`?terminal=duck`); the conversation's capture, playback and connection to the cloud model are all in that page; the duck's wake tells the page to start a conversation.
- 「喚醒詞要用另一個，先用 “Hello 鴨子” & "hey 鴨子"」 ("The wake word should be a different one; for now use 'Hello duck' & 'hey duck'") — the duck detects these two phrases locally. Nous's own "Hello Nous" and "Hey Nous" are not changed.

The user did not say which billing method (which realtime voice path) to use, and this document does not assume one; route 2 works with both.

### 8.1 The whole path

```text
人：「Hey 鴨子」
  └► 鴨子的音訊服務（D 線，Pi 上原生）：本機喚醒詞偵測
        └► duckd（A 線）──duck-link 事件 wake_word──► Nous 核心（AIOS，NOUS_DUCK=on）
                                                        └► SSE voice.request（一次性權杖）
                                                              └► Pi 上的 Chromium：Nous 頁面 ?terminal=duck
                                                                    ├► 以 wake_word 開始即時語音（麥克風、喇叭都在這個頁面）
                                                                    │     ⇅ WebRTC，直接連雲端模型
                                                                    └► 每次狀態改變回報核心：聽／想／說
Nous 核心 ──duck-link presence（wake／listening／thinking／speaking／idle）──► duckd：頭與眼睛
模型呼叫 app.duck.look／gesture… ──► Nous 核心 ──duck-link 指令──► duckd
```

### 8.2 Where each segment lives and how far it has got

| Segment | Whose | Status (2026-11-26) |
|---|---|---|
| Local wake word (「Hello 鴨子」 ("Hello duck"), 「Hey 鴨子」 ("Hey duck")) | Line D, `robot/audio/` | In progress (line D) |
| Wake → the duck-link `wake_word` event | Line D notifies duckd; duckd (line A) sends the event | **Not connected yet**: line D's service has an option to hand its state to duckd, but the duckd end has not been done. Until this segment works, the duck's wake cannot reach Nous |
| The core receives `wake_word` → asks the page to start a conversation; the page reports listening／thinking／speaking → `presence` | Line B, in AIOS | Code complete, PR awaiting review ([pcpcchen-coder/AIOS#158](https://github.com/pcpcchen-coder/AIOS/pull/158)). The server side has fixture tests; **the page side has not been run in a browser** |
| Chromium on the Pi, without a screen, opens the Nous page | Line B, `robot/deploy/pi4/terminal/` | The script exists (`run_nous_terminal.sh`); only the "not connected to Nous, no sound, no microphone" case has been measured |
| The head and eyes follow `presence` | Line A, duckd | The real head has already been confirmed by eye (T1); `speaking` had no source before and only has one as of this change |
| Telling the duck by voice to do motions (`app.duck.*`) | Line B, already in AIOS main | Not tried with real voice |

### 8.3 How the duck terminal's page differs from an ordinary terminal

- **A conversation is started only by the duck's wake.** This page does not start the page's built-in wake listening (even if Nous has `NOUS_WAKE` turned on), so it will not start because someone says "Hey Nous", and it will not compete with the duck's wake detection for the microphone.
- The duck's wake does not need `NOUS_WAKE=on`: the core issues a one-time token for every `wake_word` event, the page starts with that token, and only then does the core treat this call as wake-started.
- The existing rate limit applies as usual: at most 3 wake-started conversations per 60 seconds.
- If nobody speaks within 5 seconds after the wake, the call ends by itself.
- The page reports listening／thinking／speaking to the core, so the duck has a real "speaking" state.

### 8.4 Things not yet solved, which only a real test will answer

None of these has ever been verified. The message for aligning with line D has been sent (2026-11-26); at the time this section was written no reply had been received.

| Question | Current situation and plan |
|---|---|
| Who gets the microphone | Line D's wake detection keeps the XVF3800 open all the time; during a call Chromium has to open it too. Two approaches: ALSA shared capture (both sides read at the same time), or a handover (release the device as soon as a wake is detected and take it back when the call ends — this loses the first second or two of speech after the wake). Try sharing first. The ALSA configuration is in line D |
| Delay from wake to the start of capture | Event → core → SSE → page starts → WebRTC connection; not measured. The page cannot hear what is said during this time |
| Speaker | Chromium plays to the ALSA default output. The first version plays directly (**not through voice changing or the gates**); voice changing needs an extra loopback stage, to be done later. This is a gap from ADR-0010's "the duck's timbre = Nous's voice plus voice changing", and you need to know about it |
| Echo cancellation | The XVF3800's hardware echo cancellation needs the played sound as its reference; Chromium also has its own software echo cancellation. How the two fit together, and whether it is enough, has to be tested |
| The duck's own voice triggering the wake | While the page is speaking, line D's wake detection has to be suppressed. `presence: speaking` reaches duckd; whether line D should take this signal directly has not been decided |
| Consent to realtime voice and the microphone permission | They are stored in that Chromium profile, and the duck has no screen to press on. You have to connect from the Mac with DevTools and press once (`run_nous_terminal.sh --debug-port`); the steps are in [`voice-test.md` §7](voice-test.en.md#7-route-2-the-duck-as-a-voice-terminal-say-hey-鴨子-to-start-a-conversation) |
| Load on the Pi 4 (2 GB) | Chromium + WebRTC + duckd + wake detection + sound-source direction all running at once; not measured |
| Privacy switch | During a call the microphone's sound is sent by the browser straight to the cloud, without passing through the duck's audio service. When "always-on wake listening" on the settings page is turned off, the page will not be woken, but a call that has already started can only be stopped by ending the call |

### 8.5 What happens to the native audio channel `/duck-voice`

Before the decision, line B built a native PCM channel (capture and playback on the duck side, connected to the voice backend on the Nous side), and it had interoperated with line D's state machine. Route 2's conversation does not go through it, so it **has not been merged into `v2`**: it stays on the branch `claude/duck-b-voice-channel` (pushed, no PR) as an experiment record. If later the conversation's sound should pass through the duck's voice changing and gates, or running a browser on the Pi is not wanted, come back and look at it; that route needs the AIOS core itself to exchange audio with the voice model.
