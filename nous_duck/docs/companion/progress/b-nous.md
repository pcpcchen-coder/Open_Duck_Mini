# B 線進度：Nous 端（`nous_adapter/`）

分支：`claude/duck-b-nous-a19b67`，PR 的 base 是 `claude/duck-companion-overnight`。最後更新：2026-11-26。

一句話：**Nous 這一端的程式（本 repo 與 AIOS 分支）都寫好了、fixture 測試全過，和 duckd 的模擬身體端到端講得通；還沒有人用真實語音試過，也還沒有對真的鴨子下過指令。**

## 2026-11-26：桌上互動（T2、T3、T6）

| Step | 內容 | 狀態 | 驗證層級 |
|---|---|---|---|
| T2 | 語音命令轉頭：說話 → Nous → `app.duck.look`／`gesture` → 鴨子 | **程式完成，等你試**。AIOS 分支 `claude/duck-link`（[pcpcchen-coder/AIOS#156](https://github.com/pcpcchen-coder/AIOS/pull/156)，旗標 `NOUS_DUCK` 預設關閉，沒有合併）：`/duck-link` 端點（D1）＋ `duck` adapter（D2，先開 `status`、`stop`、`look`、`gesture`、`express`、`track`） | AIOS 的 fixture 測試（122 項，假鴨子）；AIOS 的 hub＋Dispatcher 對 duckd **模擬身體**的本機檢查（兩端都在 Mac）。**沒有真實語音、沒有實機** |
| T3 | 語音互動時的動作：真實語音事件 → `presence` | **程式完成（粗略版），等你試**。同一個 PR 的 D4a：核心的工作階段事件（開始、連上、委派、結束）→ `wake`／`thinking`／`listening`／`working`／`error`／`idle`。**沒有 `speaking`**（核心不知道模型正在說話；要頁面回報 phase，是下一批 D4b） | 同上（fixture＋假時鐘；對 duckd 模擬身體送過 presence 並回讀） |
| T6 | 鴨子自己的喇叭與麥克風進行對話（路線 A：Pi 上無螢幕跑 Nous 頁面） | **準備完成；真正連 Nous、出聲的那一步等你**（也等麥克風接上） | 見[終端 spike 紀錄](../../validation/duck-terminal-spike-2026-11-26.md)：實機（Pi 4），不連 Nous、不出聲、沒有麥克風 |
| 過渡示範 | `duckctl say-command "往左看"`：文字 → 工具 → 鴨子 | 完成。**開發用的固定關鍵字規則，不是 Nous、不是語音辨識、不是語言模型**；不開麥克風 | 單元／整合測試；對 duckd 模擬身體手動執行 |
| 對真的鴨子跑 `look`、`gesture`、`presence` | — | **沒有做**：A 線的實機頭部（T1）還沒好（Pi 上的 duckd 沒有啟動，舵機控制台占著匯流排）。B 線沒有碰 Pi 上的 duckd 與匯流排 | — |

### 你要親手做的事

1. **看 AIOS 的 PR**：[pcpcchen-coder/AIOS#156](https://github.com/pcpcchen-coder/AIOS/pull/156)。要特別看的五點寫在 PR 說明（新依賴 `ajv`、第一個入站 WebSocket、`realtime-routes.ts` 的改動、模型工具基準檔、presence 沒有 `speaking`）。
2. **用語音試（T2、T3）**，不影響正在跑的 Nous：照 AIOS 分支 `docs/validation/duck-link-2026-11-26.md` §5 另起一個開發實例（`PORT=8790`、新的 `NOUS_CONFIG_DIR`、`NOUS_DUCK=on`、`NOUS_AIL=on`、`NOUS_AIL_SERVICES=duck`；登入或 API key 你自己設定）。checkout 已經在 `~/AIOS-duck-link`（分支 `claude/duck-link`，`npm ci` 做過了，**沒有 `.env`**）。那些步驟會連雲端模型、會出聲，沒有人執行過。
   - 還沒有真的鴨子時，可以先對 duckd 的模擬身體：`cd nous_duck/robot/duckd && python -m duckd --body mock --engage --allow-unverified-gestures --url ws://127.0.0.1:8790/duck-link`（不用通道，都在 Mac）。
   - A 線的實機頭部好了之後，通道的埠要和開發實例一致：`ssh -N -R 127.0.0.1:8790:127.0.0.1:8790 duck-pi4`，Pi 上的 duckd 連 `ws://127.0.0.1:8790/duck-link`。
3. **不經 Nous 先確認「命令 → 頭」**（今天就能做，不用雲端）：`nous_adapter/README.md` 的「親手試」，把 `mock-duck` 換成 duckd；然後 `bin/duckctl say-command "往左看"`、`"點頭"`、`"回正"`。
4. **T6 的實機步驟**（接上 XVF3800、在場、會出聲）：照終端 spike 紀錄最後的「等你」步驟。

### 要你決定的事（我用了保守的預設）

| 事項 | 我用的預設 |
|---|---|
| AIOS 要不要為 schema 驗證加 `ajv` | 加了（鎖 8.20.0），在 PR 說明標出來 |
| 第一階段給模型哪些工具 | 照整合線轉達的決定：`status`、`stop`、`look`、`gesture`、`express`、`track` |
| 沒啟用的 11 個工具要不要列在 Nous 的指令表 | 不列（`hidden`），免得看起來現在能用 |
| `app.duck.resume` 給不給模型 | 不給 |
| 鴨子連 Nous 的通道方向 | 文件兩種都寫；示範用 Mac → Pi（`ssh -R`） |
| `look` 的方向 | 照 duckd 的註解：`head_yaw` 正＝往左、`head_pitch` 正＝抬頭。**還沒在實機確認**；如果相反，`say-command` 的左右或上下會反，模型也可能轉錯邊（工具說明寫的是這個方向） |
| 動作清單 | duckd 預設不列出還沒實機驗證的動作（`nod` 等），要加 `--allow-unverified-gestures`；不加的話 Nous 說「鴨子點點頭」會得到「清單裡沒有這個名稱」 |

### 這一批改了什麼（本 repo）

- `nous_adapter/`：hub 多了 `attach(server)`（AIOS 核心的接法）；`DUCK_STAGE1_TOOLS`；`sendDuckPresence()`；AIOS 契約的宣告拆成和 AIOS 模組一對一的三個檔；`duckctl say-command`。測試 144 項通過（`validator` 33、`hub` 24、`duck-adapter` 51、`terminal` 18、`cli` 18）。
- `nous_adapter/docs/`：整合計畫加 §0（實際做法、和計畫的差異、契約比對）；語音路徑依修訂後的 ADR-0003／0005／0010 更新（麥克風是標準版 XVF3800 裝在頭上、喚醒詞預設「Hey 鴨子」）。
- `robot/deploy/pi4/setup_terminal.sh`、`robot/deploy/pi4/terminal/`：T6 的安裝、探測與量測腳本（新檔）。
- 本 repo 的 ADR 編號變動（記憶 ADR-0011、低電量回家 ADR-0012、動作庫 ADR-0015）：B 線的文件沒有引用到這幾號，不用改。

以下是 2026-11-25 夜間（B1～B6）的紀錄，數字是當時的。

## 各 Step

| Step | 內容 | 狀態 | 驗證層級 |
|---|---|---|---|
| B1 | AIOS 唯讀調查與整合計畫 | 完成 | 文件（唯讀查閱 AIOS commit `c853078`，沒有執行 AIOS） |
| B2 | duck-link hub 與 SSH 通道腳本 | 完成 | 整合測試（mock 鴨子）；端到端對 duckd mock；**通道實測**（Mac ↔ Pi 的網路，對面是探測程式，不碰硬體） |
| B3 | DuckAdapter（17 個 `app.duck.*`）與 TypeScript mock 鴨子 | 完成 | 整合測試（mock 鴨子）；端到端對 duckd mock |
| B4 | DuckTerminal：事件入口、`presence` 來源 | 完成（AIOS 的真實事件還接不到；附開發用手動來源） | 單元測試（假時鐘）＋整合測試（mock 鴨子） |
| B5 | 開發 CLI `duckctl` | 完成 | 整合測試＋手動執行（對 mock） |
| B6 | 語音路徑設計 | 完成（設計文件；沒有實作、沒有試聽） | 文件 |
| 端到端（全 mock） | 本 repo 的 hub＋adapter 對 A 線 duckd（`b1f21ce`，mock 身體） | 完成 | 端到端，兩端都在 Mac，身體是 mock |
| 端到端（實機頭部） | 對 Pi 上真的 duckd 下 `look` | **沒有做**：A 線還沒部署 duckd 到 Pi。步驟已寫好，留給整合線 | — |

沒有任何一項是在真的鴨子身上驗證的。

## 交付的東西

| 路徑 | 內容 |
|---|---|
| [`nous_adapter/README.md`](../../../nous_adapter/README.md)（＋`.en.md`） | 現況、怎麼親手試、怎麼對真的鴨子、工具清單 |
| [`nous_adapter/docs/aios-integration-plan.md`](../../../nous_adapter/docs/aios-integration-plan.md)（＋`.en.md`） | B1：搬進 AIOS 要改哪些檔與函式、`/duck-link` 放哪、`presence` 的真實事件來源、7 個 AIOS 批次與風險 |
| [`nous_adapter/docs/voice-path.md`](../../../nous_adapter/docs/voice-path.md)（＋`.en.md`） | B6：現在與麥克風到貨後的對話路徑 |
| `nous_adapter/hub/`、`adapters/`、`terminal/`、`cli/`、`mock/`、`shared/`、`scripts/`、`tests/` | B2～B5 的程式與測試 |
| [`protocol/proposals/b-nous-readback-and-semantics.md`](../../../protocol/proposals/b-nous-readback-and-semantics.md)（＋`.en.md`） | 協定提案（沒有改 schema）：缺少的回讀欄位與 9 個語意歧義 |
| [`docs/validation/nous-adapter-2026-11-25.md`](../../validation/nous-adapter-2026-11-25.md) | 驗證紀錄與數字 |

沒有改任何共用檔（`nous_duck/README*.md`、`docs/roadmap.md`、`docs/architecture.md`、ADR 索引、驗證索引、`docs/companion/README.md`、`steps.md`、`protocol/schemas/**`、`.github/**`、`CLAUDE.md`、`robot/README.md`）。沒有用到 ADR-0015。

## 怎麼執行

```bash
cd nous_duck/nous_adapter
npm ci
npm run typecheck
npm test                      # 137 項通過，約 4 秒
```

親手試（不需要鴨子，三個終端機分頁）：

```bash
bin/duckctl hub               # 分頁 1
bin/duckctl mock-duck         # 分頁 2：模擬的鴨子
bin/duckctl status            # 分頁 3
bin/duckctl look --yaw 10 --deg
bin/duckctl gesture nod
bin/duckctl presence speaking --level 0.4
bin/duckctl help
```

完整說明在 [`nous_adapter/README.md`](../../../nous_adapter/README.md#親手試不需要鴨子)。

## 測試結果與數字

| 項目 | 數字 |
|---|---|
| vitest | 5 檔 137 項全過：`validator` 33、`hub` 23、`duck-adapter` 50、`terminal` 18、`cli` 13 |
| 型別檢查 | `tsc --noEmit` 無錯誤（TypeScript 7.0.2，設定比照 AIOS） |
| 協定測試（整合線的） | 32 項通過（重跑確認） |
| 端到端對 duckd mock（`b1f21ce`） | 雙向 0 則不合 schema 的訊息；18 個工具呼叫：10 個 `confirmed`、8 個 `refused`（都是預期的：能力 `unsupported` 或名稱不在清單）；8 個 `presence` 都 `confirmed` |
| `status` 結果大小（對 duckd） | 1 098 bytes（AIOS 上限 4 096；第一版 2 750，已修） |
| 通道（Mac → Pi，`ssh -R`） | 心跳往返 n=25：最小 3 ms、中位數 7 ms、最大 343 ms；Pi 收到心跳的間隔 32 秒內最大 755 ms（租約是 1 500 ms）。樣本少，只代表那半分鐘 |

細節見[驗證紀錄](../../validation/nous-adapter-2026-11-25.md)。

## 設計上自己做的判斷

| 判斷 | 理由 |
|---|---|
| `presence` 不是模型工具 | 要由語音工作階段的真實事件驅動；給模型等於讓它演 |
| `track` 是模型工具 | 使用者會說「看著我」；Nous 只是開關，跟隨在鴨子本機算 |
| `sound`、`resume` 不是模型工具 | 提示音是終端的回饋；解除暫停比較像有人在場才做的事（`duckctl resume` 可以下） |
| 鴨子回報 `unsupported` 的能力，工具不送出、直接回 `refused` | 如實回報，不送一定會被拒的指令。`stop`、`status`、`cancel_mission`、`mission_status`、`wait_here` 不受這個檢查，一律送 |
| 鴨子拒絕 → `refused`；AIOS 的原因代碼用 `unavailable`／`invalid_arguments`／`timeout`，鴨子的原因放 `data.duck_reason` | AIOS 的 `ToolResult.reason` 是固定清單，沒有改它 |
| `antennas` 最多 `unconfirmed` | v0 的 state 沒有天線位置可以回讀 |
| `look` 的 `confirmed` 分兩種：到位（`reached: true`）或已開始轉（`false`） | state 只有實際角度、沒有目標 |
| `duckctl` 與 hub 之間用 UNIX socket，不用 TCP | 8791 會經通道轉給 Pi；控制通道不該讓 Pi 上的程式連得到 |
| hub 拒絕帶 `Origin` 的連線 | 不擋的話，任何開著的網頁都能連本機的 WebSocket 冒充鴨子 |
| 驗證器用 Ajv 8.20.0 | draft 2020-12；和 Python 端 jsonschema 對同一組範例的判定一致 |

## 沒做的

- 搬進 AIOS（唯讀，只有計畫）。
- 對真的鴨子的任何指令。
- `app.duck.announce`（要不要做取決於語音路徑）、`app.duck.privacy_tighten`（等隱私設定 schema）。
- 把 hub 做成常駐服務（launchd／autossh）——會改系統設定，留給你決定。
- 鴨子事件進 Nous 之後「說出來」或「接續對話」——AIOS 沒有入口，可行性也沒有查證。

## 需要你處理

| 事項 | 說明 | 我用的預設 |
|---|---|---|
| 要不要開 AIOS 的批次，以及順序 | 整合計畫 §8 建議：D1（`/duck-link`）→ D2（註冊 adapter）→ D4a（粗略的 `presence`）。這三個做完、加上 A 線的頭部，就能用語音叫鴨子轉頭點頭 | 沒有動 AIOS |
| 第一階段給模型哪些工具 | 17 個全開會讓工具表變長；建議先開有硬體的 `status`、`stop`、`look`、`gesture` | 程式裡 17 個都是 `enabled: true`，搬進 AIOS 時再決定 |
| `app.duck.resume` 要不要給模型 | 給了，Nous 就能自己解除暫停讓鴨子開始走 | 不給（只有 `duckctl resume`） |
| SSH 通道方向 | 現在 Mac → Pi（`ssh -R`，不必開 Mac 的遠端登入）；AIOS 的 rpi4 終端是 Pi → Mac（`-L`，要開遠端登入） | Mac → Pi，手動啟動，不常駐 |
| AIOS 要不要為 schema 驗證加 `ajv` 依賴 | AIOS 整合層目前刻意不加依賴；替代方案是建置時產生純程式碼的驗證器（未驗證） | 本 repo 用 Ajv |
| 要不要先接一支 USB 麥克風做「鴨子當終端」的 spike | 語音路徑文件 §2.3：這是不用等麥克風陣列、也不用改 AIOS 的最短「鴨子說話」路徑，但要有人在場、會出聲 | 沒有做 |
| 協定提案要不要收 | `protocol/proposals/b-nous-readback-and-semantics.md` 的 9 項 | 沒有改 schema，程式都有繞過的作法 |
| 端到端（實機頭部） | 等 A 線把 duckd 部署到 Pi；步驟在 `nous_adapter/README.md` 的「對真的鴨子」 | 沒有啟動 Pi 上的任何東西 |

## 給整合線

- `steps.md` 的 B1～B6 可以標「完成」，驗證層級照上表；I1（全 mock 端到端）已經由 B 線跑過一次（對 `b1f21ce`），整合線合併後可以用 `npx tsx scripts/e2e-duckd.ts` 重跑。
- 兩條線的 mock 行為有三處不同（`mission_status` 沒有任務時、`wait_here`、`gesture_done` 的 `reason`），都在協定提案裡，Nous 端已經兩種都能處理。
- `nous_adapter/.npmrc` 設了 `legacy-peer-deps=true`（npm 10.9 解析 vitest 5 的 peer 依賴會當掉）；CI 若要跑這裡的測試，用 `npm ci` 即可。
- B 線在 Pi 上做的事只有：開過一次 `ssh -R` 通道（已關）、用 `python3 -` 從標準輸入跑過兩次探測程式（沒有在 Pi 上留下檔案）、執行唯讀的 `ss -ltn` 與 `uptime`。
