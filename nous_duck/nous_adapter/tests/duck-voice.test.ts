import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import { WebSocket } from "ws";
import { sendDuckPresence } from "../adapters/duck-exec.ts";
import { DuckLinkHub } from "../hub/duck-link-hub.ts";
import { DOWNLINK_MAX_BYTES, DuckVoiceHub, VOICE_CLOSE, type VoiceBackend, type VoiceBackendSink, type VoiceSessionStats, type VoiceTiming, type WakeInfo } from "../hub/duck-voice-hub.ts";
import { EchoVoiceBackend } from "../mock/echo-voice-backend.ts";
import { MockDuck } from "../mock/mock-duck.ts";
import { MockDuckVoice, synthTone } from "../mock/mock-duck-voice.ts";
import { DOWNLINK, parseDuckVoiceMessage, pcmRms, resampleLinear, UPLINK, type NousVoiceMessage } from "../shared/duck-voice.ts";
import { PresenceDriver, type VoiceSessionEvent } from "../terminal/presence.ts";
import { FAST, sleep, until } from "./helpers.ts";

// duck-voice（語音媒體通道）的 Nous 端。對面是標示 mock 的鴨子音訊端（照 D 線狀態機的規則做的簡化版），
// 音訊是程式合成的正弦波與靜音，語音後端是模擬的（回放或測試腳本）。
// 驗證層級：單元／整合測試；沒有麥克風、沒有喇叭、沒有語音模型。

const TIMING: Partial<VoiceTiming> = { pingMs: 100, staleMs: 600, helloTimeoutMs: 150, backendStartMs: 200, uplinkGapMs: 300, idleMs: 600, maxMs: 5_000, tickMs: 20 };

interface Rig {
  link: DuckLinkHub;
  voice: DuckVoiceHub;
  duck: MockDuckVoice;
  url: string;
  presence: VoiceSessionEvent[];
  wakes: WakeInfo[];
  ended: VoiceSessionStats[];
  logs: string[];
}

const rigs: Rig[] = [];
const extras: (() => void | Promise<void>)[] = [];
afterEach(async () => {
  for (const fn of extras.splice(0)) await fn();
  for (const r of rigs.splice(0)) {
    r.duck.disconnect();
    await r.voice.stop();
    await r.link.stop();
  }
});

async function rig(options: { backend?: VoiceBackend | null; timing?: Partial<VoiceTiming>; speed?: number; connect?: boolean; followUp?: boolean } = {}): Promise<Rig> {
  const logs: string[] = [];
  const link = new DuckLinkHub({ port: 0, heartbeatMs: 40 });
  const voice = new DuckVoiceHub({ backend: options.backend === undefined ? new EchoVoiceBackend({ endSilenceMs: 120 }) : options.backend, timing: { ...TIMING, ...options.timing }, log: (l) => logs.push(l) });
  voice.attachTo(link);
  const port = await link.start();
  const url = `ws://127.0.0.1:${port}/duck-voice`;
  const duck = new MockDuckVoice({ url, speed: options.speed ?? 10, ...(options.followUp !== undefined ? { followUp: options.followUp } : {}) });
  const presence: VoiceSessionEvent[] = [];
  const wakes: WakeInfo[] = [];
  const ended: VoiceSessionStats[] = [];
  voice.subscribe((e) => presence.push(e));
  voice.onWake((w) => wakes.push(w));
  voice.onSessionEnd((s) => ended.push(s));
  if (options.connect !== false) {
    await duck.connect();
    await until(() => voice.snapshot().connected);
  }
  const r = { link, voice, duck, url, presence, wakes, ended, logs };
  rigs.push(r);
  return r;
}

const is =
  <T extends NousVoiceMessage["type"]>(type: T) =>
  (m: NousVoiceMessage): m is Extract<NousVoiceMessage, { type: T }> =>
    m.type === type;
const types = (r: Rig) => r.duck.messages.map((m) => m.type);
const phases = (events: VoiceSessionEvent[]) => events.map((e) => (e.kind === "phase" ? e.phase : e.kind === "session_started" ? `started:${e.source}` : e.kind === "session_ended" ? `ended:${e.reason}` : e.kind));

