# 驗證紀錄：鴨子終端 spike 準備（語音路線 A，T6）— 2026-11-26

- 範圍：[`voice-path.md` §2.3](../../nous_adapter/docs/voice-path.md)（[ADR-0003](../adr/ADR-0003-mobile-terminal-wake-and-find.md) §2.1 的路線 A）——在鴨子的 Pi 4 上不接螢幕跑 Chromium、開 Nous 頁面。今天只做**不需要 Nous、不會出聲**的部分。
- 驗證層級：**實機（Pi 4），不連 Nous、不出聲、沒有麥克風**。
- **沒有連過 Mac 上的 Nous，沒有開過任何通道。** Chromium 只載入 Pi 自己 `127.0.0.1` 上的一張探測頁。
- **喇叭沒有出聲**：探測時 Chromium 用內建的假輸出串流，執行期間每 0.5 秒檢查 `/proc/asound/*/pcm*p/*/status`，七次執行都沒有任何 ALSA 播放裝置被打開。
- **沒有麥克風**：`lsusb` 沒有 VID `2886`，`arecord -l` 是空的。標「假」的那幾列用的是 Chromium 內建的假麥克風（合成嗶聲），只證明瀏覽器的管線通，**不代表真的麥克風能用**。
- 沒有碰舵機匯流排、I2C、GPIO；沒有啟動、停止或重啟 `duckd`、`duck-console`；沒有重開機；沒有改 `/etc`（apt 套件自己放的檔案除外）、`~/.asoundrc` 或預設音訊裝置；沒有新增 systemd 服務。
- 執行：2026-11-26 11:47～12:06（Pi 的時間，+0800）。Raspberry Pi 4 Model B Rev 1.5（2 GB）、Debian 13 trixie、核心 `6.18.50+rpt-rpi-v8`。全程 `duckd` 是 `inactive`、`duck-console` 是 `active`（閒置，本來就是這個狀態）。

檔案：

| 檔案 | 用途 |
|---|---|
| [`robot/deploy/pi4/setup_terminal.sh`](../../robot/deploy/pi4/setup_terminal.sh) | 在 Mac 上跑：裝套件、複製腳本到 Pi 的 `~/duck/terminal-spike/`；`--check`、`--uninstall` |
| [`terminal/probe/index.html`](../../robot/deploy/pi4/terminal/probe/index.html) | 探測頁：權限、裝置列舉、`getUserMedia`、`AudioContext`、自動播放、（選用）頁面內 WebRTC 迴路；結果寫在頁面標題 |
| [`terminal/run_local_probe.sh`](../../robot/deploy/pi4/terminal/run_local_probe.sh) | 在 Pi 上跑：起顯示＋Chromium、載入探測頁、讀結果、取樣資源 |
| [`terminal/measure.sh`](../../robot/deploy/pi4/terminal/measure.sh) | 取樣 Chromium 的 CPU、記憶體，以及可用記憶體、負載、溫度、兩個服務的狀態；CSV |
| [`terminal/run_nous_terminal.sh`](../../robot/deploy/pi4/terminal/run_nous_terminal.sh) | **之後**真的開 Nous 頁面用。**還沒有執行過**（只測了「沒有設環境變數就拒絕」與終端 ID 檢查） |
| [`terminal/lib.sh`](../../robot/deploy/pi4/terminal/lib.sh) | 共用：kiosk 旗標、顯示、收尾 |

## 1. 裝了什麼

```bash
bash nous_duck/robot/deploy/pi4/setup_terminal.sh
```

`apt-get install --no-install-recommends chromium xvfb`，一共新裝 **100 個套件**。

| 項目 | 值 |
|---|---|
| `chromium`／`chromium-common` | `1:156.0.8078.108-1~deb13u1+rpt1`（`chromium --version`：156.0.8078.108） |
| `xvfb` | `2:21.1.16-1.3+rpt1+deb13u4` |
| 100 個套件的 Installed-Size 合計 | 687,425 KiB（約 671 MiB）；其中 `chromium` 300,337 KiB、`chromium-common` 86,359 KiB |
| 根分割區實際多用 | 939,716 KiB（約 918 MiB），含 apt 下載快取與套件索引；`/var/cache/apt/archives` 現在 263 MB |
| 根分割區 | 安裝前已用 5.6 GB → 安裝後 6.5 GB，可用 21 GB |
| 只為 Xvfb 裝的部分 | 20 個套件、14,328 KiB（`apt-get remove -s --autoremove xvfb` 的模擬結果） |
| 套件清單 | Pi 上 `~/duck/terminal-spike/apt-installed.txt`（安裝前後 `dpkg-query` 的差集） |

