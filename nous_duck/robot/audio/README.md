# robot/audio：喇叭、本機音效、變聲、喚醒詞

狀態（2026-11-26）：**喚醒服務 `duck-voice` 在 Pi 上可以跑**（XVF3800 收音 → 本機喚醒詞 → 提示音＋送出 `wake_word`）；**喚醒詞「Hello 鴨子／Hey 鴨子」還沒有用真人聲音測過**；`wake_word` 要 duckd 轉成 duck-link 事件（A 線還沒接）。語音對話走路線 2（Pi 上的 Chromium，B 線）：對話的聲音不經過這個模組。
驗證層級：單元測試（131 項，其中 2 項需要 `aplay`）＋ Pi 4 實機：麥克風底噪與喇叭回授量測、和無螢幕 Chromium 共用麥克風、環境誤喚醒計數、喚醒服務的無聲端到端。合成語音的喚醒數字**不是喚醒率**。
紀錄：[`voice-duck-side-2026-11-26.md`](../../docs/validation/voice-duck-side-2026-11-26.md)（喚醒服務、麥克風、Chromium 共用）、[`audio-2026-11-25.md`](../../docs/validation/audio-2026-11-25.md)（音效、變聲、喚醒引擎的運算量測）；設計：[ADR-0003](../../docs/adr/ADR-0003-mobile-terminal-wake-and-find.md)、[ADR-0010](../../docs/adr/ADR-0010-duck-voice.md)、[ADR-0017](../../docs/adr/ADR-0017-audio-playback-path-v1.md)。

## 職責

鴨子上的聲音進出：

- **出聲**：Nous 的語音（變聲後）與本機音效，都經過同一個閘門與音量上限。說什麼由 Nous 決定；鴨子不生成語言。
- **喚醒詞**：本機偵測（還沒有麥克風，只有引擎與量測）。
- 聲音只在記憶體裡串流：未喚醒的音訊不寫檔、不進 log、不外傳。

## 結構

| 路徑 | 內容 | Step |
|---|---|---|
| `duck_audio/sfx_synth.py` | 用 numpy 合成 21 個音效（規格：[`eye_expressions.md`](../../docs/eye_expressions.md) §5.3） | D5 |
| `sounds/*.wav`、`sounds/manifest.json` | 產生的音效（**自製、原創合成**；24 kHz 單聲道，共 392 KB）。不要手改，改程式後重新產生；測試會核對與程式一致 | D5 |
| `duck_audio/playback.py` | `DuckAudioOut`：`play_voice`（`duck_voice`，變聲）、`play_raw`／`play_sfx`（`duck_raw`）；`PlaybackGate`；`AplaySink`／`NullSink`／`WavSink` | D5 |
| `duck_audio/play.py` | 播放檢查用的命令列工具 | D5 |
| `duck_audio/voice.py` | 變聲候選：`DelayLineShifter`、`PhaseVocoderShifter`（可設共振峰） | D6 |
| `duck_audio/kws.py` | 喚醒詞：`WakeConfig`（關鍵詞由設定檔決定）、`WakeEngine`（sherpa-onnx KWS、自我觸發防護、安靜重置） | D7 |
| `config/wake_keywords.candidates.json` | 喚醒詞**候選**（量測用；使用者還沒決定） | D7 |
| `fixtures/` | **合成語音 fixture**（MeloTTS，MIT；不是真人錄音）：變聲用的一句、喚醒詞用的 14 句 | D6、D7 |
| `tools/fetch_models.py` | 下載 KWS／TTS 模型並核對 SHA-256（不進版控） | D6、D7 |
| `tools/make_speech_fixture.py` | 用 MeloTTS 產生 `fixtures/` | D6、D7 |
| `tools/make_say_fixture.sh` | 用 macOS `say -o` 產生更多合成語音到 `build/say_kws/`（**不進版控**） | D7 |
| `tools/bench_voice.py`、`tools/bench_kws.py` | Pi 上的量測 | D6、D7 |

## 怎麼跑

```bash
cd nous_duck/robot/audio
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt     # numpy、pytest
.venv/bin/python -m pytest tests -q                                   # Mac：75 passed, 2 skipped（沒有 aplay）
.venv/bin/python -m duck_audio.sfx_synth --out sounds                 # 重新產生音效
```