/** 測試用的後端：測試自己決定什麼時候送音訊、狀態、插話與結束。 */
function scripted(options: { failStart?: boolean; hangStart?: boolean; startDelayMs?: number } = {}) {
  const state = { sink: null as VoiceBackendSink | null, pushed: 0, pushedBytes: 0, closed: [] as string[], playback: [] as string[], endTurns: 0, cancels: 0, starts: 0 };
  const backend: VoiceBackend = {
    label: "scripted（測試）",
    mock: true,
    async start(_info, sink) {
      state.starts += 1;
      if (options.failStart) throw new Error("backend down");
      if (options.hangStart) await new Promise(() => {});
      if (options.startDelayMs) await sleep(options.startDelayMs);
      state.sink = sink;
      return {
        pushAudio: (pcm) => {
          state.pushed += 1;
          state.pushedBytes += pcm.length;
        },
        endTurn: () => void (state.endTurns += 1),
        cancelReply: () => void (state.cancels += 1),
        playback: (s) => void state.playback.push(s),
        close: (reason) => void state.closed.push(reason),
      };
    },
  };
  return { backend, state };
}

describe("控制訊息與 PCM 小工具", () => {
  it("鴨子送來的控制訊息：欄位與範圍；多的欄位忽略；不認得的 type 不合格", () => {
    const ok = (o: object) => parseDuckVoiceMessage(JSON.stringify(o)).ok;
    expect(ok({ type: "hello", v: 0, uplink: { rate: 16000, format: "s16le", channels: 1, frame_ms: 20 }, downlink: { rate: 24000, format: "s16le", channels: 1 } })).toBe(true);
    expect(ok({ type: "hello", v: 0 })).toBe(true);
    expect(ok({ type: "hello", v: 0, uplink: { rate: 48000 } })).toBe(false);
    expect(parseDuckVoiceMessage(JSON.stringify({ type: "hello", v: 1 }))).toEqual({ ok: false, error: "version" });
    expect(ok({ type: "turn_start", turn_id: 1, trigger: "wake_word", keyword_id: "hey_duck", doa_deg: -30 })).toBe(true);
    expect(ok({ type: "turn_start", turn_id: 2, trigger: "follow_up", keyword_id: null, doa_deg: null })).toBe(true);
    expect(ok({ type: "turn_start", turn_id: 1, trigger: "remote" })).toBe(false);
    expect(ok({ type: "turn_start", turn_id: -1, trigger: "wake_word" })).toBe(false);
    expect(ok({ type: "turn_end", turn_id: 1, reason: "silence" })).toBe(true);
    expect(ok({ type: "turn_end", turn_id: 1, reason: "bored" })).toBe(false);
    expect(ok({ type: "playback", turn_id: 1, state: "refused", reason: "quiet_hours" })).toBe(true);
    expect(ok({ type: "playback", turn_id: 1, state: "paused" })).toBe(false);
    expect(ok({ type: "turn_start", turn_id: 3, trigger: "wake_word", future_field: 1 })).toBe(true);
    expect(ok({ type: "transcript", text: "hi" })).toBe(false);
    expect(parseDuckVoiceMessage("{oops")).toEqual({ ok: false, error: "不是合法的 JSON" });
  });

  it("重取樣與音量（合成資料）", () => {
    const tone = synthTone(100, 16_000, 0.5);
    expect(resampleLinear(tone, 16_000, 24_000).length).toBe(4_800);
    expect(pcmRms(tone)).toBeGreaterThan(0.3);
    expect(pcmRms(Buffer.alloc(640))).toBe(0);
  });
});