沒有裝 `cage`（Wayland 的做法，另外要 43 個套件）、沒有裝 PipeWire／PulseAudio 的服務（只有函式庫 `libpulse0` 被 Chromium 帶進來）。

移除：

```bash
bash nous_duck/robot/deploy/pi4/setup_terminal.sh --uninstall
```

它會照 `apt-installed.txt` 的清單 `apt-get purge`，再刪掉 `~/duck/terminal-spike/`。**`--uninstall` 沒有實際跑過**（東西要留給之後的實測）。想多清一點：`ssh duck-pi4 'sudo apt-get clean'` 可以清掉 apt 下載快取。只想拿掉 Xvfb：`ssh duck-pi4 'sudo apt-get remove --autoremove xvfb'`（先看它列的清單再同意）。

### Pi 上留下的東西

| 位置 | 內容 |
|---|---|
| apt 套件 | 上面那 100 個 |
| `~/duck/terminal-spike/`（412 KB） | 腳本、探測頁、`runs/`（七次執行的結果）、`apt-installed.txt`、`apt-install.log`、Chromium 的 `xdg-config/`、`xdg-cache/`、`xdg-data/` |
| `~/.local/share/pki/nssdb/`（3 個檔） | **不該在這裡**。Chromium 第一次啟動時建立的空憑證資料庫；前幾次執行還沒有把 `XDG_DATA_HOME` 指到 spike 目錄。腳本已修正（之後不會再寫到這裡，已驗證），但這個目錄我沒有刪掉。要刪：`ssh duck-pi4 'rm -rf ~/.local/share/pki'` |
| `/tmp/.X11-unix/`（空目錄） | Xvfb 建立的；重開機就沒了 |

沒有任何行程還在跑（最後檢查：沒有 chromium、Xvfb、`http.server`）。

## 2. 怎麼跑

```bash
ssh duck-pi4 'bash ~/duck/terminal-spike/run_local_probe.sh --display headless'
ssh duck-pi4 'bash ~/duck/terminal-spike/run_local_probe.sh --display headless --fake-media'
ssh duck-pi4 'bash ~/duck/terminal-spike/run_local_probe.sh --display xvfb'
ssh duck-pi4 'bash ~/duck/terminal-spike/run_local_probe.sh --display xvfb --fake-media'
ssh duck-pi4 'bash ~/duck/terminal-spike/run_local_probe.sh --display headless --fake-media --loopback'
ssh duck-pi4 'bash ~/duck/terminal-spike/run_local_probe.sh --display xvfb --fake-media --loopback'
ssh duck-pi4 'bash ~/duck/terminal-spike/run_local_probe.sh --display headless --enumerate-only --duration 5 --settle 1'
```

每次：開乾淨的 Chromium 設定檔 → 載入 `http://localhost:8931/index.html` → 等頁面回報 → 靜置 10 秒 → `measure.sh` 每 5 秒取樣一次、共 60 秒（12 筆）→ 全部收掉。結果在 Pi 的 `~/duck/terminal-spike/runs/<時間>-<變體>/`（`summary.json`、`result.json`、`measure.csv`、`command.txt`、`chromium.log`）。

Chromium 的旗標（`command.txt` 的實際內容，headless 那次）：

```text
/usr/bin/chromium --kiosk --user-data-dir=/home/duck/duck/terminal-spike/profile-probe
  --autoplay-policy=no-user-gesture-required --no-first-run --no-default-browser-check --noerrdialogs
  --disable-infobars --disable-session-crashed-bubble --disable-features=Translate,WebRtcPipeWireCamera
  --disable-background-networking --disable-component-update --disable-sync --password-store=basic
  --window-size=1024,600
  --headless=new                                       ← 顯示；Xvfb 時換成 --ozone-platform=x11 --disable-gpu
  --mute-audio --alsa-output-device=null --disable-audio-output --remote-debugging-port=9333   ← 只有探測加
```

