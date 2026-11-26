import { randomUUID } from "node:crypto";
import { WebSocket, WebSocketServer } from "ws";
import { DUCK_VOICE_PATH, parseDuckVoiceMessage, pcmRms, VOICE_PROTOCOL, type DuckVoiceMessage, type NousVoiceMessage, type PlaybackState, type SessionEndReason } from "../shared/duck-voice.ts";
import type { PresenceSource, VoiceSessionEvent } from "../terminal/presence.ts";
import type { DuckLinkHub } from "./duck-link-hub.ts";

// duck-voice hub：語音媒體通道的 Nous 端（介面見 docs/duck-voice.md；線上格式以鴨子端 D 線的實作為準）。
// - 和 /duck-link 同一個埠、同樣的守門；鴨子的音訊行程是 WebSocket client。
// - 回合制、半雙工。鴨子本機偵測到喚醒詞才送 turn_start，接著送上行音訊；這裡在那時候才向「語音後端」開一通對話。
//   什麼時候開麥克風由鴨子本機決定：Nous 只能在回話播完之後送 listen 請它接著聽一輪，不能憑空叫它收音。
//   不在「聽」的那一段收到的上行框一律丟棄並計數，連續出現就關閉連線。
// - 回話：speak_start → PCM → speak_end。「正在說話」以鴨子回報的 playback started／finished／flushed 為準（真的出聲才算）。
// - 這個檔案不知道語音後端是誰：真正接即時語音模型的後端在 AIOS（docs/duck-voice.md §7）；
//   本 repo 只有標示 mock 的回放後端（mock/echo-voice-backend.ts）。
// - 隱私：音訊只在記憶體裡經過，不寫檔、不進 log、不保留；只記框數與位元組數。
//   後端還在開的那一小段，上行框暫放在記憶體（最多 2 秒），開好就交給後端，開不起來就丟掉。

/** 語音後端回給 hub 的事件。 */
export interface VoiceBackendSink {
  /** 後端知道的對話狀態：聽到人說話、在想（＝判斷使用者說完了）、回到在聽。說話中不由後端決定，由鴨子的 playback 回報決定。 */
  phase(phase: "listening" | "hearing" | "thinking"): void;
  /** 回話的音訊（s16le、單聲道、24 kHz）。一段回話的第一塊會讓 hub 先送 speak_start。 */
  audio(pcm: Buffer): void;
  /** 這一段回話的音訊送完了（hub 送 speak_end）。 */
  audioEnd(): void;
  /** 請鴨子立刻清空播放佇列。 */
  interrupt(): void;
  /** 後端結束這通對話。 */
  end(reason: SessionEndReason): void;
}

export interface VoiceBackendCall {
  /** 上行音訊（s16le、單聲道、16 kHz）。緩衝區之後可能被重用：要留著就自己複製，而且只能留在記憶體。 */
  pushAudio(pcm: Buffer): void;
  /** 鴨子自己判斷使用者說完了（安靜夠久或說太久）。 */
  endTurn?(): void;
  /** 使用者用喚醒詞打斷了回話：停掉還沒送完的那一段。 */
  cancelReply?(): void;
  /** 鴨子的播放狀態。 */
  playback?(state: PlaybackState): void;
  close(reason: string): void | Promise<void>;
}

export interface VoiceBackend {
  /** 給人看的名稱（診斷用）。 */
  readonly label: string;
  /** 模擬的後端（不是真的語音模型）：狀態與輸出一律標示。 */
  readonly mock: boolean;
  start(info: { sessionId: string; keywordId?: string }, sink: VoiceBackendSink): Promise<VoiceBackendCall>;
}

