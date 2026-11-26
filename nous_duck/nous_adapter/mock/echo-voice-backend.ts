import type { VoiceBackend, VoiceBackendCall, VoiceBackendSink } from "../hub/duck-voice-hub.ts";
import { DOWNLINK, pcmMs, pcmRms, resampleLinear, UPLINK } from "../shared/duck-voice.ts";

// ⚠️ MOCK 語音後端：**不是語音模型，不辨識、不理解、不生成任何話**。
// 它做的事：聽到一段聲音（音量超過門檻）、安靜一小段時間之後（或鴨子說「這一輪說完了」），把剛才那段聲音原樣放回去。
// 用途：在真正的語音後端（要改 AIOS，等使用者授權）接上之前，讓鴨子端與 Nous 端先把
// 通道、開始與結束、播放回報、接著聽下一輪這幾件事跑通。
// 隱私：聽到的聲音只放在記憶體裡的一個緩衝區（最多 maxSeconds 秒），放回去之後立刻丟掉；不寫檔、不進 log。

export interface EchoBackendOptions {
  /** 音量門檻（0～1 的 RMS）。 */
  speechRms?: number;
  /** 說完之後安靜多久才回放。 */
  endSilenceMs?: number;
  /** 一段話最多留幾秒。 */
  maxSeconds?: number;
  /** 回放幾次之後結束這通對話（0＝不主動結束）。 */
  endAfterReplies?: number;
}

export class EchoVoiceBackend implements VoiceBackend {
  readonly label = "echo（模擬：把聽到的聲音原樣放回去，不是語音模型）";
  readonly mock = true;

  constructor(private readonly options: EchoBackendOptions = {}) {}

  async start(_info: { sessionId: string }, sink: VoiceBackendSink): Promise<VoiceBackendCall> {
    const speechRms = this.options.speechRms ?? 0.01;
    const endSilenceMs = this.options.endSilenceMs ?? 800;
    const maxBytes = Math.round((this.options.maxSeconds ?? 10) * UPLINK.rate * 2);
    const endAfter = this.options.endAfterReplies ?? 0;
    let chunks: Buffer[] = [];
    let bytes = 0;
    let quietMs = 0;
    let hearing = false;
    let replies = 0;
    let closed = false;

    const reply = () => {
      if (!bytes) return;
      const heard = Buffer.concat(chunks);
      chunks = [];
      bytes = 0;
      hearing = false;
      quietMs = 0;
      replies += 1;
      sink.phase("thinking");
      sink.audio(resampleLinear(heard, UPLINK.rate, DOWNLINK.rate));
      sink.audioEnd();
    };

    return {
      pushAudio(pcm) {
        if (closed) return;
        if (pcmRms(pcm) >= speechRms) {
          if (!hearing) {
            hearing = true;
            sink.phase("hearing");
          }
          quietMs = 0;
        } else if (hearing) {
          quietMs += pcmMs(pcm.length, UPLINK.rate);
        }
        if (hearing && bytes < maxBytes) {
          chunks.push(Buffer.from(pcm)); // 複製：呼叫端的緩衝區會被重用
          bytes += pcm.length;
        }
        if (hearing && (quietMs >= endSilenceMs || bytes >= maxBytes)) reply();
      },
      endTurn() {
        if (!closed && hearing) reply();
      },
      cancelReply() {
        chunks = [];
        bytes = 0;
        hearing = false;
      },
      playback(state) {
        if (!closed && state === "finished" && endAfter && replies >= endAfter) sink.end("done");
      },
      close() {
        closed = true;
        chunks = [];
        bytes = 0;
      },
    };
  }
}
