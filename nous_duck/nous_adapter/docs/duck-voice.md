> [繁體中文](duck-voice.md) | [English](duck-voice.en.md)

# duck-voice：語音媒體通道（Nous 端）

狀態（2026-11-26）：**通道的 Nous 端做好並測過；真正的對話還不能用。** 這裡只有標示 mock 的「回放」後端（把聽到的聲音放回去，不是語音模型）。把它接到 Nous 的即時語音要改 AIOS，等使用者決定走哪條路線（§7）。

驗證層級：單元／整合測試（對模擬的鴨子音訊端、合成音訊），加上一次「D 線鴨子端真正的狀態機 `session.py` 對這個 hub」的本機互通檢查（合成音訊，沒有麥克風與喇叭）。**沒有任何真人的聲音經過這條通道，沒有實機。**

- 線上格式的正本是鴨子端（D 線）的實作：`robot/audio/duck_audio/session.py`（狀態機）、`voice_service.py`（服務）。D 線的介面草案檔 `protocol/proposals/d-duck-voice-media-channel.md` 在寫這份文件時還沒進 repo；兩份有出入時以鴨子端的程式為準。
- 這份文件說明 Nous 端（`nous_adapter/`）怎麼實作它，以及 Nous 端自己加的規則。
- 相關：[ADR-0010](../../docs/adr/ADR-0010-duck-voice.md)（語音鏈）、[ADR-0003 §6](../../docs/adr/ADR-0003-mobile-terminal-wake-and-find.md)（隱私紅線）、[`voice-path.md`](voice-path.md)（路線比較）。

## 1. 為什麼另外開一條通道

`/duck-link` 是 JSON 控制面（指令、狀態、事件），語音與影像不走它（[`protocol/README`](../../protocol/README.md)）。語音需要二進位、低延遲、而且收音與播放由鴨子的音訊行程（D 線）負責，不是 duckd（A 線）。所以：

| | `/duck-link` | `/duck-voice` |
|---|---|---|
| 內容 | 指令、ack、state、event | 語音 PCM 與回合控制 |
| 鴨子端的行程 | duckd（身體） | 音訊服務（麥克風、喚醒詞、喇叭） |
| Nous 端 | `hub/duck-link-hub.ts` | `hub/duck-voice-hub.ts` |
| 埠與守門 | 同一個埠（開發時 8791）、同一條 SSH 通道、同樣的守門：只綁 loopback、`Host` 檢查、帶 `Origin` 一律拒絕 | 同左 |

兩條通道互不依賴：音訊服務沒開，身體照樣能用；反過來也是。

## 2. 線上格式（以鴨子端為準）

回合制、半雙工。一「輪」＝鴨子聽一段、Nous 回一段。

- 文字框＝JSON 控制訊息。二進位框＝PCM，**沒有標頭**。
- 上行（鴨子 → Nous）：s16le、單聲道、16 kHz、每框 20 ms（640 bytes）。只在鴨子「聽」的那一段送。
- 下行（Nous → 鴨子）：s16le、單聲道、24 kHz。Nous 端每框最多 100 ms（4 800 bytes）。

鴨子 → Nous：

| 訊息 | 欄位 | 意思 |
|---|---|---|
| `hello` | `v: 0`、`uplink`、`downlink`（可多帶 `software`、`mock`） | 連上後的第一則 |
| `turn_start` | `turn_id`、`trigger`（`wake_word`／`follow_up`）、`keyword_id`、`doa_deg` | 開始聽一輪；接著送上行音訊。`wake_word`＝本機偵測到喚醒詞；`follow_up`＝照 Nous 的 `listen` 接著聽 |
| `turn_end` | `turn_id`、`reason`（`remote`／`silence`／`max_duration`／`no_speech`／`cancelled`） | 停止上行 |
| `playback` | `turn_id`、`state`（`started`／`finished`／`flushed`／`refused`）、`reason` | 真的開始出聲／播完／被清空／本機閘門不讓播 |

Nous → 鴨子：

| 訊息 | 欄位 | 意思 |
|---|---|---|
| `hello_ack` | `v: 0`（Nous 端多帶 `software`，後端是模擬時帶 `mock: true`） | 回應 `hello` |
| `listen_stop` | `turn_id` | 使用者說完了（後端判斷），請停止上行 |
| `speak_start` | `turn_id` | 回話開始，之後是下行 PCM |
| `speak_end` | `turn_id` | 這一段回話的 PCM 送完了 |
| `flush` | — | 立刻清空播放佇列 |
| `listen` | — | 請不用喚醒詞接著聽一輪 |
| `session_end` | `reason`（Nous 端加的，見 §4） | 這通對話結束，回到待命 |

## 3. 一通對話怎麼走

