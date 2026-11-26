import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { toolResult, type ToolResult } from "../shared/aios-integrations.ts";
import type { PresenceState } from "../shared/duck-link.ts";
import { DuckTerminal, type TerminalEvent } from "../terminal/duck-terminal.ts";
import { ManualPresenceSource } from "../terminal/manual-presence-source.ts";
import { PresenceDriver } from "../terminal/presence.ts";
import { rig, until, type Rig } from "./helpers.ts";

// DuckTerminal：事件入口與 presence 來源。presence 的對應與節流用假時鐘測；事件入口對 mock 鴨子測。

describe("PresenceDriver：工作階段事件 → presence（假時鐘）", () => {
  let sent: [PresenceState, number | undefined][];
  let driver: PresenceDriver;
  let reply: ToolResult;

  beforeEach(() => {
    vi.useFakeTimers();
    sent = [];
    reply = toolResult("confirmed", "ok");
    driver = new PresenceDriver({
      send: async (state, level) => {
        sent.push([state, level]);
        return reply;
      },
    });
  });
  afterEach(() => {
    driver.stop();
    vi.useRealTimers();
  });
  const tick = (ms: number) => vi.advanceTimersByTimeAsync(ms);

  it("phase 對應：listening／hearing → listening，thinking → thinking，speaking → speaking，off → idle", async () => {
    driver.handle({ kind: "session_started", source: "user" });
    driver.handle({ kind: "phase", phase: "listening" });
    await tick(150);
    driver.handle({ kind: "phase", phase: "hearing" });
    await tick(150);
    driver.handle({ kind: "phase", phase: "thinking" });
    await tick(150);
    driver.handle({ kind: "phase", phase: "speaking" });
    await tick(150);
    driver.handle({ kind: "phase", phase: "off" });
    await tick(150);
    expect(sent.map((s) => s[0])).toEqual(["listening", "thinking", "speaking", "idle"]);
  });

  it("去抖動：120 ms 內來回跳只送最後穩定的狀態", async () => {
    driver.handle({ kind: "session_started", source: "user" });
    driver.handle({ kind: "phase", phase: "listening" });
    await tick(150);
    driver.handle({ kind: "phase", phase: "hearing" });
    await tick(50);
    driver.handle({ kind: "phase", phase: "thinking" });
    await tick(50);
    driver.handle({ kind: "phase", phase: "listening" });
    await tick(200);
    expect(sent.map((s) => s[0])).toEqual(["listening"]);
  });

  it("喚醒詞開始的工作階段：立刻送 wake，維持 600 ms 後才跟著 phase", async () => {
    driver.handle({ kind: "session_started", source: "wake_word" });
    await tick(1);
    expect(sent).toEqual([["wake", undefined]]);
    driver.handle({ kind: "phase", phase: "listening" });
    await tick(300);
    expect(sent).toHaveLength(1);
    await tick(400);
    expect(sent.map((s) => s[0])).toEqual(["wake", "listening"]);
  });

  it("不是喚醒詞開始的工作階段不演 wake", async () => {
    driver.handle({ kind: "session_started", source: "user" });
    driver.handle({ kind: "phase", phase: "listening" });
    await tick(200);
    expect(sent.map((s) => s[0])).toEqual(["listening"]);
  });

  it("thinking 時有工具在跑 → working；結束後回 thinking", async () => {
    driver.handle({ kind: "session_started", source: "user" });
    driver.handle({ kind: "phase", phase: "thinking" });
    await tick(150);
    driver.handle({ kind: "working", active: true });
    await tick(150);
    driver.handle({ kind: "working", active: false });
    await tick(150);
    expect(sent.map((s) => s[0])).toEqual(["thinking", "working", "thinking"]);
  });

  it("工作階段因錯誤結束：立刻 error，1.5 秒後回 idle；正常結束直接 idle", async () => {
    driver.handle({ kind: "session_started", source: "user" });
    driver.handle({ kind: "phase", phase: "speaking" });
    await tick(150);
    driver.handle({ kind: "session_ended", reason: "connection_lost" });
    await tick(1);
    expect(sent.at(-1)![0]).toBe("error");
    await tick(1_600);
    expect(sent.map((s) => s[0])).toEqual(["speaking", "error", "idle"]);
    driver.handle({ kind: "session_started", source: "user" });
    driver.handle({ kind: "phase", phase: "listening" });
    await tick(150);
    driver.handle({ kind: "session_ended", reason: "ended" });
    await tick(150);
    expect(sent.map((s) => s[0]).slice(3)).toEqual(["listening", "idle"]);
  });

  it("sleep：沒有工作階段時才是 sleeping", async () => {
    driver.handle({ kind: "sleep", asleep: true });
    await tick(150);
    driver.handle({ kind: "session_started", source: "user" });
    driver.handle({ kind: "phase", phase: "listening" });
    await tick(150);
    expect(sent.map((s) => s[0])).toEqual(["sleeping", "listening"]);
  });

  it("speech_level：只在 speaking 送、正規化並量化、每 200 ms 最多一次、變化不到 0.1 不送", async () => {
    driver.handle({ kind: "speech_level", rms: 0.1 }); // 不在 speaking：忽略
    await tick(300);
    expect(sent).toHaveLength(0);
    driver.handle({ kind: "session_started", source: "user" });
    driver.handle({ kind: "phase", phase: "speaking" });
    await tick(150);
    expect(sent).toEqual([["speaking", undefined]]);
    // 50 ms 一筆（AIOS 頁面的取樣間隔），連續 1 秒，音量在 0.5 附近小幅抖動。
    for (let i = 0; i < 20; i++) {
      driver.handle({ kind: "speech_level", rms: 0.1 + (i % 2) * 0.004 });
      await tick(50);
    }
    const levels = sent.slice(1);
    expect(levels.length).toBeGreaterThanOrEqual(1);
    expect(levels.length).toBeLessThanOrEqual(2);
    expect(levels[0]).toEqual(["speaking", 0.5]);
    // 音量明顯變大才再送一次；超過滿格夾在 1。
    driver.handle({ kind: "speech_level", rms: 0.9 });
    await tick(250);
    expect(sent.at(-1)).toEqual(["speaking", 1]);
    // 離開 speaking 後不再帶音量。
    driver.handle({ kind: "phase", phase: "listening" });
    await tick(150);
    expect(sent.at(-1)).toEqual(["listening", undefined]);
  });

  it("1 秒的音量串流最多送 6 則（節流上限）", async () => {
    driver.handle({ kind: "session_started", source: "user" });
    driver.handle({ kind: "phase", phase: "speaking" });
    await tick(150);
    for (let i = 0; i < 20; i++) {
      driver.handle({ kind: "speech_level", rms: i % 2 ? 0.2 : 0.02 });
      await tick(50);
    }
    expect(sent.length - 1).toBeLessThanOrEqual(6);
    expect(sent.length - 1).toBeGreaterThanOrEqual(3);
  });

  it("送出期間狀態又變：只補送最後一個，不排隊", async () => {
    let release: (() => void) | null = null;
    const slow: PresenceState[] = [];
    const d = new PresenceDriver({
      send: (state) => {
        slow.push(state);
        return new Promise<ToolResult>((resolve) => (release = () => resolve(toolResult("confirmed", "ok"))));
      },
    });
    d.handle({ kind: "session_started", source: "user" });
    d.handle({ kind: "phase", phase: "listening" });
    await tick(150);
    d.handle({ kind: "phase", phase: "thinking" });
    await tick(150);
    d.handle({ kind: "phase", phase: "speaking" });
    await tick(150);
    expect(slow).toEqual(["listening"]);
    release!();
    await tick(10);
    expect(slow).toEqual(["listening", "speaking"]);
    release!();
    d.stop();
  });

  it("沒送到（鴨子沒連線）：重連後 resend 會再送目前的狀態", async () => {
    reply = toolResult("failed", "鴨子沒有連線", { reason: "unavailable" });
    driver.handle({ kind: "session_started", source: "user" });
    driver.handle({ kind: "phase", phase: "listening" });
    await tick(150);
    reply = toolResult("confirmed", "ok");
    driver.resend();
    await tick(10);
    expect(sent.map((s) => s[0])).toEqual(["listening", "listening"]);
  });

  it("手動來源標示為開發用，並走同一套對應", async () => {
    const manual = new ManualPresenceSource();
    expect(manual.dev).toBe(true);
    expect(manual.label).toContain("不是 Nous 的事件");
    driver.attach(manual);
    expect(driver.source).toMatchObject({ dev: true });
    for (const state of ["listening", "thinking", "working", "speaking", "error", "idle", "sleeping"] as const) {
      manual.request(state, state === "speaking" ? 0.4 : undefined);
      // error 會維持 1.5 秒，等它過了再換下一個。
      await tick(state === "error" ? 1_700 : 150);
    }
    expect(sent.map((s) => s[0])).toEqual(["listening", "thinking", "working", "speaking", "error", "idle", "sleeping"]);
    expect(sent[3]).toEqual(["speaking", 0.4]);
  });
});

