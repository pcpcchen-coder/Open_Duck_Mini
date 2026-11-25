# D 線進度：感知與音訊

最後更新：2026-11-25 23:20（台北）。分支：`claude/duck-d-percept-audio-eae98e`（只有本機提交，沒有推送、沒有開 PR）。

硬體現況（2026-11-25 22:31 在 Pi 上查）：只有 USB 喇叭（`e2b7:0811 Jie Li CD002`，ALSA 卡名 `CD002`，只支援 48 kHz 雙聲道 S16）；**沒有鏡頭、沒有麥克風**。Pi 是 Debian 13、Python 3.13.5、沒有裝 PipeWire。

夜間規則的執行情況：**Mac 與鴨子的喇叭都沒有出聲**；沒有開 Mac 的鏡頭或麥克風；沒有碰舵機匯流排、I2C、GPIO；沒有重開 Pi；沒有動 `~/duck/runtime-venv`；沒有對 Nous（`127.0.0.1:8787`）發請求；AIOS 只有唯讀查閱。

## 總表

| Step | 內容 | 狀態 | 驗證層級 |
|---|---|---|---|
| D1 | 鏡頭抽象與合成影像來源 | 完成；真鏡頭來源**卡硬體**（沒有寫假驅動） | 單元測試（9 項） |
| D2 | 視覺連動頭部：人臉偵測→方位→選人→`look_at`、UDP `face` | 完成到合成資料；實機**卡硬體**（鏡頭） | 單元測試＋模擬閉迴路（28 項）；Pi 4 運算量測（合成畫面） |
| D3 | 視覺連動走路控制器 | 完成；實機**卡硬體＋等你**（鏡頭、實機走路要你在場） | 單元測試＋純運動學模擬（21 項；不是步態模擬） |
| D4 | 雙目估距 | 完成到合成資料；實機**卡硬體**（鏡頭與雙目校正） | 單元測試（10 項）＋合成雙目誤差表 |
| D5 | 喇叭輸出路徑與自製本機音效 | 完成到「送到裝置」；聽感與音量**等你**（試聽） | 單元測試（49 項）；Pi：null 裝置＋喇叭裝置靜音路徑檢查。**沒有試聽** |
| D6 | 變聲 spike | 完成（spike）；選哪個、參數多少**等你**（試聽） | 單元測試（14 項）；Pi 4 運算量測（合成語音）。**沒有試聽、沒有做可懂度檢查** |
| D7 | 喚醒詞 spike | 完成（spike）；喚醒率**卡硬體**（麥克風），喚醒詞**等你**決定 | 單元測試（14 項）；Pi 4 檔案輸入的運算量測。**喚醒率與誤喚醒率沒有量** |

測試指令與結果（2026-11-25，Mac，Python 3.13.16）：

```bash
cd nous_duck/robot/perception && .venv/bin/python -m pytest tests -q        # 67 passed
cd nous_duck/robot/audio && ../perception/.venv/bin/python -m pytest tests -q # 75 passed, 2 skipped（需要 aplay）
python -m pytest nous_duck/robot/tests -q                                    # 15 passed（既有 look_at，沒有改 look_at.py）
```

Pi 4 上：音訊 76 passed, 1 skipped（含 `aplay` 的 2 項）。`bash nous_duck/tools/check_upstream_untouched.sh` 通過。

## D1～D4（感知）

- 位置：[`robot/perception/`](../../../robot/perception/README.md)；驗證紀錄：[`perception-2026-11-25.md`](../../validation/perception-2026-11-25.md)。
- Pi 4 量到的（YuNet，合成畫面，22:42，負載 0.60，46.7→60.3 °C，沒有降頻）：

  | 輸入 | 單執行緒 | 4 執行緒 |
  |---|---:|---:|
  | 320×180 | 27 ms／張（10 Hz 佔一顆核心 28%） | 16 ms／張 |
  | 640×360 | 107 ms／張（做不到 10 Hz） | 67 ms／張（吃 3.8 顆核心） |
  | 1280×720 | 406 ms／張 | 260 ms／張 |

  雙目估距每張臉只多 1～3 ms。行程記憶體 188 MB。
- 合成資料上的結果：頭在 0.4～1.8 秒內轉到離人臉 5° 以內；走近停在 1.0～1.13 m、不衝過頭；人消失 0.5 秒後停下；雙目估距在合成畫面上誤差很小（**不代表實機**，實機誤差預估見驗證紀錄 §5）。
- 開發中修掉的問題：D3 一開始用「現在的頭角＋延遲的方位」換算，頭與身體會來回擺盪；改用拍攝當下的頭角並補償身體轉動，有回歸測試。
- 沒做的：真鏡頭來源（沒有硬體）；AprilTag、深度圖、避障（不在這次範圍）；`sound` 訊息的來源（沒有麥克風）；`look_at.py` 沒有需要改的地方，所以沒有動。
- 給 A 線：UDP 介面照約定實作（`duck_perception/link.py`，含 `decode_target` 可直接用）；`FollowController` 的介面在 README。給 C 線：`FollowController` 不看障礙與禁區，導航要包在外面。

## D5（喇叭與音效）

