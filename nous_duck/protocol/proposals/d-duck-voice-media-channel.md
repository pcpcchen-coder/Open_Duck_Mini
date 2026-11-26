> [繁體中文](d-duck-voice-media-channel.md) | [English](d-duck-voice-media-channel.en.md)

# 協定提案（D 線）：duck-voice v0——鴨子與 Nous 之間的語音媒體通道

- 提出：D 線（鴨子端音訊），2026-11-26。**沒有改 duck-link schema。**
- 狀態：**草案，鴨子端已照這份實作；Nous 端還沒有對應的實作，B 線尚未回覆同意**（2026-11-26 20:09 送出提案，寫這份文件時還沒收到回覆）。B 線回覆後以雙方同意的版本為準，這裡會跟著改。
- 鴨子端實作：[`robot/audio/duck_audio/voice_service.py`](../../robot/audio/duck_audio/voice_service.py)、[`session.py`](../../robot/audio/duck_audio/session.py)；模擬的 Nous 端（mock，測試用）：[`mock_nous.py`](../../robot/audio/duck_audio/mock_nous.py)。
- 相關：[ADR-0010](../../docs/adr/ADR-0010-duck-voice.md)（語音鏈）、[ADR-0003](../../docs/adr/ADR-0003-mobile-terminal-wake-and-find.md) §6（紅線）、[語音路徑](../../nous_adapter/docs/voice-path.md)。

## 1. 為什麼需要

AIOS 的即時語音是「瀏覽器頁面直接用 WebRTC 連雲端模型」，核心不經手音訊（voice-path.md §1）。鴨子用原生程式收音與播放（ADR-0003 的路線 B）時，Nous 端要有一個能收送 PCM 的端點。這份文件定義那個端點與鴨子之間怎麼說話。控制面（`wake_word` 事件、`presence`）仍然走 duck-link；這裡只管聲音與「這一輪」的開關。

## 2. 傳輸

- 鴨子是 WebSocket **client**，連 `ws://127.0.0.1:<埠>/duck-voice`（預設埠 8791，和 duck-link 同一條 SSH 通道）。鴨子端**只接受 loopback 的 `ws://`**，其他位址直接拒絕。
- 文字訊框＝JSON 控制訊息；二進位訊框＝PCM。
- 上行（鴨子→Nous）：16000 Hz、s16le、單聲道，每框 20 ms（320 個取樣、640 bytes）。來源是 XVF3800 處理後的聲道（回音消除、波束、降噪、自動增益）。
- 下行（Nous→鴨子）：24000 Hz、s16le、單聲道，任意長度的框（建議 20～100 ms）。是 Nous **原本的聲音**；變聲、音量上限、限幅都在鴨子端做。
- 任一邊斷線＝這一輪結束：鴨子停止收音、丟掉還沒播的聲音、回到只聽喚醒詞。鴨子會自動重連（1 秒起、最長 15 秒）。

## 3. 訊息

鴨子 → Nous：

| type | 欄位 | 什麼時候 |
|---|---|---|
| `hello` | `v:0`、`uplink:{rate,format,channels,frame_ms}`、`downlink:{rate,format,channels}` | 連上後第一則 |
| `turn_start` | `turn_id`（整數，遞增）、`trigger:"wake_word"\|"follow_up"`、`keyword_id`（例如 `"HEY_YAZI"`；手動測試是 `"MANUAL"`）、`doa_deg`（v0 一律 `null`） | 開始一輪；之後才有上行 PCM |
| `turn_end` | `turn_id`、`reason:"remote"\|"silence"\|"no_speech"\|"max_duration"\|"cancelled"` | 上行關閉；之後不會再有這一輪的 PCM |
| `playback` | `turn_id`、`state:"started"\|"finished"\|"flushed"\|"refused"`、`reason`（只有 `refused`） | 喇叭**實際**開始播、播完、被丟掉、被本機閘門擋下 |

Nous → 鴨子：

| type | 欄位 | 鴨子怎麼做 |
|---|---|---|
| `hello_ack` | `v`、（mock 會帶 `mock:true`） | 目前不檢查 |
| `listen_stop` | `turn_id` | Nous 判定說完了：關上行、回 `turn_end{reason:"remote"}`，等回話 |
| `speak_start` | `turn_id` | 開始播這一輪的回話；還在收音的話先關上行 |
| （二進位） | PCM | 只在 `speak_start` 之後、`speak_end`／`flush` 之前收；其他時候丟掉 |
| `speak_end` | `turn_id` | 沒有更多聲音；播完後回 `playback{finished}` |
| `flush` | — | 立刻停、丟掉還沒播的（打斷用）；回 `playback{flushed}` |
| `listen` | — | 不用喚醒詞再聽一輪（連續對話）。**只在剛播完回話或等回話時接受**；待命中收到會被忽略 |
| `session_end` | — | 結束這一輪，回到待命 |

`turn_id` 對不上、不認得的 `type`、不合時宜的訊息，鴨子一律忽略。

## 4. 誰開誰關

- **開**：只有鴨子本機能開上行——本機喚醒詞，或剛回完話後 Nous 要求的 `listen`。Nous 不能在鴨子待命時遠端打開麥克風。
- **喚醒詞之前的音訊不送**：上行從偵測到喚醒詞之後開始，沒有 pre-roll（ADR-0003 §6）。所以 Nous 收到的第一句話不含喚醒詞。
- **關**：正常由 Nous 送 `listen_stop`（它有模型的語音活動偵測）。鴨子另有本機的保險，全部做成設定：喚醒後沒人說話 8 秒（`no_speech`）、說完後安靜 1.5 秒（`silence`）、單輪最長 30 秒（`max_duration`）、等回話 15 秒。
- **提示音**：喚醒後鴨子先播本機的 `listen_on`，播完才開始送上行。
- **打斷**：v0 是半雙工——鴨子在播回話時不送上行，也不聽喚醒詞（設定 `audio.barge_in` 可以打開「播放時用喚醒詞打斷」，預設關，還沒用真人聲音驗證）。Nous 想中止播放就送 `flush`。
- **沒連上 Nous 時**：喚醒不會開麥克風上行，只播一聲提示音。

## 5. 需要 B 線確認或決定的事

1. Nous 端由誰實作這個端點（`nous_adapter` 裡的橋接行程，或 AIOS 核心），以及它怎麼接即時語音模型。
2. 下行能不能給 24 kHz s16le 單聲道；上行 16 kHz 夠不夠（模型若要 24 kHz，哪一邊重取樣）。
3. `listen_stop` 由 Nous 送這件事是否可行；不行的話就靠鴨子的 `silence` 判定。
4. 連續對話（`listen`）要不要在 v0 就用。
5. 喚醒事件：鴨子除了這裡的 `turn_start`，要不要同時經 duck-link 送 `wake_word` 事件（鴨子端的語音服務目前不連 duck-link；duck-link 的連線在 duckd）。建議：Nous 端收到 `turn_start` 就當作喚醒事件，不重複。
6. 埠：和 duck-link 共用 8791（不同路徑）或另開一個。

## 6. 之後才做

- `doa_deg`（喚醒當下的聲源方向）：duck-doa 服務已經在讀 XVF3800；兩個程式同時讀 USB 控制介面會互相重試，v0 先不帶。
- 全雙工與自然打斷：等用真人聲音量過回音消除後再決定。
- 把這個通道寫進 duck-link 的正式 schema（若雙方都覺得應該）。
