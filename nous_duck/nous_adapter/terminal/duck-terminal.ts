import type { DuckLink } from "../hub/duck-link-hub.ts";
import type { ToolResult } from "../shared/aios-integrations.ts";
import type { DuckEventName, EventMessage, PresenceState } from "../shared/duck-link.ts";
import { PresenceDriver, type PresenceDriverOptions, type PresenceSource } from "./presence.ts";

// DuckTerminal：鴨子作為「終端」的那一半（ADR-0001 §2）。方向和 DuckAdapter 相反：
//   鴨子 → Nous：事件（跌倒、斷線、任務進度…）整理後交給 sink
//   Nous → 鴨子：presence（語音工作階段的真實狀態）
// 語音與影像不走這裡（也不走 duck-link 的 JSON）；見 docs/voice-path.md。
//
// 這裡只定義入口與整理方式。事件進到 Nous 之後要做什麼（唸出來、接續任務、記到紀錄）是 AIOS 的批次，
// 目前 AIOS 沒有任何接收裝置事件的入口（docs/aios-integration-plan.md §5），所以現在只有開發用的 sink（duckctl events）。

export type TerminalEventCategory = "safety" | "link" | "mission" | "motion" | "wake" | "dock" | "config";

/** notify＝應該讓使用者知道（之後由 Nous 決定怎麼說）；info＝只記錄。 */
export type TerminalEventAttention = "notify" | "info";

export interface TerminalEvent {
  /** hub 收到的時間（epoch ms）。 */
  at: number;
  /** duck＝鴨子回報的事實；hub＝Nous 端自己觀察到的（連線建立或中斷）。 */
  origin: "duck" | "hub";
  name: DuckEventName | "duck_connected" | "duck_disconnected" | "voice_session_ended";
  category: TerminalEventCategory;
  attention: TerminalEventAttention;
  /** 對面是模擬的鴨子。 */
  mock: boolean;
  event_id?: string;
  request_id?: string;
  mission_id?: string;
  /** 固定的原因代碼（不是自由文字）。 */
  reason?: string;
  data?: Record<string, unknown>;
}

/** DuckTerminal 需要語音通道提供的部分（hub/duck-voice-hub.ts 的 DuckVoiceHub 實作它）。 */
export interface VoiceEvents extends PresenceSource {
  onWake(listener: (wake: { turnId: number; keywordId?: string; doaDeg?: number; at: number; outcome: string; mock: boolean }) => void): () => void;
  onSessionEnd(listener: (stats: { reason: string; durationMs: number; turns: number; replies: number; uplinkFrames: number; downlinkFrames: number; heardSpeech: boolean; interruptions: number; mock: boolean }) => void): () => void;
}

export interface DuckEventSink {
  deliver(event: TerminalEvent): void;
}

const CATEGORY: Record<DuckEventName, [TerminalEventCategory, TerminalEventAttention]> = {
  fell: ["safety", "notify"],
  picked_up: ["safety", "info"],
  estop: ["safety", "notify"],
  estop_cleared: ["safety", "info"],
  battery_low: ["safety", "notify"],
  overheat: ["safety", "notify"],
  motor_error: ["safety", "notify"],
  link_lost: ["link", "info"],
  link_restored: ["link", "info"],
  controller_takeover: ["link", "info"],
  gesture_done: ["motion", "info"],
  walk_done: ["motion", "info"],
  tracking_lost: ["motion", "info"],
  tracking_acquired: ["motion", "info"],
  mission_progress: ["mission", "info"],
  mission_done: ["mission", "notify"],
  mission_failed: ["mission", "notify"],
  wake_word: ["wake", "notify"],
  docked: ["dock", "info"],
  undocked: ["dock", "info"],
  charging_started: ["dock", "info"],
  charging_stopped: ["dock", "info"],
  privacy_switch: ["config", "notify"],
  capability_changed: ["config", "info"],
};

export interface MissionRecord {
  mission_id: string;
  status: "running" | "done" | "failed";
  progress?: number;
  phase?: string;
  reason?: string;
  updatedAt: number;
}

export interface DuckTerminalOptions {
  sink?: DuckEventSink;
  /** presence 怎麼送（通常是 DuckAdapter.presence）。 */
  sendPresence: (state: PresenceState, speechLevel?: number) => Promise<ToolResult>;
  presence?: Omit<PresenceDriverOptions, "send">;
  /** 保留最近幾則事件（給診斷與 duckctl events）。 */
  keep?: number;
  now?: () => number;
  log?: (line: string) => void;
}

export class DuckTerminal {
  readonly presence: PresenceDriver;
  private readonly recent: TerminalEvent[] = [];
  private readonly missions = new Map<string, MissionRecord>();
  private readonly listeners = new Set<(event: TerminalEvent) => void>();
  private readonly unsubscribers: (() => void)[] = [];
  private readonly keep: number;
  private readonly now: () => number;

