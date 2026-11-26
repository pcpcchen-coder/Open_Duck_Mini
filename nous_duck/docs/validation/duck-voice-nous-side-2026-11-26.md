# 驗證紀錄：語音媒體通道 `/duck-voice` 的 Nous 端

- 日期：2026-11-26（晚上）
- 範圍：[`nous_adapter/hub/duck-voice-hub.ts`](../../nous_adapter/hub/duck-voice-hub.ts)、`shared/duck-voice.ts`、`mock/echo-voice-backend.ts`、`mock/mock-duck-voice.ts`、`duckctl` 的語音指令；介面說明 [`nous_adapter/docs/duck-voice.md`](../../nous_adapter/docs/duck-voice.md)
- 分支：`claude/duck-b-voice-channel`（從 `origin/v2` `0992ffe` 開出）
- 沒有做的事：沒有開任何麥克風、沒有讓任何喇叭出聲、沒有連任何雲端語音模型；沒有改 AIOS、沒有碰 `~/AIOS` 與正在跑的 Nous；沒有讀金鑰或 `.env`；沒有碰 Pi

## 1. 結論

| 項目 | 結果 | 驗證層級 |
|---|---|---|
| 通道的 Nous 端（連線守門、回合、上行閘門、回話、接著聽、打斷、逾時、結束、presence 的 `speaking`） | 26 項測試通過；整個 `nous_adapter` 171 項通過 | 單元／整合測試：對**模擬**的鴨子音訊端（TypeScript）、**合成**音訊（正弦波與靜音）、**模擬**後端 |
| D 線鴨子端真正的狀態機對這個 hub | 互通：完整一輪加接著聽，訊息順序如預期，上行 123 框兩邊數字相同，工作階段外的音訊 0 框 | 本機互通檢查：D 線 `session.py` 原檔（唯讀載入）＋暫存的驅動腳本，合成音訊。**不是** D 線的 `voice_service`（那需要麥克風） |
| 真的麥克風、喇叭、喚醒詞 | **沒有做** | — |
| 真正的對話（Nous 的語音模型） | **不存在**：這裡的後端只有「沒有」或模擬的回放。要改 AIOS，等使用者決定路線 | — |

沒有任何真人的聲音經過這條通道。

## 2. 測試

```bash
cd nous_duck/nous_adapter && npm ci && npm run typecheck && npm test
```

171 項通過（`validator` 33、`hub` 25、`duck-adapter` 51、`terminal` 18、`cli` 18、`duck-voice` 26），約 6 秒；連跑 4 次都通過。

`tests/duck-voice.test.ts` 的內容：

| 類別 | 測了什麼 |
|---|---|
| 控制訊息 | 鴨子送來的四種訊息的欄位與範圍；多的欄位忽略；不認得的 type 不合格；`hello.v` 不是 0 視為版本不合 |
| 連線與守門 | 和 `/duck-link` 共用守門（帶 `Origin` 403、別的路徑 404）；`hello` → `hello_ack`；第一則不是 hello 或版本不合就關閉；行程卡住（不回 pong）就關閉；正常的音訊端閒置不會被關掉 |
| 一通對話 | `turn_start(wake_word)` 才開後端；`listen_stop` → `speak_start` → PCM（每框 ≤100 ms）→ `speak_end`；播完送 `listen`、鴨子開始 `follow_up`；鴨子 `no_speech` 結束；鴨子自己判斷說完（`turn_end silence`）；沒有後端、後端開不起來或逾時；後端還在開時先到的上行音訊一框不少地補送；60 秒第 4 次喚醒被限速；鴨子本機閘門不讓播 |
| 沒有在收音時音訊進不來 | 待命時的上行框丟棄並計數、後端沒被啟動；持續亂送就關閉連線；回話期間送來的音訊不交給後端；Nous 待命時送 `listen` 鴨子不理、沒有對話時的 `follow_up` 被回絕；不合格的框；**hub、通道與回放後端的原始碼裡沒有任何檔案系統的程式** |
| 打斷、逾時、中斷 | 說話中用喚醒詞打斷（`flushed`、後端被叫停）；後端要求清空；上行中斷；音訊端斷線；後端結束；單通上限；鴨子不接著聽時自己收掉；log 只有數量與時間 |
| presence | 對模擬的身體（mock 鴨子）：`wake` → `listening` → `speaking`（鴨子回報開始播才出現）→ `listening` → `idle`；presence 指令不帶音量 |

## 3. D 線狀態機的互通檢查

- 鴨子端：D 線 worktree 裡**尚未提交**的 `nous_duck/robot/audio/duck_audio/session.py`（SHA-1 前 12 碼 `62e305d68c4f`），原檔、唯讀載入，沒有修改。只載入這一個檔（它只用標準函式庫）。
- 驅動：一支暫存腳本（沒有進 repo）照 `voice_service.py` 的作法把狀態機的動作變成 WebSocket 訊息；上行是 0.6 秒的合成正弦波加靜音，「播放」只照收到的長度計時。逾時設短（沒人說話 1.2 秒）。
- Nous 端：`bin/duckctl hub --port 18796 --voice echo`。

訊息順序（`duck>` 是鴨子送的，`nous>` 是這個 hub 送的）：

```text
nous>hello_ack
duck>turn_start:wake_word
nous>listen_stop
duck>turn_end:remote
nous>speak_start
duck>playback:started
nous>speak_end
duck>playback:finished
nous>listen
duck>turn_start:follow_up
duck>turn_end:no_speech
nous>session_end:done
```

| 數字 | 值 |
|---|---|
| 狀態機最後的狀態 | `idle` |
| 輪數 | 2（喚醒一輪、接著聽一輪） |
| 鴨子送出的上行框 | 123（狀態機的 `frames_up`）；hub 記到的也是 123 |
| 狀態機擋下、沒有送的框 | 63（不在聽的時候） |
| hub 收到「不該送」的框 | 0 |
| 下行 | 14 框、65 280 bytes（約 1.36 秒的 24 kHz 音訊） |
| hub 記的結束原因 | `duck_no_speech`，4.1 秒，1 段回話，沒有打斷 |

限制：這是狀態機對 hub，不是 D 線完整的服務；沒有真的音訊裝置、沒有喚醒詞引擎、兩端都在同一台 Mac。D 線的程式還在改，之後要用它提交後的版本再跑一次。

## 4. 手動執行

`bin/duckctl hub --port 18795 --voice echo`，另一個分頁 `bin/duckctl mock-voice --port 18795`：

```text
收到的控制訊息：hello_ack → listen_stop → speak_start → speak_end → listen
收到下行 16 框、76800 bytes（約 1600 ms 的 24 kHz 音訊）；播放回報：started → finished
```

hub 的 log 只有：音訊端連線、對話開始（標示 mock）、對話結束（原因、秒數、輪數、框數）。

## 5. 沒有驗證的事

- 真的麥克風與喇叭、真人的聲音、XVF3800 的回音消除、鴨子自己的聲音會不會觸發喚醒。
- D 線的 `voice_service` 整個服務對這個 hub（等它提交、而且要有人在場）。
- 經 Wi-Fi 與 SSH 通道的延遲與抖動。
- 任何語音模型；回合切換在真的對話裡順不順。
- 搬進 AIOS 之後的行為。
