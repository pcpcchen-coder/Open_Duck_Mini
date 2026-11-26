// duck-voice v0：鴨子與 Nous 之間的語音媒體通道（和 /duck-link 的 JSON 控制面分開）。
// 線上格式以鴨子端（D 線，robot/audio/duck_audio/session.py 與 voice_service.py）的實作為準；
// 這個檔案是 Nous 端的型別、常數與控制訊息的檢查。介面說明見 docs/duck-voice.md。
// 目前沒有獨立的 JSON Schema 檔（protocol/schemas 由整合線管理）。
//
// 回合制、半雙工：鴨子本機偵測到喚醒詞才開始一輪（turn_start），只有在「聽」的那一段送上行音訊；
// 什麼時候開麥克風永遠由鴨子本機決定，Nous 只能在剛說完話時請它接著聽一輪（listen）。
// 隱私：音訊只在記憶體裡經過。這裡與 hub 都不把音訊寫檔、不放進 log；只記框數與位元組數。

export const VOICE_PROTOCOL = 0;
export const DUCK_VOICE_PATH = "/duck-voice";

/** 上行（鴨子 → Nous）：二進位框就是 PCM，沒有標頭。s16le、單聲道、16 kHz、每框 20 ms。 */
export const UPLINK = { rate: 16_000, frameMs: 20, frameBytes: 640 } as const;
/** 下行（Nous → 鴨子）：二進位框就是 PCM。s16le、單聲道、24 kHz（即時語音模型的原生格式），每框 20 ms。 */
export const DOWNLINK = { rate: 24_000, frameMs: 20, frameBytes: 960 } as const;

export const TURN_TRIGGERS = ["wake_word", "follow_up"] as const;
export type TurnTrigger = (typeof TURN_TRIGGERS)[number];

/** 鴨子結束「聽」的原因：remote＝照 Nous 的 listen_stop／speak_start；silence／max_duration＝鴨子自己判斷說完了；no_speech＝一直沒人說話；cancelled＝設定關掉或本機取消。 */
export const TURN_END_REASONS = ["remote", "silence", "max_duration", "no_speech", "cancelled"] as const;
export type TurnEndReason = (typeof TURN_END_REASONS)[number];

/** 鴨子回報的播放狀態：started＝真的開始出聲；finished＝播完；flushed＝被清空；refused＝本機閘門不讓播（靜音時段、隱私開關…）。 */
export const PLAYBACK_STATES = ["started", "finished", "flushed", "refused"] as const;
export type PlaybackState = (typeof PLAYBACK_STATES)[number];

/** Nous 結束對話時附帶的原因（session_end.reason；鴨子端可以忽略）。 */
export const SESSION_END_REASONS = ["done", "no_backend", "busy", "rate_limited", "error", "max_duration", "backend_lost"] as const;
export type SessionEndReason = (typeof SESSION_END_REASONS)[number];

export type DuckVoiceMessage =
  | { type: "hello"; v: number; uplink?: Record<string, unknown>; downlink?: Record<string, unknown>; software?: string; mock?: boolean }
  | { type: "turn_start"; turn_id: number; trigger: TurnTrigger; keyword_id?: string | null; doa_deg?: number | null }
  | { type: "turn_end"; turn_id: number; reason: TurnEndReason }
  | { type: "playback"; turn_id: number; state: PlaybackState; reason?: string };

export type NousVoiceMessage =
  | { type: "hello_ack"; v: typeof VOICE_PROTOCOL; software?: string; mock?: boolean }
  | { type: "listen_stop"; turn_id: number }
  | { type: "speak_start"; turn_id: number }
  | { type: "speak_end"; turn_id: number }
  | { type: "flush" }
  | { type: "listen" }
  | { type: "session_end"; reason?: SessionEndReason };

const NAME = /^[a-z0-9_]{1,48}$/;
const isRecord = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const isTurnId = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v) && v >= 0 && v <= 0xffffffff;

export type VoiceParse = { ok: true; message: DuckVoiceMessage } | { ok: false; error: string };

/**
 * 檢查鴨子送來的控制訊息。錯誤說明只有規則，不回顯內容。
 * 不認得的欄位忽略（鴨子端之後可能多帶欄位）；不認得的 type 算不合格。
 * hello 的版本不是 0 回 error "version"（呼叫端據此關閉連線，不猜測）。
 */
export function parseDuckVoiceMessage(text: string): VoiceParse {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    return { ok: false, error: "不是合法的 JSON" };
  }
  if (!isRecord(value)) return { ok: false, error: "不是物件" };
  switch (value.type) {
    case "hello": {
      if (value.v !== VOICE_PROTOCOL) return { ok: false, error: "version" };
      if (isRecord(value.uplink) && value.uplink.rate !== undefined && value.uplink.rate !== UPLINK.rate) return { ok: false, error: "hello.uplink.rate 不是 16000" };
      if (isRecord(value.downlink) && value.downlink.rate !== undefined && value.downlink.rate !== DOWNLINK.rate) return { ok: false, error: "hello.downlink.rate 不是 24000" };
      if (value.software !== undefined && (typeof value.software !== "string" || value.software.length > 80)) return { ok: false, error: "hello.software 不正確" };
      if (value.mock !== undefined && typeof value.mock !== "boolean") return { ok: false, error: "hello.mock 不正確" };
      break;
    }
    case "turn_start": {
      if (!isTurnId(value.turn_id)) return { ok: false, error: "turn_start.turn_id 不正確" };
      if (!(TURN_TRIGGERS as readonly unknown[]).includes(value.trigger)) return { ok: false, error: "turn_start.trigger 不正確" };
      if (value.keyword_id !== undefined && value.keyword_id !== null && (typeof value.keyword_id !== "string" || !NAME.test(value.keyword_id))) return { ok: false, error: "turn_start.keyword_id 不正確" };
      if (value.doa_deg !== undefined && value.doa_deg !== null && (typeof value.doa_deg !== "number" || !Number.isFinite(value.doa_deg) || Math.abs(value.doa_deg) > 360)) return { ok: false, error: "turn_start.doa_deg 不正確" };
      break;
    }
    case "turn_end": {
      if (!isTurnId(value.turn_id)) return { ok: false, error: "turn_end.turn_id 不正確" };
      if (!(TURN_END_REASONS as readonly unknown[]).includes(value.reason)) return { ok: false, error: "turn_end.reason 不正確" };
      break;
    }
    case "playback": {
      if (!isTurnId(value.turn_id)) return { ok: false, error: "playback.turn_id 不正確" };
      if (!(PLAYBACK_STATES as readonly unknown[]).includes(value.state)) return { ok: false, error: "playback.state 不正確" };
      if (value.reason !== undefined && (typeof value.reason !== "string" || value.reason.length > 80)) return { ok: false, error: "playback.reason 不正確" };
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