describe("連線與守門", () => {
  it("和 /duck-link 共用守門：帶 Origin 403、別的路徑 404；/duck-link 照常可用", async () => {
    const r = await rig({ connect: false });
    const status = (url: string, headers: Record<string, string> = {}) =>
      new Promise<number | "open">((resolve) => {
        const ws = new WebSocket(url, { headers });
        ws.on("open", () => (ws.terminate(), resolve("open")));
        ws.on("unexpected-response", (_q, res) => resolve(res.statusCode ?? 0));
        ws.on("error", () => {});
      });
    expect(await status(r.url, { Origin: "http://evil.example" })).toBe(403);
    expect(await status(r.url.replace("/duck-voice", "/duck-video"))).toBe(404);
    expect(await status(r.url)).toBe("open");
    const body = new MockDuck({ url: r.url.replace("/duck-voice", "/duck-link"), stateIntervalMs: 50 });
    extras.push(() => body.disconnect());
    await body.connect();
    await until(() => r.link.snapshot().connected);
  });

  it("hello → hello_ack（標示後端是模擬）；第一則不是 hello → 關閉；版本不合 → 關閉", async () => {
    const r = await rig();
    await r.duck.waitFor(is("hello_ack"));
    expect(r.duck.messages[0]).toEqual({ type: "hello_ack", v: 0, software: "duck-voice-hub 0.1.0", mock: true });
    expect(r.voice.snapshot()).toMatchObject({ connected: true, duck: { mock: true }, backend: { mock: true } });
    const second = new MockDuckVoice({ url: r.url });
    extras.push(() => second.disconnect());
    await second.connect(false);
    second.sendJson({ type: "turn_start", turn_id: 1, trigger: "wake_word" });
    await until(() => second.closeCode !== null);
    expect(second.closeCode).toBe(VOICE_CLOSE.badHello);
    const third = new MockDuckVoice({ url: r.url });
    extras.push(() => third.disconnect());
    await third.connect(false);
    third.sendJson({ type: "hello", v: 7 });
    await until(() => third.closeCode !== null);
    expect(third.closeCode).toBe(VOICE_CLOSE.version);
    expect(r.voice.snapshot().connected).toBe(true);
  });

  it("鴨子的行程卡住（連協定層的 pong 都不回）→ 關閉連線", async () => {
    const r = await rig({ connect: false });
    const silent = new WebSocket(r.url, { autoPong: false });
    extras.push(() => silent.terminate());
    let code: number | null = null;
    silent.on("close", (c) => (code = c));
    silent.on("open", () => silent.send(JSON.stringify({ type: "hello", v: 0 })));
    await until(() => code !== null, 3_000);
    expect(code).toBe(VOICE_CLOSE.stale);
  });

  it("正常的音訊端（自動回 pong）閒置時不會被關掉", async () => {
    const r = await rig();
    await sleep(900);
    expect(r.voice.snapshot().connected).toBe(true);
    expect(r.duck.closeCode).toBeNull();
  });
});

