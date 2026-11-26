# duckd：喚醒事件轉給 Nous、presence 送回喚醒服務（2026-11-27）

日期：2026-11-27 00:10～00:20。分支 `claude/duckd-wake-relay`。A 線。

驗證層級先講清楚：

- **單元測試**（Mac、Pi）：有。
- **對模擬 hub 的端到端**（真的 WebSocket 與 UDP，hub 是 duckd 自己的假 hub，不是 Nous）：Mac、Pi 都跑過。
- **Pi 實機、沒有舵機出力**：有（§3）。喚醒是**手動觸發**的，不是有人說話。
- **沒有做**：真的說「Hello 鴨子」觸發、對真的 Nous（AIOS）、頭部出力時的任何一項、舵機聲會不會誤觸發喚醒（§5）。深夜、使用者不在旁邊，這次**沒有讓任何舵機出力，也沒有出聲**。

## 1. 做了什麼

「說 Hello 鴨子 → Nous 開始對話」這條路上，原本缺 duckd 這一段（[語音路徑 §8.2](../../nous_adapter/docs/voice-path.md)、[D 線紀錄 §7](voice-duck-side-2026-11-26.md)）：

```text
duck-voice（喚醒服務）──UDP 127.0.0.1:8793 {"kind":"wake_word",…}──► duckd ──duck-link 事件 wake_word──► Nous
duck-voice ◄──UDP 127.0.0.1:8794 {"kind":"presence","state":…}── duckd ◄──duck-link 指令 presence── Nous
```

| 項目 | 作法 | 檔案 |
|---|---|---|
| 收喚醒 | 感知埠多認一種 `kind:"wake_word"`（`keyword_id`、`doa_deg`、`mock`）。喚醒是一次性的事，排進佇列，控制迴圈每圈取走；格式不對的照舊丟掉並計數 | `robot/duckd/duckd/percept.py` |
| 轉給 Nous | 每一則喚醒送一個 duck-link 事件 `wake_word`。沒有改 schema（`event.data` 本來就沒有規定形狀）；`data` 的欄位見 §2 | `robot/duckd/duckd/core.py` |
| 連不上 Nous 時 | **不轉送，也不留著等連上再送**（晚到的喚醒會讓 Nous 在沒人叫的時候開始對話）。放超過 2 秒的也丟。兩種都計數，`duckd-ctl status` 的 `wake` 看得到 | 同上 |
| 補方位 | 喚醒服務送 `doa_deg: null`；duckd 用 2 秒內最新的聲音方位（`duck-doa` 送的）補。麥克風在頭上時加上當下的頭部 yaw 換成相對身體；頭沒接手（不知道頭在哪）就照實標成相對頭部 | 同上 |
| 本機反應 | 收到喚醒且目前是 `idle`／`sleeping`／`error`：本機先把 presence 設成 `wake`（抬頭 0.10 rad；有相對身體的方位、而且設定裡「聽聲轉頭」開著，頭同時轉向聲源，範圍同 `track sound`）。之後 Nous 送來的 presence 接手；8 秒內沒有人接手就自己回 `idle`。對話期間（`wake`／`listening`／`thinking`／`speaking`）頭維持朝向，結束才回正 | `core.py`、`presence.py` |
| presence 送回喚醒服務 | 每次 presence 改變就用 UDP 送到 `127.0.0.1:8794`，另外每 5 秒重送一次（喚醒服務 30 秒沒更新會當成對話結束）。本機設的 `wake`、斷線時的 `idle` 也送。只送狀態名稱。只允許送 loopback | `robot/duckd/duckd/voice_out.py`（新） |
| 啟動參數 | `--voice-port`（預設 8794；0＝不送）。systemd 單元不用改 | `__main__.py` |
| 測試用 | 假 hub 加 `--wake`：手動丟一則喚醒、像 Nous 一樣送 presence、看轉送 | `duckd/mock_hub.py` |

順手修了一個既有的錯：感知埠收到不是物件的 JSON（例如 `[]`）時，收訊執行緒會丟例外然後停掉，之後所有方位都收不到。新測試抓到的，已改成丟掉並計數。

## 2. `wake_word` 事件的 `data`

```json
{"keyword_id": "HELLO_YAZI", "doa_deg": 11.5, "doa_frame": "body", "doa_source": "duck_doa", "mock": false}
```

| 欄位 | 意義 |
|---|---|
| `keyword_id` | 喚醒服務給的代號（`HELLO_YAZI`、`HEY_YAZI`；手動觸發是 `MANUAL`） |
| `doa_deg` | 聲源方位（度），**往鴨子的左邊為正**、0＝正前方；不知道就是 `null` |
| `doa_frame` | `body`（相對身體）或 `head`（相對頭部；頭沒接手時）。`doa_deg` 是 `null` 時沒有這一欄 |
| `doa_source` | `duck_doa`（duckd 用最新的聲音方位補的）或 `wake_service`（喚醒服務自己帶的） |
| `doa_mock` | 方位來源是合成的才會出現（`true`） |
| `mock` | 這次喚醒是不是合成／測試觸發的 |

