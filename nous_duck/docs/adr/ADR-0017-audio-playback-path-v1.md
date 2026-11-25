# ADR-0017：音訊播放路徑第一版——由鴨子的音訊行程直接寫 ALSA，暫不裝 PipeWire

- 狀態：**草案（Proposed）**，D 線 2026-11-25 夜間提出，等使用者審核。程式已照這個方向實作到「單元測試＋Pi 上不出聲的路徑檢查」。
- 日期：2026-11-25
- 相關：[ADR-0010](ADR-0010-duck-voice.md)（§3.2 變聲位置、§7 閘門與音量上限）、[ADR-0003](ADR-0003-mobile-terminal-wake-and-find.md)（終端路線 A／B）、[ADR-0006](ADR-0006-privacy-settings.md)、[ADR-0008](ADR-0008-single-board-pi4.md)（單板 Pi 4）
- 驗證：[`docs/validation/audio-2026-11-25.md`](../validation/audio-2026-11-25.md)

## 1. 背景

ADR-0010 §3.2 的草案是：Pi 上用 PipeWire 建兩個虛擬輸出 `duck_voice`（`filter-chain` 載入變聲外掛）與 `duck_raw`，輸出接到 Flex 麥克風陣列的 USB 播放裝置。寫那份 ADR 時沒有硬體。

2026-11-25 在鴨子的 Pi 4 上實際查到的：

| 項目 | 現況 |
|---|---|
| 作業系統 | Debian 13（trixie）、Raspberry Pi OS Lite（沒有桌面） |
| PipeWire／PulseAudio | **沒有安裝**；只有 ALSA（`alsa-utils 1.2.14`） |
| 喇叭 | USB `e2b7:0811 Jie Li CD002`，ALSA 卡名 `CD002`；只支援 **S16_LE、2 聲道、48000 Hz**；硬體混音器 `PCM` 0～255 |
| 預設輸出 | `~/.asoundrc` 已把預設指到 `hw:CD002,0`（`plug`） |
| 麥克風 | 沒有（Flex／XVF3800 未到貨） |
| 記憶體 | 2 GB，同一片板子還要跑步態、safety、感知（ADR-0008） |

## 2. 決定

1. **第一版不裝 PipeWire**。`duck_voice` 與 `duck_raw` 是鴨子音訊行程（`robot/audio/duck_audio`）的兩個**邏輯輸出**（`DuckAudioOut.play_voice`／`play_raw`），不是系統層的虛擬裝置。
2. 兩個輸出共用同一段：**閘門 → （`duck_voice` 才有）變聲 → 增益（夾到本機上限）→ 限幅 → 48 kHz 雙聲道 → ALSA**。ALSA 輸出用系統的 `aplay` 寫 `plughw:CARD=CD002,DEV=0`（用卡名，不用編號）。
3. 閘門、音量上限、變聲、音量包絡都在這個行程裡，符合 ADR-0010 的原則（規則在播放端執行；變聲在實際播出前的最後一段；本機音效不變聲兩次）。
4. 變聲用自己寫的 numpy 處理器（候選與量測見 D6 的驗證紀錄），不依賴 LADSPA 外掛。
5. 硬體混音器（`amixer`）不由程式調整；音量上限用數位增益實作。硬體混音器的值是「喇叭校準」的一部分，等試聽時由使用者定一次。

## 3. 為什麼

| 方案 | 優點 | 缺點 | 結果 |
|---|---|---|---|
| **A. 自己的行程直接寫 ALSA（採用，第一版）** | 不多裝常駐服務（省記憶體與 CPU）；閘門與上限在同一個行程裡，容易測（單元測試可以涵蓋到送出的每個取樣）；延遲路徑短 | 只有我們的行程能出聲；別的程式（例如 Chromium）不能把聲音送進 `duck_voice`；同時播放要自己混音 | 採用 |
| B. PipeWire `filter-chain`（ADR-0010 草案） | 任何程式都能選 `duck_voice` 當輸出；終端路線 A（Pi 上跑 Chromium）需要它 | 要裝 PipeWire＋WirePlumber 並常駐；`filter-chain` 的變聲外掛要另外找（Rubber Band LADSPA 是 GPL，且要量即時性）；閘門要用另一個機制擋在外掛之前 | **延後**：決定走路線 A 時再做 |
| C. ALSA 外掛（`.asoundrc` 的 `ladspa`／`route`） | 不用 PipeWire | 設定難維護、難測；閘門做不進去 | 不採用 |

第一版的語音來源（依 B 線規劃）是 Nous 經 duck-link 的媒體通道把聲音送給鴨子端的程式（路線 B），由我們的行程收下後呼叫 `play_voice`，所以 A 就夠用。

## 4. 後果與限制

- **ADR-0010 §3.2 的「PipeWire 虛擬輸出」在第一版不成立**；其餘（變聲在鴨子端、閘門在播放端、`duck_raw` 不變聲）不變。若之後採路線 A（Chromium），要補做方案 B，並把閘門移到 PipeWire 之前。
- 目前 `play_voice`／`play_raw` 一次處理一整段聲音。Nous 的即時語音需要**串流**（邊收邊變聲邊播），變聲器已做成可分塊處理（D6），但串流播放迴圈還沒寫，屬於語音通道的批次。
- 同時只播一段聲音；Nous 說話時不播音效（`eye_expressions.md` §5.1 本來就這樣規定），所以還不需要混音。
- 回音消除的參考訊號（ADR-0010 §4）：Flex 到貨後喇叭改接 Flex 的輸出，ALSA 裝置名會變，`AplaySink` 的裝置名做成設定即可；XVF3800 是否用自己的播放訊號當參考仍要到貨驗證。
- 現在的 USB 喇叭 CD002 是暫時的；它不是 Flex，沒有 AEC 參考。

## 5. 待決（給使用者）

1. 同意第一版不裝 PipeWire 嗎？（若很快就要在 Pi 上跑 AIOS 的 Chromium 頁面，就要改做方案 B。）
2. 本機音量上限的初值：白天 0.5、夜間 0.15（線性增益，**沒有對著喇叭量過**），要試聽後定。
3. 夜間模式下安全提示要不要出聲（ADR-0010 待決第 5 項）：程式預設**不出聲**，可設定。