- `--fake-media` 另外加 `--use-fake-device-for-media-stream --use-fake-ui-for-media-stream`。預設不加。
- 兩種顯示：**headless**＝Chromium 自己的 `--headless=new`，沒有任何顯示伺服器；**xvfb**＝先起 `Xvfb :99 -screen 0 1024x600x24 -nolisten tcp`，Chromium 用一般視窗模式。
- 結果怎麼讀：頁面把 JSON 寫進標題，腳本從 DevTools 的 `http://127.0.0.1:9333/json/list` 讀（只綁本機）。
- CPU % 的算法：兩次取樣之間所有 Chromium 行程的 `utime+stime`（`/proc/<pid>/stat`）÷ 間隔。**100 % ＝一顆核心滿載**，Pi 4 有四顆。
- RSS 是各行程加總，共用的分頁會重複算，所以遠大於實際佔用；PSS（`/proc/<pid>/smaps_rollup`）把共用分頁按比例分，比較接近實際。最直接的數字是 MemAvailable 少了多少。

## 3. 結果

### 3.1 瀏覽器行為

四個主要變體（60 秒閒置）：

| | headless・真實裝置 | headless・**假**麥克風 | Xvfb・真實裝置 | Xvfb・**假**麥克風 |
|---|---|---|---|---|
| `getUserMedia({audio:true})` | **失敗 `NotFoundError`**「Requested device not found」（30 ms） | 成功（293 ms），音軌「Fake Default Audio Input」 | **失敗 `NotFoundError`**（28 ms） | 成功（228 ms），音軌「Fake Default Audio Input」 |
| 麥克風權限（前／後） | `prompt`／`prompt` | `granted`／`granted`（旗標自動同意） | `prompt`／`prompt` | `granted`／`granted` |
| 列舉到的裝置（輸入／輸出） | 0／0 | 3／3（全是 Fake） | 0／0 | 3／3（全是 Fake） |
| 音軌設定 | — | 48000 Hz、單聲道、`echoCancellation`／`noiseSuppression`／`autoGainControl` 都是 true | — | 同左 |
| 輸入訊號 1 秒 RMS／峰值 | — | 0.070／1.02（假裝置的嗶聲；只接分析節點，沒有接到輸出） | — | 0.070／1.02 |
| `AudioContext` | `running`、44100 Hz；1 秒後時鐘前進 1.01 秒 | 同左 | 同左 | 同左 |
| 自動播放：`AudioContext` 不用手勢就 `running` | 允許 | 允許 | 允許 | 允許 |
| 自動播放：沒靜音的 `<audio>` 播全 0 的 wav | 允許 | 允許 | 允許 | 允許 |
| 頁面多久回報 | 3.6 秒 | 4.7 秒 | 3.6 秒 | 4.7 秒 |
| ALSA 播放裝置有沒有被打開 | 沒有 | 沒有 | 沒有 | 沒有 |

說明：

- 沒有麥克風時 `getUserMedia` 立刻回 `NotFoundError`，和預期一樣；因為在權限提示之前就失敗，**「沒有人能按允許時會怎樣」這次測不到**（見 §5）。
- `AudioContext` 的 44100 Hz 是 `--disable-audio-output` 的假輸出串流的參數，**不是喇叭的**（CD002 只支援 48000 Hz，見 [音訊紀錄](audio-2026-11-25.md)）。
- 真實裝置那兩欄輸出裝置是 0 個，也是 `--disable-audio-output` 造成的。拿掉這個旗標、只列舉不播放（`--enumerate-only`）時，Chromium 列出 **1 個輸出裝置、0 個輸入裝置**（沒有權限所以沒有名稱）。這一個是不是 `~/.asoundrc` 指的 USB 喇叭，沒有驗證。
- `setSinkId`、`RTCPeerConnection`、`navigator.mediaDevices` 都存在；`localhost` 是安全環境（`isSecureContext` 為 true）。
- User-Agent：headless 是 `HeadlessChrome/156.0.0.0`，Xvfb 是一般的 `Chrome/156.0.0.0`。兩者都自稱 `X11; Linux x86_64`（Chromium 的固定寫法，實際是 aarch64）。

