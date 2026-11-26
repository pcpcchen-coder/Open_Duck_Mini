# 驗證紀錄：鴨子端喚醒服務、麥克風、與 Chromium 共用（D 線）— 2026-11-26

- 範圍：[`robot/audio/`](../../robot/audio/README.md) 的喚醒服務 `duck-voice`、收音、ALSA 共用麥克風、設定登記、部署。
- 決定（使用者，2026-11-26）：語音對話走**路線 2**（Pi 上的 Chromium 開 Nous 頁面，收音與播放由 Chromium 做）；喚醒詞**先用「Hello 鴨子」與「Hey 鴨子」**，之後可能換。
- 驗證層級：單元測試＋ Pi 4 實機（XVF3800 麥克風、USB 喇叭 CD002）。實機部分逐項標明。
- **沒有驗證的最重要兩件事**：(1) **真人說喚醒詞**的喚醒率與誤喚醒率；(2) Chromium **真的連 Nous、出聲**的對話。兩件都要使用者在場（§8）。
- 隱私：量測時收到的音訊都只在記憶體裡算統計值或經過喚醒引擎，**沒有寫檔**（`arecord` 輸出到管線）。合成語音測試檔（macOS `say -o` 產生，不是錄音）測完已從 Pi 刪除。

## 1. 單元測試

```bash
cd nous_duck/robot/audio && python -m pytest tests -q        # 129 passed, 2 skipped（Mac；略過的需要 aplay）
cd nous_duck/robot/settings && python -m pytest tests -q     # 36 passed
```

（Mac，Python 3.13.16；需要 numpy、pytest、websockets，KWS 煙霧測試另需 sherpa-onnx 與模型。）這一批新增：`test_session.py`（15 項，實驗的原生通道狀態機）、`test_voice_service.py`（9 項：路線 2 的喚醒流程、串流播放、設定關掉不開麥克風、原始碼沒有寫檔呼叫）、`test_kws.py` 新增 4 項（喚醒詞組合、門檻倍數、與設定頁選項一致）。

## 2. 麥克風與喇叭（Pi 實機，20:09～20:11）

| 項目 | 值 |
|---|---|
| 麥克風 | reSpeaker XVF3800 4-Mic Array（`2886:001a`），ALSA card 4 `Array`；收音只有 S16_LE、2 聲道、16000 Hz；它也有一個 16 kHz 雙聲道的**播放**端（回音消除的參考訊號從這裡進） |
| 喇叭 | CD002，card 1；48 kHz 雙聲道（同 11-25 的紀錄） |
| 安靜時的音量（3 次量測） | ch0：−31～−46 dBFS（有自動增益，會把環境聲放大，浮動大）；ch1：−59～−65 dBFS |

喇叭以音量 0.1 播 4.3 秒的合成語音時，麥克風收到的音量（`tools/measure_mic.py echo`）：

| 情況 | ch0（處理後） | ch1 |
|---|---:|---:|
| 播放前 | −41 dBFS | −65 dBFS |
| 播放中，**沒有**給參考訊號 | **−18.8 dBFS**（峰值 −0.7） | −45.5 dBFS |
| 播放中，同一段聲音同時送進 XVF3800 的播放端當參考（2 次） | **−58.2、−52.2 dBFS** | −45.7、−46.0 dBFS |

- 給參考訊號後，ch0 的喇叭回授少了約 **33～39 dB**；ch1 不受影響（ch1 沒有經過回音消除）。所以收音用 ch0。
- 這是用我們自己的播放程式（`TeeSink`＋`RefSink`）做的。**路線 2 由 Chromium 直接播到 CD002，XVF3800 拿不到參考訊號**，第一版只能靠 Chromium 的 `echoCancellation`（沒有量）。要用到晶片的回音消除，得把喇叭改接 XVF3800 的輸出，或做一段把 Chromium 的輸出分送兩張卡的音訊路徑（兩張卡時脈不同，純 ALSA 設定我沒有可靠的作法）。

## 3. 喚醒詞：「Hello 鴨子」「Hey 鴨子」

引擎與模型不變：sherpa-onnx 2.0.1、zh-en-3M（和 AIOS 相同）。這個模型的 token 表同時有 ARPAbet 與帶聲調拼音，混合語言的詞可以直接混寫，**不用換模型**：

| 喚醒詞 | 寫法（`config/wake_keywords.json`） |
|---|---|
| Hello 鴨子 | `HH AH0 L OW1 y ā z i` |
| Hey 鴨子 | `HH EY1 y ā z i`，以及把 Hey 念成「嘿」的 `h ēi y ā z i`（任一命中都算） |

