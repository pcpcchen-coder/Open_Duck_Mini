# 鴨子 Nous 選單列 App（Mac）— 2026-11-28

- 分支：`claude/duck-h-mac-menubar`（從 `v2` 開出），H 線
- 模組：[`tools/mac_duck_menubar/`](../../tools/mac_duck_menubar/README.md)
- 環境：使用者的 Mac（Apple Silicon，macOS 27.2.1，Xcode 的 Swift 6.4.2，用 `-swift-version 5` 編譯）；8791 的 Nous 由 LaunchAgent 跑 AIOS main `607db1d`；**Pi 關機**（通道 log 是「Could not resolve hostname duck-pi4.local」）
- 驗證層級：**自我測試（fixture）＋本機建置＋對執行中的 8791 讀狀態＋App 自己存下的視窗畫面**。選單列本身沒有截圖（見 §4）；Pi 開機、鴨子連上的情況沒有看過。

## 1. 原本的 Nous 在 Mac 上的設定介面（唯讀查的）

- `/Applications/Nous.app`：Electron（`com.pcpcchen.nous`，0.1.0），原始碼在 AIOS 的 `prototype/ambient-shell/desktop/`。核心（`server.mjs`）在 App 的主程序裡用 `startNous()` 啟動，預設 8787、被占用就換埠；設定以選單列為主（`settings-menu.mjs`，資料來自核心的 `GET /api/settings`），視窗裡只剩「帳號與登入」。
- 結論：核心和 App 綁在一起，沒有「連到外部核心」的設定，所以**不能拿它來管 8791**；改它又違反「不動 Nous.app」。另外做一個只當入口的小 App。

## 2. 8791 已經有的東西

- 瀏覽器版頁面（`http://localhost:8791/`）有完整的設定畫面；正常頁面上沒有設定按鈕，要打字「設定」或按對話面板裡的設定鈕（`id="conversation-settings"`）。
- `GET /api/settings`：`provider`、`providers[]`、`chatgpt.signed_in`、`realtime.available`／`billing_line`／`active`…（**也含帳號 email**，App 不顯示它）。
- `GET /api/integrations/status`：`services[]` 裡 `service: "duck"` 的 `health`（`available`／`unknown`／`unavailable`）、`reason`、`mock`。
- Pi 的設定頁只收區網來源、檢查 `Origin` 與 `Host`（`*.local`、IP 都可），所以 Mac 上的 WebView 直接開就能用，**Pi 不用改**。`GET /healthz` 回 `ok`。

## 3. 測試與結果

### 3.1 自我測試

```bash
bash nous_duck/tools/mac_duck_menubar/build.sh --test
```

結果：`全部通過：44 項`。內容：`launchctl print` 解析（running＋pid、載入沒跑、沒載入、深層 `state` 不算）；Nous／引擎／ChatGPT／即時語音／鴨子／通道／Pi 各行的判斷；**不顯示帳號 email**；鴨子 `mock: true` 要標出來而且不算綠燈；ssh 在跑但鴨子沒連上不說「連著」；`tunnel.log` 的 `\r\n` 結尾；Pi 位址只收主機名稱或 IP；離線頁的跳脫與 CSP。fixture 是手寫的（形狀照 AIOS `607db1d`），不是實際資料。

開發中抓到並修掉的：ssh 的錯誤訊息是 `\r\n` 結尾，Swift 把 `\r\n` 當成一個字元，`split("\n")` 切不開，選單會印出整段 log（加了測試）。

### 3.2 對執行中的 8791 讀狀態

```bash
bash nous_duck/tools/mac_duck_menubar/build.sh && "nous_duck/tools/mac_duck_menubar/build/Nous Duck.app/Contents/MacOS/NousDuck" --status
```

輸出（2026-11-28，Pi 關機）：

```
● Nous（8791）在跑　— LaunchAgent com.nousduck.nous-dev，pid 56695
● AI 引擎：ChatGPT
● ChatGPT：已登入
● 即時語音：可用　— ChatGPT 方案（Codex 額度）· gpt-live-1-codex
○ 鴨子：沒有連線　— 連線斷了（Pi 關機、通道斷了，或 duckd 沒在跑）
○ 通道（SSH 到鴨子）：沒連上，會自動重試　— ssh: Could not resolve hostname duck-pi4.local: nodename nor servname provided, or not known
○ 鴨子設定頁：連不到（duck-pi4.local）　— Pi 可能關機或不在同一個 Wi-Fi
```

和 `launchctl print`、`curl /api/settings`、`curl /api/integrations/status`、`tunnel.log` 對過，一致。App 大小 228 KB，ad-hoc 簽章（`Identifier=com.nousduck.menubar`）。

### 3.3 視窗畫面（App 自己存的 PNG）

```bash
"…/NousDuck" --open nous --snapshot nous.png
```

```bash
"…/NousDuck" --open duck --snapshot duck-offline.png
```

- **Nous 設定**：第一版在頁面載完時按一次設定鈕，結果**沒有打開**（頁面還沒向核心拿到設定）。改成每 0.4 秒按一次直到看到設定畫面（最多 8 秒）後，畫面是「設定／AI 引擎」，列出 Claude（不可用）、ChatGPT（使用中）、模擬。截圖裡有帳號 email，所以**沒有放進 repo**。
- **Pi 離線**：視窗顯示「連不到鴨子的設定頁」、位址、`The request timed out.`、常見原因四條與「重試」；標題列副標「連不到」。

## 4. 沒有驗證的

- **選單列本身**（圖示、選單排版、macOS 14.4 以上的灰色說明）：這個 Mac 的螢幕操作工具找不到沒安裝的 App，沒辦法截選單列；安裝後由使用者親手看。
- **Pi 開機時**：「鴨子設定…」實際打開 Pi 的頁面、在裡面存設定、區網權限的系統提示、鴨子連上時圖示變實心。要等 Pi 開機。
- **登入的彈出視窗**：Nous 的 ChatGPT 方案登入是先開空白視窗再換網址；App 用一個看不見的 WebView 接住後交給系統瀏覽器。這條路沒有實際按過（按了會開始真的登入流程）。
- **「重新啟動 Nous…」**：沒有按（會中斷 8791）；`launchctl kickstart -k` 的用法和 `mac_launch_agents.sh` 的 label 對過。
- **安裝腳本**：寫完時還沒在這台 Mac 執行（要使用者同意）。安裝後補在 §5。
- 只在 Apple Silicon、macOS 27.2.1 上建置過。

## 5. 安裝與使用者親手試

（待補：使用者同意後執行 `install.sh`，以及使用者試用的結果。）