  constructor(
    private readonly link: DuckLink,
    private readonly options: DuckTerminalOptions,
  ) {
    this.keep = options.keep ?? 100;
    this.now = options.now ?? Date.now;
    this.presence = new PresenceDriver({ ...options.presence, send: options.sendPresence, ...(options.log ? { log: options.log } : {}) });
    this.unsubscribers.push(
      link.onEvent((event) => this.fromDuck(event)),
      link.onLink((change) => {
        if (change.up) {
          this.publish({ at: this.now(), origin: "hub", name: "duck_connected", category: "link", attention: "info", mock: change.hello.mock === true });
          // 鴨子（重新）連上：把目前的 presence 再送一次。
          this.presence.resend();
        } else {
          this.publish({ at: this.now(), origin: "hub", name: "duck_disconnected", category: "link", attention: "notify", mock: this.isMock(), reason: change.reason });
          // 斷線時進行中的任務結果不明：不改成 done 或 failed，維持最後已知的狀態。
        }
      }),
    );
  }

  attachPresenceSource(source: PresenceSource): void {
    this.presence.attach(source);
  }

  /**
   * 接上語音通道：它的真實事件（喚醒、開始、鴨子回報的播放狀態、結束）驅動 presence；
   * 喚醒與對話結束也整理成終端事件。喚醒是鴨子的音訊端本機偵測到的，這裡不保存也看不到任何音訊。
   */
  attachVoice(voice: VoiceEvents): void {
    this.presence.attach(voice);
    this.unsubscribers.push(
      voice.onWake((wake) =>
        this.publish({
          at: wake.at,
          origin: "duck",
          name: "wake_word",
          category: "wake",
          attention: wake.outcome === "open" ? "info" : "notify",
          mock: wake.mock,
          ...(wake.outcome === "open" ? {} : { reason: `voice_${wake.outcome}` }),
          data: { turn_id: wake.turnId, outcome: wake.outcome, ...(wake.keywordId ? { keyword_id: wake.keywordId } : {}), ...(wake.doaDeg !== undefined ? { doa_deg: wake.doaDeg } : {}) },
        }),
      ),
      voice.onSessionEnd((stats) =>
        this.publish({
          at: this.now(),
          origin: "hub",
          name: "voice_session_ended",
          category: "wake",
          attention: "info",
          mock: stats.mock,
          reason: stats.reason,
          // 只有數量與時間，沒有內容。
          data: { duration_ms: Math.round(stats.durationMs), turns: stats.turns, replies: stats.replies, uplink_frames: stats.uplinkFrames, downlink_frames: stats.downlinkFrames, heard_speech: stats.heardSpeech, interruptions: stats.interruptions },
        }),
      ),
    );
  }

  stop(): void {
    for (const off of this.unsubscribers.splice(0)) off();
    this.presence.stop();
  }

  onEvent(listener: (event: TerminalEvent) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /** 最近的事件（舊到新）。 */
  events(): readonly TerminalEvent[] {
    return this.recent;
  }

  mission(missionId: string): MissionRecord | null {
    return this.missions.get(missionId) ?? null;
  }

  private isMock(): boolean {
    const snapshot = this.link.snapshot();
    return snapshot.hello?.mock === true || snapshot.state?.mock === true;
  }

  private fromDuck(event: EventMessage): void {
    const [category, attention] = CATEGORY[event.event];
    const at = this.now();
    if (category === "mission" && event.mission_id) {
      const previous = this.missions.get(event.mission_id);
      const progress = typeof event.data?.progress === "number" ? event.data.progress : previous?.progress;
      const phase = typeof event.data?.phase === "string" ? event.data.phase : previous?.phase;
      this.missions.set(event.mission_id, {
        mission_id: event.mission_id,
        status: event.event === "mission_done" ? "done" : event.event === "mission_failed" ? "failed" : "running",
        ...(progress !== undefined ? { progress } : {}),
        ...(phase !== undefined ? { phase } : {}),
        ...(event.reason ? { reason: event.reason } : {}),
        updatedAt: at,
      });
      if (this.missions.size > 32) this.missions.delete(this.missions.keys().next().value!);
    }
    this.publish({
      at,
      origin: "duck",
      name: event.event,
      category,
      attention,
      mock: this.isMock(),
      event_id: event.event_id,
      ...(event.request_id ? { request_id: event.request_id } : {}),
      ...(event.mission_id ? { mission_id: event.mission_id } : {}),
      ...(event.reason ? { reason: event.reason } : {}),
      ...(event.data ? { data: event.data } : {}),
    });
  }

  private publish(event: TerminalEvent): void {
    this.recent.push(event);
    if (this.recent.length > this.keep) this.recent.shift();
    try {
      this.options.sink?.deliver(event);
    } catch (error) {
      this.options.log?.(`事件 sink 丟出錯誤：${error instanceof Error ? error.message : String(error)}`);
    }
    for (const l of this.listeners) l(event);
  }
}
