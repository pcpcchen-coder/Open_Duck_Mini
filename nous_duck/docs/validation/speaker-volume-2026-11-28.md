# 喇叭音量設定（audio.speaker_volume）驗證紀錄

- 日期：2026-11-28
- 分支：`claude/duck-e-voice-volume`（PR #57）
- **驗證層級：單元測試（假的 amixer）＋實機 Pi 4（家裡區網，從 Mac 用 curl 打設定頁的 API，`amixer` 回讀）。沒有人在旁邊聽調整後的音量，也沒有量聲壓。**

## 1. 為什麼調硬體音量

路線 2 的對話聲音是 Pi 上的 Chromium 直接送到喇叭（`--alsa-output-device=plughw:CARD=CD002AUDIO,DEV=0`），不經過 `duck_audio.playback` 的軟體增益，所以「提示音音量」管不到。能同時管到對話與提示音的只有喇叭那張 USB 音效卡（CD002-AUDIO）的硬體音量 `PCM`（0～147）。`duck-voice` 用 `amixer -M`（照聽感換算的百分比）設定並回讀。

## 2. 單元測試

`robot/audio/tests/test_mixer.py` 9 項（假的 amixer，格式照 Pi 上讀到的輸出）：解析、`-M` 與 `unmute`、控制項的挑法、`amixer` 不存在或失敗、預設 100 時不寫混音器、改值後套用、被改掉後改回、寫了沒反應時回報實際值、找不到喇叭時回報 `None` 與原因、設定頁顯示「已生效／套用失敗」、命令列。另外 `robot/settings/tests/test_schema.py` 檢查設定和語音服務讀的 key 一致。

## 3. Pi 上

部署：`deploy_voice.sh`（複製檔案）→ `sudo systemctl restart duck-voice`（載入新程式）→ `deploy_settings.sh --start`（設定頁換新 schema；`duck-settings` 仍是 enabled）。部署前喇叭是 `PCM 147 [100%] [-0.94dB]`。部署時 `duckd`、`duck-terminal`、`duck-console` 在跑，沒有動它們；`duck-doa` 停著。

| 步驟 | 設定頁回報 | `amixer -M -c CD002AUDIO sget PCM` | `duck-voice` 的 log |
|---|---|---|---|
| 部署後 | 100、「已生效」 | 147 [100%] [−0.94 dB]（沒有改變） | （和現況一樣，沒有寫） |
| 經區網存 85 | 3 秒內「已生效」 | 133 [85%] [−3.56 dB] | 設成 85%，回讀 85% |
| 改回 100 | 「已生效」 | 147 [100%] [−0.94 dB] | 設成 100%，回讀 100% |
| 存 150 | 400「超出範圍 0～100%」，沒有寫入 | 沒變 | — |
| 在 Pi 上手動 `amixer sset PCM 50%`（模擬拔插或別人改） | — | 92 [50%] → 6 秒內回到 147 [100%] | 設成 100%，回讀 100% |

變更紀錄兩筆都有時間、`source: web`、來源 IP、前後值。驗證結束時喇叭是 100%，和部署前一樣。

## 4. 限制

- 沒有在對話中實際聽過：85% 時對話聲音有沒有變小，是由「Chromium 走的就是這張卡」推論的（`duck-terminal` 的 `--alsa-output-device`），沒有人耳確認。
- `-M` 的百分比和聽感的對應依卡片回報的 dB 範圍算，沒有量聲壓；85% 是 −3.56 dB、50% 是 −11.21 dB。
- 喇叭真的拔插後的行為只用手動改混音器模擬，沒有真的拔過。
- 設成 0 時喇叭完全沒聲音，連安全提示也聽不到；這是使用者可以選的，頁面說明有寫。
