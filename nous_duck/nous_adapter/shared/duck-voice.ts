// duck-voice v0：鴨子與 Nous 之間的語音媒體通道（和 /duck-link 的 JSON 控制面分開）。
// 介面說明見 docs/duck-voice.md；這個檔案是 Nous 端的型別、常數、二進位框的編解碼與控制訊息的檢查。
// 目前沒有獨立的 JSON Schema 檔（protocol/schemas 由整合線管理）；要不要正式納入協定見
// ../../protocol/proposals/b-nous-duck-voice-channel.md。
//
// 隱私：這條通道上的音訊只在記憶體裡經過。這裡與 hub 都不把音訊寫檔、不放進 log；只記框數與位元組數。

export const VOICE_VERSION = "0.1";
export const DUCK_VOICE_PATH = "/duck-voice";

/** 上行（鴨子 → Nous）：s16le、單聲道、16 kHz、每框 20 ms。 */
export const UPLINK = { rate: 16_000, frameMs: 20, frameBytes: 640 } as const;
/** 下行（Nous → 鴨子）：s16le、單聲道、24 kHz（即時語音模型的原生格式），每框最長 100 ms。 */
export const DOWNLINK = { rate: 24_000, maxFrameMs: 100, maxFrameBytes: 4_800 } as const;

export const FRAME_HEADER_BYTES = 8;
export const FRAME_UPLINK = 1;
export const FRAME_DOWNLINK = 2;

export interface AudioFrame {
  kind: typeof FRAME_UPLINK | typeof FRAME_DOWNLINK;
  seq: number;
  /** s16le 單聲道 PCM（是原始緩衝區的一段視圖，不複製）。 */
  pcm: Buffer;
}

/** 二進位框：byte0 = 種類（1 上行、2 下行）；byte1-3 = 0（保留）；byte4-7 = uint32 big-endian 序號；之後是 PCM。 */
export function encodeFrame(kind: AudioFrame["kind"], seq: number, pcm: Buffer): Buffer {
  const out = Buffer.allocUnsafe(FRAME_HEADER_BYTES + pcm.length);
  out[0] = kind;
  out[1] = 0;
  out[2] = 0;
  out[3] = 0;
  out.writeUInt32BE(seq >>> 0, 4);
  pcm.copy(out, FRAME_HEADER_BYTES);
  return out;
}

/** 解不開（太短、種類不對、保留位不是 0、PCM 不是偶數個 byte 或是空的）回 null。 */
export function decodeFrame(data: Buffer): AudioFrame | null {
  if (data.length <= FRAME_HEADER_BYTES) return null;
  const kind = data[0];
  if (kind !== FRAME_UPLINK && kind !== FRAME_DOWNLINK) return null;
  if (data[1] !== 0 || data[2] !== 0 || data[3] !== 0) return null;
  const pcm = data.subarray(FRAME_HEADER_BYTES);
  if (pcm.length % 2 !== 0) return null;
  return { kind, seq: data.readUInt32BE(4), pcm };
}

// ---- 控制訊息（文字框，JSON） ----

export const SESSION_REFUSALS = ["no_backend", "busy", "rate_limited", "disabled"] as const;
export type SessionRefusal = (typeof SESSION_REFUSALS)[number];

/** Nous 結束工作階段的原因。 */
export const NOUS_END_REASONS = ["done", "silence", "max_duration", "error", "backend_lost"] as const;
export type NousEndReason = (typeof NOUS_END_REASONS)[number];
/** 鴨子結束工作階段的原因。 */
export const DUCK_END_REASONS = ["user", "local_stop", "privacy", "error"] as const;
export type DuckEndReason = (typeof DUCK_END_REASONS)[number];

export const PLAYBACK_STATES = ["started", "drained", "cleared"] as const;
export type PlaybackState = (typeof PLAYBACK_STATES)[number];

export type DuckVoiceMessage =
  | { v: typeof VOICE_VERSION; type: "hello"; role: "duck"; software: string; mock?: boolean; uplink?: { rate: number; frame_ms: number }; downlink?: { rate: number } }
  | { v: typeof VOICE_VERSION; type: "wake"; wake_id: string; keyword_id?: string; doa_deg?: number }
  | { v: typeof VOICE_VERSION; type: "playback"; session_id: string; state: PlaybackState; played_ms?: number }
  | { v: typeof VOICE_VERSION; type: "end"; session_id: string; reason: DuckEndReason }
  | { v: typeof VOICE_VERSION; type: "pong"; t: number };

export type NousVoiceMessage =
  | { v: typeof VOICE_VERSION; type: "hello"; role: "nous"; software: string; mock?: boolean }
  | { v: typeof VOICE_VERSION; type: "session"; session_id: string; wake_id?: string; state: "open" }
  | { v: typeof VOICE_VERSION; type: "session"; session_id: string; wake_id?: string; state: "refused"; reason: SessionRefusal }
  | { v: typeof VOICE_VERSION; type: "clear"; session_id: string }
  | { v: typeof VOICE_VERSION; type: "end"; session_id: string; reason: NousEndReason }
  | { v: typeof VOICE_VERSION; type: "ping"; t: number };

const ID = /^[A-Za-z0-9_-]{8,64}$/;
const NAME = /^[a-z0-9_]{1,48}$/;
const isRecord = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const onlyKeys = (v: Record<string, unknown>, keys: readonly string[]) => Object.keys(v).every((k) => keys.includes(k));

export type VoiceParse = { ok: true; message: DuckVoiceMessage } | { ok: false; error: string };