describe("喚醒 → 聽 → 回話 → 接著聽 → 結束", () => {
  it("完整的一通：turn_start 才開後端；listen_stop、speak_start、PCM、speak_end；播完送 listen；speaking 以鴨子回報為準", async () => {
    const r = await rig();
    r.duck.wake({ keyword_id: "hey_duck", doa_deg: -30 });
    await r.duck.stream(300, 0.3);
    await r.duck.stream(400, 0);
    await until(() => r.duck.playback.includes("finished"));
    expect(r.wakes).toEqual([expect.objectContaining({ turnId: 1, keywordId: "hey_duck", doaDeg: -30, outcome: "open", mock: true })]);
    // 回放後端把聽到的聲音以 24 kHz 放回來；每框最多 100 ms。
    const bytes = r.duck.downlink.reduce((n, b) => n + b, 0);
    expect(bytes).toBeGreaterThanOrEqual((300 / 1000) * DOWNLINK.rate * 2);
    expect(r.duck.downlink.every((b) => b <= DOWNLINK_MAX_BYTES && b % 2 === 0)).toBe(true);
    expect(pcmRms(Buffer.concat(r.duck.downlinkPcm))).toBeGreaterThan(0.1);
    // 播完之後 Nous 請鴨子接著聽，鴨子開始第 2 輪（follow_up）。
    await until(() => r.duck.turnId === 2);
    expect(types(r).slice(0, 5)).toEqual(["hello_ack", "listen_stop", "speak_start", "speak_end", "listen"]);
    expect(r.duck.sent).toEqual(["hello", "turn_start", "turn_end", "playback", "playback", "turn_start"]);
    await until(() => phases(r.presence).at(-1) === "listening");
    expect(phases(r.presence)).toEqual(["started:wake_word", "listening", "hearing", "thinking", "speaking", "listening"]);
    // 第 2 輪一直沒有人說話：鴨子自己結束（no_speech），對話收掉。
    await r.duck.stream(100, 0);
    r.duck.endTurn("no_speech");
    await until(() => r.ended.length === 1);
    expect(r.ended[0]).toMatchObject({ reason: "duck_no_speech", turns: 2, replies: 1, heardSpeech: true, interruptions: 0, mock: true });
    expect(phases(r.presence).at(-1)).toBe("ended:ended");
    expect(r.duck.messages.at(-1)).toEqual({ type: "session_end", reason: "done" });
  });

  it("鴨子自己判斷說完了（turn_end silence）→ 後端收到 endTurn 並回話", async () => {
    const r = await rig({ backend: new EchoVoiceBackend({ endSilenceMs: 60_000 }), followUp: false });
    r.duck.wake();
    await r.duck.stream(200, 0.3);
    r.duck.endTurn("silence");
    await until(() => r.duck.playback.includes("finished"));
    // 鴨子已經自己停止上行，所以不需要 listen_stop。
    expect(types(r)).not.toContain("listen_stop");
    expect(phases(r.presence).slice(0, 5)).toEqual(["started:wake_word", "listening", "hearing", "thinking", "speaking"]);
  });

  it("沒有語音後端：session_end no_backend，不演 wake，上行全部丟掉", async () => {
    const r = await rig({ backend: null });
    r.duck.wake();
    expect((await r.duck.waitFor(is("session_end"))).reason).toBe("no_backend");
    expect(r.duck.state).toBe("idle");
    expect(r.wakes[0]).toMatchObject({ outcome: "no_backend" });
    expect(r.presence).toEqual([]);
    expect(r.voice.snapshot().counters).toMatchObject({ wakes: 1, sessions: 0, refused: 1 });
  });

  it("後端開不起來或逾時：session_end no_backend，presence 先 started 再以 connect_failed 結束", async () => {
    for (const options of [{ failStart: true }, { hangStart: true }]) {
      const r = await rig({ backend: scripted(options).backend });
      r.duck.wake();
      void r.duck.stream(400, 0.3);
      expect((await r.duck.waitFor(is("session_end"))).reason).toBe("no_backend");
      expect(phases(r.presence)).toEqual(["started:wake_word", "ended:connect_failed"]);
      expect(r.voice.snapshot().session).toBeNull();
    }
  });

  it("後端還在開的時候先到的上行音訊：暫放在記憶體，開好就補送，一框不少", async () => {
    const s = scripted({ startDelayMs: 120 });
    const r = await rig({ backend: s.backend, timing: { backendStartMs: 1_000 } });
    r.duck.wake();
    const sentFrames = await r.duck.stream(400, 0.3);
    await until(() => s.state.pushed === sentFrames);
    expect(sentFrames).toBe(20);
    expect(s.state.pushedBytes).toBe(20 * UPLINK.frameBytes);
    expect(r.voice.snapshot().counters.strayFrames).toBe(0);
  });

  it("60 秒內第 4 次喚醒 → rate_limited", async () => {
    const r = await rig({ backend: scripted().backend });
    for (let i = 1; i <= 3; i++) {
      r.duck.wake();
      await until(() => r.voice.snapshot().session?.state === "listening");
      r.duck.endTurn("cancelled");
      await until(() => r.voice.snapshot().session === null);
    }
    r.duck.messages.length = 0;
    r.duck.wake();
    expect((await r.duck.waitFor(is("session_end"))).reason).toBe("rate_limited");
    expect(r.wakes.at(-1)).toMatchObject({ outcome: "rate_limited" });
  });

  it("鴨子本機的閘門不讓播（playback refused）→ 對話結束，不是錯誤", async () => {
    const s = scripted();
    const r = await rig({ backend: s.backend });
    r.duck.wake();
    await until(() => s.state.sink !== null);
    r.duck.sendJson({ type: "playback", turn_id: 1, state: "refused", reason: "quiet_hours" });
    await until(() => r.ended.length === 1);
    expect(r.ended[0]!.reason).toBe("duck_playback_refused_quiet_hours");
    expect(phases(r.presence).at(-1)).toBe("ended:ended");
  });
});