- 位置：[`robot/audio/`](../../../robot/audio/README.md)；驗證紀錄：[`audio-2026-11-25.md`](../../validation/audio-2026-11-25.md) §2；設計決定：[ADR-0017](../../adr/ADR-0017-audio-playback-path-v1.md)（草案：第一版直接寫 ALSA，不裝 PipeWire）。
- 21 個自製音效（numpy 合成，原始碼與 wav 都進版控，共 392 KB）。上游 runtime 的 wav 沒有使用。
- 播放路徑：`duck_voice`（變聲）與 `duck_raw` 兩個邏輯輸出、播放閘門、本機音量上限、限幅、音量包絡。
- Pi 驗證（22:51）：null 裝置播 21 個音效無錯誤；喇叭裝置在「混音器音量 0＋靜音＋送全零取樣」下寫入成功；檢查後混音器已還原（192、on）。
- 沒做的：預錄的安全提示語音（要先定變聲參數與 Nous 的聲音）；串流播放迴圈；PipeWire 虛擬裝置（ADR-0017 延後）。

## D6（變聲 spike）

- Pi 4（22:57，負載 1.42，A 線的 duckd 測試同時在跑）：`delay_line` 佔一顆核心 1.7%、延遲 20 ms；`phase_vocoder`（可控共振峰）6.4%、延遲 53 ms；每 20 ms 一塊最慢 3 ms。Rubber Band 與 SoX 以系統指令比較（整檔即時倍率 0.01～0.07）。
- 試聽檔 12 個在 `docs/validation/media/voice-2026-11-25-*.wav`（清單見驗證紀錄 §3.3）。
- 沒做的：可懂度（CER）檢查；用 Nous 真正的聲音測；小喇叭的濾波。

## D7（喚醒詞 spike）

- 安裝：`pip install sherpa-onnx==2.0.1`（aarch64 wheel，不用編譯；與 AIOS 同版本線）＋模型 zh-en-3M（下載腳本核對 SHA-256）。
- Pi 4（23:03，負載 0.93，1 執行緒）：即時常駐佔一顆核心 **14.7%**；記憶體約 **98 MB**；模型載入 3.2 秒；關鍵詞說完到引擎回報 0.30～0.71 秒（中位數 0.49 秒；不含麥克風與驅動的緩衝）。2 執行緒沒有變快但 CPU 變 5 倍，所以用 1 個。
- 發現：串流不重置時，前面有別的句子的關鍵詞容易漏（合成語音 17 句只回報 7 句）；加「安靜 0.7 秒重置」後 12～13 句。中文候選在不同合成聲音上差很多（MeloTTS 9 句只回報 1 句）。**這些都不是喚醒率。**
- XVF3800 到貨後的步驟列在驗證紀錄 §4.4。

## 需要你處理

| 事項 | 說明 | 預設（你沒決定之前） |
|---|---|---|
| **試聽音效**（白天） | 21 個音效沒有人聽過。指令在 `robot/audio/README.md`「第一次真的出聲」；也可以直接在 Mac 開 `nous_duck/robot/audio/sounds/*.wav` | 不改 |
| **試聽變聲並選參數** | 在 Mac 開 `nous_duck/docs/validation/media/voice-2026-11-25-*.wav`。建議先聽 `pv_formant112_p5`，再和 `pv_keep_formant_p5`、`delay_line_p5`、`rubberband_formant_p5` 比；告訴我哪個像鴨子又聽得懂、要不要更高或更低 | 起點：相位聲碼器、+5 半音、共振峰 ×1.12（沒有試聽，只依 ADR-0010 的目標挑） |
| **喚醒詞** | 候選：嘿鴨子、小鴨小鴨、鴨子鴨子、Hey Duck、Hello Duck（設定檔可改）。中文在這個模型上可能不好認（AIOS 的 Nous 也因此改用英文），要等麥克風到貨用真人聲音量 | 不定案；設定檔標 `candidates_for_benchmark` |
| **音量上限** | 白天 0.5、夜間 0.15（線性增益），沒有對著喇叭量過；硬體混音器目前 75% | 維持 |
| **夜間安全提示要不要出聲**（ADR-0010 待決 5） | 跌倒、電量低在夜間模式下要不要出聲 | 不出聲（可設定） |
| **ADR-0017** | 第一版不裝 PipeWire、由自己的行程直接寫 ALSA。若很快要在 Pi 上跑 AIOS 的 Chromium 頁面就要改 | 照 ADR-0017 草案 |
| **Pi 上多了系統套件** | `rubberband-cli`、`sox`（apt；變聲比較用，GPL 工具，只在 Pi 上）；不想留可以 `sudo apt remove rubberband-cli sox` | 留著 |
| **KWS 模型的授權** | zh-en-3M 的壓縮檔沒有授權檔（AIOS 已記錄同樣的問題）。目前只在本機下載做 spike，不進版控 | 產品化前要釐清或換模型 |
| 硬體 | AR0144 雙目鏡頭（D1～D4 實機）、XVF3800 麥克風陣列（D7、DOA、`sound` 訊息） | — |

## 給整合線

- 協定提案：[`protocol/proposals/d-audio-reasons-and-sound-names.md`](../../../protocol/proposals/d-audio-reasons-and-sound-names.md)（沒有改 schema）。
- 新 ADR：ADR-0017（草案）—— 需要加進 `docs/adr/README.md` 索引。
- 新驗證紀錄：`perception-2026-11-25.md`、`audio-2026-11-25.md` —— 需要加進 `docs/validation/README.md` 索引。
- `nous_duck/.gitignore` 加了 4 行（D 線的 `models/`、`build/`）。
- `robot/README.md` 的 `perception/`、`audio/` 兩列狀態可以更新（那個檔由整合線改）。
- 能力回報建議：`speaker: degraded`（路徑通、沒有試聽）、`camera`／`microphone`／`tracking_face`／`tracking_sound: unsupported`。
- Python 版本：Pi 實際是 3.13.5；numpy 2.5.x 需要 3.12 以上，所以 D 線的 venv 用 3.13（程式沒有用 3.11 之後才有的語法，但鎖定的 numpy 版本裝不進 3.11）。
