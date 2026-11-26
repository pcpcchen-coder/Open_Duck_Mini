import { randomUUID } from "node:crypto";
import { WebSocket, WebSocketServer } from "ws";
import {
  decodeFrame,
  DOWNLINK,
  DUCK_VOICE_PATH,
  encodeFrame,
  FRAME_DOWNLINK,
  FRAME_UPLINK,
  parseDuckVoiceMessage,
  pcmRms,
  UPLINK,
  VOICE_VERSION,
  type DuckVoiceMessage,
  type NousEndReason,
  type NousVoiceMessage,
  type PlaybackState,
  type SessionRefusal,
} from "../shared/duck-voice.ts";
import type { PresenceSource, VoiceSessionEvent } from "../terminal/presence.ts";
import type { DuckLinkHub } from "./duck-link-hub.ts";

// duck-voice hub：語音媒體通道的 Nous 端（介面見 docs/duck-voice.md）。
// - 和 /duck-link 同一個埠、同樣的守門；鴨子的音訊行程是 WebSocket client。
// - 鴨子本機偵測到喚醒詞才送 wake；這裡向「語音後端」開一通對話，成功才回 session open。
//   鴨子只有在 open 之後才送上行音訊——這是「未喚醒的音訊不外傳」在協定上的界線；
//   沒有工作階段時收到的上行框一律丟棄並計數，連續出現就關閉連線。
// - 下行音訊來自語音後端；「正在說話」以鴨子回報的 playback started／drained／cleared 為準（真的出聲才算）。
// - 這個檔案不知道語音後端是誰：真正接即時語音模型的後端在 AIOS（docs/duck-voice.md §8）；
//   本 repo 只有標示 mock 的回放後端（mock/echo-voice-backend.ts）。
// - 隱私：音訊只在記憶體裡經過，不寫檔、不進 log、不保留；只記框數、位元組數與掉框數。

/** 語音後端回給 hub 的事件。 */
export interface VoiceBackendSink {
  /** 回話的音訊（s16le、單聲道、24 kHz）。 */
  audio(pcm: Buffer): void;
  /** 後端知道的對話狀態：在聽、聽到人說話、在想。說話中不由後端決定，由鴨子的 playback 回報決定。 */
  phase(phase: "listening" | "hearing" | "thinking"): void;
  /** 使用者插話：請鴨子立刻清空播放佇列。 */
  interrupt(): void;
  /** 後端結束這通對話。 */
  end(reason: NousEndReason): void;
}

export interface VoiceBackendCall {
  /** 上行音訊（s16le、單聲道、16 kHz）。緩衝區之後可能被重用：要留著就自己複製，而且只能留在記憶體。 */
  pushAudio(pcm: Buffer): void;
  /** 鴨子的播放狀態（讓後端知道實際播到哪、能不能判斷插話）。 */
  playback?(state: PlaybackState, playedMs: number | undefined): void;
  close(reason: string): void | Promise<void>;
}

export interface VoiceBackend {
  /** 給人看的名稱（診斷用）。 */
  readonly label: string;
  /** 模擬的後端（不是真的語音模型）：狀態與輸出一律標示。 */
  readonly mock: boolean;
  start(info: { sessionId: string; wakeId: string; keywordId?: string }, sink: VoiceBackendSink): Promise<VoiceBackendCall>;
}

export interface VoiceTiming {
  pingMs: number;
  /** 多久沒收到鴨子的任何訊息就關閉連線。 */
  staleMs: number;
  helloTimeoutMs: number;
  /** 後端多久沒開起來就當作失敗。 */
  backendStartMs: number;
  /** 工作階段開著時，多久沒收到上行框就結束。 */
  uplinkGapMs: number;
  /** 喚醒後一直沒有人說話，多久結束。 */
  silenceMs: number;
  /** 單通上限。 */
  maxMs: number;
  /** 檢查逾時的間隔。 */
  tickMs: number;
}