Nous 核心目前只看事件種類。這些欄位的形狀是 duckd 自己定的，已補進協定提案（[`a-duckd-gaps.md` §9](../../protocol/proposals/a-duckd-gaps.md)），沒有改 schema。

方位的可信度沿用昨天的結論（[實機紀錄 §8](duckd-head-hardware-2026-11-26.md)）：電視關時聽聲轉頭通過，有背景人聲時未定；所以喚醒時補的方位在有背景聲時也可能是錯的。

## 3. 結果

### 3.1 單元測試與端到端（Mac）

`cd nous_duck/robot/duckd && .venv/bin/python -m pytest tests -q`：**158 通過、3 略過**（略過的是需要 Pi 上游 runtime 的步態載入測試）。這一批新增 `tests/test_wake.py`（26 項）與 `tests/test_presence.py` 一項。其中一項是端到端：真的 WebSocket＋UDP（loopback 臨時埠）、假 hub、模擬身體、不接手頭部。

### 3.2 Pi 上的測試

`deploy_duckd.sh --test`：**159 通過、2 略過**（82 秒；不碰硬體）。

### 3.3 Pi 實機、不出力：手動封包（00:14:49～00:15:13）

`duckd` 用 systemd 單元啟動（`--body head`，**沒有 engage**，`mode: limp`、`head: null`），hub 是 Pi 上的假 hub（埠 8795）。假 hub 往 8793 丟一則 `wake_word`（`mock: true`），並在 8794 收 duckd 轉送的 presence（喚醒服務當時沒在跑）。

| 量到的 | 值 |
|---|---|
| 丟出封包 → hub 收到 `wake_word` 事件 | 38.2 ms；`data` 是 `{"keyword_id":"HELLO_YAZI","doa_deg":null,"mock":true}` |
| 丟出封包 → 8794 收到 `presence: wake` | 21.0 ms（第二次 21.9 ms） |
| hub 送 `presence` → 8794 收到 | listening 11.0、thinking 17.9、speaking 10.9、idle 14.9 ms |
| 沒有人接手時，本機的 `wake` 回到 `idle` | 8.04 秒 |
| 兩次喚醒 → 事件數、`event_id` | 2 個、不重複 |
| 不合 schema 的訊息 | 0 |
| duckd 自己的計數 | `wake: received 2, forwarded 2, dropped 0`；轉送 11 則、錯誤 0；迴圈 50.0 Hz、超時 0、單圈最長 17.3 ms |

延遲是同一台機器上的 loopback，量的是 duckd 這一段（最多等一圈 20 ms），**不是**「說完喚醒詞到 Nous 開始收音」的時間。

### 3.4 Pi 實機、不出力：真的喚醒服務，手動觸發（00:15:56～00:16:23）

喚醒服務照 D 線的作法直接執行模組（`--mode wake`、共用麥克風 `duck_mic`、暫用的設定資料夾只把 `audio.mute` 設成開），用 `SIGUSR1` 手動觸發。麥克風有開（機上設定的喚醒聆聽本來就是開的）；音訊沒有離開那個行程；**沒有出聲**（log：「音效 listen_on 沒播：hard_mute」）。`duckd` 同 §3.3。

| 步驟 | 結果 |
|---|---|
| 1. 觸發 | hub 收到 `wake_word`，`data` 是 `{"keyword_id":"MANUAL","doa_deg":null,"mock":false}`，22.0 ms |
| 2. hub 送 `presence: listening`，等 11 秒（超過喚醒服務自己的 8 秒退路），再觸發 | 喚醒服務 log 有「喚醒詞 MANUAL（第 2 次）」，但**沒有送出**，hub 沒收到事件——是 duckd 轉送的 presence 擋下的 |
| 3. hub 送 `presence: idle`，1.6 秒後觸發 | hub 收到第二個事件，21.3 ms；duckd 的 presence 變成 `wake` |
| 不合 schema 的訊息 | 0 |

`mock: false` 是喚醒服務自己填的；這兩次是手動觸發（`MANUAL`），不是有人說話。喚醒服務的 systemd 單元這次**沒有啟動**（仍然 disabled、沒啟動過）。

## 4. 測完的狀態（00:16:40）

- `duckd`、`duck-voice`、`duck-doa`：都停著、都沒有 enable。測試用的 drop-in 已移除，暫存檔已刪。
- Pi 沒有重開；`throttled=0x0`。
- Pi 上的 `~/duck/duckd/` 是這個分支的程式。`~/duck/settings/`（設定與校正值）沒有動，設定頁服務沒有重啟。
- **舵機匯流排**：這次沒有任何程式由我接上匯流排。**舵機控制台現在是連線狀態**，不是我昨天收尾時的「未連線」——它的事件紀錄顯示 2026-11-26 20:49～20:50 有人在用，20:50:19 因為「ID 12 電壓 5.9 V < 6.0 V（電池快沒電）」自動緊急停止（扭力關閉），20:50:53 起匯流排連續讀取失敗（舵機沒有回應，像是電源已經關掉或電池沒電）。我沒有碰它。**下次要動頭之前，電池要先充電，控制台要先按「釋放硬體」。**

