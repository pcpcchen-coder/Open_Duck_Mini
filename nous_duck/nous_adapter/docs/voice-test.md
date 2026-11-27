> [繁體中文](voice-test.md) | [English](voice-test.en.md)

# 語音實測步驟：用說的讓鴨子轉頭、點頭、搖頭（T2、T3）

狀態：**步驟寫好，還沒有人照著跑過。** 日期：2026-11-26（當天晚上加了 §7：路線 2，對鴨子說「Hey 鴨子」開始對話）。這份是給使用者照做的；裡面會連雲端語音模型、會出聲、會開麥克風、會讓鴨子的頭動，所以每一步都由你自己執行。

現況：AIOS 的 `/duck-link` 端點、`duck` adapter 與互動狀態已經合併進 AIOS main（PR #156，旗標預設關閉）。鴨子端的實機頭部與 `duckctl` 經通道下 `look`／`gesture` 已有人眼確認（A 線，2026-11-26）。**還沒驗證的就是中間這一段：真的語音 → 模型選工具 → 鴨子。**

## 0. 先看這張表：誰做什麼

| 事情 | 誰做 | 為什麼 |
|---|---|---|
| 啟動開了鴨子旗標的 Nous、寫它的 `.env`、登入或填 API key | **你** | 會動到你的 Nous 設定與金鑰；開發代理不讀、不寫、不複製這些 |
| 要不要動正在跑的 Nous（`127.0.0.1:8787`） | **你決定**。這份步驟預設**不動它**，另外開一個開發實例 | 正在跑的那個 checkout 有你沒提交的修改 |
| 打開鴨子電源、把鴨子擺好、在場看著 | **你** | 頭會動；有狀況要能馬上處理 |
| 在 Pi 上啟動 duckd、接手頭部（`engage`） | **你**（指令在下面，都是從 Mac 下） | 會開舵機匯流排 |
| 對著麥克風說話 | **你** | — |

鴨子的狀態：坐在桌上、腿不出力、只動頭。Nous 這一批只開了 6 個工具（查狀態、停、轉頭、預錄動作、表情、視線跟隨），**叫它走路會被拒絕**。

## 1. 準備（一次）

### 1.1 取得合併後的 AIOS 程式

用一個**不是**正在跑 Nous 的 checkout。`~/AIOS-duck-link` 是之前為了這件事另外 clone 的，可以直接用：

```bash
cd ~/AIOS-duck-link && git switch main && git pull && git log -1 --oneline
```

確認最新的 commit 在 `Merge pull request #156` 之後（含它）。然後：

```bash
cd ~/AIOS-duck-link/prototype/ambient-shell && npm ci
```

### 1.2 寫開發實例的 `.env`（你自己寫）

檔案：`~/AIOS-duck-link/prototype/ambient-shell/.env`（終端機版讀這個檔；**不是** macOS App 的那一份）。內容：

```bash
PORT=8791
NOUS_CONFIG_DIR=/Users/<你的帳號>/.config/nous-duck-dev
NOUS_OAUTH_PORT=1456
NOUS_DUCK=on
NOUS_AIL=on
NOUS_AIL_SERVICES=duck
```