喚醒詞與合成語音（選用）：

```bash
uv pip install --python .venv/bin/python -r requirements-kws.txt      # sherpa-onnx 2.0.1
.venv/bin/python tools/fetch_models.py kws-zh-en                      # 需要網路
.venv/bin/python tools/bench_kws.py --set melo
```

Pi 4（不動 `~/duck/runtime-venv`；D 線的檔案在 `~/duck/d-line/`）：

```bash
rsync -a --delete --exclude models --exclude build --exclude __pycache__ --exclude .pytest_cache --exclude .venv nous_duck/robot/audio/ duck-pi4:duck/d-line/audio/
ssh duck-pi4 bash -s -- --kws --system < nous_duck/robot/deploy/pi4/setup_audio.sh
ssh duck-pi4 'cd ~/duck/d-line/audio && ~/duck/audio-venv/bin/python -m duck_audio.play --device null --sfx all'
ssh duck-pi4 'cd ~/duck/d-line/audio && ~/duck/audio-venv/bin/python tools/bench_voice.py'
```

**第一次真的出聲**（白天、有人在場）：

```bash
ssh duck-pi4 'cd ~/duck/d-line/audio && ~/duck/audio-venv/bin/python -m duck_audio.play --device plughw:CARD=CD002,DEV=0 --sfx listen_on --volume 0.1'
```

`--volume` 是要求的音量（0～1），會被夾到本機上限（白天 0.5）。先從 0.1 開始；硬體混音器目前是 75%。

## 喚醒服務 duck-voice（路線 2）

使用者 2026-11-26 的決定：語音對話由鴨子 Pi 上的 Chromium 開 Nous 頁面來做（路線 2）；喚醒詞先用「**Hello 鴨子**」與「**Hey 鴨子**」。所以這個服務只做一件事：

```text
XVF3800（共用裝置 duck_mic，ch0）─► 喚醒引擎（本機；音訊不離開這個行程）
        └─ 聽到喚醒詞 ─► 播本機提示音 listen_on（喇叭 CD002）
                      └► UDP 127.0.0.1:8793  {"v":1,"kind":"wake_word","keyword_id":"HELLO_YAZI","doa_deg":null,"t_ms":…,"mock":false}
                               └─ duckd 轉成 duck-link 的 wake_word 事件（**A 線還沒接**）─► Nous ─► Pi 上的 Nous 頁面開始對話
Chromium 語音終端（B 線）同時讀 duck_mic、直接播到 CD002；對話期間這個服務不偵測喚醒詞
```

| 檔案 | 內容 |
|---|---|
| `duck_audio/voice_service.py` | 常駐服務。`--mode wake`（預設）＝上面這條；`--mode native`＝實驗的原生上下行通道（未採用，見下） |
| `duck_audio/capture.py` | `arecord` 收音（只經管線進記憶體） |
| `alsa/duck-audio.conf` | ALSA dsnoop 的共用麥克風 `duck_mic`：喚醒服務與 Chromium 同時讀 |
| `config/wake_keywords.json` | 喚醒詞清單與組合（`YAZI_EN`＝Hello 鴨子＋Hey 鴨子）；用哪一組由設定頁決定 |
| `tools/measure_mic.py`、`tools/acoustic_wake_test.py` | 實機量測（底噪、回授、合成語音經喇叭、環境誤觸發） |
| [`../deploy/pi4/deploy_voice.sh`](../deploy/pi4/deploy_voice.sh) | 部署到 Pi、裝 systemd 服務 `duck-voice`（不 enable、不啟動） |

規則：

