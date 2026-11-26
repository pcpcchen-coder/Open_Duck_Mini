# 鴨子設定（robot/settings）

狀態：**第一版**（2026-11-26，E 線）。驗證層級：單元測試、對模擬服務的端到端（模擬麥克風、模擬身體，都是 mock）、無頭瀏覽器（桌面與手機寬度）。2026-11-26 晚上設定頁已部署到 Pi 並經區網驗證（頁面、存檔、拒絕規則），Pi 上的 duckd 與 duck-doa 也已用會讀設定的版本重新部署，**但還沒有啟動過，所以還沒有在實機上用它調過任何東西**；紀錄見 [`docs/validation/settings-2026-11-26.md`](../../docs/validation/settings-2026-11-26.md)。設計見 [ADR-0019](../../docs/adr/ADR-0019-duck-settings-page.md)。

鴨子沒有螢幕，所以設定用網頁改：手機或電腦連到鴨子（同一個區網），開 `http://duck-pi4.local:8081/`；手機認不得 `.local` 名稱時改用 Pi 的 IP：`http://<Pi 的 IP>:8081/`（IP 用 `ssh duck-pi4 hostname -I` 看）。不用密碼。

## 職責

- **設定的單一來源**：哪些東西可以調、預設值、範圍、誰讀它，全部定義在 [`duck_settings/schema.py`](duck_settings/schema.py)；值存在 Pi 的 `~/duck/settings/`。
- **設定網頁**：顯示每一項的目前值、預設值、範圍、說明、改了要不要重啟、生效了沒；驗證後儲存；回復預設；還原上一版。
- **給鴨子上其他服務讀設定的介面**（`duck_settings.reader`）：`duckd`、`duck-doa` 用它讀值並回報實際套用的值。