- `PORT=8791`：鴨子端 duckd 的服務預設就是連 `ws://127.0.0.1:8791/duck-link`，通道也是 8791；用同一個埠，Pi 上什麼都不用改。Nous 會檢查 `Host` 標頭，所以**鴨子那邊的埠一定要等於 Nous 的埠**。
- `NOUS_CONFIG_DIR`：一個新的空資料夾，和正在跑的 Nous 分開（登入狀態、設定都不共用）。
- 即時語音需要的登入或 API key：照 AIOS 的 [INSTALL](https://github.com/pcpcchen-coder/AIOS/blob/main/prototype/ambient-shell/INSTALL.md) 由你自己設定。新的設定目錄是空的，所以要重新登入或自己填 key。
- **8791 不能同時有別的程式在聽**：如果之前用 `bin/duckctl hub` 或 `scripts/duck-link-dev.sh hub-start` 開過開發用的 hub，先關掉（`scripts/duck-link-dev.sh hub-stop`）。

還不確定的地方：`NOUS_OAUTH_PORT` 改成 1456 之後 ChatGPT 登入是否正常沒有試過；用 API key 的路徑不經過它。

## 2. 每次實測

### 2.1 啟動開發實例（你）

```bash
cd ~/AIOS-duck-link/prototype/ambient-shell && npm start
```

預期在終端機看到：

- `Nous 原型已啟動：http://localhost:8791`
- `鴨子：duck-link 已開在 ws://127.0.0.1:8791/duck-link（只聽本機；等鴨子經 SSH 通道連進來）`
- 即時語音那一行是「可用」。如果是「不可用」，先把登入或 API key 弄好，後面才有意義。

沒有「鴨子：duck-link 已開在…」那一行，代表 `NOUS_DUCK=on` 沒有生效（檢查 `.env` 的位置與拼字）。

### 2.2 開通道（Mac 的另一個終端機分頁）

```bash
ssh -N -R 127.0.0.1:8791:127.0.0.1:8791 duck-pi4
```

這個指令會一直掛著，不要關。它讓 Pi 上的 `127.0.0.1:8791` 接到 Mac 的 `127.0.0.1:8791`。注意：這也讓 Pi 上的程式能呼叫這個開發實例的整個 HTTP API（AIOS 的 Pi 終端本來就是這樣）。

### 2.3 啟動 duckd 並接手頭部（Mac 的第三個分頁）

以 [`robot/duckd/README.md`](../../robot/duckd/README.md) 為準；目前是：

```bash
ssh duck-pi4 'sudo systemctl start duckd'
```

```bash
ssh duck-pi4 '~/duck/duckd/duckd-ctl engage'
```

- `engage` 才會開舵機匯流排、讓頭部出力。舵機控制台如果還占著匯流排，`engage` 會拒絕並說是誰；先在控制台頁面按「釋放硬體」。
- 服務的預設是每軸 ±15°、30°/s。

預期：Nous 的終端機出現 `鴨子：鴨子已連線：duckd …`。**後面沒有「（mock）」才是真的頭**；有的話代表 duckd 是用模擬身體啟動的。

### 2.4 開頁面、開始對話（你）

用瀏覽器開 <http://localhost:8791>，允許麥克風，開始即時語音。

先問一句確認整條路通了：

| 你說 | 預期 Nous 的行為 | 預期鴨子 |
|---|---|---|
| 「鴨子現在怎麼樣？」 | 呼叫 `app.duck.status`，說出鴨子已連線、頭部可用；會提到目前有哪些預錄動作 | 不動 |

如果 Nous 說鴨子沒有連線：回 2.2、2.3 檢查。如果 Nous 完全沒有提到鴨子、像是不知道有這個東西：`NOUS_AIL_SERVICES=duck` 沒有生效。

### 2.5 要說的句子

一次說一句，等它做完再說下一句。

| # | 你說 | 預期 Nous 呼叫 | 預期鴨子 | 預期 Nous 怎麼回 |
|---|---|---|---|---|
| 1 | 「鴨子看左邊」 | `app.duck.look`（`head_yaw` 為正） | 頭往**牠的左邊**轉 | 說轉過去了（`confirmed`） |
| 2 | 「鴨子看右邊」 | `app.duck.look`（`head_yaw` 為負） | 頭往右轉 | 同上 |
| 3 | 「鴨子抬頭」 | `app.duck.look`（`head_pitch` 為正） | 抬頭 | 同上 |
| 4 | 「鴨子看前面」 | `app.duck.look`（各軸回 0） | 回正 | 同上 |
| 5 | 「鴨子點點頭」 | `app.duck.gesture`（`nod`） | 點頭 | 說開始做了 |
| 6 | 「鴨子搖頭」 | `app.duck.gesture`（`shake`） | 搖頭 | 同上 |
| 7 | 「鴨子把頭轉到最左邊」 | `app.duck.look`（很大的角度） | 轉到 ±15° 的視窗邊緣就停 | 應該提到角度被鴨子限制了（`clamped`） |
| 8 | 「鴨子往前走」 | 沒有可用的工具（走路這一批沒有開） | **不動** | 說現在做不到，不應該說「好，走了」 |
| 9 | 「鴨子停」 | `app.duck.stop` | 停在原地 | 說停了 |

同時留意互動狀態（T3）：開始對話時鴨子應該有「在聽」的反應，結束對話後回到平常的樣子。這一批**沒有「說話中」的狀態**——Nous 說話時鴨子不會跟著點動，這是已知的限制（核心不知道模型正在說話），不是壞掉。

第 5、6 句的前提：duckd 有把 `nod`、`shake` 列給 Nous。動作庫裡還沒標成「實機驗證過」的動作，duckd 預設不列；那時 Nous 會回「鴨子的動作清單裡沒有這個名稱」。這是鴨子端的設定（A 線），不是 Nous 的問題——請看第 2.4 步 Nous 說的動作清單裡有沒有它們。

### 2.6 請記下來的事

這些是這次實測真正要回答的問題：

1. 每一句：模型有沒有呼叫工具？選對了嗎？鴨子動的方向對嗎？
2. 第 1～3 句的**方向**：左右、上下有沒有相反。（工具說明寫的是 `head_yaw` 正＝左、`head_pitch` 正＝抬頭。）
3. 從說完到頭開始動，大約幾秒。
4. Nous 的回話和實際發生的事一不一致（特別是第 7、8 句：做不到的事有沒有老實說）。
5. 開始、結束對話時鴨子的反應看起來對不對、會不會太頻繁。
6. Nous 終端機裡 `整合層：… app.duck.… → …` 那幾行（每次工具呼叫一行，有結果與耗時），可以整段貼回來。

## 3. 收

照這個順序：

1. 結束頁面上的對話，關掉瀏覽器分頁。
2. 停 duckd（頭會以限速回到接手時的位置，然後放開匯流排）：

   ```bash
   ssh duck-pi4 'sudo systemctl stop duckd'
   ```

3. 在開通道的那個分頁按 Ctrl-C。
4. 在 `npm start` 的那個分頁按 Ctrl-C。

正在跑的 Nous（8787）從頭到尾沒有被動過。要完全回到沒有鴨子的狀態，不需要做別的事；開發實例的設定都在 `~/.config/nous-duck-dev` 與 `~/AIOS-duck-link` 裡。

## 4. 出狀況時

| 現象 | 先看 |
|---|---|
| 頭的動作不對勁、想立刻停 | 說「鴨子停」；或直接 `ssh duck-pi4 '~/duck/duckd/duckd-ctl estop'`（本機緊急停止，之後要在 Pi 上解除）；或停服務（上面第 2 步） |
| Nous 說「結果不明，請看一下鴨子」 | 指令送出後沒有收到回覆或連線斷了。看鴨子實際有沒有動；看通道的分頁有沒有斷 |
| Nous 說鴨子拒絕了 | 回話裡會帶原因（例如有人在用控制台、緊急停止中、過熱）。照原因處理 |
| duckd 連不上（Nous 沒有出現「鴨子已連線」） | 通道還開著嗎；`.env` 的 `PORT` 是不是 8791；8791 是不是被別的程式占了（`lsof -nP -iTCP:8791 -sTCP:LISTEN`） |
| `npm start` 說 8791 被占用 | 關掉開發用的 hub：`cd nous_duck/nous_adapter && scripts/duck-link-dev.sh hub-stop` |

## 5. 另一個作法：直接用你平常的 Nous（不建議先做）

如果之後要讓平常的 Nous 就能叫鴨子，要做的是：把 `NOUS_DUCK=on`、`NOUS_AIL=on`、`NOUS_AIL_SERVICES`（加上 `duck`）寫進**它的** `.env`，更新到含 #156 的程式，重新啟動它；通道與 duckd 的埠都要改成它的埠（預設 8787，duckd 要加 `--url ws://127.0.0.1:8787/duck-link`，屬於鴨子端服務設定的修改）。

這會動到正在跑的 Nous、它的 `.env` 與 Pi 上的服務設定，全部要由你決定與執行。建議先用上面的開發實例把語音 → 鴨子這一段確認過再說。

## 6. 驗證層級

這份文件本身沒有驗證任何事。到 2026-11-26 為止，和它有關的已驗證範圍是：

- AIOS 端：fixture 測試與對 duckd 模擬身體的本機檢查（沒有真實語音）。
- 鴨子端：實機頭部與 `duckctl` 經通道對實機的 `look`／`gesture`（A 線，人眼確認）。
- **沒有驗證**：真實語音、模型怎麼使用這些工具、開發實例的啟動步驟（`.env` 的組合、另一個設定目錄下的登入）。

## 7. 路線 2：鴨子當語音終端（說「Hey 鴨子」開始對話）

§1～§3 是「在 Mac 的頁面說話、鴨子做動作」。這一節是 2026-11-26 你決定的路線 2：**對鴨子說話、鴨子的喇叭回話**——Pi 上的 Chromium 開 Nous 頁面當終端，鴨子本機偵測「Hello 鴨子」「Hey 鴨子」來開始對話。設計與還沒解決的事見 [`voice-path.md` §8](voice-path.md#8-2026-11-26-的決定路線-2)。

**這一節的前提還沒有全部到位**，寫這份文件時：

| 需要 | 狀態 |
|---|---|
| AIOS 的 DUCK-2（[pcpcchen-coder/AIOS#158](https://github.com/pcpcchen-coder/AIOS/pull/158)）合併，或你用那個分支啟動 Nous | PR 待審 |
| 鴨子本機的喚醒詞偵測（D 線的 `duck-voice` 服務，預設不啟用） | D 線已做成設定，兩句都有效 |
| 喚醒送到 duck-link（D 線 → duckd → `wake_word` 事件） | 還沒接：duckd 現在會忽略 D 線送來的喚醒，要 A 線補上 |
| 麥克風共用：D 線的 `~/duck/voice/alsa/duck-audio.conf` 在 Pi 上，且 `~/duck/terminal-spike` 裡的 `run_nous_terminal.sh` 是有 `--alsa-config`／`--mic`／`--speaker` 的新版（重跑一次 `setup_terminal.sh` 更新） | D 線實測共用可行；新版腳本帶這些選項**還沒有執行過** |

這四項沒有全部到位之前，可以先做 7.2 的一次性設定與 7.4 的「不靠喚醒詞」檢查。

### 7.1 誰做什麼

| 事情 | 誰做 | 為什麼 |
|---|---|---|
| 啟動開了旗標的 Nous、它的 `.env` 與金鑰 | **你** | 同 §0 |
| 在鴨子的瀏覽器設定檔上同意即時語音、允許麥克風 | **你**（從 Mac 用 DevTools 連過去按） | 這是你的同意；鴨子沒有螢幕 |
| 在 Pi 上啟動終端頁面、喚醒服務、duckd 與 `engage` | **你** | 會開麥克風、會出聲、頭會動 |
| 在場、說話、聽 | **你** | — |

### 7.2 一次性設定

1. Nous（開發實例，同 §1；用含 DUCK-2 的程式）：`.env` 和 §1.2 相同（`PORT=8791`、`NOUS_DUCK=on`、`NOUS_AIL=on`、`NOUS_AIL_SERVICES=duck`）。終端 ID 預設是 `duck`，不用另外設。**不需要** `NOUS_WAKE=on`。
2. Pi 上的 Chromium 與腳本（裝過就跳過）：

   ```bash
   bash nous_duck/robot/deploy/pi4/setup_terminal.sh
   ```

3. 在鴨子的瀏覽器設定檔上按同意（每個設定檔一次）。先照 §2.1、§2.2 啟動 Nous 與通道，然後：

   ```bash
   ssh duck-pi4 'cd ~/duck/terminal-spike && AIOS_PORT=8791 I_AM_PRESENT_AND_OK_WITH_SOUND=yes bash run_nous_terminal.sh --auto-accept-mic --debug-port 9333 --alsa-config "$HOME/duck/voice/alsa/duck-audio.conf" --mic duck_mic --speaker plughw:CARD=CD002AUDIO,DEV=0'
   ```

   ```bash
   ssh -N -L 9333:127.0.0.1:9333 duck-pi4
   ```

   在 Mac 的 Chrome 開 `chrome://inspect`，把 `localhost:9333` 加進 Discover network targets，點那個頁面的 inspect，就能看到並操作鴨子上的 Nous 頁面：點電子腦開始一次即時語音、在同意說明按同意（左邊的「啟用語音」），然後說「再見」結束對話。之後這個設定檔會記得。用完把 `--debug-port` 拿掉重開（7.3 的指令），並關掉 Mac 上的 `ssh -L`：除錯埠開著時，Pi 上任何行程都能操控這個瀏覽器。

   2026-11-27 實際照做時遇到的事（見[驗證紀錄](../../docs/validation/duck-first-voice-call-2026-11-27.md)）：
   - **即時語音要另外登入。** Nous 開發實例的聊天登入不等於即時語音登入；頁面最下面寫「即時語音：不可用」時，在 Mac 開 `http://localhost:8791/` → 設定 → 即時語音 →「用 ChatGPT 方案登入」。沒登入時點電子腦跳出的是另一種同意（瀏覽器語音辨識，送 Google），要按「不要」。
   - **麥克風權限提示在無螢幕的 Chromium 看不到**，DevTools 也按不到（它在瀏覽器外框）。所以指令加了 `--auto-accept-mic`：只對這個 Chromium 自動允許，麥克風仍是真的。2026-11-27 使用者同意這樣做。
   - **DevTools 畫面上的中文是方塊**（Pi 沒裝中文字型），不影響語音；同意框的按鈕是左「啟用語音」、右「不要」。

### 7.3 每次實測

1. Mac：啟動 Nous（§2.1）。log 要有 `鴨子：duck-link 已開在 ws://127.0.0.1:8791/duck-link…；語音終端頁面：http://localhost:8791/?terminal=duck`。
2. Mac：開通道（§2.2）。
3. Pi：啟動終端頁面。

   ```bash
   ssh duck-pi4 'cd ~/duck/terminal-spike && AIOS_PORT=8791 I_AM_PRESENT_AND_OK_WITH_SOUND=yes bash run_nous_terminal.sh --auto-accept-mic --alsa-config "$HOME/duck/voice/alsa/duck-audio.conf" --mic duck_mic --speaker plughw:CARD=CD002AUDIO,DEV=0'
   ```

4. Pi：啟動 duckd 並 `engage`（§2.3）。Nous 的 log 出現 `鴨子：鴨子已連線`。
5. Pi：啟動鴨子的喚醒服務（指令以 [`robot/audio/README.md`](../../robot/audio/README.md) 為準）。
6. 對鴨子說「Hey 鴨子」（或「Hello 鴨子」），等它有反應後說一句話，例如「鴨子看左邊」或「今天星期幾」。

### 7.4 不靠喚醒詞先檢查頁面這一段

喚醒那一段還沒接好時，可以先確認「Pi 上的頁面能不能對話」：做完 7.3 的第 1～4 步，用 7.2 第 3 步的 DevTools 連到頁面，手動開始一次即時語音，對著鴨子的麥克風說話。聲音應該從鴨子的喇叭出來，Nous 說話時鴨子的頭是「說話」的姿勢（這是頁面回報的狀態，這次才有）。

### 7.5 預期

| 時間點 | Nous 的 log | 鴨子 |
|---|---|---|
| 說完喚醒詞 | `鴨子：聽到喚醒詞，已請終端頁面（duck）開始對話（1 個頁面）`，接著是即時語音開始 | 被叫醒的反應（頭、提示音依鴨子端設定） |
| 連上之後 | — | Nous 打招呼（喚醒開始的對話會先打招呼），聲音從鴨子的喇叭出來 |
| 你說話、它想、它回答 | 用到工具時有 `整合層：… app.duck.… → …` | 頭依序是在聽、在想、**說話中**、在聽 |
| 5 秒沒人說話 | 即時語音結束 | 回到待命 |

如果 log 是 `鴨子：聽到喚醒詞，但終端頁面（?terminal=duck）沒有連著，沒有開始對話`：Pi 上的頁面沒開或通道斷了。如果完全沒有「聽到喚醒詞」這一行：喚醒沒有送到 Nous（鴨子端那一段）。

### 7.6 請記下來的事

1. 喚醒詞中幾次；沒叫的時候有沒有自己醒；Nous 說話時鴨子有沒有被自己的聲音叫醒。
2. 從說完喚醒詞到可以開始說話，大約幾秒；頭一句話有沒有被漏掉。
3. Nous 聽不聽得清楚你（回答對不對題）；它說話時你插話，它會不會停。
4. 喇叭的聲音清不清楚、音量、有沒有回音或嘯叫。
5. 頭的狀態跟不跟得上（特別是「說話中」的開始與結束）。
6. Pi 的負載：`ssh duck-pi4 'cd ~/duck/terminal-spike && bash measure.sh'` 的輸出（CPU、記憶體、溫度）。
7. 一分鐘內連叫四次：第四次應該被拒絕（限速）。

### 7.7 收

1. Pi：停喚醒服務；`ssh duck-pi4 'sudo systemctl stop duckd'`。
2. Pi：在 `run_nous_terminal.sh` 的終端機按 Ctrl-C（關掉 Chromium，麥克風放開）。
3. Mac：通道 Ctrl-C；`npm start` Ctrl-C。

### 7.8 這一節的驗證層級

2026-11-27：使用者在場，照 7.2～7.3 在實機上完成第一次對話：手動開始的即時語音、與說「Hey 鴨子」開始的對話都成功，聲音從鴨子的喇叭出來。見[驗證紀錄](../../docs/validation/duck-first-voice-call-2026-11-27.md)。以下是 2026-11-26 寫的原文。

到 2026-11-26 為止：AIOS 那一側的伺服器端有 fixture 測試（假鴨子、假的語音路徑）；頁面端只有型別檢查與建置，**沒有在瀏覽器裡跑過**。Pi 上的 Chromium 只量過不連 Nous、不出聲、沒有麥克風的情況。**上面的步驟沒有任何一步有人照著跑過。**