門檻與提升分數用 AIOS 的全域值（0.15／1.5），設定頁的「喚醒門檻倍數」可調。

### 3.1 合成語音（檔案輸入，**不是喚醒率**）

輸入：macOS `say -o` 的 7 個中文（台灣）系統語音各念一次，接成一條音訊；另有 88 句不含這兩個詞的句子（含「嘿鴨子」「Hello 爺爺，鴨子在哪裡？」「Hey nurse」等相近的）。Mac 上跑，每 100 ms 一塊。

| 設定 | Hello 鴨子 | Hey 鴨子 | 其他句子觸發 |
|---|---:|---:|---|
| 只用 ARPAbet 寫法，門檻倍數 0.7／1.0／1.5 | 2／7 | 1／7 | 1／88（「嘿鴨子」，等於同一句話） |
| 同上，門檻倍數 2.0 | 2／7 | 1／7 | 0／88 |
| 加上各種拼法（15 種），0.15／1.5 | 3／7 | 2／7 | 6 句都是「嘿鴨子」 |
| 同上，提升 3.0、門檻 0.05 | 5／7 | 3／7 | 「嘿鴨子」5 句＋「Hello 爺爺…」1 句 |

回報延遲（關鍵詞說完到引擎回報）中位數約 0.43 秒。對照同一批語音上的其他候選（11-26 傍晚較小的一批，每詞 3～4 句）：Hello Duck 4／4、Hey Duck 3／4、Hello Nous 3／4、Hey Nous 2／4、小鴨小鴨 2／3。

讀法：

1. 合成語音上這兩個詞**認得不好**（各 1～3／7）。但合成語音的參考價值有限：這些系統語音念「Hello／Hey」是中文腔，同一個模型對不同合成聲音的結果差很多（11-25 的紀錄：一種聲音 12／17、另一種 1／9），AIOS 用真人量 Hey Nous 是 8／10。
2. 「Hey 鴨子」實際被認出來時，命中的幾乎都是「嘿鴨子」的拼音寫法，所以清單裡兩種寫法都留。
3. **可不可行要用使用者本人的聲音量**（§8）。我沒有換詞。如果真人測出來不行，依合成語音的數字，替代方案的順序是：(a) 先把「喚醒門檻倍數」調低到 0.5～0.7、或把提升分數加大（誤喚醒會變多，要一起量）；(b) 英文結尾的「Hello Duck／Hey Duck」在這個模型上最穩；(c) 純中文的「小鴨小鴨」居中。

### 3.2 喇叭播合成語音 → 空氣 → 麥克風（實機，20:20～20:30）

用鴨子自己的喇叭播上面的合成語音當聲源（`tools/acoustic_wake_test.py play`）：28 句關鍵詞只回報 1～6 句（音量 0.04／0.15／0.3 都差不多）。對照診斷：同一批 15 句直接餵檔案回報 10 句；經喇叭→空氣→麥克風後，ch0 與 ch1 各只回報 1 句（用全新的引擎離線解，排除串流邏輯）。

結論：**十幾公分外的小喇叭播合成語音不能代表人在 1～3 m 外說話**，這條路量不出喚醒率。附帶的好消息是自我觸發的風險低——鴨子自己喇叭播出來的話，喚醒引擎幾乎認不出。

### 3.3 環境誤喚醒（實機，只聽不播）

| 時間 | 啟用的喚醒詞 | 長度 | 觸發 | 當時 ch0 音量（p10／p50／p90） |
|---|---|---:|---:|---|
| 20:35～20:50 | 7 個候選全開（Hey 鴨子、嘿鴨子、Hey Duck、Hello Duck、Hey Nous、Hello Nous、小鴨小鴨） | 15 分鐘 | **0** | −47／−39／−28 dBFS（房間裡有環境聲） |
| 23:47～00:02 | Hello 鴨子＋Hey 鴨子（共用裝置 `duck_mic`） | 15 分鐘 | **0** | −50／−48／−43 dBFS（深夜，房間安靜） |

樣本只有各 15 分鐘、不知道期間有沒有人說話或開電視，**不能換算成每小時誤喚醒率**；要長時間（至少幾小時、含電視聲與日常對話）再量。

### 3.4 CPU 與記憶體（Pi 4，1 執行緒）

喚醒偵測常駐：佔一顆核心 **15.7～16.8%**（15 分鐘平均）；整個服務行程（含收音與主迴圈）約 21%、RSS 約 **89～96 MB**；模型載入約 3 秒。量測時負載 0.3～0.5、47～55 °C、`get_throttled=0x0`。

## 4. 和 Chromium 共用麥克風（Pi 實機，23:37～23:42）