## 5. 沒有量的：頭在動時，舵機聲會不會誤觸發喚醒詞

昨天量到頭轉動時麥克風的語音能量約 1e6（比安靜時高很多）。喚醒引擎會不會把這個聲音認成「Hello 鴨子」，**沒有量過**；要讓頭出力才量得到。

先講現在的保護到哪裡：

- 對話期間（presence 不是 `idle`）喚醒服務不偵測，而頭大部分的動作都發生在對話期間——這一段已經擋住。
- **沒擋住的**：`idle` 時頭在動的情況——`track sound` 開著、對話剛結束頭回正的那一兩秒、Nous 在沒有對話時下的 `look`／`gesture`。

量法（要你在場；電池充好、控制台釋放之後）。全程房間保持安靜、不要說話：

```bash
# 1. duckd：不把 presence 送給喚醒服務（這樣它整段都在偵測），hub 用假的
ssh duck-pi4 'sudo mkdir -p /etc/systemd/system/duckd.service.d && printf "[Service]\nEnvironment=DUCKD_TEST_ARGS=\"--url ws://127.0.0.1:8795/duck-link --voice-port 0\"\n" | sudo tee /etc/systemd/system/duckd.service.d/wake-noise.conf && sudo systemctl daemon-reload'
# 2. 喚醒服務：事件送到沒人聽的埠、提示音靜音，只看 log 裡「喚醒詞」出現幾次
ssh duck-pi4 'mkdir -p /tmp/wn && echo "{\"revision\":1,\"schema_version\":1,\"updated_at\":0,\"updated_by\":\"test\",\"values\":{\"audio.mute\":true}}" > /tmp/wn/settings.json && cd ~/duck/voice && ALSA_CONFIG_PATH=/usr/share/alsa/alsa.conf:$HOME/duck/voice/alsa/duck-audio.conf DUCK_MIC_DEVICE=duck_mic ~/duck/audio-venv/bin/python -m duck_audio.voice_service --mode wake --settings-dir /tmp/wn --models-dir ~/duck/voice/models --wake-udp-port 18793 --control-udp-port 0 2>&1 | tee /tmp/wn/voice.log'
# 3. 對照組：頭不動，安靜 3 分鐘，數 log 裡「喚醒詞」的次數
# 4. 另一個終端機：頭出力、連續動 3 分鐘（±15°、30°/s 的 look 與四個動作，重複 3 次）
bash nous_duck/robot/duckd/tools/head_check.sh; bash nous_duck/robot/duckd/tools/head_check.sh; bash nous_duck/robot/duckd/tools/head_check.sh
# 5. 收尾：停喚醒服務（Ctrl-C）、移除 drop-in
ssh duck-pi4 'sudo systemctl stop duckd; sudo rm -rf /etc/systemd/system/duckd.service.d; sudo systemctl daemon-reload; rm -rf /tmp/wn'
```

這份步驟**還沒有執行過**（`head_check.sh` 本身昨天在實機跑過；它會自己啟動、接手、釋放 duckd，和第 1 步的 drop-in 會不會互相蓋掉要在執行時確認）。

判讀：頭動的 3 分鐘裡只要出現一次喚醒，就要加「頭在動時不偵測」。那個改動兩邊都要動，這次沒有做：

- duckd 這邊已經知道頭是不是在動（仲裁器的設定值有沒有到位），可以在送給 8794 的訊息多帶一欄（例如 `"head_moving": true`），或在頭動時把狀態當成不是 `idle` 來送。
- 喚醒服務（D 線，`robot/audio/duck_audio/voice_service.py` 的 `on_control`）要認這一欄，頭在動以及停下後約 1 秒（昨天聽聲轉頭用的停穩等待）不偵測。

## 6. 還缺什麼

1. 對真的 Nous（AIOS、`NOUS_DUCK=on`）跑：`wake_word` 事件 → 頁面開始對話 → Nous 的 presence 回來。這次的 hub 都是假的。
2. 真的說「Hello 鴨子」觸發（要出聲，白天、你在場）。
3. 頭部出力時的喚醒反應：抬頭、轉向聲源、對話期間維持朝向、結束回正。這些只在模擬身體上測過；角度與時間是初始值。
4. §5 的舵機聲誤觸發。
5. 喚醒服務改用 systemd 單元啟動後這條路有沒有照樣通（單元有 `IPAddressDeny` 等限制，D 線紀錄 §5 說還沒在啟動狀態下驗證）。
6. `capabilities.microphone` 仍回報 `unsupported: no microphone`。麥克風已經在了（喚醒與聲源方位在用，對話收音走 Chromium），這一欄該怎麼報要和 B 線對一下，這次沒改。
7. `hello`／`state` 裡沒有「喚醒服務在不在」的資訊：喚醒服務沒在跑時，Nous 看不出鴨子叫不醒。
