> [繁體中文](voice-test.md) | [English](voice-test.en.md)

# Voice test steps: telling the duck by voice to turn its head, nod and shake its head (T2, T3)

Status: **the steps are written; nobody has run these steps yet.** Date: 2026-11-26 (§7 was added that evening: the channel test with wake word + microphone + speaker). This document is for the user to follow; it connects to a cloud voice model, makes sound, and makes the duck's head move, so you do every step yourself.

Current situation: AIOS's `/duck-link` endpoint, the `duck` adapter and the interaction states have been merged into AIOS main (PR #156, flags off by default). On the duck side, the real head and `duckctl` sending `look` / `gesture` through the tunnel have been confirmed by eye (line A, 2026-11-26). **What has not been verified yet is exactly the part in between: real voice → the model picks a tool → the duck.**

## 0. Read this table first: who does what

| What | Who does it | Why |
|---|---|---|
| Starting a Nous with the duck flags turned on, writing its `.env`, logging in or filling in an API key | **You** | It touches your Nous settings and keys; the development agent does not read, write or copy these |
| Whether to touch the running Nous (`127.0.0.1:8787`) | **You decide.** By default these steps **do not touch it** and start a separate development instance instead | The checkout that is running has modifications you have not committed |
| Turning on the duck's power, positioning the duck, being present and watching | **You** | The head will move; you need to be able to deal with a problem immediately |
| Starting duckd on the Pi and taking over the head (`engage`) | **You** (the commands are below, all issued from the Mac) | It opens the servo bus |
| Speaking into the microphone | **You** | — |

The duck's state: sitting on the desk, legs not powered, only the head moves. Nous has only 6 tools enabled in this batch (query status, stop, turn the head, pre-recorded motions, expressions, gaze following); **telling it to walk will be refused**.

## 1. Preparation (once)

### 1.1 Get the merged AIOS code

Use a checkout that is **not** the one running Nous. `~/AIOS-duck-link` was cloned separately for this purpose earlier and can be used directly:

```bash
cd ~/AIOS-duck-link && git switch main && git pull && git log -1 --oneline
```

Confirm that the latest commit is at or after `Merge pull request #156` (inclusive). Then:

```bash
cd ~/AIOS-duck-link/prototype/ambient-shell && npm ci
```

### 1.2 Write the development instance's `.env` (you write it yourself)