### 3.2 資源（每列 12 筆、每 5 秒一筆）

| 變體 | Chromium 行程數 | CPU % 平均／最大 | RSS 加總（MB） | PSS 加總（MB） | MemAvailable（MB）前／最低／收掉後 | 1 分鐘負載 平均／最大 | 溫度（°C）平均／最大 |
|---|---|---|---|---|---|---|---|
| headless・真實裝置（沒有音軌） | 14 | 0.8／6.9 | 1056 | 435 | 1615／1418／1600 | 0.2／0.3 | 46.5／48.7 |
| headless・**假**麥克風（音軌開著） | 14 | 8.3／15.2 | 1067 | 439 | 1611／1407／1613 | 0.2／0.3 | 46.8／48.2 |
| Xvfb・真實裝置（沒有音軌） | 14＋Xvfb | 0.8／7.7 | 1075＋17 | 449 | 1614／1399／1600 | 0.6／0.8 | 46.8／47.2 |
| Xvfb・**假**麥克風（音軌開著） | 14＋Xvfb | 8.5／15.2 | 1086＋17 | 454 | 1611／1397／1597 | 0.3／0.5 | 47.2／48.2 |
| headless・**假**麥克風＋WebRTC 迴路 | 14 | 26.1／30.5 | 1091 | 458 | 1615／1402／1603 | 0.9／1.3 | 47.7／48.2 |
| Xvfb・**假**麥克風＋WebRTC 迴路 | 14＋Xvfb | 25.9／29.9 | 1110＋17 | 471 | 1609／1391／1593 | 0.4／0.6 | 48.2／48.7 |

- Xvfb 自己的 CPU 在取樣裡是 0.0 %（迴路那次最大 0.2 %），RSS 17.4 MB。
- 開著一頁閒置的 Chromium，**可用記憶體少約 195～220 MB**（1.6 GB → 1.4 GB）。收掉後回到原來的水準。
- 閒置、沒有音軌：CPU 平均不到 1 %（一顆核心的 1 %）。**假**麥克風音軌開著：約 8 %。
- WebRTC 迴路是頁面內兩個 `RTCPeerConnection` 互連（沒有 STUN／TURN、沒有信令伺服器、封包不出這台 Pi），收到的音軌接在靜音的元素上。60 多秒內送出、收到各 3537 個封包，0 遺失，編碼是 Opus 48 kHz，狀態 `connected`。這時 Chromium 用掉約 **26 % 的一顆核心**（四顆合計的 6.5 % 左右）。
- 這個迴路只是「Opus 編碼＋解碼＋回音消除等前處理在跑」的粗估，**不是通話的實際負載**：沒有真的麥克風、沒有真的播放、沒有網路、沒有 Nous 頁面本身的程式（喚醒詞的 wasm、畫面、SSE）。真的通話只會更高。
- 溫度沒有明顯變化（46～49 °C）；板子當時沒有裝進外殼。

### 3.3 途中發現的兩個問題（都已在腳本裡處理）

1. **`enumerateDevices()` 會卡住。** 不關掉 `WebRtcPipeWireCamera` 這個功能時，`navigator.mediaDevices.enumerateDevices()` 超過 10 秒不回來（探測頁的時限），headless 與 Xvfb 都一樣；Chromium 的紀錄裡有 `camera_portal.cc: Failed to access portal … org.freedesktop.portal.Desktop was not provided`——Pi 上沒有桌面，沒有 xdg-desktop-portal。加上 `--disable-features=WebRtcPipeWireCamera` 之後正常回來，頁面回報時間從 23.3 秒降到 3.6 秒。`lib.sh` 的 kiosk 旗標已經預設關掉它。**Nous 頁面會列舉音訊裝置（`voice-path.md` 事實 4），不關的話很可能卡在那裡；有沒有真的影響 Nous 頁面沒有驗證。**（這幾次試跑的結果目錄已刪，數字是當時看到的。）
2. **不能只靠 ALSA 的 `null` 裝置來靜音。** 一開始用 `--alsa-output-device=null`，`AudioContext` 的時鐘在 1 秒內前進了 547.8 秒——`null` 裝置不照真實時間消耗資料，音訊執行緒空轉，量到的 CPU 會失真。改用 `--disable-audio-output`（假輸出串流、照真實時間、不開裝置）後時鐘正常（1 秒前進 1.01 秒）。這只影響探測；真的執行不加這些旗標。

