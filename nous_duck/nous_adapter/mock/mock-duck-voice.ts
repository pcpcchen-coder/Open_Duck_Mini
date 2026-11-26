import { WebSocket } from "ws";
import { DOWNLINK, pcmMs, UPLINK, VOICE_PROTOCOL, type NousVoiceMessage, type TurnEndReason } from "../shared/duck-voice.ts";

// ⚠️ MOCK 鴨子音訊端（TypeScript）。只用來測 duck-voice hub。
// 沒有麥克風、沒有喇叭、沒有喚醒詞引擎：「喚醒」是測試直接呼叫 wake()，上行音訊是程式合成的正弦波或靜音，
// 「播放」只是照收到的音訊長度計時，然後回報 playback started／finished／flushed。
// 狀態機照鴨子端真正的實作（robot/audio/duck_audio/session.py，D 線）的規則做一個簡化版：
// 待命 → 聽（上行）→ 等回話 → 說（下行播放）→ 等對方說要不要接著聽 → 待命。

export interface MockDuckVoiceOptions {
  url: string;
  /** 時間倍率：上行送框與模擬播放都除以它（測試用）。 */
  speed?: number;
  software?: string;
  /** 收到 listen 時要不要接著聽（預設要）。 */
  followUp?: boolean;
}

/** 合成一段 s16le 單聲道的正弦波（amplitude 0～1）。合成資料，不是錄音。 */
export function synthTone(ms: number, rate: number, amplitude = 0.3, hz = 440): Buffer {
  const n = Math.round((ms / 1000) * rate);
  const out = Buffer.allocUnsafe(n * 2);
  for (let i = 0; i < n; i++) out.writeInt16LE(Math.round(Math.sin((2 * Math.PI * hz * i) / rate) * amplitude * 32767), i * 2);
  return out;
}

export type MockVoiceState = "idle" | "listening" | "waiting" | "speaking";