- **音訊不離開這個行程**：喚醒前後的音訊都只經過喚醒引擎，不寫檔、不進 log、不上網。送出去的只有「哪一句、什麼時候」。
- **`privacy.wake_listening` 或 `features.wake_word` 關掉時不開麥克風。**
- 叫醒一次後先不偵測：有人把對話狀態送到 `127.0.0.1:8794`（`{"v":1,"kind":"presence","state":"speaking"}`）時，非 `idle` 就不偵測；沒人送就固定 8 秒（`audio.wake_holdoff_s`）。
- systemd 單元另外限制：整個檔案系統唯讀（只有 `~/duck/settings/applied` 可寫）、網路只允許 loopback。
- 手動觸發（測事件有沒有送出）：`sudo systemctl kill -s USR1 duck-voice`。
- 設定都在「鴨子設定」：`audio.wake_keyword`、`audio.wake_sensitivity`、`audio.wake_holdoff_s`、`audio.volume`／`volume_cap_day`／`mute`（**只管本機提示音**，管不到 Chromium 播的對話聲音）、`features.wake_word`、`features.sound_effects`、`privacy.wake_listening`。變聲的三項標成「路線 2 不適用」。

在 Pi 上試：

```bash
bash nous_duck/robot/deploy/pi4/deploy_voice.sh
ssh duck-pi4 'sudo systemctl start duck-voice && journalctl -u duck-voice -f'
```

對鴨子說「Hello 鴨子」或「Hey 鴨子」：應該聽到往上的「嘟嘟」，log 出現「喚醒詞 HELLO_YAZI（第 n 次）」。

Chromium 語音終端要共用麥克風：啟動時設 `ALSA_CONFIG_PATH=/usr/share/alsa/alsa.conf:$HOME/duck/voice/alsa/duck-audio.conf`，加 `--alsa-input-device=duck_mic --alsa-output-device=plughw:CARD=CD002,DEV=0`。

還沒做、要別的線配合的：

- **duckd（A 線）**：感知埠收到 `kind:"wake_word"` 時發 duck-link 的 `wake_word` 事件（`data` 帶 `keyword_id`、`doa_deg`；`doa_deg` 可由 duckd 用自己最新的聲音方位補）；把 presence 轉送到 `127.0.0.1:8794`；喚醒時轉向聲源。duckd 現在會靜靜忽略這個 `kind`。
- **Chromium 語音終端的啟動與服務化、真的連 Nous 出聲**（B 線＋使用者在場）。
- **回音消除的參考訊號**：Chromium 直接播到 CD002 時，XVF3800 拿不到參考；第一版靠 Chromium 的 `echoCancellation`。

### 實驗：原生上下行通道（未採用）

路線 2 定案前寫的：`--mode native` 會在喚醒後把語音送到 Nous 端的 `/duck-voice`，把回話變聲後播出（`session.py`、`playback.StreamPlayer`／`RefSink`、`mock_nous.py`，介面 [duck-voice v0](../../protocol/proposals/d-duck-voice-media-channel.md)）。對模擬的 Nous 在 Pi 上跑通過，測試也還在跑，但**Nous 端沒有採用、不是鴨子現有的能力**；systemd 服務不用這個模式。留著的理由：之後若要讓對話的聲音經過變聲或鴨子的音量閘門，這是現成的起點。

## 播放路徑（D5）

```text
Nous 的語音 ─► play_voice ─► 閘門 ─► 變聲 ─┐
本機音效   ─► play_raw／play_sfx ─► 閘門 ──┴─► 增益（≤ 本機上限）─► 限幅 ─► 48 kHz 雙聲道 S16 ─► aplay ─► plughw:CARD=CD002
                                                                      └─► 音量包絡（10 Hz）─► 說話時的動作
```

- 第一版不用 PipeWire（Pi 上沒有裝），`duck_voice`／`duck_raw` 是這個行程的兩個邏輯輸出（ADR-0017）。
- 閘門（`PlaybackGate`）：

  | 狀態 | `voice` | `sfx` | `safety` |
  |---|---|---|---|
  | 一般 | 播（≤ 白天上限 0.5） | 播 | 播（用上限音量） |
  | 夜間 | 播（≤ 夜間上限 0.15） | 不播（`night_mode`） | **預設不播**（待決；可設定） |
  | 房間禁止出聲 | 不播（`privacy_policy`） | 不播 | 播 |
  | 實體隱私開關關閉 | 不播（`privacy_switch_off`） | 不播 | 不播 |
  | 本機強制靜音 | 不播（`hard_mute`） | 不播 | 不播 |

