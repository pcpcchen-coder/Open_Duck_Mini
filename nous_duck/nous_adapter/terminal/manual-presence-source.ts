import type { PresenceState } from "../shared/duck-link.ts";
import type { PresenceSource, VoiceSessionEvent } from "./presence.ts";

// ⚠️ 開發用的手動 presence 來源。事件是人從終端機（duckctl presence …）觸發的，**不是** Nous 語音工作階段的事件。
// 用途：在 AIOS 還接不到真實事件之前，讓人親手看鴨子對每個 presence 狀態的反應。
// 不能拿它的結果宣稱「鴨子會跟著 Nous 的對話做動作」——那要等 AIOS 的批次完成（docs/aios-integration-plan.md §6）。

export class ManualPresenceSource implements PresenceSource {
  readonly label = "dev_manual（開發用手動來源，不是 Nous 的事件）";
  readonly dev = true;
  private readonly listeners = new Set<(event: VoiceSessionEvent) => void>();

  subscribe(listener: (event: VoiceSessionEvent) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  emit(event: VoiceSessionEvent): void {
    for (const l of this.listeners) l(event);
  }

  /**
   * 把「想看的 presence 狀態」換成等效的工作階段事件，走和真實事件相同的對應與節流。
   * level（0～1）只在 speaking 有意義；這裡換成 RMS 時假設滿格是 fullScaleRms。
   */
  request(state: PresenceState, level?: number, fullScaleRms = 0.2): void {
    switch (state) {
      case "idle":
        this.emit({ kind: "sleep", asleep: false });
        this.emit({ kind: "session_ended", reason: "ended" });
        break;
      case "sleeping":
        this.emit({ kind: "session_ended", reason: "ended" });
        this.emit({ kind: "sleep", asleep: true });
        break;
      case "wake":
        this.emit({ kind: "session_started", source: "wake_word" });
        break;
      case "listening":
        this.emit({ kind: "session_started", source: "user" });
        this.emit({ kind: "phase", phase: "listening" });
        break;
      case "thinking":
        this.emit({ kind: "session_started", source: "user" });
        this.emit({ kind: "working", active: false });
        this.emit({ kind: "phase", phase: "thinking" });
        break;
      case "working":
        this.emit({ kind: "session_started", source: "user" });
        this.emit({ kind: "phase", phase: "thinking" });
        this.emit({ kind: "working", active: true });
        break;
      case "speaking":
        this.emit({ kind: "session_started", source: "user" });
        this.emit({ kind: "phase", phase: "speaking" });
        if (level !== undefined) this.emit({ kind: "speech_level", rms: level * fullScaleRms });
        break;
      case "error":
        this.emit({ kind: "session_ended", reason: "error" });
        break;
    }
  }
}