export class MockDuckVoice {
  readonly mock = true;
  private ws: WebSocket | null = null;
  private readonly speed: number;
  private playTimer: ReturnType<typeof setTimeout> | null = null;
  private playStartedAt = 0;
  private queuedMs = 0;
  private playing = false;
  private speakEnded = false;
  state: MockVoiceState = "idle";
  turnId = 0;
  /** 收到的控制訊息（測試檢查用）。 */
  readonly messages: NousVoiceMessage[] = [];
  /** 收到的下行框的位元組數。 */
  readonly downlink: number[] = [];
  /** 收到的下行 PCM（測試用；只在記憶體）。 */
  downlinkPcm: Buffer[] = [];
  /** 送出的 playback 回報。 */
  readonly playback: string[] = [];
  /** 送出的控制訊息的 type（測試檢查順序用）。 */
  readonly sent: string[] = [];
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
        if (hello) {
          this.sendJson({ type: "hello", v: VOICE_PROTOCOL, software: this.options.software ?? "mock-duck-voice-ts 0.1.0", mock: true, uplink: { rate: UPLINK.rate, format: "s16le", channels: 1, frame_ms: UPLINK.frameMs }, downlink: { rate: DOWNLINK.rate, format: "s16le", channels: 1 } });
        }
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
    if (typeof body.type === "string") this.sent.push(body.type);
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(body));
  }

  sendRaw(data: string | Buffer): void {
    this.ws?.send(data);
  }

  /** 模擬「本機偵測到喚醒詞」：開始新的一輪並打開上行。說話中被喚醒＝打斷（先回報 flushed）。 */
  wake(extra: { keyword_id?: string | null; doa_deg?: number | null } = {}): void {
    if (this.state === "speaking") this.stopPlayback("flushed");
    this.startTurn("wake_word", extra);
  }

  private startTurn(trigger: "wake_word" | "follow_up", extra: { keyword_id?: string | null; doa_deg?: number | null } = {}): void {
    this.turnId += 1;
    this.state = "listening";
    this.speakEnded = false;
    if (trigger === "wake_word") this.downlinkPcm = [];
    this.sendJson({ type: "turn_start", turn_id: this.turnId, trigger, keyword_id: extra.keyword_id ?? null, doa_deg: extra.doa_deg ?? null });
  }

  /** 鴨子自己結束「聽」：silence／max_duration → 等回話；no_speech／cancelled → 回待命。 */
  endTurn(reason: TurnEndReason): void {
    if (this.state !== "listening") return;
    this.state = reason === "no_speech" || reason === "cancelled" ? "idle" : "waiting";
    this.sendJson({ type: "turn_end", turn_id: this.turnId, reason });
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

  /** 直接送一個上行框，不看狀態（測試用來驗證 hub 會丟掉不該收的音訊）。 */
  sendUplinkFrame(pcm: Buffer): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(pcm, { binary: true });
  }

  /** 以（加速後的）即時速度送一段合成音訊；只有在「聽」的時候才送（和真的鴨子一樣）。amplitude 0＝靜音。回傳實際送出的框數。 */
  async stream(ms: number, amplitude: number): Promise<number> {
    const frames = Math.round(ms / UPLINK.frameMs);
    let sentFrames = 0;
    for (let i = 0; i < frames; i++) {
      if (this.state === "listening") {
        this.sendUplinkFrame(amplitude > 0 ? synthTone(UPLINK.frameMs, UPLINK.rate, amplitude) : Buffer.alloc(UPLINK.frameBytes));
        sentFrames += 1;
      }
      await new Promise((r) => setTimeout(r, UPLINK.frameMs / this.speed));
    }
    return sentFrames;
  }

  private onControl(message: NousVoiceMessage): void {
    this.messages.push(message);
    switch (message.type) {
      case "listen_stop":
        if (this.state === "listening" && message.turn_id === this.turnId) {
          this.state = "waiting";
          this.sendJson({ type: "turn_end", turn_id: this.turnId, reason: "remote" });
        }
        break;
      case "speak_start":
        if ((this.state === "listening" || this.state === "waiting") && message.turn_id === this.turnId) {
          if (this.state === "listening") this.sendJson({ type: "turn_end", turn_id: this.turnId, reason: "remote" });
          this.state = "speaking";
          this.speakEnded = false;
          this.queuedMs = 0;
        }
        break;
      case "speak_end":
        if (this.state === "speaking" && message.turn_id === this.turnId) {
          this.speakEnded = true;
          if (!this.playing && this.queuedMs === 0) this.report("finished");
        }
        break;
      case "flush":
        if (this.state === "speaking") this.stopPlayback("flushed");
        break;
      case "listen":
        // 只在剛說完話（或等回話）時接受，待命時不接受——不讓遠端憑空開麥克風。
        if (this.options.followUp !== false && (this.state === "waiting" || (this.state === "speaking" && !this.playing && this.speakEnded))) this.startTurn("follow_up");
        break;
      case "session_end":
        if (this.playTimer) clearTimeout(this.playTimer);
        this.playing = false;
        this.state = "idle";
        break;
      case "hello_ack":
        break;
    }
  }

  private onAudio(pcm: Buffer): void {
    if (this.state !== "speaking" || this.speakEnded) return;
    this.downlink.push(pcm.length);
    this.downlinkPcm.push(Buffer.from(pcm));
    // 模擬播放：第一框開始「出聲」，之後照累積的長度計時。
    this.queuedMs += pcmMs(pcm.length, DOWNLINK.rate);
    if (!this.playing) {
      this.playing = true;
      this.playStartedAt = Date.now();
      this.report("started");
    }
    if (this.playTimer) clearTimeout(this.playTimer);
    const remaining = this.queuedMs / this.speed - (Date.now() - this.playStartedAt);
    this.playTimer = setTimeout(() => {
      this.playing = false;
      this.queuedMs = 0;
      this.report("finished");
    }, Math.max(0, remaining));
  }

  private stopPlayback(state: "flushed"): void {
    if (this.playTimer) clearTimeout(this.playTimer);
    this.playing = false;
    this.queuedMs = 0;
    this.speakEnded = true;
    this.report(state);
  }

  private report(state: "started" | "finished" | "flushed"): void {
    this.playback.push(state);
    this.sendJson({ type: "playback", turn_id: this.turnId, state });
  }
}