- 音量只能收緊：`request_volume()` 超過上限就夾到上限。上限是線性增益，**沒有對著喇叭量過**。
- 被擋下回 `status:"refused"` 與原因，不開裝置、不假裝播了。`status:"played"` 只代表送到 sink，**不代表有人聽到**。
- `play_voice` 沒有設定變聲器時拒絕（`voice_changer_missing`），不會用原聲冒充鴨子的聲音。
- 現在一次處理一整段；即時語音需要的串流播放迴圈還沒寫。
- 預錄的安全提示（「我跌倒了…」等，ADR-0010 §6）**還沒做**：要先定變聲參數，並用 Nous 的聲音產生。

## 變聲（D6）與喚醒詞（D7）

量測數字、試聽檔清單、發現的問題都在[驗證紀錄](../../docs/validation/audio-2026-11-25.md) §3、§4。摘要（Pi 4）：

| 項目 | 數字 |
|---|---|
| 變聲 `delay_line` | 佔一顆核心 1.7%，演算法延遲 20 ms |
| 變聲 `phase_vocoder`（可控共振峰） | 佔一顆核心 6.4%，演算法延遲 53 ms |
| 喚醒詞（sherpa-onnx 2.0.1，zh-en-3M，1 執行緒） | 即時常駐佔一顆核心 14.7%；記憶體約 98 MB；載入 3.2 秒；關鍵詞說完到回報 0.3～0.7 秒（中位數 0.49 秒，不含麥克風與驅動緩衝） |

## 聲源方向（DOA，T4）

狀態（2026-11-26 傍晚）：**實機讀得到**（Pi 4＋頭頂的 XVF3800，`2886:001a`、`bcdDevice` 2.06）。正前方校正、角度方向、聽聲轉頭在一個房間裡由使用者目視確認過；有電視聲時的表現與能量門檻 2e5 **還沒確認**。紀錄：[`docs/validation/duckd-head-hardware-2026-11-26.md`](../../docs/validation/duckd-head-hardware-2026-11-26.md)。

實機量到、和原本假設不同的三件事：

- `DOA_VALUE` 的角度與語音旗標在聲音停後會停留 2–3 秒，不適合拿來追蹤。現在預設用語音能量（`speech_source: energy`）：自動選擇波束的能量大於 `min_speech_energy` 才算有語音。
- 頭一轉動，舵機聲就被判成語音，而且比人聲還大。能量門檻擋不掉，靠 duckd 在頭停穩 1.0 秒內丟掉方位。
- 麥克風平放在頭頂、USB 接頭朝後時，原始角度是順時針為正：`counterclockwise` 要設 `false`。

| 路徑 | 內容 |
|---|---|
| `duck_audio/doa.py` | XVF3800 經 USB 控制介面讀角度與語音旗標、環狀分群、正前方校準、只在有語音時把方位送給 duckd（UDP `127.0.0.1:8793`）；每秒送一次存活訊息 |
| `config/doa.json` | `mount`（`head`／`body`／`desk`）、`front_angle_deg`、`counterclockwise`、`speech_source`、`min_speech_energy`、`calibrated`。**校正值不進 repo**：`front_angle_deg` 是每次安裝的量測值，只留在 Pi 的 `~/duck/doa/config/doa.json`（部署不會覆蓋）。**服務帶 `--settings-dir` 時改從[鴨子設定](../settings/README.md)讀**（ADR-0019）：門檻、視窗、安裝位置、校正值都在設定頁改，約 1 秒內生效、不用重啟；設定裡的「讀取聲源方向」關掉時服務不開也不讀麥克風。這時 `doa.json` 只在設定讀不到時當備援，校正值存在 Pi 的 `~/duck/settings/calibration.json` |
| `requirements-doa.txt` | pyusb 1.3.1（Pi 上沿用 runtime-venv 的） |
| [`../deploy/pi4/setup_doa.sh`](../deploy/pi4/setup_doa.sh) | 複製到 `~/duck/doa/`、udev 規則（VID 2886 給 plugdev）、服務 `duck-doa`（不 enable、不啟動） |