/**
 * 檢查鴨子送來的控制訊息。錯誤說明只有規則，不回顯內容。
 * 版本不是 "0.1" 回 error "version"（呼叫端據此關閉連線，不猜測）。
 */
export function parseDuckVoiceMessage(text: string): VoiceParse {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    return { ok: false, error: "不是合法的 JSON" };
  }
  if (!isRecord(value)) return { ok: false, error: "不是物件" };
  if (value.v !== VOICE_VERSION) return { ok: false, error: "version" };
  switch (value.type) {
    case "hello": {
      if (!onlyKeys(value, ["v", "type", "role", "software", "mock", "uplink", "downlink"])) return { ok: false, error: "hello 有不認得的欄位" };
      if (value.role !== "duck") return { ok: false, error: "hello.role 必須是 duck" };
      if (typeof value.software !== "string" || !value.software || value.software.length > 80) return { ok: false, error: "hello.software 不正確" };
      if (value.mock !== undefined && typeof value.mock !== "boolean") return { ok: false, error: "hello.mock 不正確" };
      if (value.uplink !== undefined && !(isRecord(value.uplink) && value.uplink.rate === UPLINK.rate && value.uplink.frame_ms === UPLINK.frameMs)) return { ok: false, error: "hello.uplink 不是 16000 Hz／20 ms" };
      if (value.downlink !== undefined && !(isRecord(value.downlink) && value.downlink.rate === DOWNLINK.rate)) return { ok: false, error: "hello.downlink 不是 24000 Hz" };
      break;
    }
    case "wake": {
      if (!onlyKeys(value, ["v", "type", "wake_id", "keyword_id", "doa_deg"])) return { ok: false, error: "wake 有不認得的欄位" };
      if (typeof value.wake_id !== "string" || !ID.test(value.wake_id)) return { ok: false, error: "wake.wake_id 不正確" };
      if (value.keyword_id !== undefined && (typeof value.keyword_id !== "string" || !NAME.test(value.keyword_id))) return { ok: false, error: "wake.keyword_id 不正確" };
      if (value.doa_deg !== undefined && (typeof value.doa_deg !== "number" || !Number.isFinite(value.doa_deg) || value.doa_deg < -360 || value.doa_deg > 360)) return { ok: false, error: "wake.doa_deg 不正確" };
      break;
    }
    case "playback": {
      if (!onlyKeys(value, ["v", "type", "session_id", "state", "played_ms"])) return { ok: false, error: "playback 有不認得的欄位" };
      if (typeof value.session_id !== "string" || !ID.test(value.session_id)) return { ok: false, error: "playback.session_id 不正確" };
      if (!(PLAYBACK_STATES as readonly unknown[]).includes(value.state)) return { ok: false, error: "playback.state 不正確" };
      if (value.played_ms !== undefined && (typeof value.played_ms !== "number" || !Number.isFinite(value.played_ms) || value.played_ms < 0)) return { ok: false, error: "playback.played_ms 不正確" };
      break;
    }
    case "end": {
      if (!onlyKeys(value, ["v", "type", "session_id", "reason"])) return { ok: false, error: "end 有不認得的欄位" };
      if (typeof value.session_id !== "string" || !ID.test(value.session_id)) return { ok: false, error: "end.session_id 不正確" };
      if (!(DUCK_END_REASONS as readonly unknown[]).includes(value.reason)) return { ok: false, error: "end.reason 不正確" };
      break;
    }
    case "pong": {
      if (!onlyKeys(value, ["v", "type", "t"])) return { ok: false, error: "pong 有不認得的欄位" };
      if (typeof value.t !== "number" || !Number.isFinite(value.t)) return { ok: false, error: "pong.t 不正確" };
      break;
    }
    default:
      return { ok: false, error: "不認得的 type" };
  }
  return { ok: true, message: value as unknown as DuckVoiceMessage };
}

// ---- PCM 小工具（只在記憶體裡算，不保存） ----

/** s16le 單聲道 PCM 的均方根，正規化到 0～1。 */
export function pcmRms(pcm: Buffer): number {
  const n = Math.floor(pcm.length / 2);
  if (!n) return 0;
  let sum = 0;
  for (let i = 0; i < n; i++) {
    const s = pcm.readInt16LE(i * 2) / 32768;
    sum += s * s;
  }
  return Math.sqrt(sum / n);
}

/** PCM 的長度（毫秒）。 */
export function pcmMs(bytes: number, rate: number): number {
  return (bytes / 2 / rate) * 1000;
}

/** 線性內插重取樣（s16le 單聲道）。只給開發用的回放後端用；品質不講究。 */
export function resampleLinear(pcm: Buffer, fromRate: number, toRate: number): Buffer {
  const n = Math.floor(pcm.length / 2);
  if (!n || fromRate === toRate) return Buffer.from(pcm.subarray(0, n * 2));
  const outN = Math.max(1, Math.round((n * toRate) / fromRate));
  const out = Buffer.allocUnsafe(outN * 2);
  for (let i = 0; i < outN; i++) {
    const pos = (i * fromRate) / toRate;
    const i0 = Math.min(n - 1, Math.floor(pos));
    const i1 = Math.min(n - 1, i0 + 1);
    const frac = pos - i0;
    out.writeInt16LE(Math.round(pcm.readInt16LE(i0 * 2) * (1 - frac) + pcm.readInt16LE(i1 * 2) * frac), i * 2);
  }
  return out;
}
