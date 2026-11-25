# robot/audio：喇叭、本機音效、變聲、喚醒詞

狀態：**D5 播放路徑與音效可用到「送到裝置」；D6 變聲與 D7 喚醒詞是 spike**（2026-11-25，D 線）。
驗證層級：單元測試（77 項）＋ Pi 4 上的運算量測（輸入是合成語音檔）＋不出聲的裝置路徑檢查。
**沒有人聽過任何聲音；沒有麥克風，喚醒率與誤喚醒率沒有量。**
紀錄：[`docs/validation/audio-2026-11-25.md`](../../docs/validation/audio-2026-11-25.md)；設計：[ADR-0010](../../docs/adr/ADR-0010-duck-voice.md)、[ADR-0017](../../docs/adr/ADR-0017-audio-playback-path-v1.md)（草案）。

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