File: `~/AIOS-duck-link/prototype/ambient-shell/.env` (the terminal version reads this file; it is **not** the macOS App's copy). Contents:

```bash
PORT=8791
NOUS_CONFIG_DIR=/Users/<your account>/.config/nous-duck-dev
NOUS_OAUTH_PORT=1456
NOUS_DUCK=on
NOUS_AIL=on
NOUS_AIL_SERVICES=duck
```

- `PORT=8791`: the duck-side duckd service connects to `ws://127.0.0.1:8791/duck-link` by default, and the tunnel is also 8791; with the same port, nothing needs to change on the Pi. Nous checks the `Host` header, so **the port on the duck side must equal Nous's port**.
- `NOUS_CONFIG_DIR`: a new, empty folder, separate from the running Nous (login state and settings are not shared).
- The login or API key that realtime voice needs: you set it up yourself following AIOS's [INSTALL](https://github.com/pcpcchen-coder/AIOS/blob/main/prototype/ambient-shell/INSTALL.md). The new config directory is empty, so you have to log in again or fill in the key yourself.
- **No other program may be listening on 8791 at the same time**: if you previously started the development hub with `bin/duckctl hub` or `scripts/duck-link-dev.sh hub-start`, stop it first (`scripts/duck-link-dev.sh hub-stop`).

Still uncertain: whether ChatGPT login works normally after `NOUS_OAUTH_PORT` is changed to 1456 has not been tried; the API-key path does not go through it.

## 2. Every test session

### 2.1 Start the development instance (you)

```bash
cd ~/AIOS-duck-link/prototype/ambient-shell && npm start
```

Expected in the terminal:

- `Nous 原型已啟動：http://localhost:8791` (Nous prototype started: http://localhost:8791)
- `鴨子：duck-link 已開在 ws://127.0.0.1:8791/duck-link（只聽本機；等鴨子經 SSH 通道連進來）` (Duck: duck-link is open at ws://127.0.0.1:8791/duck-link (listening on localhost only; waiting for the duck to connect in through the SSH tunnel))
- The realtime voice line says 「可用」 (available). If it says 「不可用」 (unavailable), sort out the login or API key first; otherwise the rest is pointless.

If there is no 「鴨子：duck-link 已開在…」 (Duck: duck-link is open at…) line, `NOUS_DUCK=on` did not take effect (check the location and spelling of `.env`).

### 2.2 Open the tunnel (another terminal tab on the Mac)

```bash
ssh -N -R 127.0.0.1:8791:127.0.0.1:8791 duck-pi4
```

This command keeps running; do not close it. It makes `127.0.0.1:8791` on the Pi reach `127.0.0.1:8791` on the Mac. Note: this also lets programs on the Pi call the whole HTTP API of this development instance (AIOS's Pi terminal already works this way).

### 2.3 Start duckd and take over the head (a third tab on the Mac)

[`robot/duckd/README.md`](../../robot/duckd/README.md) is authoritative; at present it is:

```bash
ssh duck-pi4 'sudo systemctl start duckd'
```

```bash
ssh duck-pi4 '~/duck/duckd/duckd-ctl engage'
```

- Only `engage` opens the servo bus and powers the head. If the servo console is still holding the bus, `engage` refuses and says who holds it; first press 「釋放硬體」 (Release hardware) on the console page.
- The service default is ±15° per axis, 30°/s.

Expected: `鴨子：鴨子已連線：duckd …` (Duck: duck connected: duckd …) appears in Nous's terminal. **It is the real head only if there is no 「（mock）」 ((mock)) after it**; if there is, duckd was started with a simulated body.

### 2.4 Open the page and start the conversation (you)

Open <http://localhost:8791> in a browser, allow the microphone, and start realtime voice.

First ask one question to confirm the whole path works:

| You say | Expected Nous behaviour | Expected duck |
|---|---|---|
| 「鴨子現在怎麼樣？」 (Duck, how are you right now?) | Calls `app.duck.status`, says the duck is connected and the head is available; mentions which pre-recorded motions currently exist | Does not move |

If Nous says the duck is not connected: go back to 2.2 and 2.3 and check. If Nous does not mention the duck at all, as if it does not know such a thing exists: `NOUS_AIL_SERVICES=duck` did not take effect.

### 2.5 Sentences to say

Say one sentence at a time, and wait for it to finish before saying the next.

| # | You say | Expected Nous call | Expected duck | Expected Nous reply |
|---|---|---|---|---|
| 1 | 「鴨子看左邊」 (Duck, look left) | `app.duck.look` (`head_yaw` positive) | Head turns to **its own left** | Says it has turned (`confirmed`) |
| 2 | 「鴨子看右邊」 (Duck, look right) | `app.duck.look` (`head_yaw` negative) | Head turns right | Same as above |
| 3 | 「鴨子抬頭」 (Duck, look up) | `app.duck.look` (`head_pitch` positive) | Raises its head | Same as above |
| 4 | 「鴨子看前面」 (Duck, look ahead) | `app.duck.look` (all axes back to 0) | Returns to centre | Same as above |
| 5 | 「鴨子點點頭」 (Duck, nod) | `app.duck.gesture` (`nod`) | Nods | Says it has started |
| 6 | 「鴨子搖頭」 (Duck, shake your head) | `app.duck.gesture` (`shake`) | Shakes its head | Same as above |
| 7 | 「鴨子把頭轉到最左邊」 (Duck, turn your head all the way to the left) | `app.duck.look` (a very large angle) | Turns to the edge of the ±15° window and stops | Should mention that the angle was limited by the duck (`clamped`) |
| 8 | 「鴨子往前走」 (Duck, walk forward) | No tool available (walking is not enabled in this batch) | **Does not move** | Says it cannot do that right now; it should not say "OK, walking" |
| 9 | 「鴨子停」 (Duck, stop) | `app.duck.stop` | Stops where it is | Says it has stopped |

Also watch the interaction states (T3): when the conversation starts the duck should show a "listening" reaction, and after the conversation ends it should go back to its usual look. This batch has **no "speaking" state** — the duck does not bob along while Nous speaks; this is a known limitation (the core does not know the model is speaking), not a fault.

Precondition for sentences 5 and 6: duckd has listed `nod` and `shake` to Nous. Motions in the motion library that are not yet marked as "verified on the real robot" are not listed by duckd by default; in that case Nous replies 「鴨子的動作清單裡沒有這個名稱」 (the duck's motion list does not contain this name). This is a duck-side setting (line A), not a Nous problem — check whether they are in the motion list Nous reads out in step 2.4.

### 2.6 Things to note down

These are the questions this test is really meant to answer:

1. For each sentence: did the model call a tool? Did it pick the right one? Did the duck move in the right direction?
2. The **direction** of sentences 1–3: whether left/right or up/down are reversed. (The tool description says `head_yaw` positive = left, `head_pitch` positive = head up.)
3. Roughly how many seconds from the end of the sentence until the head starts moving.
4. Whether Nous's reply matches what actually happened (especially sentences 7 and 8: whether it is honest about things it cannot do).
5. Whether the duck's reactions at the start and end of the conversation look right, and whether they happen too often.
6. The `整合層：… app.duck.… → …` (Integration layer: … app.duck.… → …) lines in Nous's terminal (one line per tool call, with result and elapsed time); you can paste the whole block back.

## 3. Wrapping up

In this order:

1. End the conversation on the page and close the browser tab.
2. Stop duckd (the head returns at limited speed to the position it had when taken over, then the bus is released):

   ```bash
   ssh duck-pi4 'sudo systemctl stop duckd'
   ```

3. Press Ctrl-C in the tab where the tunnel is open.
4. Press Ctrl-C in the tab running `npm start`.

The running Nous (8787) has not been touched from start to finish. To return completely to the state without the duck, nothing else needs to be done; the development instance's settings are all in `~/.config/nous-duck-dev` and `~/AIOS-duck-link`.

## 4. When something goes wrong

| Symptom | Look at first |
|---|---|
| The head's motion looks wrong and you want to stop immediately | Say 「鴨子停」 (Duck, stop); or directly `ssh duck-pi4 '~/duck/duckd/duckd-ctl estop'` (local emergency stop; it has to be cleared on the Pi afterwards); or stop the service (step 2 above) |
| Nous says 「結果不明，請看一下鴨子」 (result unknown, please take a look at the duck) | No reply was received after the command was sent, or the connection dropped. See whether the duck actually moved; see whether the tunnel tab has dropped |
| Nous says the duck refused | The reply carries the reason (for example someone is using the console, emergency stop active, overheating). Deal with it according to the reason |
| duckd cannot connect (「鴨子已連線」 (duck connected) does not appear in Nous) | Is the tunnel still open; is `PORT` in `.env` 8791; is 8791 occupied by another program (`lsof -nP -iTCP:8791 -sTCP:LISTEN`) |
| `npm start` says 8791 is in use | Stop the development hub: `cd nous_duck/nous_adapter && scripts/duck-link-dev.sh hub-stop` |

## 5. Another approach: use your everyday Nous directly (not recommended as the first thing to do)

If later you want your everyday Nous to be able to command the duck, what has to be done is: write `NOUS_DUCK=on`, `NOUS_AIL=on` and `NOUS_AIL_SERVICES` (with `duck` added) into **its** `.env`, update it to code that includes #156, and restart it; the ports of both the tunnel and duckd have to be changed to its port (default 8787; duckd needs `--url ws://127.0.0.1:8787/duck-link` added, which is a modification of the duck-side service settings).

This touches the running Nous, its `.env` and the service settings on the Pi, all of which is for you to decide and carry out. It is recommended to first confirm the voice → duck part with the development instance above before considering this.

## 6. Verification level

This document itself has not verified anything. As of 2026-11-26, the verified scope related to it is:

- AIOS side: fixture tests and a local check against duckd's simulated body (no real voice).
- Duck side: the real head, and `look` / `gesture` from `duckctl` through the tunnel against the real robot (line A, confirmed by eye).
- **Not verified**: real voice, how the model uses these tools, the startup steps of the development instance (the `.env` combination, login under a separate config directory).

## 7. Wake word, microphone and speaker: testing the voice channel (echo backend, no cloud)

What this section tests is the channel itself: "speak to the duck → the duck captures the sound → the sound is sent to the Mac → the reply is sent back to the duck → the speaker plays it and the head moves along". **The reply is not spoken by Nous**: what is connected on the Mac side is the "echo" (replay) backend, marked simulated; after you finish speaking it plays the stretch of sound you just made back unchanged. Really having Nous reply requires changing AIOS, and the route is still waiting for your decision ([`duck-voice.md` §7](duck-voice.en.md#7-what-is-still-missing-before-it-is-a-real-conversation)).

This section and the earlier §1–§3 (the development instance of Nous) **cannot run at the same time**: both use 8791. Shut one of them down first.

### 7.1 Who does what

| What | Who does it | Why |
|---|---|---|
| Starting the duck's voice service on the Pi (opens the microphone, always-on wake-word listening) | **You** | It opens the microphone; this is what "always-on wake listening" on the privacy settings page governs |
| Being present, speaking, listening to the speaker | **You** | It makes sound |
| Starting the hub and opening the tunnel on the Mac | Either you or the development agent (it touches no keys, does not connect to the cloud, makes no sound) | — |

### 7.2 Steps

1. Mac, tab 1: start the hub, with the voice channel connected to the echo backend.

   ```bash
   cd nous_duck/nous_adapter && bin/duckctl hub --voice echo
   ```

   Expect to see `語音通道：ws://127.0.0.1:8791/duck-voice；後端：echo（模擬：把聽到的聲音原樣放回去，不是語音模型）` (voice channel: ws://127.0.0.1:8791/duck-voice; backend: echo (simulated: plays the sound it heard back unchanged, not a speech model)).

2. Mac, tab 2: open the tunnel (the same one the body uses).

   ```bash
   ssh -N -R 127.0.0.1:8791:127.0.0.1:8791 duck-pi4
   ```

3. (Optional) Make the head move along: start duckd and `engage` as in §2.3. The sound can be tested without starting it; the head just will not move.

4. Pi: start the duck's voice service. The command in [`robot/audio/README.md`](../../robot/audio/README.md) (line D) prevails; when this document was written its form was:

   ```bash
   ssh duck-pi4 'cd ~/duck/d-line/audio && ~/duck/audio-venv/bin/python -m duck_audio.voice_service --url ws://127.0.0.1:8791/duck-voice'
   ```

   Expect tab 1 to show `語音通道：鴨子的音訊端已連線` (voice channel: the duck's audio end is connected). At this point the duck starts listening for the wake word (the audio does not leave the duck).

5. Say the wake word to the duck (default 「Hey 鴨子」, "Hey duck"), say a sentence after you hear the cue sound (for example 「今天天氣不錯」, "the weather is nice today"), and then stop.

### 7.3 What to expect

| Point in time | The duck | Tab 1 on the Mac |
|---|---|---|
| After the wake word is said | Cue sound; the head lifts (when duckd is running) | `事件 wake_word` (event wake_word), `語音通道：對話開始（後端：echo…，mock）` (voice channel: conversation started (backend: echo…, mock)) |
| You are speaking | The head is in the "listening" pose | — |
| About 1 second after you stop | The speaker plays **the sentence you just said** (passed through the duck's voice changer); the head is in the "speaking" pose | — |
| Playback finished | Back to "listening"; you can go on to say the next sentence without saying the wake word again | — |
| Not speaking for a long while (about 8 seconds) | Cue sound, back to standby | `語音通道：對話結束（duck_no_speech）：… 秒，N 輪、M 段回話，上行 … 框、下行 … 框` (voice channel: conversation ended (duck_no_speech): … seconds, N turns, M reply stretches, uplink … frames, downlink … frames) |

At any time you can look in another tab on the Mac: `bin/duckctl voice` (whether the audio end is connected, the conversation in progress, the statistics of the last conversation), `bin/duckctl events`.

### 7.4 Things to note down

1. The wake word: how many hits out of how many times said; whether it woke up by itself when nobody said it.
2. From when you stop to when the speaker makes sound, roughly how many seconds.
3. Whether the sound played back is clear, whether it is choppy, and whether the duck's own cue sound or motor noise was recorded into it as well.
4. While the speaker is playing, whether the duck was woken or interrupted by its own sound.
5. After playback finishes, whether going on to say a second sentence is picked up.
6. The final statistics line in tab 1 (number of turns, number of frames), and whether `strayFrames` in the `計數` (counters) of `bin/duckctl voice` is 0 (not 0 means the duck sent audio when it should not have).

### 7.5 Wrapping up

1. Stop the voice service on the Pi (press Ctrl-C in its terminal; the microphone closes).
2. If duckd was started: `ssh duck-pi4 'sudo systemctl stop duckd'`.
3. Press Ctrl-C in the tunnel's tab; press Ctrl-C in the hub's tab.

### 7.6 Verification level of this section

As of 2026-11-26: the Nous-side channel has only been through unit/integration tests (a simulated audio end, synthetic audio), and one local interoperability check of "line D's real duck-side state machine against this hub" (synthetic audio). **Nobody has run the steps above with a real microphone and speaker yet.**