export interface VoiceTiming {
  pingMs: number;
  /** 多久沒收到鴨子的任何東西（含 pong）就關閉連線。 */
  staleMs: number;
  helloTimeoutMs: number;
  /** 後端多久沒開起來就當作失敗。 */
  backendStartMs: number;
  /** 「聽」的時候多久沒收到上行框就結束。 */
  uplinkGapMs: number;
  /** 對話開著但沒有在聽、沒有在說、也沒有回話在路上，多久結束（鴨子沒有接著聽時的保險）。 */
  idleMs: number;
  /** 單通上限。 */
  maxMs: number;
  /** 檢查逾時的間隔。 */
  tickMs: number;
}

export const VOICE_TIMING: VoiceTiming = { pingMs: 2_000, staleMs: 6_000, helloTimeoutMs: 3_000, backendStartMs: 1_500, uplinkGapMs: 2_000, idleMs: 20_000, maxMs: 300_000, tickMs: 250 };

/** 上行音量超過這個值才算「有人說話」（0～1 的 RMS；只用在統計，未經實機校準）。 */
export const SPEECH_RMS = 0.01;
/** 喚醒開始的對話每 60 秒最多 3 次（和 AIOS 的 WAKE_START_RATE 相同）。 */
export const WAKE_RATE = { perWindow: 3, windowMs: 60_000 } as const;
/** 不在「聽」的時候收到這麼多上行框就關閉連線。 */
const STRAY_LIMIT = 20;
/** 單一上行框的 PCM 上限（100 ms）。 */
const UPLINK_MAX_BYTES = 3_200;
/** 後端還在開的時候，暫放上行音訊的上限（2 秒）。 */
const PENDING_MAX_BYTES = 64_000;
/** 下行每框最多 100 ms。 */
export const DOWNLINK_MAX_BYTES = 4_800;

export const VOICE_CLOSE = { stale: 4000, replaced: 4001, version: 4002, badHello: 4003, shutdown: 4004, stray: 4005 } as const;

export interface DuckVoiceHubOptions {
  /** 語音後端；null＝沒有（每次喚醒都回 session_end: no_backend）。 */
  backend: VoiceBackend | null;
  timing?: Partial<VoiceTiming>;
  speechRms?: number;
  software?: string;
  now?: () => number;
  log?: (line: string) => void;
}

export interface WakeInfo {
  turnId: number;
  keywordId?: string;
  doaDeg?: number;
  at: number;
  /** 這次喚醒的結果：開了對話（或打斷了回話接著聽），或沒開的原因。 */
  outcome: "open" | "no_backend" | "busy" | "rate_limited";
  mock: boolean;
}

export interface VoiceSessionStats {
  sessionId: string;
  /** 結束原因：Nous 的原因，或 duck_<鴨子的原因>，或 client_lost／uplink_lost／idle。 */
  reason: string;
  durationMs: number;
  turns: number;
  replies: number;
  uplinkFrames: number;
  uplinkBytes: number;
  downlinkFrames: number;
  downlinkBytes: number;
  heardSpeech: boolean;
  interruptions: number;
  mock: boolean;
}

export interface VoiceSnapshot {
  connected: boolean;
  duck: { software: string | null; mock: boolean } | null;
  backend: { label: string; mock: boolean } | null;
  session: { sessionId: string; state: "starting" | "listening" | "thinking" | "speaking" | "idle"; ageMs: number; turns: number; uplinkFrames: number; downlinkFrames: number } | null;
  counters: { connections: number; wakes: number; sessions: number; refused: number; strayFrames: number; rxInvalid: number };
  last: VoiceSessionStats | null;
}

interface Session {
  id: string;
  call: VoiceBackendCall | null;
  starting: boolean;
  pending: Buffer[];
  pendingBytes: number;
  /** 目前（或最後一個）回合的編號，由鴨子給。 */
  turnId: number;
  /** 鴨子正在「聽」（上行開著）。 */
  listening: boolean;
  /** 已經送了 speak_start、還沒送 speak_end 的回話屬於哪一輪；沒有就是 null。 */
  replyTurn: number | null;
  /** 鴨子回報正在出聲。 */
  speaking: boolean;
  /** 回話已經送完、等鴨子回報播完。 */
  awaitingPlayback: boolean;
  /** Nous 送了 flush、還沒收到鴨子的 flushed。 */
  flushRequested: boolean;
  openedAt: number;
  lastActivityAt: number;
  lastUplinkAt: number;
  turns: number;
  replies: number;
  upFrames: number;
  upBytes: number;
  downFrames: number;
  downBytes: number;
  heardSpeech: boolean;
  interruptions: number;
}