```text
鴨子（音訊服務）                         Nous（duck-voice hub）              語音後端
  本機偵測到喚醒詞
  turn_start{1, wake_word} ───────────►  沒有對話 → 向後端開一通 ───────────► start()
  上行 PCM… ──────────────────────────►  （後端還在開：暫放記憶體，≤2 秒）
                                         開好 → 補送暫放的音訊 ─────────────► pushAudio…
  上行 PCM… ──────────────────────────► ───────────────────────────────────► pushAudio…
                                         ◄── 後端：使用者說完了
  ◄─────────────── listen_stop{1}
  turn_end{1, remote} ────────────────►
                                         ◄── 後端：回話的音訊
  ◄─────────────── speak_start{1}
  ◄─────────────── 下行 PCM…
  playback{1, started} ───────────────►  presence → speaking
  ◄─────────────── speak_end{1}
  playback{1, finished} ──────────────►  presence → listening
  ◄─────────────── listen
  turn_start{2, follow_up} ───────────►  （同一通對話的下一輪）
  …一直沒有人說話…
  turn_end{2, no_speech} ─────────────►  結束：關後端
  ◄─────────────── session_end{done}     presence → idle
```

## 4. Nous 端的規則

| 規則 | 作法 |
|---|---|
| 誰決定開麥克風 | **鴨子本機**。Nous 只在收到 `turn_start(wake_word)` 才向後端開一通；只在回話播完（`playback finished`）之後送 `listen`。待命時送 `listen` 沒有用——鴨子端的狀態機不接受 |
| 沒有在聽的時候收到上行音訊 | 丟棄並計數；連續 20 框就關閉連線（代表鴨子端的閘門有問題） |
| 後端還在開的時候 | 上行音訊暫放在記憶體，最多 2 秒；開好就交給後端，開不起來就丟掉 |
| 沒有後端、後端開不起來、太頻繁 | 回 `session_end`，`reason` 是 `no_backend`／`rate_limited`。喚醒開始的對話每 60 秒最多 3 次（和 AIOS 相同） |
| `session_end.reason` | Nous 端加的欄位（鴨子端目前忽略）：`done`、`no_backend`、`busy`、`rate_limited`、`error`、`max_duration`、`backend_lost`。之後鴨子可以依原因播不同的提示音 |
| 誰判斷使用者說完了 | 兩邊都可以：後端先判斷 → Nous 送 `listen_stop`；鴨子先判斷 → 它送 `turn_end(silence／max_duration)`，Nous 轉告後端 |
| 鴨子送 `turn_end(no_speech／cancelled)` | 這通對話結束：關後端、回 `session_end` |
| 鴨子送 `playback refused` | 本機閘門不讓播（靜音時段、隱私開關）：對話結束，不算錯誤 |
| 打斷 | 第一版靠鴨子本機：說話中又聽到喚醒詞 → 鴨子回 `playback flushed` 並開始新的一輪，Nous 叫後端停掉上一段回話。鴨子在說話時不送上行，所以沒有「模型端偵測插話」 |
| 逾時 | 聽的時候 2 秒沒收到上行框 → 結束（`error`）；對話開著但沒在聽、沒在說、沒有回話在路上超過 20 秒 → 結束；單通上限 5 分鐘。「一直沒人說話」由鴨子端判斷 |
| 連線活著與否 | WebSocket 協定層的 ping，每 2 秒；6 秒沒有任何回應就關閉連線 |
| 版本 | `hello.v` 不是 0 → 關閉連線，不嘗試相容 |
| 同時只有一個音訊端 | 新的連線完成 `hello` 就取代舊的 |

### 隱私

- 音訊只在記憶體裡經過。`hub/duck-voice-hub.ts`、`shared/duck-voice.ts` 與回放後端都沒有任何檔案系統的程式（有測試檢查原始碼）。
- log 與事件只有數量與時間：輪數、框數、位元組數、持續時間、結束原因。沒有音訊、沒有文字內容。
- 喚醒前的音訊不離開鴨子：那是鴨子端的責任（D 線）；Nous 端的對應是「沒有在聽的時候收到的框一律丟掉」。

## 5. 和控制面的關係

| 語音通道上發生的事 | 控制面（`/duck-link`）上的結果 |
|---|---|
| `turn_start(wake_word)`，對話開了 | `presence: wake`（至少 600 ms）→ `listening` |
| 後端回報聽到人說話 | `presence: listening` |
| 使用者說完、還沒開始播 | `presence: thinking` |
| `playback started` | `presence: speaking`——**真的出聲才算** |
| `playback finished`／`flushed` | `presence: listening` |
| 對話結束 | `presence: idle`；因錯誤結束先 `error` 約 1.5 秒 |

- `presence` 照舊由 Nous 經 `/duck-link` 送給 duckd，duckd 決定頭與眼睛怎麼演。`speaking` 現在有真實來源了。
- 說話時跟著音量動：**不經網路**。鴨子自己量正在播的聲音（D 線已有音量包絡）；`presence` 只帶狀態，不帶 `speech_level`。
- 喚醒的方向（`doa_deg`）原樣放進終端事件 `wake_word` 的資料裡；要不要轉向聲源是鴨子本機的事（A 線的 `track sound`）。
- `duckctl events` 看得到 `wake_word`（含這次有沒有開成對話）與 `voice_session_ended`（只有數量）。