export const VOICE_TIMING: VoiceTiming = { pingMs: 2_000, staleMs: 6_000, helloTimeoutMs: 3_000, backendStartMs: 1_500, uplinkGapMs: 2_000, silenceMs: 8_000, maxMs: 300_000, tickMs: 250 };

/** 上行音量超過這個值才算「有人說話」（0～1 的 RMS；未經實機校準）。 */
export const SPEECH_RMS = 0.01;
/** 喚醒開始的對話每 60 秒最多 3 次（和 AIOS 的 WAKE_START_RATE 相同）。 */
export const WAKE_RATE = { perWindow: 3, windowMs: 60_000 } as const;
/** 工作階段外收到這麼多上行框就關閉連線。 */
const STRAY_LIMIT = 20;
/** 單一上行框的 PCM 上限（100 ms）。 */
const UPLINK_MAX_BYTES = 3_200;

export const VOICE_CLOSE = { stale: 4000, replaced: 4001, version: 4002, badHello: 4003, shutdown: 4004, stray: 4005 } as const;

export interface DuckVoiceHubOptions {
  /** 語音後端；null＝沒有（每次喚醒都回 refused: no_backend）。 */
  backend: VoiceBackend | null;
  timing?: Partial<VoiceTiming>;
  speechRms?: number;
  software?: string;
  now?: () => number;
  log?: (line: string) => void;
}

export interface WakeInfo {
  wakeId: string;
  keywordId?: string;
  doaDeg?: number;
  at: number;
  /** 這次喚醒的結果：開了工作階段，或被拒絕的原因。 */
  outcome: "open" | SessionRefusal;
  mock: boolean;
}

export interface VoiceSessionStats {
  sessionId: string;
  wakeId: string;
  /** 結束原因：Nous 的原因，或 duck_<鴨子的原因>，或 client_lost。 */
  reason: string;
  durationMs: number;
  uplinkFrames: number;
  uplinkBytes: number;
  uplinkGaps: number;
  downlinkFrames: number;
  downlinkBytes: number;
  heardSpeech: boolean;
  interruptions: number;
  mock: boolean;
}

export interface VoiceSnapshot {
  connected: boolean;
  duck: { software: string; mock: boolean } | null;
  backend: { label: string; mock: boolean } | null;
  session: { sessionId: string; state: "starting" | "open"; ageMs: number; speaking: boolean; uplinkFrames: number; downlinkFrames: number } | null;
  counters: { connections: number; wakes: number; sessions: number; refused: number; strayFrames: number; rxInvalid: number };
  last: VoiceSessionStats | null;
}

interface Session {
  id: string;
  wakeId: string;
  state: "starting" | "open";
  call: VoiceBackendCall | null;
  openedAt: number;
  lastUplinkAt: number;
  upNext: number;
  upFrames: number;
  upBytes: number;
  upGaps: number;
  downSeq: number;
  downFrames: number;
  downBytes: number;
  heardSpeech: boolean;
  speaking: boolean;
  backendPhase: "listening" | "hearing" | "thinking";
  interruptions: number;
}

export class DuckVoiceHub implements PresenceSource {
  readonly label = "duck_voice（語音通道的真實事件：喚醒、開始、鴨子回報的播放狀態、結束）";
  readonly dev = false;

  private readonly timing: VoiceTiming;
  private readonly speechRms: number;
  private readonly now: () => number;
  private readonly log: (line: string) => void;
  private readonly software: string;
  private backend: VoiceBackend | null;
  private readonly wss = new WebSocketServer({ noServer: true, maxPayload: 64 * 1024 });