不負責：緊急停止、安全門檻、腿、扭力、零點偏移、啟動或停止服務（見 [ADR-0019 §2.6](../../docs/adr/ADR-0019-duck-settings-page.md#26-不能出現在設定頁上的東西)）。這個服務碰不到舵機匯流排。它是本機工具，不經過 duck-link，不是 Nous 的能力。

## 頁面分區

| 分區 | 內容 | 現況 |
|---|---|---|
| 功能開關 | 聽聲轉頭、具名動作、對話時的頭部小動作、說話時點頭 | 4 項接上 duckd，即時生效；看人（鏡頭未到）、喚醒詞、本機音效是停用的 |
| 語音與聲音 | 音量上限、夜間時段、靜音、變聲、喚醒詞 | **全部只能看**：喇叭播放路徑還沒接成常駐服務，沒有程式讀這些值 |
| 聽聲轉頭門檻 | 語音能量門檻、停穩等待、回正時間、死區；進階 5 項 | 9 項都接上（`duck-doa` 5 項、duckd 4 項），即時生效 |
| 頭部動作 | 最高角速度、活動範圍、對話小動作幅度 | 前兩項要重啟 duckd；幅度即時 |
| 眼睛表情 | 8 個 presence 狀態各用哪個表情；25 個表情的預覽圖；在鴨子上預覽 | 對應表接上 duckd，即時；預覽圖由 `duck_eyes` 渲染；螢幕未到，鴨子上只有虛擬面板（PNG）；亮度、自動眨眼停用 |
| 隱私 | 讀取聲源方向；固定規則（沒有開關） | 1 項接上 `duck-doa`（關掉就不讀麥克風）；模式、鏡頭、常駐聆聽、臉部辨識停用。**這一頁只能收緊** |
| 機體量測值 | 麥克風裝在哪、正前方校正值、角度方向、是否校正過 | 4 項接上 `duck-doa`；要先勾確認才能改；回復預設不會動它 |
| 系統狀態（唯讀） | 四個服務有沒有在跑、duckd 狀態、Pi 溫度與負載、設定檔版本與問題、還原上一版、不在這一頁的東西、最近的變更 | 只讀，不啟動也不停止任何東西 |

共 47 項，其中 29 項可以設定（有程式在讀）、18 項顯示但停用。

## 盤點（2026-11-26）

目前鴨子上可調的東西，以及這一版把它們放到哪。「狀態」：已實作＝有執行中的程式讀它；規劃中＝程式或服務還沒有；硬體未到。

| 項目 | 原本存在哪 | 誰讀 | 改了要重啟嗎 | 狀態 | 這一版 |
|---|---|---|---|---|---|
| 頭部最高角速度 | `duckd.service` 的 `--head-speed-deg 30` | duckd（仲裁器 `Limits`） | 要重啟 duckd | 已實作 | `head.speed_deg_s`（5～60°/s） |
| 頭部活動範圍 | `duckd.service` 的 `--head-window-deg 15` | duckd | 要重啟 duckd | 已實作 | `head.window_deg`（±5～30°） |
| 頭部角度上限、角速度硬上限、租約、跌倒角度 | `duckd/limits.py` | duckd | — | 已實作 | **不上設定頁**（安全） |
| 過熱、低電壓門檻 | `duckd/limits.py`、`servo_console/controller.py` | duckd、舵機控制台 | — | 已實作（暫定值） | **不上設定頁**（安全） |
| 聽聲轉頭：死區、停穩等待、回正時間、信心下限 | `duckd/track.py` 的常數 | duckd | 原本要改程式；現在即時 | 已實作 | `hearing.deadzone_deg`、`settle_s`、`recenter_s`、`min_confidence` |
| 聽聲轉頭：平滑視窗（0.8 s／2 筆／25°） | `duckd/track.py` | duckd | 改程式 | 已實作 | 沒接（留在程式裡） |
| 人臉追蹤增益、觀測新鮮度 | `duckd/core.py`（`TRACK_GAIN` 等） | duckd | 改程式 | 鏡頭未到 | 沒接 |
| 聽聲轉頭開關 | 沒有（Nous 下 `track sound` 才開始） | — | — | — | `features.track_sound`（關掉後拒絕並停止） |
| 具名動作開關 | 沒有 | — | — | — | `features.gestures` |
| 還沒實機驗證的動作要不要列出 | `--allow-unverified-gestures` | duckd | 要重啟 | 已實作 | 沒接（開發用，留在命令列） |
| presence → 表情 | `duckd/presence.py` 的 `EXPRESSION` | duckd | 原本改程式；現在即時 | 已實作 | `eyes.presence.<狀態>` 8 項 |
| presence → 頭部小動作的角度與節奏 | `duckd/presence.py` 的常數 | duckd | 原本改程式 | 已實作 | 開關兩個（`features.presence_head_motion`、`features.speaking_bob`）＋幅度倍率 `head.presence_amplitude`（0～1）；個別角度沒接 |
| 動作庫的動作內容 | `duckd/library/*.json` | duckd | 重新部署 | 已實作 | 沒接（動作要過載入檢查，ADR-0015） |
| 眼睛虛擬面板的更新率 | `--eyes-fps 1` | duckd | 要重啟 | 已實作 | 沒接 |
| 眼睛亮度、夜間調暗 | `duck_eyes/status.py` 的常數 | — | — | 硬體未到 | `eyes.brightness`（停用） |
| 眨眼間隔 | 各表情的定義（`duck_eyes/expressions.py`） | duck_eyes | 改程式 | 已實作 | `eyes.auto_blink`（停用：還沒有開關可接） |
| 麥克風裝在哪、正前方校正值、角度方向、是否校正 | Pi 的 `~/duck/doa/config/doa.json` | duck-doa | 原本要重啟；現在即時 | 已實作 | `calibration.mic.*` 4 項（量測值） |
| 語音能量門檻、判斷語音的方式 | 同上 | duck-doa | 原本要重啟；現在即時 | 已實作 | `hearing.min_speech_energy`、`speech_source` |
| 方位視窗、最少樣本數、分群角度 | `DoaConfig` 的預設（可寫進 `doa.json`） | duck-doa | 原本要重啟；現在即時 | 已實作 | `hearing.window_s`、`min_speech_samples`、`cluster_tolerance_deg` |
| 取樣率、送出頻率 | `DoaConfig` | duck-doa | 要重啟 | 已實作 | 沒接（沒有調的理由） |
| 讀不讀麥克風的方向 | 沒有（服務有跑就讀） | — | — | — | `privacy.sound_direction`（關掉就不讀裝置） |
| 白天／夜間音量上限、夜間安全提示 | `duck_audio/playback.py` 的 `GateConfig` | 沒有常駐服務 | — | 規劃中 | `audio.volume_cap_day`、`volume_cap_night`（停用） |
| 夜間時段、本機靜音、房間禁止出聲 | `GateState`（沒有來源在設定它） | — | — | 規劃中 | `audio.night_start`／`night_end`、`audio.mute`（停用） |
| 變聲方式、音高、共振峰 | `duck_audio/voice.py` 的參數 | 量測工具 | — | 規劃中（使用者還沒試聽） | `audio.voice_*` 3 項（停用） |
| 喚醒詞、門檻 | `config/wake_keywords.candidates.json`（量測用候選） | 量測工具 | — | 規劃中（還沒決定） | `audio.wake_keyword`、`features.wake_word`（停用） |
| 音效開關、各音效的冷卻時間 | `sounds/manifest.json` | — | — | 規劃中 | `features.sound_effects`（停用） |
| 鏡頭、常駐聆聽、臉部辨識、隱私模式 | ADR-0006（沒有程式） | — | — | 硬體未到／規劃中 | `privacy.camera`、`wake_listening`、`face_recognition`、`mode`（停用） |
| 舵機零點偏移 | 上游 `~/duck_config.json` | duckd、舵機控制台 | — | 已實作 | **不上設定頁**（舵機控制台，要人在場） |
| hub 位址、duck_id、感知輸入埠 | duckd 命令列 | duckd | 要重啟 | 已實作 | 沒接（部署參數，不是使用者設定） |

## 結構

| 檔案 | 內容 |
|---|---|
| `duck_settings/schema.py` | 47 項設定的定義、驗證、跨項目規則、禁止上頁面的 key |
| `duck_settings/reader.py` | 讀檔（壞掉就退回預設並說明）、`Watcher`（檔案有變才重讀、回報實際套用的值）。只用標準函式庫 |
| `duck_settings/store.py` | 唯一的寫入入口：驗證、整批不寫、只收緊規則、原子寫入、上一版、變更紀錄 |
| `duck_settings/status.py` | 系統狀態（唯讀）、每一項「生效了沒」的判斷 |
| `duck_settings/eyes_preview.py` | 用 `duck_eyes` 渲染 25 個表情的預覽圖（沒有 numpy 就照實說不能） |
| `duck_settings/server.py` | HTTP 伺服器與存取限制 |
| `duck_settings/web/index.html` | 頁面（單一檔案，樣式與程式內嵌，不從網路載入任何東西；沒有建置步驟） |
| `duck_settings/cli.py` | 本機命令列：`list`／`get`／`set`／`reset`／`import-doa` |
| `tests/` | 單元測試、HTTP、對模擬聲源方位服務的端到端（36 項） |
| `tests/web/check_settings.cjs` | 無頭瀏覽器檢查與截圖（自己啟動設定頁＋模擬的 duckd 與聲源方位服務） |
| [`../deploy/pi4/deploy_settings.sh`](../deploy/pi4/deploy_settings.sh) | 部署到 Pi、systemd 服務 `duck-settings` |

其他模組裡跟設定有關的檔案：[`../duckd/duckd/settings_in.py`](../duckd/duckd/settings_in.py)（duckd 讀設定）、[`../audio/duck_audio/doa.py`](../audio/duck_audio/doa.py) 的 `DoaSettings`。

## 在電腦上試（不碰硬體）

需要 `uv`（系統 Python 3.9 太舊）。

```bash
cd nous_duck/robot/settings && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements-dev.txt
```

```bash
cd nous_duck/robot/settings && .venv/bin/python -m pytest tests -q
```

```bash
cd nous_duck/robot/settings && .venv/bin/python -m duck_settings --dir /tmp/duck-settings --bind 127.0.0.1 --port 8765
```

開 `http://127.0.0.1:8765/`。只開設定頁時，每一項會顯示「沒在跑；下次啟動時會用這個值」，因為沒有服務在讀。要看到「已生效」，另外開兩個終端機跑模擬的服務（都帶 `mock: true`，不碰硬體）：

```bash
cd nous_duck/robot/audio && ../settings/.venv/bin/python -m duck_audio.doa --run --mock-angle 30 --settings-dir /tmp/duck-settings
```

```bash
cd nous_duck/robot/duckd && .venv/bin/python -m duckd --body mock --settings-dir /tmp/duck-settings --eyes-panel /tmp/duck_eyes.png
```

（duckd 的 venv 見 [duckd 的 README](../duckd/README.md)；設定頁要連到這個 duckd 的本機控制介面時，啟動設定頁前先 `export DUCKD_SOCKET=~/.cache/nous-duck/duckd.sock`。）

無頭瀏覽器檢查（要 Node.js 22 與 Playwright；`PYTHON` 要是裝了 duckd 依賴與 numpy 的 Python）：

```bash
PYTHON=$PWD/nous_duck/robot/duckd/.venv/bin/python node nous_duck/robot/settings/tests/web/check_settings.cjs
```

## 部署到 Pi

前提：跑過 `deploy_duckd.sh`（用它的 `~/duck/duckd-venv`）。

```bash
bash nous_duck/robot/deploy/pi4/deploy_settings.sh --start
```

- 不加參數：只安裝，**不 enable、不啟動**。`--start`：安裝後啟動（Pi 重開機後不會自己起來）。`--enable`：開機自動啟動。`--uninstall`：移除服務。
- 做的事：複製到 `~/duck/settings/app/`；在 `~/duck/duckd-venv` 加一個 `.pth`（不動 `runtime-venv`）；第一次把 `~/duck/doa/config/doa.json` 手改過的值搬進設定；裝 systemd 服務（`PrivateDevices=true`，碰不到舵機匯流排）。
- **不會**啟動、停止或重啟 duckd、duck-doa、duck-console，不碰舵機。
- duckd 與 duck-doa 要用這個分支的程式重新部署並重啟，才會讀這份設定：

```bash
bash nous_duck/robot/deploy/pi4/deploy_duckd.sh
```

```bash
bash nous_duck/robot/deploy/pi4/setup_doa.sh
```

在那之前，設定頁打得開、也存得進去，但每一項會顯示「沒在跑」或「還是舊版程式」，不會說已生效。

本機指令（登入 Pi 的人；可以放寬隱私設定）：

```bash
ssh duck-pi4 '~/duck/settings/duck-settings list'
```

```bash
ssh duck-pi4 '~/duck/settings/duck-settings set privacy.sound_direction true'
```

## 存取與安全

| 規則 | 做法 |
|---|---|
| 誰連得到 | **對區網開放，不用密碼**（使用者 2026-11-26 決定，[ADR-0019 §2.4.1](../../docs/adr/ADR-0019-duck-settings-page.md#241-使用者決定對區網開放不用密碼2026-11-26)）。只接受區網內的來源位址（loopback、私有網段、link-local）；不做對外網的穿透或轉送。同一個 Wi-Fi 上的裝置都能改這一頁 |
| 跨站請求 | 寫入只接受 JSON、要帶標頭 `X-Duck-Settings: 1`、`Origin` 要是這個頁面自己；`Host` 要是 IP、`*.local`、`localhost` 或主機名稱（擋 DNS rebinding） |
| 秘密 | 頁面與 API 不顯示任何金鑰、權杖、Wi-Fi 密碼 |
| 變更紀錄 | 每次變更記在 Pi 本機的 `~/duck/settings/changes.jsonl`：時間、來源、來源 IP、哪個 key、前後的值 |
| 範圍 | 超出範圍就拒絕並說明，不夾限；一批裡有一項不合格就整批不寫 |
| 未實作的項目 | 顯示但停用；任何來源都寫不進去 |
| 隱私 | 設定頁只能收緊；放寬要本機指令。「讀取聲源方向」關掉後服務不再讀麥克風 |
| 量測值 | 要先勾確認；回復預設、還原上一版不動它 |
| 硬體 | 服務看不到 `/dev` 裡的硬體裝置；不啟動、不停止任何服務 |
| 安全項目 | 不在 schema 裡（測試會檢查 key）；設定的上限低於 duckd 的硬上限 |

## API

`GET /api/state`、`GET /api/expressions`、`POST /api/save {changes, base_revision, confirm_measurements}`、`POST /api/reset {keys}`、`POST /api/restore_previous`、`POST /api/preview_expression {name}`、`GET /healthz`。被拒絕時回 400（不合格，`errors` 逐項說明）、409（別人先改過了）、403（存取限制）、503（duckd 沒在跑，不能預覽）、500（寫不進檔案，附原因）。

## 還沒做

- **在實機上看設定生效**：設定頁（啟動中、沒有設成開機自動啟動）與會讀設定的 duckd、duck-doa 都已在 Pi 上，但兩個服務還沒有啟動過；下次有人在場啟動時要補實機紀錄。
- 頁面看不出 Pi 上裝的 duckd／duck-doa 是不是會讀設定的版本：服務沒在跑時一律說「下次啟動時會用這個值」（[驗證紀錄 §4.3](../../docs/validation/settings-2026-11-26.md)）。
- 「語音與聲音」整區：等喇叭播放接成常駐服務（D 線）再接。
- 隱私模式、鏡頭、常駐聆聽：等對應的服務與硬體。
- Nous 經 duck-link 讀設定、收緊設定：只有[提案](../../protocol/proposals/e-settings-over-duck-link.md)。
- presence 各狀態的個別角度、人臉追蹤的增益、聽聲轉頭的平滑視窗：還在程式裡。
- 頁面只有繁體中文。