## 6. 語音後端的介面

hub 不知道後端是誰。介面在 `hub/duck-voice-hub.ts`：

```ts
interface VoiceBackend {
  readonly label: string;
  readonly mock: boolean;
  start(info: { sessionId: string; keywordId?: string }, sink: VoiceBackendSink): Promise<VoiceBackendCall>;
}
interface VoiceBackendCall {
  pushAudio(pcm: Buffer): void;        // 上行：s16le／16 kHz／單聲道
  endTurn?(): void;                    // 鴨子判斷使用者說完了
  cancelReply?(): void;                // 回話被打斷
  playback?(state: PlaybackState): void;
  close(reason: string): void | Promise<void>;
}
interface VoiceBackendSink {
  phase(phase: "listening" | "hearing" | "thinking"): void;   // thinking＝使用者說完了
  audio(pcm: Buffer): void;            // 回話：s16le／24 kHz／單聲道
  audioEnd(): void;
  interrupt(): void;                   // 請鴨子清空播放
  end(reason: SessionEndReason): void;
}
```

本 repo 裡的後端：

| 後端 | 是什麼 | 用途 |
|---|---|---|
| 沒有（預設） | 每次喚醒都回 `session_end: no_backend` | 誠實的預設：這裡沒有語音模型 |
| `echo`（`mock/echo-voice-backend.ts`） | **模擬**：把聽到的聲音在你停止說話後原樣放回去。不辨識、不理解、不生成 | 讓兩端先把通道、開始結束、播放回報、接著聽跑通 |

## 7. 還差什麼才是真的對話

真正的後端要接 Nous 的即時語音，這要改 AIOS。AIOS 的現況（唯讀查閱 main `265cbee`）：兩條即時語音路徑的音訊都是「瀏覽器頁面 ↔ 雲端模型」的 WebRTC，核心從不經手音訊，也沒有任何讓非瀏覽器裝置當語音終端的機制。兩條可行的路線：

| | 路線 1：核心端的鴨子語音工作階段 | 路線 2：鴨子的 Pi 上跑 Chromium 開 Nous 頁面 |
|---|---|---|
| 作法 | AIOS 核心用 WebSocket 連即時語音模型，實作上面的 `VoiceBackend`；這條 `/duck-voice` 通道原樣搬進核心 | 對話的收音與播放由 Pi 上的瀏覽器做；AIOS 加一個小改動讓鴨子的喚醒能叫頁面開始對話 |
| 用得到這條通道嗎 | 用得到（全部） | 用不到（對話音訊走瀏覽器） |
| D 線的原生收音、變聲、閘門 | 全部用得上 | 對話音訊不經過它們 |
| AIOS 改動 | 估 500～800 行含測試，旗標預設關閉 | 約 100～150 行加測試 |
| 限制 | 只能用 OpenAI API key、依用量計費的那條路徑；第一版沒有家庭記憶、家人問候、頁面工具與確認卡 | Pi 4 同時跑 Chromium 的負載、無螢幕下取得麥克風、回音消除都沒驗證 |
| 驗證狀態 | 沒有任何實測；模型的 WebSocket 模式在 AIOS 沒有既有程式 | 沒有任何實測（上次 spike 只量到沒有麥克風的情況） |

**走哪一條要使用者決定**（有沒有可以給鴨子用的 OpenAI API key、接不接受依用量計費）。拿到決定與授權之前，AIOS 沒有任何改動。

## 8. 怎麼試（不需要鴨子、不出聲）

```bash
cd nous_duck/nous_adapter
bin/duckctl hub --voice echo        # 分頁 1：hub，語音通道接模擬的回放後端
bin/duckctl mock-voice              # 分頁 2：模擬的鴨子音訊端送一次「喚醒」與合成音
bin/duckctl voice                   # 看通道的狀態與上一通的統計
bin/duckctl events                  # wake_word、voice_session_ended
```

`mock-voice` 會印出收到的控制訊息順序（`hello_ack → listen_stop → speak_start → speak_end → listen`）、下行的框數與播放回報。全部標示模擬。

接上真的鴨子音訊端（D 線的 `voice_service`）的步驟見 [`voice-test.md`](voice-test.md)。

## 9. 沒有驗證的事

- 真人的聲音、真的麥克風與喇叭、XVF3800 的回音消除夠不夠讓半雙工以外的模式成立。
- 經 Wi-Fi 與 SSH 通道時的延遲與抖動（24 kHz PCM 約 48 kB/s 下行、16 kHz 約 32 kB/s 上行）。
- 任何真正的語音模型。回合切換的時機（誰先判斷說完）在真的對話裡順不順。
- 長時間連線、音訊端重啟、和 duckd 同時運作的負載。