  private client: WebSocket | null = null;
  private hello: Extract<DuckVoiceMessage, { type: "hello" }> | null = null;
  private lastRxAt = 0;
  private ping: ReturnType<typeof setInterval> | null = null;
  private tick: ReturnType<typeof setInterval> | null = null;
  private session: Session | null = null;
  private stray = 0;
  private wakeStarts: number[] = [];
  private last: VoiceSessionStats | null = null;
  private readonly counters = { connections: 0, wakes: 0, sessions: 0, refused: 0, strayFrames: 0, rxInvalid: 0 };
  private readonly presenceListeners = new Set<(event: VoiceSessionEvent) => void>();
  private readonly wakeListeners = new Set<(wake: WakeInfo) => void>();
  private readonly sessionListeners = new Set<(stats: VoiceSessionStats) => void>();

  constructor(options: DuckVoiceHubOptions) {
    this.backend = options.backend;
    this.timing = { ...VOICE_TIMING, ...options.timing };
    this.speechRms = options.speechRms ?? SPEECH_RMS;
    this.now = options.now ?? Date.now;
    this.log = options.log ?? (() => {});
    this.software = options.software ?? "duck-voice-hub 0.1.0";
  }

  /** 掛到 duck-link hub 的埠上（共用它的守門）。要在 hub.start()／attach() 之前或之後呼叫都可以。 */
  attachTo(link: Pick<DuckLinkHub, "route">): void {
    link.route(DUCK_VOICE_PATH, (req, socket, head) => this.wss.handleUpgrade(req, socket, head, (ws) => this.onConnection(ws)));
  }

  async stop(): Promise<void> {
    this.finish("error", "shutdown");
    this.dropClient(VOICE_CLOSE.shutdown, "shutdown");
    for (const ws of this.wss.clients) ws.terminate();
    this.wss.close();
  }

  // ---- 訂閱 ----

  subscribe(listener: (event: VoiceSessionEvent) => void): () => void {
    this.presenceListeners.add(listener);
    return () => this.presenceListeners.delete(listener);
  }

  onWake(listener: (wake: WakeInfo) => void): () => void {
    this.wakeListeners.add(listener);
    return () => this.wakeListeners.delete(listener);
  }

  onSessionEnd(listener: (stats: VoiceSessionStats) => void): () => void {
    this.sessionListeners.add(listener);
    return () => this.sessionListeners.delete(listener);
  }

  snapshot(): VoiceSnapshot {
    const s = this.session;
    return {
      connected: this.client !== null && this.hello !== null,
      duck: this.hello ? { software: this.hello.software, mock: this.hello.mock === true } : null,
      backend: this.backend ? { label: this.backend.label, mock: this.backend.mock } : null,
      session: s ? { sessionId: s.id, state: s.state, ageMs: this.now() - s.openedAt, speaking: s.speaking, uplinkFrames: s.upFrames, downlinkFrames: s.downFrames } : null,
      counters: { ...this.counters },
      last: this.last,
    };
  }

  private get mock(): boolean {
    return this.hello?.mock === true || this.backend?.mock === true;
  }

  private lastPhase: string | null = null;

  private presence(event: VoiceSessionEvent): void {
    // 同一個 phase 不重複送（鴨子的播放回報與後端的狀態可能同時說「回到在聽」）。
    if (event.kind === "phase") {
      if (event.phase === this.lastPhase) return;
      this.lastPhase = event.phase;
    } else {
      this.lastPhase = null;
    }
    for (const l of this.presenceListeners) l(event);
  }

  // ---- 連線 ----