describe("DuckTerminal：事件入口（對 mock 鴨子）", () => {
  let r: Rig | null = null;
  let terminal: DuckTerminal | null = null;
  afterEach(async () => {
    terminal?.stop();
    await r?.close();
    r = null;
    terminal = null;
  });

  async function setup(options: Parameters<typeof rig>[0] = {}) {
    r = await rig(options);
    const delivered: TerminalEvent[] = [];
    terminal = new DuckTerminal(r.hub, { sink: { deliver: (e) => delivered.push(e) }, sendPresence: (s, l) => r!.adapter.presence(s, l), presence: { debounceMs: 10, wakeHoldMs: 30, errorHoldMs: 30 } });
    return { r, terminal, delivered };
  }

  it("鴨子的事件分類後交給 sink，並標示 mock 與來源", async () => {
    const { r, delivered } = await setup();
    r.duck.fall();
    r.duck.emitEvent("battery_low");
    r.duck.emitEvent("wake_word", { data: { doa_deg: 30 } });
    await until(() => delivered.length === 3);
    expect(delivered.map((e) => [e.name, e.category, e.attention])).toEqual([
      ["fell", "safety", "notify"],
      ["battery_low", "safety", "notify"],
      ["wake_word", "wake", "notify"],
    ]);
    expect(delivered.every((e) => e.origin === "duck" && e.mock === true)).toBe(true);
    expect(delivered[2]!.data).toEqual({ doa_deg: 30 });
  });

  it("任務事件更新任務紀錄：進度 → 完成；失敗帶原因代碼", async () => {
    const { r, terminal, delivered } = await setup();
    const started = await r.adapter.execute("app.duck.go_to", { place: "brother_room" }, { actor: "agent", route: "live", sessionId: "s", requestId: "terminal_req_1", signal: new AbortController().signal });
    const id = (started.data as { mission_id: string }).mission_id;
    await until(() => terminal.mission(id)?.status === "done");
    expect(terminal.mission(id)).toMatchObject({ status: "done", progress: 0.5, phase: "moving" });
    expect(delivered.filter((e) => e.category === "mission").map((e) => [e.name, e.attention])).toEqual([
      ["mission_progress", "info"],
      ["mission_done", "notify"],
    ]);
  });

  it("任務失敗", async () => {
    const { r, terminal } = await setup({ duck: { missionOutcome: "failed" } });
    const started = await r.adapter.execute("app.duck.go_to", { place: "dock" }, { actor: "agent", route: "live", sessionId: "s", requestId: "terminal_req_2", signal: new AbortController().signal });
    const id = (started.data as { mission_id: string }).mission_id;
    await until(() => terminal.mission(id)?.status === "failed");
    expect(terminal.mission(id)?.reason).toBe("door_closed");
  });

  it("斷線與重連由 hub 這一端回報（origin: hub），不假裝是鴨子說的", async () => {
    const { r, delivered } = await setup();
    r.duck.disconnect();
    await until(() => delivered.some((e) => e.name === "duck_disconnected"));
    expect(delivered.at(-1)).toMatchObject({ origin: "hub", category: "link", attention: "notify" });
    await r.duck.connect();
    await until(() => delivered.some((e) => e.name === "duck_connected"));
  });

  it("presence 經 terminal 送到鴨子並回讀；重連後自動重送", async () => {
    const { r, terminal } = await setup();
    const manual = new ManualPresenceSource();
    terminal.attachPresenceSource(manual);
    manual.request("speaking", 0.6);
    const sent = await terminal.presence.settled();
    expect(sent).toMatchObject({ state: "speaking", speechLevel: 0.6, result: { status: "confirmed" } });
    expect(r.hub.snapshot().state?.presence).toBe("speaking");
    r.duck.disconnect();
    await until(() => !r.hub.snapshot().connected);
    const before = r.duck.received.length;
    await r.duck.connect();
    await until(() => r.duck.received.length > before);
    expect(r.duck.received.at(-1)).toMatchObject({ action: "presence", params: { state: "speaking" } });
  });

  it("只保留最近 N 則事件", async () => {
    r = await rig();
    terminal = new DuckTerminal(r.hub, { sendPresence: (s, l) => r!.adapter.presence(s, l), keep: 3 });
    for (let i = 0; i < 5; i++) r.duck.emitEvent("picked_up");
    await until(() => r!.hub.seq > 5);
    await until(() => terminal!.events().length === 3);
    expect(terminal.events()).toHaveLength(3);
  });
});
