# 協定提案（D 線）：聲音被擋下的原因代碼、`sound` 的名稱清單

- 提出：D 線（感知與音訊），2026-11-25。**沒有改 schema**；由整合線決定要不要採用。
- 相關：`duck-link.v0.schema.json` 的 `reason`、`sound` 動作、`presence_params.speech_level`；[`robot/audio/`](../../robot/audio/README.md)。

## 1. 被播放閘門擋下時的原因代碼

鴨子端的播放閘門（`duck_audio/playback.py`）會回這些本機原因：

| 本機原因 | 意思 | v0 `reason` 裡最接近的 |
|---|---|---|
| `privacy_policy` | 所在房間禁止出聲（ADR-0006） | `privacy` |
| `privacy_switch_off` | 實體隱私開關關閉 | `privacy` |
| `night_mode` | 夜間模式（音效不播；安全提示預設不播） | **沒有** |
| `hard_mute` | 本機強制靜音 | **沒有** |
| `volume_zero` | 要求的音量是 0 | **沒有** |
| `cooldown` | 同一個音效還在冷卻時間內（`eye_expressions.md` §5.1） | **沒有** |
| `voice_changer_missing` | `duck_voice` 沒有設定變聲器 | `unsupported` |

提案：v0 的 `reason` 加 `quiet_mode`（涵蓋 `night_mode`、`hard_mute`、`volume_zero`）與 `rate_limited`（`cooldown`）。

在採用之前的繞法：`night_mode`／`hard_mute`／`volume_zero` 回 `privacy`、`cooldown` 回 `busy_mission` 都不貼切，建議先回 `rejected`＋`reason: "privacy"`（夜間與靜音）或 `reason: "invalid"`（冷卻），並把本機原因放在 `detail`（例如 `"detail": "night_mode"`）。

## 2. `sound` 動作的 `name`

`name` 目前是自由字串。鴨子端可用的名稱是 `robot/audio/sounds/manifest.json` 的 21 個（`boot_chirp`、`quack_hello`、`listen_on`…，與 `eye_expressions.md` §5.3 一致）。不在清單裡的回 `unknown_name`。不需要改 schema；Nous 端可以讀 manifest 產生工具的列舉。

## 3. `speech_level`

與 B 線的結論一致（AIOS 核心沒有音量資料）：`speech_level` 由鴨子端從**實際送到喇叭的聲音**算（`DuckAudioOut` 的 `on_level` 回呼，10 Hz，0～1 的 RMS），不經網路。不需要改 schema；`presence_params.speech_level` 可以留著當選用欄位。

## 4. 感知

本機 UDP 介面（`face`／`sound` 方位）不屬於 duck-link，沒有要改 schema 的地方。`capabilities` 現有的 `camera`、`microphone`、`speaker`、`tracking_face`、`tracking_sound` 夠用；目前鴨子應回報：`speaker: degraded`（裝置在、路徑通，但沒有試聽、沒有校準音量）、`camera`／`microphone`／`tracking_face`／`tracking_sound: unsupported`（沒有硬體）。