  private onConnection(ws: WebSocket): void {
    this.counters.connections += 1;
    let ready = false;
    const helloTimer = setTimeout(() => ws.close(VOICE_CLOSE.badHello, "hello timeout"), this.timing.helloTimeoutMs);
    this.send(ws, { v: VOICE_VERSION, type: "hello", role: "nous", software: this.software, ...(this.backend?.mock ? { mock: true } : {}) });

    ws.on("message", (raw, isBinary) => {
      if (isBinary) {
        if (ws === this.client) this.onAudio(raw as Buffer);
        return;
      }
      const parsed = parseDuckVoiceMessage(raw.toString());
      if (!parsed.ok) {
        this.counters.rxInvalid += 1;
        if (parsed.error === "version") {
          this.log("語音通道：協定版本不合，關閉連線");
          ws.close(VOICE_CLOSE.version, "version mismatch");
        } else {
          this.log(`語音通道：收到不合格的控制訊息，已丟棄（${parsed.error}）`);
          if (!ready) ws.close(VOICE_CLOSE.badHello, "first message must be a valid hello");
        }
        return;
      }
      const message = parsed.message;
      if (!ready) {
        if (message.type !== "hello") return void ws.close(VOICE_CLOSE.badHello, "first message must be hello");
        clearTimeout(helloTimer);
        ready = true;
        this.adopt(ws, message);
        return;
      }
      if (ws !== this.client) return;
      this.lastRxAt = this.now();
      this.onControl(message);
    });
    ws.on("close", () => {
      clearTimeout(helloTimer);
      if (ws === this.client) {
        this.client = null;
        this.stopTimers();
        this.finish("error", "client_lost");
        this.log("語音通道：鴨子的音訊端離線");
      }
    });
    ws.on("error", () => {});
  }

  private adopt(ws: WebSocket, hello: Extract<DuckVoiceMessage, { type: "hello" }>): void {
    if (this.client) {
      this.finish("error", "client_lost");
      this.dropClient(VOICE_CLOSE.replaced, "replaced");
    }
    this.client = ws;
    this.hello = hello;
    this.lastRxAt = this.now();
    this.stray = 0;
    this.ping = setInterval(() => {
      if (this.now() - this.lastRxAt > this.timing.staleMs) {
        this.log("語音通道：太久沒有收到鴨子的訊息，關閉連線");
        this.finish("error", "client_lost");
        return this.dropClient(VOICE_CLOSE.stale, "stale");
      }
      this.send(ws, { v: VOICE_VERSION, type: "ping", t: this.now() });
    }, this.timing.pingMs);
    this.tick = setInterval(() => this.checkSession(), this.timing.tickMs);
    this.log(`語音通道：鴨子的音訊端已連線（${hello.software}${hello.mock ? "，mock" : ""}）`);
  }

  private stopTimers(): void {
    if (this.ping) clearInterval(this.ping);
    if (this.tick) clearInterval(this.tick);
    this.ping = this.tick = null;
  }

  private dropClient(code: number, reason: string): void {
    const ws = this.client;
    this.client = null;
    this.stopTimers();
    if (ws && ws.readyState === WebSocket.OPEN) ws.close(code, reason);
  }

