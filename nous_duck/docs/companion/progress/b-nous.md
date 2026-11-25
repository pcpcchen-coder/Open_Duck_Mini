# B 線進度：Nous 端（`nous_adapter/`）

分支：`claude/duck-b-nous-a19b67`（從 `claude/duck-companion-overnight` 的 `3b2b0f6` 開出；只有本機 commit，沒有 push、沒有 PR、沒有合併別的分支）。最後更新：2026-11-25 23:10。

一句話：**Nous 端的程式都寫好了，測試 137 項全過，和 A 線的 duckd（mock 身體）端到端講得通；還沒搬進 AIOS，也還沒對真的鴨子下過指令。**

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