讀法沿用使用者的 [FamilyRecorder](https://github.com/pcpcchen-coder/FamilyRecorder)（`src/family_recorder/direction.py`，commit `ff76063`）。該 repo 的 `LICENSE` 是 **MIT**（ADR-0003 寫 Apache-2.0，和 repo 裡的檔案不一致，以檔案為準）；這裡是讀過之後重寫，沒有整段複製。

- 只用 USB 控制端點：不 claim 介面、不 detach `snd-usb-audio`，**不占用收音與播放**（那是 B 線「鴨子當終端」要用的）。
- 只送方位，不讀也不存任何聲音。
- 找裝置只看 VID `2886`；PID 不是 `001a`（FamilyRecorder 驗證過的標準版）時照樣嘗試，`--probe` 會標成未驗證。

麥克風接上後（在 Mac 上下指令）：

```bash
ssh duck-pi4 'lsusb | grep -i 2886'
```

```bash
ssh duck-pi4 'cd ~/duck/doa && ~/duck/duckd-venv/bin/python -m duck_audio.doa --probe'
```

校準正前方（指令開始後 5 秒內，站在鴨子正前方約 1 m 說話）：

```bash
ssh duck-pi4 'cd ~/duck/doa && ~/duck/duckd-venv/bin/python -m duck_audio.doa --calibrate 5 --write-config --settings-dir ~/duck/settings --config ~/duck/doa/config/doa.json'
```

看即時讀值（在不同方向說話，確認左邊是正的；不對就把 `counterclockwise` 反過來。`duck-doa` 在跑時兩個程式會互相要求重試，讀值變慢）：

```bash
ssh duck-pi4 'cd ~/duck/doa && ~/duck/duckd-venv/bin/python -m duck_audio.doa --watch 20 --config ~/duck/doa/config/doa.json'
```

```bash
ssh duck-pi4 'sudo systemctl start duck-doa'
```

測試：`cd nous_duck/robot/audio && ../duckd/.venv/bin/python -m pytest tests/test_doa.py -q`（需要 duckd 的 venv 或任何有 pytest 的 Python 3.10+；不需要 pyusb）。

## 等硬體／等你

| 等什麼 | 要做 |
|---|---|
| 使用者試聽（白天） | 21 個音效的聽感與音量；變聲候選與參數（`docs/validation/media/voice-2026-11-25-*.wav`）；音量上限 |
| 使用者決定 | 喚醒詞；夜間安全提示要不要出聲；ADR-0017（不裝 PipeWire） |
| XVF3800（Flex）麥克風陣列 | 收音迴圈、DOA、AEC 參考與自我觸發防護、真人喚醒率與誤喚醒率、走路噪音（清單見驗證紀錄 §4.4） |
| 語音通道（B 線、AIOS） | 串流播放迴圈；用 Nous 真正的聲音重選變聲參數；可懂度（CER）檢查 |

## 第三方

| 項目 | 授權 | 怎麼用 |
|---|---|---|
| numpy 2.5.3 | BSD-3-Clause | PyPI |
| sherpa-onnx 2.0.1 | Apache-2.0 | PyPI（選用）；與 AIOS 同版本線 |
| KWS 模型 zh-en-3M（2025-12-20） | **壓縮檔裡沒有授權檔與訓練資料說明**（AIOS 已記錄） | `fetch_models.py` 下載到 `models/`，不進版控、不散布；只做本機 spike |
| KWS 模型 wenetspeech-3.3M | 模型卡 Apache-2.0；訓練資料授權有疑義 | 同上（已下載，這次沒有用來量測） |
| MeloTTS zh_en（`vits-melo-tts-zh_en`） | MIT | 只在開發機合成 fixture；模型不進版控，合成出的 wav 進版控並標示合成 |
| macOS `say` | 系統語音 | 只在本機產生量測用的檔案，**不進版控** |
| Rubber Band 3.3.0（`rubberband-cli`） | GPL-2.0-or-later | Pi 上的系統套件，只當外部指令做比較；不放進 repo、不連結。它輸出的 3 個試聽檔在 `docs/validation/media/` |
| SoX 14.4.2 | GPL-2.0-or-later／LGPL | 同上 |
| 上游 runtime 的 wav | **沒有授權** | 沒有複製、沒有使用 |
