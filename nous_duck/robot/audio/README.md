# robot/audio：喇叭、本機音效、變聲、喚醒詞

狀態（2026-11-26）：**語音服務 `duck-voice` 在 Pi 上對「模擬的 Nous」跑通**（手動喚醒 → 收音上行 → 回話變聲後從喇叭播出）；**真的 Nous 端還沒有對應的端點**（B 線）；**喚醒詞還沒有用真人聲音測過**。D5 播放路徑與音效、D6 變聲、D7 喚醒詞引擎見下面各節。
驗證層級：單元測試（129 項，其中 2 項需要 `aplay`）＋對模擬 Nous 的端到端（合成音訊）＋ Pi 4 實機：麥克風底噪與喇叭回授量測、合成語音經喇叭的聲學測試、對模擬 Nous 的實機端到端。
**喚醒率與誤喚醒率沒有用真人聲音量過；回話的聽感（變聲、音量）沒有人確認過。**
紀錄：[`voice-duck-side-2026-11-26.md`](../../docs/validation/voice-duck-side-2026-11-26.md)（語音服務）、[`audio-2026-11-25.md`](../../docs/validation/audio-2026-11-25.md)（音效、變聲、喚醒引擎的運算量測）；設計：[ADR-0010](../../docs/adr/ADR-0010-duck-voice.md)、[ADR-0017](../../docs/adr/ADR-0017-audio-playback-path-v1.md)；介面：[duck-voice v0](../../protocol/proposals/d-duck-voice-media-channel.md)（草案）。

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

## 語音服務 duck-voice（喚醒詞、收音、喇叭回話）

```text
XVF3800 ch0（處理後）─► 喚醒引擎（本機，音訊不離開記憶體）
        │                    └─ 喚醒 ─► 提示音 listen_on ─► 開上行
        └─ 只有「聽」的狀態 ─► 16 kHz PCM ─► ws://127.0.0.1:8791/duck-voice ─►（SSH 通道）─► Nous 端
Nous 的回話（24 kHz PCM）◄───────────────────────────────────────────────────────┘
        └─► 閘門 ─► 變聲 ─► 增益（≤ 上限）─► 限幅 ─► 喇叭 CD002
                                                └─► 同一段聲音送 XVF3800 的 USB 播放端（回音消除的參考）
```

| 檔案 | 內容 |
|---|---|
| `duck_audio/voice_service.py` | 常駐服務：麥克風執行緒、喚醒、連線、設定、播放 |
| `duck_audio/session.py` | 對話狀態機（純邏輯）：待命／聽／等回話／說；所有逾時；什麼時候音訊可以上行 |
| `duck_audio/capture.py` | `arecord` 收音（只經管線進記憶體） |
| `duck_audio/playback.py` 的 `StreamPlayer`、`RefSink`、`TeeSink` | 串流播放、回音消除參考 |
| `duck_audio/mock_nous.py` | **模擬的 Nous 端（mock）**：回一句固定的合成語音，測試用 |
| `config/wake_keywords.json` | 喚醒詞清單（Hey 鴨子、嘿鴨子、Hey Duck、Hey Nous…）；用哪一句由設定頁決定 |
| `tools/measure_mic.py`、`tools/acoustic_wake_test.py` | 實機量測（底噪、回授、合成語音經喇叭的喚醒測試、環境誤觸發） |
| [`../deploy/pi4/deploy_voice.sh`](../deploy/pi4/deploy_voice.sh) | 部署到 Pi、裝 systemd 服務 `duck-voice`（不 enable、不啟動） |

規則（細節在 `session.py` 與介面文件）：

- **喚醒前的音訊不離開記憶體**：只經過喚醒引擎；沒有 pre-roll、不寫檔、不進 log。只有「聽」的狀態會上行，而且只送到 loopback。
- **`privacy.wake_listening` 或 `features.wake_word` 關掉時不開麥克風。**
- 逾時都在鴨子本機：沒人說話 8 秒、說完安靜 1.5 秒、單輪最長 30 秒、等回話 15 秒（都在設定頁）。
- 半雙工：鴨子說話時不上行、不聽喚醒詞（`audio.barge_in` 可開，預設關）。
- 沒連上 Nous 時被叫醒：只播一聲提示音，不收音。
- systemd 單元另外限制：整個檔案系統唯讀（只有 `~/duck/settings/applied` 可寫）、網路只允許 loopback。
- 測試用的手動喚醒：`sudo systemctl kill -s USR1 duck-voice`（等於在鴨子上按一下「開始聽」）。
- 設定全部在「鴨子設定」（`robot/settings`）：`audio.*`、`features.wake_word`、`features.sound_effects`、`privacy.wake_listening`。

怎麼在 Pi 上試（先不接 Nous）：

```bash
bash nous_duck/robot/deploy/pi4/deploy_voice.sh
ssh duck-pi4 'cd ~/duck/voice && ~/duck/audio-venv/bin/python -m duck_audio.mock_nous --port 8791 --listen-s 4'   # 分頁 1：模擬的 Nous
ssh duck-pi4 'sudo systemctl start duck-voice && journalctl -u duck-voice -f'                                       # 分頁 2
```

然後對鴨子說喚醒詞（預設「Hey 鴨子」）：應該聽到「嘟嘟」（往上），說一句話，約 4 秒後鴨子用變聲後的合成語音回一句固定的話。那句話是 mock 的，不是 Nous 的回答。

還沒做、要別的線配合的：

- **Nous 端的 `duck-voice` 端點**（B 線）：沒有它就只能對 mock。
- **duckd 的動作**（A 線）：服務可以用 `--notify-duckd 127.0.0.1:8793` 把 `{"v":1,"kind":"voice_state","state":"listening"|"waiting"|"speaking"|"idle"|"error","turn_id":…,"t_ms":…}` 丟給 duckd，但 duckd 還不認得這個 `kind`，所以預設關。喚醒時轉向聲源、說話時點頭都要 duckd 那邊接。
- 喚醒當下的聲源方向（`doa_deg`）：duck-doa 與這個服務同時讀 XVF3800 的 USB 控制介面會互相重試，先不帶。

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
