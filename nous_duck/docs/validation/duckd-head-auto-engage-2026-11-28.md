# 對話時讓頭出力、聽聲轉頭只在對話中、設定頁誠實顯示（2026-11-28 深夜）

- 分支：`claude/duck-head-auto-engage`（從 v2 `bdd912e` 開出）
- **驗證層級：單元測試（mock 身體、舵機控制台的模擬匯流排）＋開發機上的 mock 端到端＋Pi 唯讀查詢與部署後回讀**。
  **實機沒有驗證**：使用者睡了，整晚無人看顧，規定是任何舵機都不出力、不 engage、不出聲、不重開 Pi。
- 設計：[ADR-0014 補充 §A～§D](../adr/ADR-0014-duckd-head-direct-and-single-process.md#補充2026-11-28對話時讓頭出力聽聲轉頭只在對話中)

```bash
cd nous_duck/robot/duckd && .venv/bin/python -m pytest tests -q        # 205 通過、3 跳過，約 75 秒
cd nous_duck/robot/settings && ../duckd/.venv/bin/python -m pytest tests -q   # 39 通過
```

## 1. 為什麼頭沒動（Pi 唯讀，22:52）

使用者附了設定頁的截圖，「聽聲轉頭」「具名動作」「對話時的頭部小動作」「說話時跟著音量點頭」四項都顯示「已生效」，但他說對話時沒體驗到。

| 查什麼 | 結果 | 說明 |
|---|---|---|
| `duckd-ctl status` | `engaged: false`、`mode: limp`、`presence: idle` | duckd 常駐後沒有人接手頭部（11-27 整合線規定不 engage）。頭部的程式都在，只是沒有出力 |
| `wake.received` | 0 | duckd 22:44 重啟過（蹲低試跑之後恢復設定），計數會歸零 |
| `duck-voice` 的 log | 這次開機後沒有任何「喚醒詞 … 第 N 次」 | Pi 約 21:55 開機（使用者修左腳線時可能斷過電）；journal 不保存上一次開機的紀錄，所以白天的喚醒查不到 |
| 22:44 之後 duckd 收到的指令 | `commands: 1` | 這段時間沒有人對話 |
| `duck-doa` | inactive／disabled | 聽聲轉頭沒有聲音來源 |
| `speech_level` | repo 裡唯一的來源是 `nous_adapter` 的開發用手動來源；AIOS 的 presence（PR #158）沒有 `speaking` 的音量 | 「跟著音量點頭」沒有資料可用 |

所以設定頁的「已生效」只代表「duckd 讀到了這個值」，不代表頭會動。

## 2. 改了什麼

見 ADR-0014 補充：

- §A「對話時讓頭出力」（`features.head_auto_engage`，**預設關**）。
- §B 聽聲轉頭只在對話中。
- §C duckd 回報 `inactive` 原因，設定頁顯示「已讀到，但現在不會動」。
- §D 要別人補的。

`duckd-ctl status` 另外加了 `commands_by_action`、`presence_log`、`speech_level_seen`、`auto_engage`、`tracking_paused`、`settings_inactive`。

## 3. 單元測試（`robot/duckd/tests/test_auto_engage.py` 9 項，另改 3 個檔案）

| 測試 | 檢查 |
|---|---|
| `test_default_off_never_opens_the_bus` | 內建預設（沒有設定檔）時，送完 `wake→listening→thinking→speaking→idle`，**匯流排打開次數 0**；`look`、`gesture` 回 `rejected`／`unsupported`（`head is not engaged`），不是假成功 |
| `test_explicit_off_setting_also_never_opens` | 設定明確關：一樣 0 次 |
| `test_on_engages_at_conversation_start_and_releases_after_idle` | 開著但沒有對話：不接手；`listening` 一來就接手（開 1 次）、目標是歪頭 0.12 rad；`idle` 115 秒還接著、125 秒放開；放開後頭部扭力維持接手前（有出力）；腿的扭力從頭到尾沒被寫 |
| `test_head_was_limp_before_auto_engage_is_restored_to_limp` | 接手前頭沒出力：接手時開扭力，放開時關回去 |
| `test_bus_busy_blocks_and_retries` | 舵機控制台占著匯流排：不接手、`blocked` 附原因、設定頁原因是「自動接手失敗」；控制台放開後 5 秒還不試，30 秒後才接手 |
| `test_manual_engage_is_never_auto_released` | 本機 `engage` 的，對話結束 130 秒也不放開（`manual`） |
| `test_switching_off_releases_auto_engaged_head` | 對話中把開關關掉：放開 |
| `test_inactive_reasons_for_settings_page` | 關著：四項都是「頭部沒有出力」；開著並接手後：說話點頭變成「還沒收到說話音量」、聽聲轉頭變成「duck-doa 沒有在跑」；收到 `speech_level` 後說話點頭的原因消失 |
| `test_status_has_diagnostics` | `commands_by_action`、`presence_log`、`auto_engage`、`speech_level_seen` |

另外：

- `test_track_sound.py`：既有測試改成在「在聽」時追蹤，另加 `test_sound_tracking_pauses_outside_conversation`（idle 時頭不跟著 20° 的聲音轉、`tracking_paused`；回到 listening 才轉）。
- `test_percept_track.py`：同樣在「在聽」時追蹤。
- `test_settings_in.py`：預設功能多了 `head_auto_engage: False`。
- 設定頁：`test_inactive_reason_replaces_applied`（有 `inactive` 原因時狀態是 `inactive`，標籤不含「已生效」；原因消失後回到 `applied`），`test_head_auto_engage_defaults_off`。

## 4. 開發機上的 mock 端到端

`duckd.mock_hub --wake`（假的 Nous；手動丟兩次 `wake_word`）＋ `python -m duckd --body mock`，設定資料夾裡把「對話時讓頭出力」打開：

- `wake`：received 2、forwarded 2；`auto_engage`：`engaged`，engages 1、failures 0。
- presence 依序：`listening` → `thinking` → `speaking` → `idle`（`presence_log`）。轉送給喚醒服務的狀態：`idle, wake, listening, thinking, speaking, idle, wake, wake, idle`。schema 錯誤 0。
- `applied/duckd.json` 的 `inactive`：
  - 說話點頭：「還沒收到說話音量（speech_level）：Nous 目前沒有送，說話時頭不會點」。
  - 聽聲轉頭：「聽聲轉頭的來源（duck-doa）沒有在跑」。

這只證明 mock 上的流程通了：mock 身體不是真的舵機，mock hub 也不是真的 Nous。

## 5. 部署到 Pi：沒有部署

23:03 開始部署時 Pi 已經連不到：`duck-pi4.local` 解析不到，區網裡也找不到它（`192.168.1.112` 是另一台機器，主機金鑰不同；`192.168.1.53` host is down）。可能是使用者睡前把鴨子關機了，或 Pi 斷了網路。`deploy_duckd.sh` 卡在第一個 ssh（檢查 venv），**還沒停 duckd、沒複製任何檔案**，已手動中止。

所以 Pi 上還是舊版：沒有「對話時讓頭出力」開關，設定頁也還會顯示「已生效」。下次 Pi 開機、連得到時要部署：

```bash
bash nous_duck/robot/deploy/pi4/deploy_duckd.sh duck-pi4            # 停 duckd、複製；不會自己啟動
bash nous_duck/robot/deploy/pi4/deploy_settings.sh --start duck-pi4 # 設定頁（schema 多了這個開關）
ssh duck-pi4 'sudo systemctl start duckd'
```

部署後要回讀確認：duckd `engaged: false`、`auto_engage.state: off`、`fuser /dev/ttyACM0` 沒有 duckd、`applied/duckd.json` 有 `inactive`。

## 6. 沒有驗證的

- **實機頭部**：自動接手、接手後的頭部小動作、放開回位、垂頭。要使用者在場。
- 真的 Nous 送了哪些 presence、多久送一次：下次對話後看 `duckd-ctl status` 的 `presence_log`、`commands_by_action`。
- 自動接手的延遲：開匯流排、讀 4 顆、開扭力。喚醒後頭要多久才開始動，沒有量。
- 聽聲轉頭：`duck-doa` 沒有啟動，§B 的「只在對話中」只有單元測試。
- 說話點頭：要等 `speech_level` 有來源（ADR-0014 補充 §D）。
