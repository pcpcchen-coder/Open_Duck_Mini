# 驗證紀錄：換喇叭與自動找喇叭 — 2026-11-27

- 範圍：使用者換了鴨子的 USB 喇叭；程式改成自動找喇叭（[`robot/audio/duck_audio/speaker.py`](../../robot/audio/duck_audio/speaker.py)）。
- 驗證層級：單元測試＋ Pi 4 實機（**使用者親耳確認聽到**）。

## 1. 新喇叭

| 項目 | 舊（2026-11-22～26） | 新（2026-11-27） |
|---|---|---|
| USB | `e2b7:0811` Jie Li CD002 | `e2b8:0811` Jieli Technology CD002-AUDIO（同時被認成一個 USB 隨身碟與 HID 裝置） |
| ALSA 卡名 | `CD002` | `CD002AUDIO` |
| 格式 | S16_LE、2 聲道、48 kHz | 相同 |
| 硬體音量 | `PCM` 0～255 | `PCM` 0～147，接上時是 44（30%、−20 dB） |

程式、`~/.asoundrc` 都寫死舊卡名 `CD002`，換了之後喚醒服務的提示音、系統預設輸出、Chromium 的輸出都會找不到喇叭。

## 2. 試聽（22:27～22:40，使用者在場）

| 播了什麼 | 硬體音量 | 軟體增益 | 送出的峰值 | 使用者 |
|---|---:|---:|---:|---|
| `listen_on`、`quack_hello` | 44（30%、−20 dB） | 0.1 | 0.013、0.025 | **沒聽到**（太小聲） |
| 合成語音一句（4.3 秒） | 44 | 0.1 | — | 沒聽到 |
| 合成語音一句（正規化到滿刻度） | **110（75%、−7.9 dB）** | 0.5 | 0.5 | **聽到了** |
| `listen_on`，經自動找喇叭（`--device speaker`） | 110 | 0.3 | 0.038 | （沒有另外問） |

硬體音量留在 110。設定頁的提示音音量預設 0.2；音效檔峰值 −6 dBFS、「小」等級再 −12 dB，所以提示音實際峰值約 0.025，**可能還是太小聲**，要再聽一次決定。

## 3. 改了什麼

- `duck_audio/speaker.py`：環境變數 `DUCK_SPEAKER_DEVICE` 優先；否則在 `/proc/asound/cards` 找卡名以 `CD002` 開頭的 USB 音效卡；沒有就用唯一一張不是麥克風（`Array`）的 USB 音效卡；分不出來就報錯，不亂挑、不退回系統預設。`python -m duck_audio.speaker` 印出結果給 shell 腳本用。
- 喚醒服務每次播提示音前重新找（喇叭可以在服務執行中換）；`duck_audio.play --device speaker`；量測工具同樣改用自動找。
- `deploy_voice.sh` 印出找到的喇叭；`terminal/run_nous_terminal.sh` 的說明改成用 `duck_audio.speaker` 查名稱。
- Pi 上的 `~/.asoundrc`：照 [`pi4-runtime-2026-11-22.md`](pi4-runtime-2026-11-22.md) 的說明（「換喇叭時要改卡片名稱」）把 `CD002` 改成 `CD002AUDIO`；舊檔備份在 `~/.asoundrc.bak-cd002-20261127`。改完 `aplay -D default` 開得起來（送全零取樣，沒有聲音）。

單元測試：`tests/test_speaker.py` 5 項（用 Pi 上新舊兩次 `/proc/asound/cards` 的原文）；`robot/audio` 全部 134 passed、2 skipped（Mac）。

## 4. 麥克風

換喇叭之後第一次收音時，XVF3800 回 I/O 錯誤（kernel：`xhci_hcd … Transfer event for disabled endpoint slot 4 ep 5`），重新綁定 USB 驅動、USB 重置、暫時拔掉喇叭都沒救回；讀聲源方向的 USB 控制介面仍有回應。之後它回報的封包間隔是 125 µs（11-26 是 500 µs）。22:41 再試一次，1 秒只讀到 55 bytes（應該是 64000），**還是不正常**。原因不明；可能要把麥克風的 USB 拔插一次（斷電重開）。麥克風不正常時喚醒詞不能用。