  private send(ws: WebSocket | null, message: NousVoiceMessage): void {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(message));
  }

  // ---- 控制訊息 ----

  private onControl(message: DuckVoiceMessage): void {
    switch (message.type) {
      case "wake":
        void this.onWakeMessage(message);
        break;
      case "playback": {
        const s = this.session;
        if (!s || s.id !== message.session_id) break;
        s.speaking = message.state === "started";
        // 先讓後端知道播放狀態（它可能因此改變自己的狀態，例如播完回到在聽），再決定 presence。
        s.call?.playback?.(message.state, message.played_ms);
        if (this.session !== s) break;
        // 真的開始出聲才算 speaking；播完或被清空就回到後端最後回報的狀態。
        this.presence({ kind: "phase", phase: s.speaking ? "speaking" : s.backendPhase === "thinking" ? "thinking" : "listening" });
        break;
      }
      case "end": {
        const s = this.session;
        if (!s || s.id !== message.session_id) break;
        this.finish(message.reason === "error" ? "error" : "done", `duck_${message.reason}`, false);
        break;
      }
      case "pong":
      case "hello":
        break;
    }
  }

  private async onWakeMessage(message: Extract<DuckVoiceMessage, { type: "wake" }>): Promise<void> {
    this.counters.wakes += 1;
    const ws = this.client;
    const now = this.now();
    const report = (outcome: WakeInfo["outcome"]) => {
      const info: WakeInfo = { wakeId: message.wake_id, ...(message.keyword_id ? { keywordId: message.keyword_id } : {}), ...(message.doa_deg !== undefined ? { doaDeg: message.doa_deg } : {}), at: now, outcome, mock: this.mock };
      for (const l of this.wakeListeners) l(info);
    };
    const refuse = (reason: SessionRefusal) => {
      this.counters.refused += 1;
      this.send(ws, { v: VOICE_VERSION, type: "session", session_id: `none_${message.wake_id}`.slice(0, 64), wake_id: message.wake_id, state: "refused", reason });
      this.log(`語音通道：喚醒沒有開始對話（${reason}）`);
      report(reason);
    };
    if (this.session) return refuse("busy");
    if (!this.backend) return refuse("no_backend");
    this.wakeStarts = this.wakeStarts.filter((t) => now - t < WAKE_RATE.windowMs);
    if (this.wakeStarts.length >= WAKE_RATE.perWindow) return refuse("rate_limited");
    this.wakeStarts.push(now);

    const session: Session = {
      id: `vs_${randomUUID().replaceAll("-", "")}`,
      wakeId: message.wake_id,
      state: "starting",
      call: null,
      openedAt: now,
      lastUplinkAt: now,
      upNext: 0,
      upFrames: 0,
      upBytes: 0,
      upGaps: 0,
      downSeq: 0,
      downFrames: 0,
      downBytes: 0,
      heardSpeech: false,
      speaking: false,
      backendPhase: "listening",
      interruptions: 0,
    };
    this.session = session;
    this.counters.sessions += 1;
    this.presence({ kind: "session_started", source: "wake_word" });

    const sink: VoiceBackendSink = {
      audio: (pcm) => this.downlink(session, pcm),
      phase: (phase) => {
        if (this.session !== session) return;
        session.backendPhase = phase;
        if (phase === "hearing") session.heardSpeech = true;
        if (!session.speaking) this.presence({ kind: "phase", phase });
      },
      interrupt: () => {
        if (this.session !== session || session.state !== "open") return;
        session.interruptions += 1;
        this.send(this.client, { v: VOICE_VERSION, type: "clear", session_id: session.id });
      },
      end: (reason) => {
        if (this.session === session) this.finish(reason, reason);
      },
    };
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const call = await Promise.race([
        this.backend.start({ sessionId: session.id, wakeId: message.wake_id, ...(message.keyword_id ? { keywordId: message.keyword_id } : {}) }, sink),
        new Promise<never>((_resolve, reject) => (timer = setTimeout(() => reject(new Error("backend start timeout")), this.timing.backendStartMs))),
      ]);
      if (this.session !== session) return void call.close("client_lost");
      session.call = call;
      session.state = "open";
      session.openedAt = session.lastUplinkAt = this.now();
      this.send(this.client, { v: VOICE_VERSION, type: "session", session_id: session.id, wake_id: message.wake_id, state: "open" });
      this.presence({ kind: "phase", phase: "listening" });
      this.log(`語音通道：對話開始（後端：${this.backend.label}${this.backend.mock ? "，mock" : ""}）`);
      report("open");
    } catch (error) {
      if (this.session !== session) return;
      this.session = null;
      this.log(`語音通道：後端開不起來（${error instanceof Error ? error.message.slice(0, 80) : "unknown"}）`);
      this.presence({ kind: "session_ended", reason: "connect_failed" });
      refuse("no_backend");
    } finally {
      clearTimeout(timer);
    }
  }

  // ---- 音訊 ----

  private onAudio(data: Buffer): void {
    this.lastRxAt = this.now();
    const frame = decodeFrame(data);
    const s = this.session;
    if (!frame || frame.kind !== FRAME_UPLINK || frame.pcm.length > UPLINK_MAX_BYTES) {
      this.counters.rxInvalid += 1;
      return;
    }
    if (!s || s.state !== "open") {
      // 沒有開著的工作階段卻收到音訊：丟棄。持續發生代表鴨子端的閘門有問題，關閉連線。
      this.counters.strayFrames += 1;
      if (++this.stray >= STRAY_LIMIT) {
        this.log("語音通道：工作階段外持續收到上行音訊，關閉連線");
        this.dropClient(VOICE_CLOSE.stray, "audio outside a session");
      }
      return;
    }
    this.stray = 0;
    if (frame.seq !== s.upNext) s.upGaps += 1;
    s.upNext = (frame.seq + 1) >>> 0;
    s.upFrames += 1;
    s.upBytes += frame.pcm.length;
    s.lastUplinkAt = this.now();
    if (!s.heardSpeech && pcmRms(frame.pcm) >= this.speechRms) s.heardSpeech = true;
    s.call?.pushAudio(frame.pcm);
  }

  private downlink(session: Session, pcm: Buffer): void {
    if (this.session !== session || session.state !== "open") return;
    const ws = this.client;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const even = pcm.length - (pcm.length % 2);
    for (let offset = 0; offset < even; offset += DOWNLINK.maxFrameBytes) {
      const chunk = pcm.subarray(offset, Math.min(even, offset + DOWNLINK.maxFrameBytes));
      ws.send(encodeFrame(FRAME_DOWNLINK, session.downSeq, chunk));
      session.downSeq = (session.downSeq + 1) >>> 0;
      session.downFrames += 1;
      session.downBytes += chunk.length;
    }
  }

  // ---- 逾時與結束 ----

  private checkSession(): void {
    const s = this.session;
    if (!s || s.state !== "open") return;
    const now = this.now();
    if (now - s.lastUplinkAt > this.timing.uplinkGapMs) return this.finish("error", "uplink_lost");
    if (!s.heardSpeech && now - s.openedAt > this.timing.silenceMs) return this.finish("silence", "silence");
    if (now - s.openedAt > this.timing.maxMs) return this.finish("max_duration", "max_duration");
  }

  /**
   * 結束目前的工作階段。wire＝告訴鴨子的原因；reason＝記錄用的原因。
   * notifyDuck＝false：是鴨子自己說要結束的，不用再告訴它。
   */
  private finish(wire: NousEndReason, reason: string, notifyDuck = true): void {
    const s = this.session;
    if (!s) return;
    this.session = null;
    if (notifyDuck && s.state === "open") this.send(this.client, { v: VOICE_VERSION, type: "end", session_id: s.id, reason: wire });
    try {
      void s.call?.close(reason);
    } catch {
      // 後端關閉時的錯誤不影響結束
    }
    const failed = wire === "error" || wire === "backend_lost";
    this.presence({ kind: "session_ended", reason: failed ? (reason === "client_lost" || reason === "uplink_lost" ? "connection_lost" : "error") : "ended" });
    const stats: VoiceSessionStats = {
      sessionId: s.id,
      wakeId: s.wakeId,
      reason,
      durationMs: this.now() - s.openedAt,
      uplinkFrames: s.upFrames,
      uplinkBytes: s.upBytes,
      uplinkGaps: s.upGaps,
      downlinkFrames: s.downFrames,
      downlinkBytes: s.downBytes,
      heardSpeech: s.heardSpeech,
      interruptions: s.interruptions,
      mock: this.mock,
    };
    this.last = stats;
    // 只記數量與時間，不記內容。
    this.log(`語音通道：對話結束（${reason}）：${Math.round(stats.durationMs / 100) / 10} 秒，上行 ${stats.uplinkFrames} 框、下行 ${stats.downlinkFrames} 框，掉框 ${stats.uplinkGaps}`);
    for (const l of this.sessionListeners) l(stats);
  }

  /** 換語音後端（開發用；進行中的工作階段會先結束）。 */
  setBackend(backend: VoiceBackend | null): void {
    this.finish("backend_lost", "backend_changed");
    this.backend = backend;
  }
}

/** 上行每框的長度（毫秒），給測試與診斷用。 */
export const UPLINK_FRAME_MS = UPLINK.frameMs;