export class DuckVoiceHub implements PresenceSource {
  readonly label = "duck_voice（語音通道的真實事件：喚醒、聽、鴨子回報的播放狀態、結束）";
  readonly dev = false;

  private readonly timing: VoiceTiming;
  private readonly speechRms: number;
  private readonly now: () => number;
  private readonly log: (line: string) => void;
  private readonly software: string;
  private backend: VoiceBackend | null;
  private readonly wss = new WebSocketServer({ noServer: true, maxPayload: 256 * 1024 });

  private client: WebSocket | null = null;
  private hello: Extract<DuckVoiceMessage, { type: "hello" }> | null = null;
  private lastRxAt = 0;
  private ping: ReturnType<typeof setInterval> | null = null;
  private tick: ReturnType<typeof setInterval> | null = null;
  private session: Session | null = null;
  private stray = 0;
  private wakeStarts: number[] = [];
  private last: VoiceSessionStats | null = null;
  private lastPhase: string | null = null;
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

  /** 掛到 duck-link hub 的埠上（共用它的守門）。 */
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
      duck: this.hello ? { software: this.hello.software ?? null, mock: this.hello.mock === true } : null,
      backend: this.backend ? { label: this.backend.label, mock: this.backend.mock } : null,
      session: s
        ? { sessionId: s.id, state: s.starting ? "starting" : s.speaking ? "speaking" : s.listening ? "listening" : s.replyTurn !== null || s.awaitingPlayback ? "thinking" : "idle", ageMs: this.now() - s.openedAt, turns: s.turns, uplinkFrames: s.upFrames, downlinkFrames: s.downFrames }
        : null,
      counters: { ...this.counters },
      last: this.last,
    };
  }

  private get mock(): boolean {
    return this.hello?.mock === true || this.backend?.mock === true;
  }

  private presence(event: VoiceSessionEvent): void {
    // 同一個 phase 不重複送。
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

    ws.on("pong", () => {
      if (ws === this.client) this.lastRxAt = this.now();
    });
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
    this.send({ type: "hello_ack", v: VOICE_PROTOCOL, software: this.software, ...(this.backend?.mock ? { mock: true } : {}) });
    this.ping = setInterval(() => {
      if (this.now() - this.lastRxAt > this.timing.staleMs) {
        this.log("語音通道：太久沒有收到鴨子的回應，關閉連線");
        this.finish("error", "client_lost");
        return this.dropClient(VOICE_CLOSE.stale, "stale");
      }
      if (ws.readyState === WebSocket.OPEN) ws.ping();
    }, this.timing.pingMs);
    this.tick = setInterval(() => this.checkSession(), this.timing.tickMs);
    this.log(`語音通道：鴨子的音訊端已連線${hello.software ? `（${hello.software}${hello.mock ? "，mock" : ""}）` : hello.mock ? "（mock）" : ""}`);
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

  private send(message: NousVoiceMessage): void {
    const ws = this.client;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(message));
  }

  // ---- 控制訊息 ----

  private onControl(message: DuckVoiceMessage): void {
    switch (message.type) {
      case "turn_start":
        void this.onTurnStart(message);
        break;
      case "turn_end": {
        const s = this.session;
        if (!s || message.turn_id !== s.turnId) break;
        s.listening = false;
        s.lastActivityAt = this.now();
        if (message.reason === "silence" || message.reason === "max_duration") {
          // 鴨子自己判斷使用者說完了。
          s.call?.endTurn?.();
          if (this.session === s) this.presence({ kind: "phase", phase: "thinking" });
        } else if (message.reason === "no_speech") {
          this.finish("done", "duck_no_speech");
        } else if (message.reason === "cancelled") {
          this.finish("done", "duck_cancelled");
        }
        break;
      }
      case "playback": {
        const s = this.session;
        if (!s) break;
        s.lastActivityAt = this.now();
        s.call?.playback?.(message.state);
        if (this.session !== s) break;
        if (message.state === "started") {
          s.speaking = true;
          this.presence({ kind: "phase", phase: "speaking" });
        } else if (message.state === "refused") {
          // 鴨子本機的閘門不讓播（靜音時段、隱私開關…）：它自己會回到待命，這裡結束對話。
          this.finish("done", `duck_playback_refused${message.reason ? `_${message.reason.replaceAll(/[^a-z0-9_]/g, "").slice(0, 24)}` : ""}`);
        } else {
          s.speaking = false;
          s.awaitingPlayback = false;
          if (message.state === "flushed" && !s.flushRequested) {
            // 不是 Nous 要求的清空＝鴨子本機打斷了回話（例如說話中又聽到喚醒詞）。它會自己開始新的一輪，這裡不用請它聽。
            s.interruptions += 1;
            s.call?.cancelReply?.();
            if (s.replyTurn !== null) this.send({ type: "speak_end", turn_id: s.replyTurn });
            s.replyTurn = null;
            break;
          }
          s.flushRequested = false;
          // 播完（或照 Nous 的要求清空）而且沒有新的一輪在聽：請鴨子不用喚醒詞接著聽一輪。它那邊一直沒人說話會自己結束。
          if (!s.listening && s.replyTurn === null) {
            this.presence({ kind: "phase", phase: "listening" });
            this.send({ type: "listen" });
          }
        }
        break;
      }
      case "hello":
        this.hello = message;
        break;
    }
  }

  private async onTurnStart(message: Extract<DuckVoiceMessage, { type: "turn_start" }>): Promise<void> {
    const now = this.now();
    const wake = message.trigger === "wake_word";
    const report = (outcome: WakeInfo["outcome"]) => {
      if (!wake) return;
      const info: WakeInfo = { turnId: message.turn_id, ...(message.keyword_id ? { keywordId: message.keyword_id } : {}), ...(typeof message.doa_deg === "number" ? { doaDeg: message.doa_deg } : {}), at: now, outcome, mock: this.mock };
      for (const l of this.wakeListeners) l(info);
    };
    if (wake) this.counters.wakes += 1;

    const existing = this.session;
    if (existing) {
      // 對話已經開著：新的一輪（接著聽，或用喚醒詞打斷了回話）。
      if (existing.replyTurn !== null || existing.speaking || existing.awaitingPlayback) {
        existing.interruptions += 1;
        existing.call?.cancelReply?.();
        if (existing.replyTurn !== null) this.send({ type: "speak_end", turn_id: existing.replyTurn });
        existing.replyTurn = null;
        existing.speaking = false;
        existing.awaitingPlayback = false;
      }
      this.beginTurn(existing, message.turn_id);
      if (!existing.starting) this.presence({ kind: "phase", phase: "listening" });
      return report("open");
    }

    const refuse = (reason: "no_backend" | "busy" | "rate_limited" | "error") => {
      this.counters.refused += 1;
      this.send({ type: "session_end", reason });
      this.log(`語音通道：這一輪沒有開始對話（${reason}）`);
      if (reason !== "error") report(reason);
    };
    // 沒有對話卻說要「接著聽」：這裡沒有東西可以接，請鴨子回到待命。
    if (!wake) return refuse("error");
    if (!this.backend) return refuse("no_backend");
    this.wakeStarts = this.wakeStarts.filter((t) => now - t < WAKE_RATE.windowMs);
    if (this.wakeStarts.length >= WAKE_RATE.perWindow) return refuse("rate_limited");
    this.wakeStarts.push(now);

    const session: Session = {
      id: `vs_${randomUUID().replaceAll("-", "")}`,
      call: null,
      starting: true,
      pending: [],
      pendingBytes: 0,
      turnId: message.turn_id,
      listening: false,
      replyTurn: null,
      speaking: false,
      awaitingPlayback: false,
      flushRequested: false,
      openedAt: now,
      lastActivityAt: now,
      lastUplinkAt: now,
      turns: 0,
      replies: 0,
      upFrames: 0,
      upBytes: 0,
      downFrames: 0,
      downBytes: 0,
      heardSpeech: false,
      interruptions: 0,
    };
    this.session = session;
    this.counters.sessions += 1;
    this.beginTurn(session, message.turn_id);
    this.presence({ kind: "session_started", source: "wake_word" });

    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const call = await Promise.race([
        this.backend.start({ sessionId: session.id, ...(message.keyword_id ? { keywordId: message.keyword_id } : {}) }, this.sinkFor(session)),
        new Promise<never>((_resolve, reject) => (timer = setTimeout(() => reject(new Error("backend start timeout")), this.timing.backendStartMs))),
      ]);
      if (this.session !== session) return void call.close("client_lost");
      session.call = call;
      session.starting = false;
      if (session.listening) this.presence({ kind: "phase", phase: "listening" });
      // 後端開好之前收到的上行音訊（只在記憶體）現在補送，然後丟掉。
      for (const pcm of session.pending.splice(0)) call.pushAudio(pcm);
      session.pendingBytes = 0;
      this.log(`語音通道：對話開始（後端：${this.backend.label}${this.backend.mock ? "，mock" : ""}）`);
      report("open");
    } catch (error) {
      if (this.session !== session) return;
      this.session = null;
      session.pending.length = 0;
      this.log(`語音通道：後端開不起來（${error instanceof Error ? error.message.slice(0, 80) : "unknown"}）`);
      this.presence({ kind: "session_ended", reason: "connect_failed" });
      refuse("no_backend");
    } finally {
      clearTimeout(timer);
    }
  }

  private beginTurn(s: Session, turnId: number): void {
    const now = this.now();
    s.turnId = turnId;
    s.listening = true;
    s.turns += 1;
    s.lastUplinkAt = s.lastActivityAt = now;
  }

  private sinkFor(session: Session): VoiceBackendSink {
    const alive = () => this.session === session;
    return {
      phase: (phase) => {
        if (!alive()) return;
        if (phase === "hearing") session.heardSpeech = true;
        if (phase === "thinking" && session.listening) {
          // 後端（模型的語音偵測）判斷使用者說完了：請鴨子停止上行。
          session.listening = false;
          this.send({ type: "listen_stop", turn_id: session.turnId });
        }
        if (!session.speaking && !(phase === "listening" && !session.listening)) this.presence({ kind: "phase", phase });
      },
      audio: (pcm) => {
        if (!alive() || session.starting) return;
        const ws = this.client;
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        if (session.replyTurn === null) {
          session.replyTurn = session.turnId;
          session.listening = false;
          session.replies += 1;
          this.send({ type: "speak_start", turn_id: session.replyTurn });
        }
        const even = pcm.length - (pcm.length % 2);
        for (let offset = 0; offset < even; offset += DOWNLINK_MAX_BYTES) {
          const chunk = pcm.subarray(offset, Math.min(even, offset + DOWNLINK_MAX_BYTES));
          ws.send(chunk, { binary: true });
          session.downFrames += 1;
          session.downBytes += chunk.length;
        }
        session.lastActivityAt = this.now();
      },
      audioEnd: () => {
        if (!alive() || session.replyTurn === null) return;
        this.send({ type: "speak_end", turn_id: session.replyTurn });
        session.replyTurn = null;
        session.awaitingPlayback = true;
        session.lastActivityAt = this.now();
      },
      interrupt: () => {
        if (!alive()) return;
        session.interruptions += 1;
        session.flushRequested = true;
        this.send({ type: "flush" });
      },
      end: (reason) => {
        if (alive()) this.finish(reason, reason);
      },
    };
  }

  // ---- 音訊 ----

  private onAudio(pcm: Buffer): void {
    this.lastRxAt = this.now();
    const s = this.session;
    if (pcm.length === 0 || pcm.length % 2 !== 0 || pcm.length > UPLINK_MAX_BYTES) {
      this.counters.rxInvalid += 1;
      return;
    }
    if (!s || !s.listening) {
      // 不在「聽」的那一段卻收到音訊：丟棄。持續發生代表鴨子端的閘門有問題，關閉連線。
      this.counters.strayFrames += 1;
      if (++this.stray >= STRAY_LIMIT) {
        this.log("語音通道：不在收音的時候持續收到上行音訊，關閉連線");
        this.finish("error", "stray_audio");
        this.dropClient(VOICE_CLOSE.stray, "audio outside a turn");
      }
      return;
    }
    this.stray = 0;
    s.upFrames += 1;
    s.upBytes += pcm.length;
    s.lastUplinkAt = s.lastActivityAt = this.now();
    if (!s.heardSpeech && pcmRms(pcm) >= this.speechRms) s.heardSpeech = true;
    if (s.call) s.call.pushAudio(pcm);
    else if (s.starting && s.pendingBytes + pcm.length <= PENDING_MAX_BYTES) {
      s.pending.push(Buffer.from(pcm));
      s.pendingBytes += pcm.length;
    }
  }

  // ---- 逾時與結束 ----

  private checkSession(): void {
    const s = this.session;
    if (!s || s.starting) return;
    const now = this.now();
    if (now - s.openedAt > this.timing.maxMs) return this.finish("max_duration", "max_duration");
    if (s.listening && now - s.lastUplinkAt > this.timing.uplinkGapMs) return this.finish("error", "uplink_lost");
    if (!s.listening && !s.speaking && now - s.lastActivityAt > this.timing.idleMs) return this.finish("done", "idle");
  }

  /** 結束目前的對話。wire＝告訴鴨子的原因；reason＝記錄用的原因。 */
  private finish(wire: SessionEndReason, reason: string): void {
    const s = this.session;
    if (!s) return;
    this.session = null;
    s.pending.length = 0;
    this.send({ type: "session_end", reason: wire });
    try {
      void s.call?.close(reason);
    } catch {
      // 後端關閉時的錯誤不影響結束
    }
    const failed = wire === "error" || wire === "backend_lost";
    this.presence({ kind: "session_ended", reason: failed ? (reason === "client_lost" || reason === "uplink_lost" ? "connection_lost" : "error") : "ended" });
    const stats: VoiceSessionStats = {
      sessionId: s.id,
      reason,
      durationMs: this.now() - s.openedAt,
      turns: s.turns,
      replies: s.replies,
      uplinkFrames: s.upFrames,
      uplinkBytes: s.upBytes,
      downlinkFrames: s.downFrames,
      downlinkBytes: s.downBytes,
      heardSpeech: s.heardSpeech,
      interruptions: s.interruptions,
      mock: this.mock,
    };
    this.last = stats;
    // 只記數量與時間，不記內容。
    this.log(`語音通道：對話結束（${reason}）：${Math.round(stats.durationMs / 100) / 10} 秒，${stats.turns} 輪、${stats.replies} 段回話，上行 ${stats.uplinkFrames} 框、下行 ${stats.downlinkFrames} 框`);
    for (const l of this.sessionListeners) l(stats);
  }

  /** 換語音後端（開發用；進行中的對話會先結束）。 */
  setBackend(backend: VoiceBackend | null): void {
    this.finish("backend_lost", "backend_changed");
    this.backend = backend;
  }
}
