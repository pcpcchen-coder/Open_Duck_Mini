# 驗證紀錄：路線 2 第一次對話——對鴨子說「Hey 鴨子」開始對話 — 2026-11-27

- 驗證層級：**實機、真人聲音（使用者本人一人在場）**。Pi 4＋XVF3800 麥克風＋CD002 喇叭；Mac 上的 Nous 開發實例（埠 8791，AIOS main `607db1d`，含 pcpcchen-coder/AIOS#157、#158）；即時語音走 ChatGPT 方案（Codex 額度）。
- 結果：**手動開始的即時語音成功**，**說「Hey 鴨子」開始的對話成功**，兩次都是聲音從鴨子的喇叭出來（使用者回報）。
- 次數很少（各一次成功），不是穩定度的數字。
- 隱私：麥克風的聲音只經過鴨子本機的喚醒引擎，與 Nous 即時語音本身（瀏覽器直接送 OpenAI）；這次沒有錄音、沒有存檔。這份紀錄不放對話內容。

## 設定

| 項目 | 值 |
|---|---|
| Nous | 開發實例，整合線用環境變數啟動：`PORT=8791`、`NOUS_DUCK=on`、`NOUS_AIL=on`、`NOUS_AIL_SERVICES=duck`，設定目錄獨立；沒有寫 `.env`、沒有動 8787 的 Nous |
| 通道 | Mac → Pi：`ssh -N -R 127.0.0.1:8791:127.0.0.1:8791 duck-pi4`（整合線開的） |
| duckd | systemd 服務，已連到 duck-link；**沒有 `engage`**（頭不動） |
| 喚醒 | `duck-voice` 服務 `--mode wake`，喚醒詞 `YAZI_EN`（Hello 鴨子＋Hey 鴨子），門檻倍數 0.7；事件經 UDP 8793 給 duckd，duckd 發 duck-link `wake_word` |
| 終端腳本 | `setup_terminal.sh` 從 `v2`（`6c60bcb`）複製到 Pi（Chromium 已裝過，沒有 apt 安裝） |
| 終端頁面 | `run_nous_terminal.sh --auto-accept-mic --alsa-config ~/duck/voice/alsa/duck-audio.conf --mic duck_mic --speaker plughw:CARD=CD002AUDIO,DEV=0`，headless；同意那一次另外加 `--debug-port 9333` |

## 過程

| 時間 | 事情 | 結果 |
|---|---|---|
| 23:36 | 啟動終端頁面（含除錯埠）；Mac 用 `ssh -L 9333` 轉 DevTools | Nous log「終端機已連線：duck」；頁面在 |
| 23:39 | 使用者用 `chrome://inspect` 打開頁面，點了開始 | 跳出的是「語音模式」（瀏覽器語音辨識，送 Google）的同意，**不是即時語音**。原因：開發實例的即時語音還沒登入（頁面寫「即時語音：不可用」）。使用者按「不要」 |
| — | 使用者在 Mac 的 `http://localhost:8791/` 用 ChatGPT 方案登入即時語音 | 鴨子頁面變成「即時語音：ChatGPT 方案（Codex 額度）· gpt-live-1-codex」 |
| 約 23:45 | 使用者在鴨子頁面點電子腦、自己按同意，說了話 | **聲音從鴨子的喇叭出來**；說「再見」結束 |
| 23:50:42 | 使用者說「Hey 鴨子」 | `duck-voice`：`喚醒詞 HEY_YAZI`；Nous：「鴨子：聽到喚醒詞，已請終端頁面（duck）開始對話（1 個頁面）」；對話開始，**聲音從鴨子的喇叭出來** |
| 之後 | 拿掉除錯埠重開終端頁面，關掉 Mac 上的 `ssh -L` | Pi 上 9333 沒有在聽；Chromium 在跑 |

同意（即時語音的同意說明）由使用者自己在 DevTools 的畫面上按；B 線只用 DevTools 讀頁面上的文字與即時語音是否可用（唯讀），沒有替他按任何東西。麥克風權限用 `--auto-accept-mic` 自動允許，這是先問過使用者、他選的（無螢幕的 Chromium 顯示不出權限提示，DevTools 也按不到）。

## 量到的數字（只有一個時間點）

對話結束後（23:51 左右）：可用記憶體 1210 MB（總共 1844 MB）、溫度 65 °C；Chromium 各行程 RSS 加總約 1280 MB（RSS 會重複算共用頁，不是實際用量）。開始前（23:36）可用 1496 MB、53.5 °C。**通話中的 CPU 與記憶體沒有連續量。**

## 遇到的問題

1. **即時語音的登入和聊天登入是分開的**。開發實例只有聊天登入時，頁面點開始會落到瀏覽器語音辨識（送 Google）的同意，容易誤按。已寫進 `voice-test.md` §7.2。
2. **Pi 沒有中文字型**，DevTools 畫面上的中文全是方塊；B 線用 DevTools 讀頁面文字念給使用者。不影響語音。要修得在 Pi 上 apt 裝字型（沒有做）。
3. **喇叭的 ALSA 名稱是 `CD002AUDIO`**，不是先前文件寫的 `CD002`；已改 `voice-test.md`。
4. 重開終端頁面時，`pkill -f "bash run_nous_terminal.sh"` 也比對到下指令的那個 ssh 遠端 shell，第一次重開沒有成功；改成分兩次 ssh 後正常。

## 沒有驗證的

- 對話期間喚醒有沒有被壓住（`presence` 有沒有到 `duck-voice` 的 8794）：這次 log 看不出來，沒有測。
- 回音消除夠不夠、鴨子自己的聲音會不會把自己叫醒：沒有特別測。
- 「Hello 鴨子」開始的對話：這次只說了「Hey 鴨子」。
- 頭的動作（`presence` 到 duckd 後的姿勢）：duckd 沒有 `engage`，頭不動。
- 通話中的連續負載、長時間通話、重開機後是否還記得同意（同意存在 Chromium 設定檔 `~/duck/terminal-spike/profile-nous-duck`，理論上會記得，沒有驗證）。
- 終端頁面與 Mac 上的 Nous 開機常駐：沒有做（要先由整合線決定，見下一節）。

## 現在的狀態

- Pi：終端頁面（Chromium，headless，沒有除錯埠）在背景跑著，用 `setsid nohup` 啟動，**不是服務**，Pi 重開就沒了。關法：`ssh duck-pi4 'pkill -TERM -f "run_nous_terminal[.]sh"'`。
- Mac：開發實例與通道是整合線啟動的，B 線沒有動。

## 開機常駐的做法與風險（只是提案，沒有安裝）

- Pi：寫一個 systemd **使用者**服務（或系統服務，`User=duck`）跑 `run_nous_terminal.sh`，`Restart=on-failure`，排在 duckd 與 `duck-voice` 之後。腳本要求 `I_AM_PRESENT_AND_OK_WITH_SOUND=yes`（設計時假設有人在場），常駐等於永遠同意出聲、永遠開麥克風（只有喚醒後才送出）。通道沒開時頁面連不到 Nous，腳本會直接結束——常駐要先解決通道常駐。不要帶 `--debug-port`。
- Mac：通道與開發實例要常駐，得用 launchd（`~/Library/LaunchAgents`），會改使用者的系統設定；開發實例用的是 `~/AIOS-duck-link` 這個 clone 與獨立設定目錄，常駐後更新程式要手動 `git pull` 並重啟。
- 共同風險：常駐的即時語音會用 ChatGPT 方案的額度；誤喚醒會耗額度（沒人說話要等頁面的閒置時間到才結束）。每分鐘 3 次的限速仍在。
