import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import { WebSocket } from "ws";
import { DuckLinkHub } from "../hub/duck-link-hub.ts";
import { DuckVoiceHub, VOICE_CLOSE, type VoiceBackend, type VoiceBackendSink, type VoiceSessionStats, type VoiceTiming, type WakeInfo } from "../hub/duck-voice-hub.ts";
import { EchoVoiceBackend } from "../mock/echo-voice-backend.ts";
import { MockDuckVoice, synthTone } from "../mock/mock-duck-voice.ts";
import { decodeFrame, DOWNLINK, encodeFrame, FRAME_DOWNLINK, FRAME_UPLINK, parseDuckVoiceMessage, pcmRms, resampleLinear, UPLINK, type NousVoiceMessage } from "../shared/duck-voice.ts";
import { sendDuckPresence } from "../adapters/duck-exec.ts";
import { PresenceDriver, type VoiceSessionEvent } from "../terminal/presence.ts";
import { MockDuck } from "../mock/mock-duck.ts";
import { FAST, sleep, until } from "./helpers.ts";

// duck-voice（語音媒體通道）的 Nous 端。對面是標示 mock 的鴨子音訊端，音訊是程式合成的正弦波與靜音，
// 語音後端是模擬的（回放或測試腳本）。驗證層級：單元／整合測試；沒有麥克風、沒有喇叭、沒有語音模型。

const TIMING: Partial<VoiceTiming> = { pingMs: 100, staleMs: 600, helloTimeoutMs: 150, backendStartMs: 200, uplinkGapMs: 300, silenceMs: 400, maxMs: 5_000, tickMs: 20 };

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

let rigs: Rig[] = [];
let extras: (() => void | Promise<void>)[] = [];
afterEach(async () => {
  for (const fn of extras.splice(0)) await fn();
  for (const r of rigs.splice(0)) {
    r.duck.disconnect();
    await r.voice.stop();
    await r.link.stop();
  }
});