describe("沒有在收音的時候，音訊進不來", () => {
  it("待命時的上行框：丟棄並計數，後端完全沒被啟動", async () => {
    const s = scripted();
    const r = await rig({ backend: s.backend });
    for (let i = 0; i < 5; i++) r.duck.sendUplinkFrame(synthTone(20, UPLINK.rate));
    await until(() => r.voice.snapshot().counters.strayFrames === 5);
    expect(s.state.starts).toBe(0);
    expect(r.voice.snapshot().connected).toBe(true);
  });

  it("持續在不該送的時候送音訊（鴨子端閘門壞了）→ 關閉連線", async () => {
    const r = await rig();
    for (let i = 0; i < 25; i++) r.duck.sendUplinkFrame(synthTone(20, UPLINK.rate));
    await until(() => r.duck.closeCode !== null);
    expect(r.duck.closeCode).toBe(VOICE_CLOSE.stray);
  });

  it("回話期間（已經 listen_stop）送來的音訊不交給後端", async () => {
    const s = scripted();
    const r = await rig({ backend: s.backend });
    r.duck.wake();
    await r.duck.stream(60, 0.3);
    await until(() => s.state.pushed === 3);
    s.state.sink!.phase("thinking");
    await r.duck.waitFor(is("listen_stop"));
    r.duck.sendUplinkFrame(synthTone(20, UPLINK.rate));
    await until(() => r.voice.snapshot().counters.strayFrames === 1);
    expect(s.state.pushed).toBe(3);
  });

  it("Nous 沒辦法憑空叫鴨子收音：待命時送 listen，鴨子不理；沒有對話時的 follow_up 被回絕", async () => {
    const s = scripted();
    const r = await rig({ backend: s.backend });
    // 這條規則在鴨子端（D 線的狀態機）；模擬的音訊端照同一條規則做。
    (r.voice as unknown as { send(m: NousVoiceMessage): void }).send({ type: "listen" });
    await r.duck.waitFor(is("listen"));
    expect(r.duck.state).toBe("idle");
    expect(r.duck.sent).toEqual(["hello"]);
    r.duck.sendJson({ type: "turn_start", turn_id: 9, trigger: "follow_up", keyword_id: null, doa_deg: null });
    expect((await r.duck.waitFor(is("session_end"))).reason).toBe("error");
    expect(s.state.starts).toBe(0);
  });

  it("不合格的框（奇數長度、太大）不交給後端", async () => {
    const s = scripted();
    const r = await rig({ backend: s.backend });
    r.duck.wake();
    await until(() => s.state.sink !== null);
    r.duck.sendUplinkFrame(Buffer.alloc(641));
    r.duck.sendUplinkFrame(Buffer.alloc(8_000));
    r.duck.sendUplinkFrame(synthTone(20, UPLINK.rate));
    await until(() => s.state.pushed === 1);
    expect(r.voice.snapshot().counters.rxInvalid).toBe(2);
    expect(s.state.pushedBytes).toBe(UPLINK.frameBytes);
  });

  it("hub、通道與回放後端的程式不碰檔案系統（音訊不可能被寫檔）", () => {
    for (const file of ["../hub/duck-voice-hub.ts", "../shared/duck-voice.ts", "../mock/echo-voice-backend.ts"]) {
      const source = readFileSync(fileURLToPath(new URL(file, import.meta.url)), "utf8");
      expect(source, file).not.toMatch(/node:fs|writeFile|createWriteStream|appendFile/);
    }
  });
});