ALSA 的硬體收音裝置一次只能被一個程式打開。用 dsnoop 做共用裝置 `duck_mic`（[`robot/audio/alsa/duck-audio.conf`](../../robot/audio/alsa/duck-audio.conf)，用環境變數 `ALSA_CONFIG_PATH` 載入，**沒有改 `~/.asoundrc` 或 `/etc`**）：

| 檢查 | 結果 |
|---|---|
| 兩個 `arecord` 同時讀 `duck_mic`（16 kHz 雙聲道＋48 kHz 單聲道，各 3 秒，輸出到管線） | 兩邊都拿到完整資料（192000、288000 bytes）；這時直接開 `hw:Array` 會失敗（裝置忙），符合預期 |
| 無螢幕 Chromium 156（`--headless=new`，B 線的 `run_local_probe.sh --enumerate-only`，加 `--use-fake-ui-for-media-stream --alsa-input-device=duck_mic`） | `getUserMedia` 成功（226 ms）、音軌 `live`；輸入裝置清單 7 個，含 `duck_mic` |
| 同上，**喚醒偵測同時在讀 `duck_mic`** | Chromium：`getUserMedia` 成功、音軌 `live`；喚醒偵測照常（45 秒、CPU 16.8%） |
| 那 20 秒的負載 | Chromium CPU 平均 5.7%（最高 6.9%）、PSS 平均 442 MB；可用記憶體最低 1301 MB（平常約 1520 MB）；51.6～52.1 °C；load1 平均 1.7 |

- 探測頁只回報成功與裝置名稱，沒有錄、沒有傳；沒有連 Nous；沒有任何播放裝置被打開。
- 注意：`run_local_probe.sh` 在非 `--enumerate-only` 模式會加 `--disable-audio-output`，Chromium 會換成假的音訊管理員，**列不到任何輸入裝置**（`audioinput: 0`、`NotFoundError`）。所以「通話中」（WebRTC 編解碼）的負載在真麥克風下還沒量到，要等真的通話。
- Chromium 的音訊輸出：`--alsa-output-device=plughw:CARD=CD002,DEV=0`（沒有實際播放過；深夜）。

## 5. 喚醒服務的端到端（Pi 實機）

| 時間 | 做了什麼 | 結果 |
|---|---|---|
| 23:46 | `voice_service --mode wake`（共用麥克風、暫用的設定資料夾把 `audio.mute` 設成開、事件送到測試用的 UDP 埠），用 `SIGUSR1` 手動觸發一次 | 測試埠收到 `{"v":1,"kind":"wake_word","keyword_id":"MANUAL","doa_deg":null,"t_ms":…,"mock":false}`；log：「喚醒詞 MANUAL」「音效 listen_on 沒播：hard_mute」（靜音時照實回報沒播）；`applied/duck-voice.json` 寫出實際在用的設定。**沒有出聲** |
| 20:35（方向調整前） | 實驗的原生通道：`--mode native` 對模擬的 Nous（mock），手動觸發 → 收音 4 秒 → mock 回一句合成語音 → 變聲後從喇叭播出（音量 0.2，同時送參考訊號）→ 回到待命 | 狀態依序 listening → waiting → speaking → idle，播放 4.3 秒的回話無錯誤。這條路**未採用** |

**真的由說話觸發的喚醒（說「Hello 鴨子」→ 聽到提示音）還沒有發生過**：沒有真人聲音。提示音 `listen_on` 經服務播到喇叭只在 20:35 那次原生模式跑過（當時沒有人回報聽感）。

systemd 服務 `duck-voice` 已安裝、**disabled、沒有啟動過**（上面的測試是直接執行模組）。單元檔的限制（`ProtectSystem=strict`、`IPAddressDeny=any`＋`IPAddressAllow=localhost`）**還沒有在啟動狀態下驗證**——特別是 `IPAddressDeny` 需要核心支援 cgroup BPF，第一次 `systemctl start` 時要看 log 有沒有警告。

## 6. 在 Pi 上裝了什麼、留下什麼

| 項目 | 說明 |
|---|---|
| `~/duck/voice/` | 服務的程式、音效、喚醒詞清單、ALSA 共用設定、`duck_settings` 的讀取端、喚醒模型（`fetch_models.py` 核對 SHA-256） |
| `~/duck/audio-venv` | 多裝 `websockets==17.4`（原有 numpy 2.5.3、sherpa-onnx 2.0.1） |
| `/etc/systemd/system/duck-voice.service` | disabled、未啟動 |
| `~/duck/d-line/audio/` | 量測工具（同步更新） |
| `~/duck/terminal-spike/runs/` | B 線探測腳本這次的 4 個結果資料夾（只有 JSON 與 log，沒有音訊） |
| 沒有動 | `~/.asoundrc`、`/etc/alsa`、混音器、`duck-settings`（**設定頁還是舊版**，見 §7）、duckd、duck-doa、舵機匯流排；沒有重開機；沒有新裝 apt 套件（Chromium 是 B 線先前裝的） |
| 測試檔 | 合成語音（`say` 產生）放過 `~/duck/d-line/audio/build/say_kws/`，量測結束後刪除。**沒有任何錄音落地** |