## 4. 建議用哪一種

**建議真的執行時先用 headless（`--headless=new`）**，Xvfb 當備案。`run_nous_terminal.sh` 預設就是 headless。

- 量得到的項目兩種沒有差別：`getUserMedia`（假裝置）、自動播放、`AudioContext`、WebRTC 迴路的結果相同，CPU 在誤差內。
- headless 少一個行程、PSS 少約 14～15 MB、少 Xvfb 的 17 MB，而且不需要另外 20 個套件。差距不大，但它的零件比較少。
- 改用 Xvfb 的理由只會來自還沒測的東西：Nous 頁面或雲端服務若因為 User-Agent 是 `HeadlessChrome` 而行為不同，或 headless 下真的麥克風／權限提示有問題，就換 `--display xvfb`。所以 Xvfb 先留著，等實測有結論再決定要不要移除。

## 5. 沒有驗證的事

- **真的麥克風**：XVF3800 還沒接。Chromium 看不看得到它、取樣率與聲道數、`getUserMedia` 成不成功，都不知道。
- **權限提示**：鴨子沒有螢幕，沒有人能按「允許」。沒有麥克風時在提示之前就失敗了，所以不知道 headless／Xvfb 下提示會自動拒絕、卡住還是別的。`run_nous_terminal.sh` 有 `--auto-accept-mic`（只加 `--use-fake-ui-for-media-stream`，裝置仍是真的），要明講才會加；它對真實裝置有沒有效，沒有測。
- **真的播放與聲音**：沒有任何聲音從喇叭出來。Chromium 經 ALSA 到 USB 喇叭（`~/.asoundrc`）通不通、音量、延遲、和 `duck_voice` 變聲鏈怎麼接，都沒有測。
- **連到雲端模型的 WebRTC**：只測了頁面內的迴路，沒有任何對外的連線、沒有 ICE／TURN。
- **回音消除**：假裝置回報 `echoCancellation: true` 只是設定值，效果完全沒有測。
- **和 duckd 共存**：全程 `duckd` 是 `inactive`，舵機沒有動。Chromium 通話時會不會影響步態迴圈時序（[ADR-0008](../adr/ADR-0008-single-board-pi4.md) §2.5），沒有量。
- **Nous 頁面本身**：沒有載入過。它的 CPU 與記憶體（喚醒詞 wasm、畫面、SSE）、在 headless 下能不能用、需不需要有人點一下才開始對話、輸出裝置偏好（`voice-path.md` 事實 4）在 Pi 上怎麼表現，都不知道。
- **通道**：沒有開過。Host 標頭的限制、`-R` 方向能不能用，是依交辦說明寫的，這次沒有查 AIOS 的程式，也沒有試。
- 喚醒詞、舵機噪音下的收音、長時間執行（記憶體會不會慢慢長）、開機自動啟動、斷線重連：都沒有做。
- `setup_terminal.sh --uninstall` 沒有實際跑過。

## 6. 等你：有人在場的實測步驟

這一段**會出聲、會開麥克風、會連到 Mac 上的 Nous**，要你在場、白天做。

1. **接上 XVF3800**（USB，接到 Pi 4）。
2. **確認系統看得到它**（唯讀）：

   ```bash
   ssh duck-pi4 'lsusb | grep -i 2886; arecord -l; aplay -l'
   ```

   `lsusb` 要有 VID `2886` 的裝置，`arecord -l` 要列出一張錄音卡。看不到就先停在這裡。接上之後可以先再跑一次不出聲的本機探測，看 Chromium 拿不拿得到真的麥克風（不加 `--fake-media`）：

   ```bash
   ssh duck-pi4 'bash ~/duck/terminal-spike/run_local_probe.sh --display headless'
   ```

   `get_user_media` 是 `ok`、音軌名稱是那支麥克風，才往下。如果是 `ProbeTimeout`，代表卡在權限提示，第 4 步要加 `--auto-accept-mic`。