describe("打斷、逾時、中斷", () => {
  it("回話播放中用喚醒詞打斷：鴨子回報 flushed 並開始新的一輪；後端被叫停；不再是 speaking", async () => {
    const r = await rig({ speed: 2, backend: new EchoVoiceBackend({ endSilenceMs: 120 }) });
    r.duck.wake();
    await r.duck.stream(600, 0.3);
    await r.duck.stream(300, 0);
    await until(() => r.duck.playback.includes("started"));
    await until(() => phases(r.presence).at(-1) === "speaking");
    r.duck.wake();
    await until(() => r.duck.turnId === 2 && r.voice.snapshot().session?.state === "listening");
    expect(r.duck.playback).toEqual(["started", "flushed"]);
    expect(phases(r.presence).at(-1)).toBe("listening");
    expect(r.wakes).toHaveLength(2);
    r.duck.endTurn("cancelled");
    await until(() => r.ended.length === 1);
    expect(r.ended[0]).toMatchObject({ turns: 2, interruptions: 1 });
  });

  it("後端要求清空（flush）→ 鴨子清掉播放並回報 flushed", async () => {
    const s = scripted();
    const r = await rig({ backend: s.backend, speed: 1, followUp: false });
    r.duck.wake();
    await until(() => s.state.sink !== null);
    s.state.sink!.audio(synthTone(1_000, DOWNLINK.rate));
    await until(() => r.duck.playback.includes("started"));
    s.state.sink!.interrupt();
    await until(() => r.duck.playback.includes("flushed"));
    expect(s.state.playback).toEqual(["started", "flushed"]);
    expect(r.duck.playback).not.toContain("finished");
  });

  it("聽的時候上行斷掉（鴨子不再送框）→ error；presence 以 connection_lost 結束", async () => {
    const s = scripted();
    const r = await rig({ backend: s.backend });
    r.duck.wake();
    await r.duck.stream(60, 0.3);
    expect((await r.duck.waitFor(is("session_end"))).reason).toBe("error");
    expect(r.ended[0]!.reason).toBe("uplink_lost");
    expect(s.state.closed).toEqual(["uplink_lost"]);
    expect(phases(r.presence).at(-1)).toBe("ended:connection_lost");
  });

  it("鴨子的音訊端斷線 → 後端被關閉、紀錄 client_lost", async () => {
    const s = scripted();
    const r = await rig({ backend: s.backend });
    r.duck.wake();
    await until(() => s.state.sink !== null);
    r.duck.disconnect();
    await until(() => r.ended.length === 1);
    expect(r.ended[0]!.reason).toBe("client_lost");
    expect(s.state.closed).toEqual(["client_lost"]);
    expect(r.voice.snapshot()).toMatchObject({ connected: false, session: null });
  });

  it("後端結束（done、backend_lost）會告訴鴨子；單通上限 → max_duration；鴨子不接著聽 → idle 收掉", async () => {
    const s = scripted();
    const r = await rig({ backend: s.backend, timing: { maxMs: 300 }, followUp: false });
    r.duck.wake();
    await until(() => s.state.sink !== null);
    s.state.sink!.end("backend_lost");
    expect((await r.duck.waitFor(is("session_end"))).reason).toBe("backend_lost");
    expect(phases(r.presence).at(-1)).toBe("ended:error");
    r.duck.messages.length = 0;
    r.duck.wake();
    void r.duck.stream(900, 0.3);
    expect((await r.duck.waitFor(is("session_end"))).reason).toBe("max_duration");

    const s2 = scripted();
    const r2 = await rig({ backend: s2.backend, followUp: false });
    r2.duck.wake();
    await until(() => s2.state.sink !== null);
    s2.state.sink!.audio(synthTone(100, DOWNLINK.rate));
    s2.state.sink!.audioEnd();
    await until(() => r2.duck.playback.includes("finished"));
    await until(() => r2.ended.length === 1, 3_000);
    expect(r2.ended[0]!.reason).toBe("idle");
    expect(phases(r2.presence).at(-1)).toBe("ended:ended");
  });

  it("log 只有數量與時間，沒有音訊內容", async () => {
    const r = await rig();
    r.duck.wake();
    await r.duck.stream(200, 0.3);
    r.duck.endTurn("cancelled");
    await until(() => r.ended.length === 1);
    expect(r.logs.join("\n").length).toBeLessThan(600);
    expect(r.logs.some((l) => /對話結束（duck_cancelled）：.*上行 10 框/.test(l))).toBe(true);
  });
});

describe("接到 presence：鴨子的身體跟著真實的語音狀態（對 mock 鴨子）", () => {
  it("喚醒 → wake；回話真的開始播 → state.presence 是 speaking；播完 → listening；結束 → idle", async () => {
    const r = await rig({ speed: 2 });
    const body = new MockDuck({ url: r.url.replace("/duck-voice", "/duck-link"), stateIntervalMs: 40 });
    extras.push(() => body.disconnect());
    await body.connect();
    await until(() => r.link.snapshot().state !== null);
    const seen: string[] = [];
    r.link.onState((s) => {
      if (s.presence && seen.at(-1) !== s.presence) seen.push(s.presence);
    });
    const driver = new PresenceDriver({ send: (state, level) => sendDuckPresence(r.link, state, level, undefined, FAST), debounceMs: 10, wakeHoldMs: 60, errorHoldMs: 60 });
    extras.push(() => driver.stop());
    driver.attach(r.voice);
    expect(driver.sources[0]).toMatchObject({ dev: false });
    r.duck.wake();
    await r.duck.stream(500, 0.3);
    await r.duck.stream(300, 0);
    await until(() => seen.includes("speaking"), 4_000);
    await until(() => r.duck.playback.includes("finished"));
    await until(() => seen.at(-1) === "listening", 4_000);
    r.duck.endTurn("no_speech");
    await until(() => seen.at(-1) === "idle", 4_000);
    expect(seen).toContain("wake");
    expect(seen.indexOf("speaking")).toBeGreaterThan(seen.indexOf("wake"));
    // speech_level 不經網路：presence 指令只帶狀態。
    expect(body.received.filter((c) => c.action === "presence").every((c) => c.params?.speech_level === undefined)).toBe(true);
  });
});
