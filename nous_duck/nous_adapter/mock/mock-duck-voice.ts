import { WebSocket } from "ws";
import { decodeFrame, DOWNLINK, encodeFrame, FRAME_DOWNLINK, FRAME_UPLINK, pcmMs, UPLINK, VOICE_VERSION, type NousVoiceMessage } from "../shared/duck-voice.ts";

// ⚠️ MOCK 鴨子音訊端（TypeScript）。只用來測 duck-voice hub。
// 沒有麥克風、沒有喇叭、沒有喚醒詞引擎：「喚醒」是測試直接呼叫 wake()，上行音訊是程式合成的正弦波或靜音，
// 「播放」只是照收到的音訊長度計時，然後回報 playback started／drained／cleared。
// 鴨子端真正的實作是 robot/audio（Python，D 線）；兩者只共用 docs/duck-voice.md 的介面。

export interface MockDuckVoiceOptions {
  url: string;
  /** 時間倍率：上行送框與模擬播放都除以它（測試用）。 */
  speed?: number;
  software?: string;
}

/** 合成一段 s16le 單聲道的正弦波（amplitude 0～1）。合成資料，不是錄音。 */
export function synthTone(ms: number, rate: number, amplitude = 0.3, hz = 440): Buffer {
  const n = Math.round((ms / 1000) * rate);
  const out = Buffer.allocUnsafe(n * 2);
  for (let i = 0; i < n; i++) out.writeInt16LE(Math.round(Math.sin((2 * Math.PI * hz * i) / rate) * amplitude * 32767), i * 2);
  return out;
}

export class MockDuckVoice {
  readonly mock = true;
  private ws: WebSocket | null = null;
  private readonly speed: number;
  private upSeq = 0;
  private playTimer: ReturnType<typeof setTimeout> | null = null;
  private playStartedAt = 0;
  private queuedMs = 0;
  private playing = false;
  /** 收到的控制訊息（測試檢查用）。 */
  readonly messages: NousVoiceMessage[] = [];
  /** 收到的下行框的序號與位元組數（不保留音訊內容以外的東西；測試要比對內容時看 downlinkPcm）。 */
  readonly downlink: { seq: number; bytes: number }[] = [];
  /** 目前工作階段收到的下行 PCM（測試用；只在記憶體）。 */
  downlinkPcm: Buffer[] = [];
  /** 送出的 playback 回報。 */
  readonly playback: string[] = [];
  sessionId: string | null = null;
  closeCode: number | null = null;

  constructor(private readonly options: MockDuckVoiceOptions) {
    this.speed = options.speed ?? 1;
  }

  get connected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  connect(hello = true): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      const ws = new WebSocket(this.options.url);
      this.ws = ws;
      ws.once("error", reject);
      ws.once("open", () => {
        ws.off("error", reject);
        ws.on("error", () => {});
        if (hello) this.sendJson({ type: "hello", role: "duck", software: this.options.software ?? "mock-duck-voice-ts 0.1.0", mock: true, uplink: { rate: UPLINK.rate, frame_ms: UPLINK.frameMs }, downlink: { rate: DOWNLINK.rate } });
        resolve();
      });
      ws.on("message", (raw, isBinary) => (isBinary ? this.onAudio(raw as Buffer) : this.onControl(JSON.parse(raw.toString()) as NousVoiceMessage)));
      ws.on("close", (code) => {
        this.closeCode = code;
        if (this.playTimer) clearTimeout(this.playTimer);
      });
    });
  }

  disconnect(): void {
    if (this.playTimer) clearTimeout(this.playTimer);
    this.ws?.terminate();
    this.ws = null;
  }

  sendJson(body: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ v: VOICE_VERSION, ...body }));
  }

  sendRaw(data: string | Buffer): void {
    this.ws?.send(data);
  }

  /** 模擬「本機偵測到喚醒詞」。 */
  wake(wakeId: string, extra: { keyword_id?: string; doa_deg?: number } = {}): void {
    this.upSeq = 0;
    this.downlinkPcm = [];
    this.sendJson({ type: "wake", wake_id: wakeId, ...extra });
  }

  /** 等到收到符合條件的控制訊息。 */
  async waitFor<T extends NousVoiceMessage>(match: (m: NousVoiceMessage) => m is T, timeoutMs = 2_000): Promise<T> {
    const start = Date.now();
    for (;;) {
      const found = this.messages.find(match);
      if (found) return found;
      if (Date.now() - start > timeoutMs) throw new Error("等待語音通道的控制訊息逾時");
      await new Promise((r) => setTimeout(r, 5));
    }
  }

  /** 送一個上行框（不看有沒有工作階段；測試用來驗證 hub 會丟掉工作階段外的音訊）。 */
  sendUplinkFrame(pcm: Buffer, seq = this.upSeq++): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(encodeFrame(FRAME_UPLINK, seq, pcm));
  }

  /** 以（加速後的）即時速度送一段合成音訊：amplitude 0＝靜音。 */
  async stream(ms: number, amplitude: number): Promise<void> {
    const frames = Math.round(ms / UPLINK.frameMs);
    for (let i = 0; i < frames; i++) {
      this.sendUplinkFrame(amplitude > 0 ? synthTone(UPLINK.frameMs, UPLINK.rate, amplitude) : Buffer.alloc(UPLINK.frameBytes));
      await new Promise((r) => setTimeout(r, UPLINK.frameMs / this.speed));
    }
  }

  end(reason: "user" | "local_stop" | "privacy" | "error"): void {
    if (this.sessionId) this.sendJson({ type: "end", session_id: this.sessionId, reason });
    this.sessionId = null;
  }

  private onControl(message: NousVoiceMessage): void {
    this.messages.push(message);
    if (message.type === "ping") this.sendJson({ type: "pong", t: message.t });
    if (message.type === "session" && message.state === "open") this.sessionId = message.session_id;
    if (message.type === "clear" && message.session_id === this.sessionId) {
      const played = this.playing ? Math.min(this.queuedMs, (Date.now() - this.playStartedAt) * this.speed) : 0;
      if (this.playTimer) clearTimeout(this.playTimer);
      this.playing = false;
      this.queuedMs = 0;
      this.report("cleared", played);
    }
    if (message.type === "end" && message.session_id === this.sessionId) {
      if (this.playTimer) clearTimeout(this.playTimer);
      this.playing = false;
      this.sessionId = null;
    }
  }

  private onAudio(data: Buffer): void {
    const frame = decodeFrame(data);
    if (!frame || frame.kind !== FRAME_DOWNLINK) return;
    this.downlink.push({ seq: frame.seq, bytes: frame.pcm.length });
    this.downlinkPcm.push(Buffer.from(frame.pcm));
    // 模擬播放：第一框開始「出聲」，之後照累積的長度計時，播完回報 drained。
    this.queuedMs += pcmMs(frame.pcm.length, DOWNLINK.rate);
    if (!this.playing) {
      this.playing = true;
      this.playStartedAt = Date.now();
      this.report("started", 0);
    }
    if (this.playTimer) clearTimeout(this.playTimer);
    const remaining = this.queuedMs / this.speed - (Date.now() - this.playStartedAt);
    this.playTimer = setTimeout(() => {
      const total = this.queuedMs;
      this.playing = false;
      this.queuedMs = 0;
      this.report("drained", total);
    }, Math.max(0, remaining));
  }

  private report(state: "started" | "drained" | "cleared", playedMs: number): void {
    this.playback.push(state);
    if (this.sessionId) this.sendJson({ type: "playback", session_id: this.sessionId, state, played_ms: Math.round(playedMs) });
  }
}