3. **在 Mac 上開通道**（另開一個終端機視窗，開著不要關）。Nous 核心會檢查 Host 標頭，所以 **Pi 這邊的埠要和 Nous 的埠相同**（預設 8787）。兩個方向擇一：

   ```bash
   # Mac → Pi（建議：用現有的 duck-pi4 金鑰，Pi 不需要能登入 Mac）
   ssh -N -R 127.0.0.1:8787:127.0.0.1:8787 duck-pi4
   ```

   或照 AIOS 的 rpi4 套件從 Pi 連回 Mac（`ssh -L`），那需要 Pi 有能登入 Mac 的金鑰，現在沒有設。

   **通道開著的時候，Pi 上任何行程都能呼叫 Nous 的整套 HTTP API**（不只是這張頁面）。做完就按 Ctrl-C 關掉。
4. **在 Pi 上開 Nous 頁面**（再開一個視窗）：

   ```bash
   ssh -t duck-pi4 'I_AM_PRESENT_AND_OK_WITH_SOUND=yes bash ~/duck/terminal-spike/run_nous_terminal.sh'
   ```

   - 終端 ID 預設 `duck`（`DUCK_TERMINAL_ID=...` 可改；規則 `/^[a-z0-9][a-z0-9-]{0,31}$/`，不能是 `main`）；埠用 `AIOS_PORT`。
   - 沒有設 `I_AM_PRESENT_AND_OK_WITH_SOUND=yes` 會拒絕啟動；通道沒開也會拒絕並印出通道指令。
   - 第 2 步若卡在權限提示，加 `--auto-accept-mic`。
   - 想從 Mac 看頁面的狀態或代替點擊：加 `--debug-port 9333`，Mac 上 `ssh -N -L 9333:127.0.0.1:9333 duck-pi4`，再用 Chrome 開 `chrome://inspect`。這個埠能操控瀏覽器，用完就關。
   - headless 不行就加 `--display xvfb` 再試一次。
5. **量測**（第三個視窗；每一段各量一次，存成不同檔名）：

   ```bash
   ssh duck-pi4 'bash ~/duck/terminal-spike/measure.sh -i 5 -d 300' | tee ~/Downloads/duck-terminal-idle.csv
   ```

   | 段落 | 做什麼 |
   |---|---|
   | 閒置 | 頁面開著、不對話，5 分鐘 |
   | 通話 | 對鴨子說話、聽 Nous 從鴨子的喇叭回話，來回至少 10 句 |
   | 通話＋動作 | 通話的同時讓 duckd 做頭部動作（之後能走路時加上走路） |

   另外記下：`ssh duck-pi4 'vcgencmd get_throttled'`（前後各一次）、說完到聽到回話大約幾秒、有沒有聽到自己的回音或 Nous 被自己的聲音打斷。
6. **收尾**：在第 4 步的視窗按 Ctrl-C（會收掉 Chromium），再關第 3 步的通道。確認：`ssh duck-pi4 'pgrep -a chromium; ss -ltn | grep 8787'` 沒有輸出。

**怎樣算通過**（以下是建議的判斷方式，不是量出來的門檻；第一次實測後再定數字）：

| 項目 | 通過 |
|---|---|
| 頁面 | Nous 頁面在無螢幕下載入，終端 ID 是鴨子的，不需要有人碰 Pi |
| 麥克風 | 頁面拿得到 XVF3800 的音軌；Nous 聽得懂你說的話 |
| 聲音 | Nous 的回話從鴨子的喇叭出來，聽得清楚 |
| 回音 | Nous 不會被自己的聲音觸發或打斷 |
| 記憶體 | 通話中 MemAvailable 一直有餘裕，沒有用到 swap（`free -m`），沒有行程被 OOM 結束 |
| CPU | 通話中 Chromium 的 CPU 留得下 duckd 與之後感知要用的量；`duckd` 的動作沒有變卡 |
| 供電與溫度 | `vcgencmd get_throttled` 是 `0x0`；溫度在 ADR-0008 §2.5 的 80 °C 以下 |
| 步態 | 能走路之後：通話時步態迴圈時序符合 ADR-0008 §2.5 |

任一項不過，先記下實際現象與數字，再決定是調整（換 Xvfb、調旗標）還是走路線 B。結果請補進這份紀錄或另開一份。
