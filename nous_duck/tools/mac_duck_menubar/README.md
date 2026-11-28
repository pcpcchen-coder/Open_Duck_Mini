# 鴨子 Nous：Mac 選單列 App（H 線）

狀態：**第一版，已裝在使用者的 Mac、使用者親手試過（Pi 關機時）**（2026-11-28）。驗證層級：自我測試（44 項，fixture）；在這台 Mac 上建置並對執行中的 8791 讀狀態；App 自己存下的視窗畫面（設定畫面自動打開、Pi 離線頁）。**Pi 開機、鴨子連上時的樣子還沒看過**；選單列本身要使用者親手試。紀錄見 [`docs/validation/mac-duck-menubar-2026-11-28.md`](../../docs/validation/mac-duck-menubar-2026-11-28.md)。

## 為什麼有這個

鴨子沒有螢幕。鴨子用的 Nous 是 Mac 上另一個開發實例（`127.0.0.1:8791`，由 LaunchAgent `com.nousduck.nous-dev` 常駐，見 [`../mac_launch_agents.sh`](../mac_launch_agents.sh)），它的設定原本只能用瀏覽器開；鴨子自己的設定頁在 Pi 上（`http://duck-pi4.local:8081/`，[ADR-0019](../../docs/adr/ADR-0019-duck-settings-page.md)）。平常用的 `/Applications/Nous.app` 是 Electron 包的，核心跑在 App 裡面，**接不到 8791**，而且它不能動。

所以另外做一個很小的原生選單列 App（Swift／AppKit，約 230 KB），選單列上一隻鴨子：

| 選單 | 內容 |
|---|---|
| 狀態（只顯示） | Nous（8791）在不在跑、AI 引擎、ChatGPT 有沒有登入（不顯示帳號）、即時語音能不能用、鴨子有沒有連上（mock 會標出來）、SSH 通道、Pi 設定頁連不連得到。打開選單時更新，平常每 20 秒更新一次 |
| Nous 設定… | 在視窗裡開 8791 現有的設定畫面（引擎、帳號與登入、即時語音、語音秒數…）。**不重寫設定畫面**，AIOS 改了這裡就跟著變 |
| 鴨子設定… | 在視窗裡開 Pi 上現有的設定頁（喚醒詞與門檻、喇叭音量、聽聲轉頭、表情…）。直接連 Pi、不轉手，Pi 那邊的防護（只收區網、Origin／Host 檢查）照常有效。Pi 連不到時這一項是灰的；視窗開著時 Pi 斷了會顯示說明頁與「重試」 |
| 鴨子的位址… | `.local` 名稱認不得時改成 Pi 的 IP；只存在這台 Mac（`defaults read com.nousduck.menubar piHost`），不進 repo |
| 在瀏覽器打開 Nous、打開 log 資料夾 | log 在 `~/Library/Logs/nous-duck-dev/` |
| 重新啟動 Nous… | 先跳確認（會中斷鴨子的對話）；`launchctl kickstart -k gui/<uid>/com.nousduck.nous-dev`。平常用的 Nous（8787）不受影響 |

圖示：實心的鳥＝鴨子已連線（真的鴨子），空心＝沒有連線或是 mock。

## 刻意不做的事

- 不動 `/Applications/Nous.app`、8787、它的設定與登入；不讀、不寫金鑰、`.env`、`~/.config/nous-duck-dev/` 的憑證檔。
- 不啟動、停止 Pi 上的服務，不碰舵機與緊急停止（這些照 ADR-0019 §2.6 留在本機指令與舵機控制台）。
- 網頁要開的外部連結（ChatGPT 登入頁、用量頁等）一律交給系統瀏覽器，帳密由你自己輸入。
- 兩個視窗都**不給麥克風與鏡頭**：這是設定用的視窗，要對話請用鴨子或瀏覽器。
- 關掉視窗就把頁面卸掉（8791 的頁面有事件串流，不讓它在背景一直開著）。

## 安裝與移除

需要 Xcode 或 Command Line Tools（`swiftc`），macOS 13 以上。

```bash
bash nous_duck/tools/mac_duck_menubar/install.sh
```

做的事：跑自我測試 → 建置 → 裝到 `~/Applications/Nous Duck.app`（顯示名稱「鴨子 Nous」）→ 寫 `~/Library/LaunchAgents/com.nousduck.menubar.plist`（登入 Mac 時打開；從選單結束後不會自己重開）→ 現在打開一次。不需要管理員權限，不改系統設定。

第一次打開「鴨子設定…」時，macOS 可能會問「允許尋找區域網路上的裝置」，要按允許（之後可在 系統設定 → 隱私權與安全性 → 區域網路 改）。

```bash
bash nous_duck/tools/mac_duck_menubar/install.sh --status
```

```bash
bash nous_duck/tools/mac_duck_menubar/install.sh --uninstall
```

移除只刪 App 與 `com.nousduck.menubar`；8791 的兩個 LaunchAgent、`~/.config/nous-duck-dev`、Nous.app 都不會被碰到。App 自己的偏好與網頁資料（`defaults delete com.nousduck.menubar`、`~/Library/WebKit/com.nousduck.menubar`）留著，腳本會印出怎麼一起清掉。

## 開發

| 檔案 | 內容 |
|---|---|
| `Sources/Status.swift` | 把 `/api/settings`、`/api/integrations/status`、`launchctl print`、`tunnel.log`、Pi 的 `/healthz` 變成選單上的一行字（純函式） |
| `Sources/main.swift` | 選單列、網頁視窗、外部連結交給系統瀏覽器、離線頁、重新啟動確認 |
| `Tests/main.swift` | `Status.swift` 的自我測試（手寫 fixture，帳號是假的 `fixture@example.invalid`） |
| `Info.plist` | `LSUIElement`（不在 Dock）、ATS 只開區網（`NSAllowsLocalNetworking`）、區網權限說明 |
| `build.sh` | 建置（ad-hoc 簽章）；`--test` 只跑自我測試 |
| `install.sh` | 安裝、`--status`、`--uninstall` |

```bash
bash nous_duck/tools/mac_duck_menubar/build.sh --test
```

```bash
bash nous_duck/tools/mac_duck_menubar/build.sh && "nous_duck/tools/mac_duck_menubar/build/Nous Duck.app/Contents/MacOS/NousDuck" --status
```

驗證用的參數：`--status`（只印狀態就結束）、`--open nous|duck`（啟動時開那個視窗）、`--snapshot <檔名.png>`（頁面載完後把視窗內容存成 PNG 就結束；不需要螢幕權限）。

### 和 AIOS 頁面的接點（會壞的地方）

8791 的瀏覽器版頁面沒有網址可以直接開設定畫面，所以 App 在頁面載完後按頁面上既有的「設定」按鈕（`id="conversation-settings"`，AIOS main `607db1d`），直到看到設定畫面（`.surface-header .eyebrow` 是「設定」或「Settings」），最多 8 秒。AIOS 改了這兩個地方時，視窗標題會寫「沒有自動打開設定：在頁面上打字「設定」再按 Enter」，不會假裝打開了。