## 7. 交給別的線

**整合線／E 線（設定）**：我改了 `robot/settings/`——

- `schema.py`：新增 `VOICE` 服務常數；`features.wake_word`、`features.sound_effects`、`privacy.wake_listening`、`audio.volume_cap_day`、`audio.mute` 從「規劃中」改成已實作（由 `duck-voice` 讀），說明文字改成「只管本機提示音」；新增 `audio.volume`、`audio.wake_sensitivity`、`audio.wake_holdoff_s`、`features.voice_terminal`（規劃中）；`audio.wake_keyword` 的選項與預設改成 `YAZI_EN`；`audio.voice_*` 三項維持停用、原因改成「路線 2 不適用」；`audio.volume_cap_night` 的原因改成夜間排程還沒做。
- `status.py`：服務清單加 `duck-voice`。
- 測試：`test_schema.py`、`test_server.py`、`test_store.py`、`tests/web/check_settings.cjs` 裡拿 `audio.volume_cap_day`／`audio.mute`／`features.wake_word` 當「停用項目」範例的地方，換成仍然停用的項目。`check_settings.cjs`（無頭瀏覽器）我**沒有在本機跑**，交給 CI。
- **Pi 上的設定頁還沒重新部署**（那是使用者在用的常駐服務，我沒有重啟它）。合併後請跑 `deploy_settings.sh`，新的項目才會出現在頁面上；在那之前 `duck-voice` 用預設值。
- CI 目前只跑音訊的 DOA 測試；`robot/audio/tests` 其他測試沒有進 CI（`.github/` 不是我的範圍）。

**A 線（duckd）**——我沒有改 `robot/duckd/`：

1. 感知埠 `127.0.0.1:8793` 收到 `{"v":1,"kind":"wake_word","keyword_id":…,"doa_deg":null,"t_ms":…,"mock":false}` 時，發 duck-link 事件 `wake_word`（`data` 帶 `keyword_id`、`doa_deg`）。現在 duckd 會靜靜忽略這個 `kind`，所以**喚醒目前到不了 Nous**。
2. `doa_deg`：我送 `null`；duckd 手上有 duck-doa 的最新方位，可以補上，也可以順便做「喚醒時轉向聲源」。
3. 把目前的 presence 用 UDP 送到 `127.0.0.1:8794`（`{"v":1,"kind":"presence","state":"…"}`），讓對話期間不偵測喚醒詞。沒做的話退路是固定 8 秒。
4. 頭轉動時的舵機聲很大（A 線紀錄：能量約 1e6）：會不會誤觸發喚醒詞**沒有量**（不能啟動 duckd）。

**B 線**：Chromium 的啟動參數（§4）、事件格式已用訊息告知。

## 8. 需要使用者做的事

1. **用你的聲音測喚醒詞**（白天，約 10 分鐘，會聽到「嘟嘟」）：
   ```bash
   ssh duck-pi4 'sudo systemctl start duck-voice && journalctl -u duck-voice -f'
   ```
   等 log 出現「喚醒詞：YAZI_EN」後，站在鴨子前面約 1 m，用平常的音量說「Hello 鴨子」10 次、「Hey 鴨子」10 次（每次間隔約 10 秒，因為叫醒後 8 秒內不再偵測）；再退到約 3 m 各說 5 次。每次成功會聽到往上的「嘟嘟」，log 多一行「喚醒詞 HELLO_YAZI／HEY_YAZI（第 n 次）」。請記下各說了幾次、成功幾次。然後正常聊天或開電視 10 分鐘，看有沒有自己叫醒。結束：`ssh duck-pi4 'sudo systemctl stop duck-voice'`。
   第一次啟動時若 log 有 `IPAddressDeny` 或 `ProtectSystem` 的警告或服務起不來，把那幾行給我。
2. **提示音的音量與聽感**：太小或太大，在設定頁調「提示音音量」（要先重新部署設定頁，§7），或告訴我。
3. **決定**：測完若這兩個詞不好叫，要不要換（§3.1 的替代方案）。
4. 真的連 Nous 出聲的對話（Chromium 語音終端）：等 B 線與 A 線接好，要你在場。