async function rig(options: { backend?: VoiceBackend | null; timing?: Partial<VoiceTiming>; speed?: number; connect?: boolean } = {}): Promise<Rig> {
  const logs: string[] = [];
  const link = new DuckLinkHub({ port: 0, heartbeatMs: 40 });
  const voice = new DuckVoiceHub({ backend: options.backend === undefined ? new EchoVoiceBackend({ endSilenceMs: 120 }) : options.backend, timing: { ...TIMING, ...options.timing }, log: (l) => logs.push(l) });
  voice.attachTo(link);
  const port = await link.start();
  const url = `ws://127.0.0.1:${port}/duck-voice`;
  const duck = new MockDuckVoice({ url, speed: options.speed ?? 10 });
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

const isOpen = (m: NousVoiceMessage): m is Extract<NousVoiceMessage, { type: "session"; state: "open" }> => m.type === "session" && m.state === "open";
const isRefused = (m: NousVoiceMessage): m is Extract<NousVoiceMessage, { type: "session"; state: "refused" }> => m.type === "session" && m.state === "refused";
const isEnd = (m: NousVoiceMessage): m is Extract<NousVoiceMessage, { type: "end" }> => m.type === "end";
const isClear = (m: NousVoiceMessage): m is Extract<NousVoiceMessage, { type: "clear" }> => m.type === "clear";
const phases = (events: VoiceSessionEvent[]) => events.map((e) => (e.kind === "phase" ? e.phase : e.kind === "session_started" ? `started:${e.source}` : e.kind === "session_ended" ? `ended:${e.reason}` : e.kind));

/** 測試用的後端：測試自己決定什麼時候送音訊、狀態、插話與結束。 */
function scripted(options: { failStart?: boolean; hangStart?: boolean } = {}) {
  const state = { sink: null as VoiceBackendSink | null, pushed: 0, pushedBytes: 0, closed: [] as string[], playback: [] as string[], starts: 0 };
  const backend: VoiceBackend = {
    label: "scripted（測試）",
    mock: true,
    async start(_info, sink) {
      state.starts += 1;
      if (options.failStart) throw new Error("backend down");
      if (options.hangStart) await new Promise(() => {});
      state.sink = sink;
      return {
        pushAudio: (pcm) => {
          state.pushed += 1;
          state.pushedBytes += pcm.length;
        },
        playback: (s) => void state.playback.push(s),
        close: (reason) => void state.closed.push(reason),
      };
    },
  };
  return { backend, state };
}

describe("框與控制訊息", () => {
  it("二進位框：8 bytes 標頭（種類、保留、uint32 序號）＋PCM，可逆", () => {
    const pcm = synthTone(20, UPLINK.rate);
    const frame = encodeFrame(FRAME_UPLINK, 0x01020304, pcm);
    expect(frame.length).toBe(8 + UPLINK.frameBytes);
    expect([...frame.subarray(0, 8)]).toEqual([1, 0, 0, 0, 1, 2, 3, 4]);
    const back = decodeFrame(frame)!;
    expect(back).toMatchObject({ kind: FRAME_UPLINK, seq: 0x01020304 });
    expect(back.pcm.equals(pcm)).toBe(true);
  });

  it("解不開的框回 null：太短、種類不對、保留位不是 0、PCM 長度是奇數", () => {
    expect(decodeFrame(Buffer.alloc(8))).toBeNull();
    expect(decodeFrame(Buffer.from([3, 0, 0, 0, 0, 0, 0, 0, 1, 2]))).toBeNull();
    expect(decodeFrame(Buffer.from([1, 9, 0, 0, 0, 0, 0, 0, 1, 2]))).toBeNull();
    expect(decodeFrame(Buffer.from([1, 0, 0, 0, 0, 0, 0, 0, 1, 2, 3]))).toBeNull();
  });

  it("控制訊息的檢查：欄位、範圍、多餘欄位、版本", () => {
    const ok = (o: object) => parseDuckVoiceMessage(JSON.stringify({ v: "0.1", ...o })).ok;
    expect(ok({ type: "hello", role: "duck", software: "x", uplink: { rate: 16000, frame_ms: 20 }, downlink: { rate: 24000 } })).toBe(true);
    expect(ok({ type: "hello", role: "duck", software: "x", uplink: { rate: 48000, frame_ms: 20 } })).toBe(false);
    expect(ok({ type: "hello", role: "nous", software: "x" })).toBe(false);
    expect(ok({ type: "wake", wake_id: "wake_0001", keyword_id: "hey_duck", doa_deg: 30 })).toBe(true);
    expect(ok({ type: "wake", wake_id: "short" })).toBe(false);
    expect(ok({ type: "wake", wake_id: "wake_0001", audio: "AAAA" })).toBe(false);
    expect(ok({ type: "playback", session_id: "vs_12345678", state: "started", played_ms: 0 })).toBe(true);
    expect(ok({ type: "playback", session_id: "vs_12345678", state: "paused" })).toBe(false);
    expect(ok({ type: "end", session_id: "vs_12345678", reason: "user" })).toBe(true);
    expect(ok({ type: "end", session_id: "vs_12345678", reason: "bored" })).toBe(false);
    expect(ok({ type: "transcript", text: "hi" })).toBe(false);
    expect(parseDuckVoiceMessage(JSON.stringify({ v: "9.0", type: "pong", t: 1 }))).toEqual({ ok: false, error: "version" });
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

  it("連上後 hub 送 hello（role nous）；第一則不是 hello → 關閉；版本不合 → 關閉", async () => {
    const r = await rig();
    expect(r.duck.messages[0]).toMatchObject({ type: "hello", role: "nous" });
    expect(r.voice.snapshot()).toMatchObject({ connected: true, duck: { mock: true } });
    const second = new MockDuckVoice({ url: r.url });
    extras.push(() => second.disconnect());
    await second.connect(false);
    second.sendJson({ type: "pong", t: 1 });
    await until(() => second.closeCode !== null);
    expect(second.closeCode).toBe(VOICE_CLOSE.badHello);
    const third = new MockDuckVoice({ url: r.url });
    extras.push(() => third.disconnect());
    await third.connect(false);
    third.sendRaw(JSON.stringify({ v: "9.0", type: "hello", role: "duck", software: "future" }));
    await until(() => third.closeCode !== null);
    expect(third.closeCode).toBe(VOICE_CLOSE.version);
    // 原本的連線不受影響。
    expect(r.voice.snapshot().connected).toBe(true);
  });

  it("鴨子不回任何訊息（不回 pong）→ 關閉連線", async () => {
    const r = await rig({ connect: false });
    const silent = new WebSocket(r.url);
    let code: number | null = null;
    silent.on("close", (c) => (code = c));
    silent.on("open", () => silent.send(JSON.stringify({ v: "0.1", type: "hello", role: "duck", software: "silent", mock: true })));
    await until(() => code !== null, 3_000);
    expect(code).toBe(VOICE_CLOSE.stale);
  });
});

describe("喚醒 → 對話 → 回話 → 結束", () => {
  it("完整的一通：open 之後才收上行；回話切成 ≤100 ms 的下行框；speaking 以鴨子回報的播放為準", async () => {
    const r = await rig();
    r.duck.wake("wake_00000001", { keyword_id: "hey_duck", doa_deg: -30 });
    const open = await r.duck.waitFor(isOpen);
    expect(open.wake_id).toBe("wake_00000001");
    expect(r.wakes).toEqual([expect.objectContaining({ wakeId: "wake_00000001", keywordId: "hey_duck", doaDeg: -30, outcome: "open", mock: true })]);
    await r.duck.stream(300, 0.3);
    await r.duck.stream(200, 0);
    await until(() => r.duck.playback.includes("drained"));
    // 回放後端把聽到的 300 ms（加上尾端的靜音）以 24 kHz 放回來。
    const bytes = r.duck.downlink.reduce((n, f) => n + f.bytes, 0);
    expect(bytes).toBeGreaterThanOrEqual((300 / 1000) * DOWNLINK.rate * 2);
    expect(r.duck.downlink.every((f) => f.bytes <= DOWNLINK.maxFrameBytes)).toBe(true);
    expect(r.duck.downlink.map((f) => f.seq)).toEqual(r.duck.downlink.map((_f, i) => i));
    expect(pcmRms(Buffer.concat(r.duck.downlinkPcm))).toBeGreaterThan(0.1);
    await until(() => phases(r.presence).at(-1) === "listening");
    expect(phases(r.presence)).toEqual(["started:wake_word", "listening", "hearing", "thinking", "speaking", "listening"]);
    r.duck.end("user");
    await until(() => r.ended.length === 1);
    expect(r.ended[0]).toMatchObject({ reason: "duck_user", heardSpeech: true, uplinkGaps: 0, mock: true });
    expect(r.ended[0]!.uplinkFrames).toBe(25);
    expect(phases(r.presence).at(-1)).toBe("ended:ended");
    // 鴨子自己說要結束的，不再回送 end。
    expect(r.duck.messages.some(isEnd)).toBe(false);
  });

  it("沒有語音後端：refused no_backend，不演 wake", async () => {
    const r = await rig({ backend: null });
    r.duck.wake("wake_00000002");
    expect((await r.duck.waitFor(isRefused)).reason).toBe("no_backend");
    expect(r.wakes[0]).toMatchObject({ outcome: "no_backend" });
    expect(r.presence).toEqual([]);
    expect(r.voice.snapshot().counters).toMatchObject({ wakes: 1, sessions: 0, refused: 1 });
  });

  it("後端開不起來或逾時：refused no_backend，presence 先 started 再以 connect_failed 結束", async () => {
    for (const options of [{ failStart: true }, { hangStart: true }]) {
      const r = await rig({ backend: scripted(options).backend });
      r.duck.wake("wake_00000003");
      expect((await r.duck.waitFor(isRefused)).reason).toBe("no_backend");
      expect(phases(r.presence)).toEqual(["started:wake_word", "ended:connect_failed"]);
      expect(r.voice.snapshot().session).toBeNull();
    }
  });

  it("對話中再喚醒 → busy；60 秒內第 4 次喚醒 → rate_limited", async () => {
    const r = await rig({ backend: scripted().backend });
    for (let i = 1; i <= 3; i++) {
      r.duck.messages.length = 0;
      r.duck.wake(`wake_1000000${i}`);
      await r.duck.waitFor(isOpen);
      if (i === 1) {
        r.duck.wake("wake_1000000x");
        expect((await r.duck.waitFor(isRefused)).reason).toBe("busy");
      }
      r.duck.end("user");
      await until(() => r.voice.snapshot().session === null);
    }
    r.duck.messages.length = 0;
    r.duck.wake("wake_10000004");
    expect((await r.duck.waitFor(isRefused)).reason).toBe("rate_limited");
  });
});

describe("未喚醒的音訊不進來", () => {
  it("沒有工作階段時的上行框：丟棄並計數，後端完全沒收到", async () => {
    const s = scripted();
    const r = await rig({ backend: s.backend });
    for (let i = 0; i < 5; i++) r.duck.sendUplinkFrame(synthTone(20, UPLINK.rate));
    await until(() => r.voice.snapshot().counters.strayFrames === 5);
    expect(s.state.starts).toBe(0);
    expect(s.state.pushed).toBe(0);
    expect(r.voice.snapshot().connected).toBe(true);
  });

  it("持續在工作階段外送音訊（鴨子端閘門壞了）→ 關閉連線", async () => {
    const r = await rig();
    for (let i = 0; i < 25; i++) r.duck.sendUplinkFrame(synthTone(20, UPLINK.rate));
    await until(() => r.duck.closeCode !== null);
    expect(r.duck.closeCode).toBe(VOICE_CLOSE.stray);
  });

  it("wake 之後、open 之前送的音訊也不算", async () => {
    const s = scripted({ hangStart: true });
    const r = await rig({ backend: s.backend, timing: { backendStartMs: 150 } });
    r.duck.wake("wake_20000001");
    await sleep(20);
    r.duck.sendUplinkFrame(synthTone(20, UPLINK.rate));
    await r.duck.waitFor(isRefused);
    expect(s.state.pushed).toBe(0);
    expect(r.voice.snapshot().counters.strayFrames).toBe(1);
  });

  it("不合格的框（下行種類、太大）不交給後端", async () => {
    const s = scripted();
    const r = await rig({ backend: s.backend });
    r.duck.wake("wake_20000002");
    await r.duck.waitFor(isOpen);
    r.duck.sendRaw(encodeFrame(FRAME_DOWNLINK, 0, synthTone(20, UPLINK.rate)));
    r.duck.sendRaw(encodeFrame(FRAME_UPLINK, 0, Buffer.alloc(8_000)));
    r.duck.sendUplinkFrame(synthTone(20, UPLINK.rate));
    await until(() => s.state.pushed === 1);
    expect(r.voice.snapshot().counters.rxInvalid).toBe(2);
    expect(s.state.pushedBytes).toBe(UPLINK.frameBytes);
  });

  it("hub 與通道的程式不碰檔案系統（音訊不可能被寫檔）", () => {
    for (const file of ["../hub/duck-voice-hub.ts", "../shared/duck-voice.ts", "../mock/echo-voice-backend.ts"]) {
      const source = readFileSync(fileURLToPath(new URL(file, import.meta.url)), "utf8");
      expect(source, file).not.toMatch(/node:fs|writeFile|createWriteStream|appendFile/);
    }
  });
});

describe("插話、逾時、中斷", () => {
  it("回話播放中使用者插話：後端 interrupt → clear → 鴨子回 cleared → 不再是 speaking", async () => {
    const r = await rig({ speed: 2 });
    r.duck.wake("wake_30000001");
    await r.duck.waitFor(isOpen);
    await r.duck.stream(600, 0.3);
    await r.duck.stream(200, 0);
    await until(() => r.duck.playback.includes("started"));
    await until(() => phases(r.presence).at(-1) === "speaking");
    // 播放要 300 ms 以上（600 ms 的聲音、2 倍速）；這時候再說話。
    await r.duck.stream(60, 0.3);
    await r.duck.waitFor(isClear);
    await until(() => r.duck.playback.includes("cleared"));
    expect(r.duck.playback).not.toContain("drained");
    await until(() => !phases(r.presence).slice(-2).includes("speaking"));
    r.duck.end("user");
    await until(() => r.ended.length === 1);
    expect(r.ended[0]!.interruptions).toBe(1);
  });

  it("喚醒後沒有人說話 → Nous 以 silence 結束（presence 正常結束，不是 error）", async () => {
    const r = await rig({ backend: scripted().backend });
    r.duck.wake("wake_30000002");
    await r.duck.waitFor(isOpen);
    void r.duck.stream(1_500, 0);
    expect((await r.duck.waitFor(isEnd)).reason).toBe("silence");
    expect(r.ended[0]).toMatchObject({ reason: "silence", heardSpeech: false });
    expect(phases(r.presence).at(-1)).toBe("ended:ended");
  });

  it("上行斷掉（鴨子不再送框）→ error；presence 以 connection_lost 結束", async () => {
    const s = scripted();
    const r = await rig({ backend: s.backend });
    r.duck.wake("wake_30000003");
    await r.duck.waitFor(isOpen);
    await r.duck.stream(60, 0.3);
    expect((await r.duck.waitFor(isEnd)).reason).toBe("error");
    expect(r.ended[0]!.reason).toBe("uplink_lost");
    expect(s.state.closed).toEqual(["uplink_lost"]);
    expect(phases(r.presence).at(-1)).toBe("ended:connection_lost");
  });

  it("鴨子的音訊端斷線 → 後端被關閉、紀錄 client_lost", async () => {
    const s = scripted();
    const r = await rig({ backend: s.backend });
    r.duck.wake("wake_30000004");
    await r.duck.waitFor(isOpen);
    r.duck.disconnect();
    await until(() => r.ended.length === 1);
    expect(r.ended[0]!.reason).toBe("client_lost");
    expect(s.state.closed).toEqual(["client_lost"]);
    expect(r.voice.snapshot()).toMatchObject({ connected: false, session: null });
  });

  it("後端結束（done、backend_lost）會告訴鴨子；單通上限 → max_duration", async () => {
    const s = scripted();
    const r = await rig({ backend: s.backend, timing: { maxMs: 250, silenceMs: 10_000 } });
    r.duck.wake("wake_30000005");
    await r.duck.waitFor(isOpen);
    s.state.sink!.end("backend_lost");
    expect((await r.duck.waitFor(isEnd)).reason).toBe("backend_lost");
    expect(phases(r.presence).at(-1)).toBe("ended:error");
    r.duck.messages.length = 0;
    r.duck.wake("wake_30000006");
    await r.duck.waitFor(isOpen);
    void r.duck.stream(800, 0.3);
    expect((await r.duck.waitFor(isEnd)).reason).toBe("max_duration");
  });

  it("掉框會被數出來（序號不連續）", async () => {
    const s = scripted();
    const r = await rig({ backend: s.backend });
    r.duck.wake("wake_30000007");
    await r.duck.waitFor(isOpen);
    for (const seq of [0, 1, 3, 4, 7]) r.duck.sendUplinkFrame(synthTone(20, UPLINK.rate), seq);
    await until(() => s.state.pushed === 5);
    r.duck.end("user");
    await until(() => r.ended.length === 1);
    expect(r.ended[0]).toMatchObject({ uplinkFrames: 5, uplinkGaps: 2 });
  });

  it("log 只有數量與時間，沒有音訊內容", async () => {
    const r = await rig();
    r.duck.wake("wake_30000008");
    await r.duck.waitFor(isOpen);
    await r.duck.stream(200, 0.3);
    r.duck.end("user");
    await until(() => r.ended.length === 1);
    expect(r.logs.join("\n").length).toBeLessThan(600);
    expect(r.logs.at(-1)).toMatch(/對話結束（duck_user）：.*上行 10 框/);
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
    r.duck.wake("wake_40000001");
    await r.duck.waitFor(isOpen);
    await r.duck.stream(500, 0.3);
    await r.duck.stream(200, 0);
    await until(() => seen.includes("speaking"), 4_000);
    expect(r.link.snapshot().state?.presence === "speaking" || r.duck.playback.includes("drained")).toBe(true);
    await until(() => r.duck.playback.includes("drained"));
    await until(() => seen.at(-1) === "listening", 4_000);
    r.duck.end("user");
    await until(() => seen.at(-1) === "idle", 4_000);
    expect(seen).toContain("wake");
    expect(seen.indexOf("speaking")).toBeGreaterThan(seen.indexOf("wake"));
    // speech_level 不經網路：presence 指令只帶狀態。
    expect(body.received.filter((c) => c.action === "presence").every((c) => c.params?.speech_level === undefined)).toBe(true);
  });
});
