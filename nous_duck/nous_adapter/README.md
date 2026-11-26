> [繁體中文](README.md) | [English](README.en.md)

# ④ Nous adapter（nous_adapter）

狀態（2026-11-26）：**程式完成，驗證到「單元／整合測試」與「對 duckd 的模擬身體端到端」。D1、D2、D4a 已經搬進 AIOS 的分支 `claude/duck-link` 並開了 PR（旗標預設關閉、還沒合併）；還沒有用真實語音試過，也還沒有對真的鴨子下過指令。**

這個目錄放**之後要搬回 AIOS** 的程式：讓 Nous 透過 duck-link 使用鴨子。現在它可以獨立執行（不需要 AIOS），用來開發與親手測試。

| 元件 | 做什麼 | 狀態 | 驗證層級 |
|---|---|---|---|
| duck-link hub（[`hub/`](hub/duck-link-hub.ts)） | Mac 本機 `127.0.0.1:8791/duck-link` 的 WebSocket server；`hello`、每 500 ms 心跳與往返時間、指令與 `ack` 配對、最新 `state`、轉發 `event`；雙向訊息用 duck-link v0 schema 驗證 | 完成 | 整合測試（mock 鴨子）；對 duckd mock 端到端；通道實測（Mac ↔ Pi，不碰硬體） |
| DuckAdapter（[`adapters/`](adapters/duck.ts)） | AIOS `IntegrationAdapter`，`service = "duck"`，17 個 `app.duck.*` 工具 | 完成 | 整合測試（mock 鴨子）；對 duckd mock 端到端 |
| DuckTerminal（[`terminal/`](terminal/duck-terminal.ts)） | 鴨子事件的入口；`presence` 的來源介面與節流 | 完成（AIOS 的真實事件還沒接，只有開發用手動來源） | 單元／整合測試（mock 鴨子） |
| `duckctl`（[`cli/`](cli/duckctl.ts)） | 不經過 AIOS，從終端機下 `app.duck.*` | 完成 | 整合測試；手動試過（對 mock） |
| mock 鴨子（[`mock/`](mock/mock-duck.ts)） | **模擬**的鴨子，只給測試與試用；`hello` 與 `state` 帶 `mock: true` | 完成 | — |
| 開發用文字命令（[`cli/text-command.ts`](cli/text-command.ts)） | `duckctl say-command "往左看"`：固定關鍵字規則把一句文字對應到一個工具。**不是 Nous、不是語音辨識、不是語言模型** | 完成 | 單元／整合測試（mock 鴨子） |
| 搬進 AIOS | `/duck-link` 端點（D1）、註冊 adapter（D2，第一階段 6 個工具）、工作階段事件 → `presence`（D4a） | **已在 AIOS 分支 `claude/duck-link` 實作、PR 待審**（使用者 2026-11-26 同意；見 [`docs/aios-integration-plan.md` §0](docs/aios-integration-plan.md#0-2026-11-26-更新d1d2d4a-已在-aios-分支實作)） | AIOS 的 fixture 測試 122 項＋對 duckd 模擬身體的本機檢查；沒有實機、沒有真實語音 |

沒有做的事、不能宣稱的事：

- **還不能宣稱「用語音叫得動鴨子」。** AIOS 那一端的程式在分支上、旗標預設關閉、還沒合併；沒有人用真實的即時語音試過。要試的步驟在 AIOS 分支的 `docs/validation/duck-link-2026-11-26.md` §5（另起開發實例，不影響正在跑的 Nous），由使用者自己啟動。
- **沒有對真的鴨子下過指令。** 所有工具結果都來自 mock（這裡的 TypeScript mock，或 A 線 duckd 的 mock 身體）。實機步驟寫在下面的「對真的鴨子」。
- `presence` 目前只有**開發用手動來源**（`duckctl presence`），不是 Nous 語音工作階段的事件。
- 語音不在這裡：使用者 2026-11-26 決定走路線 2（鴨子的 Pi 上跑 Chromium 開 Nous 頁面，鴨子本機的喚醒詞「Hello 鴨子」「Hey 鴨子」叫頁面開始對話）。設計與還沒解決的事見 [`docs/voice-path.md` §8](docs/voice-path.md#8-2026-11-26-的決定路線-2)；Nous 端的改動在 AIOS（[pcpcchen-coder/AIOS#158](https://github.com/pcpcchen-coder/AIOS/pull/158)，未合併）。**還沒有人用真的麥克風與喇叭跑過。** 另一條原生音訊通道（`/duck-voice`）是實驗，沒有併進 `v2`，留在分支 `claude/duck-b-voice-channel`。

## 親手試（不需要鴨子）

需要 Node.js 22.12 以上。

```bash
cd nous_duck/nous_adapter
npm ci
```

開三個終端機分頁：

```bash
# 分頁 1：hub（只聽本機 127.0.0.1:8791，等鴨子連進來）
bin/duckctl hub
```

```bash
# 分頁 2：模擬的鴨子（沒有真的鴨子時用；所有輸出都會標示「模擬」）
bin/duckctl mock-duck
```

```bash
# 分頁 3：下指令
bin/duckctl link                      # 連線、往返時間、對面是不是模擬
bin/duckctl status                    # 模式、頭部角度、能力清單
bin/duckctl look --yaw 0.2            # 頭轉到 0.2 rad（正＝往左）
bin/duckctl look --yaw 10 --deg       # 用「度」
bin/duckctl gesture nod               # 點頭
bin/duckctl express happy             # 眼睛表情
bin/duckctl presence speaking --level 0.4   # 手動送互動狀態（開發用，不是 Nous 的事件）
bin/duckctl go_to brother_room        # 任務：confirmed 只代表「已出發」
bin/duckctl say-command "往左看"      # 開發用：文字 → 工具（固定規則，不是 Nous；認不得就不送）
bin/duckctl events --follow           # 看鴨子回報的事件
bin/duckctl help                      # 完整用法
```

每個指令印出 `ToolResult`（和 Nous 之後拿到的一樣）與回讀的 state：

```text
app.duck.look {"head_yaw":-0.9} → confirmed ✔
  （模擬）頭已經轉到位。（數值超出鴨子的限制，已由鴨子夾限，實際值見 applied）
  ⚠ 對面是模擬的鴨子（mock），不是實機。
  結果：{"applied":{"head_yaw":-0.5,"duration_s":0.5},"clamped":true,"rtt_ms":0,"reached":true,"connected":true}
  回讀的狀態：{"mode":"standing", …,"head":{"head_yaw":-0.5, …}, …}
```

結果怎麼讀：

| 狀態 | 意思 |
|---|---|
| `confirmed` | 鴨子接受了，而且之後讀回的 state（或事件）符合。動作與任務類只代表「**已接受並開始**」，不是做完、走到或找到 |
| `unconfirmed` | 鴨子接受了，但沒有讀到符合的 state（或協定沒有可回讀的欄位，例如天線） |
| `unknown` | 已送出，鴨子沒有回覆或連線中斷。**不能當成沒有執行**，要去看一下鴨子 |
| `refused` | 沒有執行：鴨子拒絕（`data.duck_reason` 是鴨子的原因代碼），或參數不對，或鴨子自己回報沒有這項能力（`unsupported`） |
| `failed` | 沒有送出（例如鴨子沒有連線） |

`duckctl` 的結束代碼：0＝`confirmed`；2＝`unconfirmed`／`unknown`；1＝`refused`／`failed`；3＝連不到 hub。

## 對真的鴨子（留給整合線或使用者執行）

前提：鴨子端的 `duckd`（[`../robot/duckd/`](../robot/README.md)，A 線）已經部署到 Pi 並且可以啟動。**B 線沒有啟動 Pi 上的 duckd，也沒有對實機下過任何指令。**

```bash
cd nous_duck/nous_adapter
scripts/duck-link-dev.sh hub-start        # Mac：hub 在背景執行
scripts/duck-link-dev.sh tunnel-start     # Mac → Pi 的 SSH 通道（預設主機 duck-pi4）
scripts/duck-link-dev.sh status           # 鴨子連上後會顯示「已連線」
```

通道是 `ssh -N -R 127.0.0.1:8791:127.0.0.1:8791 duck-pi4`：由 Mac 發起，Pi 的 `127.0.0.1:8791` 接到 Mac 的 `127.0.0.1:8791`；兩邊都只綁 loopback。腳本不改任何系統設定、不裝常駐服務；Mac 重開機後要重新執行。

鴨子端啟動 duckd（指令以 A 線的文件為準）之後：

```bash
bin/duckctl link          # 確認對面「不是」模擬，並看往返時間
bin/duckctl status        # 看 capabilities：head 是 available 還是 degraded；其他應該是 unsupported
bin/duckctl look --yaw 5 --deg --time 1.5    # 小角度、慢慢轉；看真的頭有沒有動、回讀角度對不對
bin/duckctl look --yaw 0 --time 1.5          # 回正
bin/duckctl stop
```

注意事項：

- 先看 `duckctl link` 顯示的 `duck` 那一行：有「⚠ 模擬」就是還連到 mock。
- 夜間規則（[總體設計 §5](../docs/companion/README.md#5-安全與夜間規則)）：無人看顧時只做頭部小幅慢速動作，不走路、不出聲。`walk` 在鴨子回報 `walk: unsupported` 時不會送出。
- 只想確認通道、不想啟動 duckd：`ssh duck-pi4 python3 - < scripts/tunnel-probe.py`（不碰硬體的探測程式，會以「不是鴨子」的身分回應幾秒心跳）。
- 結束：`scripts/duck-link-dev.sh tunnel-stop`、`scripts/duck-link-dev.sh hub-stop`。

## 測試

```bash
cd nous_duck/nous_adapter
npm ci
npm run typecheck
npm test
```

2026-11-26 的結果：145 項通過（`validator` 33、`hub` 25、`duck-adapter` 51、`terminal` 18、`cli` 18），約 4 秒。測試只連本機的臨時埠，不碰 8791，也不連執行中的 Nous。測試工具與 AIOS 相同：vitest 5.0.3、tsx 4.23.15、TypeScript 7.0.2。

對 A 線 duckd（mock 身體）的端到端檢查：

```bash
# 分頁 1（在 A 線的 robot/duckd 目錄）：python -m duckd --body mock --engage --url ws://127.0.0.1:18792/duck-link
# 分頁 2：
npx tsx scripts/e2e-duckd.ts --port 18792
```

紀錄與數字見 [`../docs/validation/nous-adapter-2026-11-25.md`](../docs/validation/nous-adapter-2026-11-25.md)。

## 工具清單

每個工具的 `effect`、參數與說明以 [`adapters/duck.ts`](adapters/duck.ts) 為準（`bin/duckctl tools` 會印出來）。

| 工具 ID | effect | `confirmed` 代表 | 需要鴨子的能力 |
|---|---|---|---|
| `app.duck.status` | read | 鴨子回了目前的狀態 | — |
| `app.duck.walk` | reversible_write | state 讀到開始走（不是走完） | `walk` |
| `app.duck.stop` | reversible_write | state 讀到已停下、沒有任務 | —（任何時候都送） |
| `app.duck.look` | reversible_write | 頭到位（`data.reached: true`），或已開始轉（`false`） | `head` |
| `app.duck.gesture` | reversible_write | 動作已開始（`gesture_done` 事件，或 state 顯示由 duck-link 控制） | `head` |
| `app.duck.antennas` | reversible_write | **目前不會是 `confirmed`**：v0 的 state 沒有天線位置可回讀，最多 `unconfirmed` | `antennas` |
| `app.duck.express` | reversible_write | state 讀到表情已換 | `eyes` |
| `app.duck.track` | reversible_write | state 讀到跟隨設定生效（不是已經看到人） | `head`＋`tracking_face` 或 `tracking_sound` |
| `app.duck.where` | read | 鴨子回了位置 | `navigation` |
| `app.duck.places` | read | 鴨子回了地點清單 | `navigation` |
| `app.duck.mission_status` | read | 鴨子回了任務狀態（沒有任務也是成功的讀取） | — |
| `app.duck.go_to` | reversible_write | 任務已開始（**已出發，不是已到達**），`data.mission_id` | `navigation`、`walk` |
| `app.duck.find_person` | reversible_write | 開始找（不是找到） | `navigation`、`walk`、`camera` |
| `app.duck.return_home` | reversible_write | 開始回充電座（不是已充電） | `navigation`、`walk`、`dock` |
| `app.duck.cancel_mission` | reversible_write | state 讀到沒有進行中的任務 | — |
| `app.duck.follow_me` | reversible_write | 開始找你（不是已跟上） | `walk`、`camera` |
| `app.duck.wait_here` | reversible_write | state 讀到 `mode: waiting` | — |

**第一階段只啟用 6 個**（`DUCK_STAGE1_TOOLS`，使用者 2026-11-26 決定）：`status`、`stop`、`look`、`gesture`、`express`、`track`。其餘 11 個的定義都在，但 `enabled: false`、在給人看的總表上隱藏；AIOS 的 Dispatcher 對它們回 `refused`／`disabled`。`duckctl` 是開發入口，17 個全開（`enableAllTools`）。

鴨子回報某項能力 `unsupported` 時，對應的工具不會送出，直接回 `refused`（`data.duck_reason: "unsupported"`、`data.capability`）。以鴨子現在的硬體（只有頭部舵機與喇叭），實機上會動的只有 `status`、`stop`、`look`、`gesture`。

不給模型的 duck-link 指令與理由：

| 指令 | 理由 | 誰可以下 |
|---|---|---|
| `presence` | 要由語音工作階段的**真實事件**驅動；給模型等於讓它「演」正在聽或正在說 | DuckTerminal（`PresenceDriver`）；開發時 `duckctl presence` |
| `sound` | 本機提示音是終端的回饋，不是模型的決定 | 之後由 DuckTerminal |
| `resume` | 解除暫停之後 `walk` 才會被接受，比較像有人在場才做的事。**要不要給模型由使用者決定**（預設不給） | `duckctl resume` |

`track` 給了模型：使用者會說「看著我」「不要一直看我」，而且 Nous 只是開關，跟隨在鴨子本機計算。

刻意不提供的操作（[ADR-0001 §4、§7.3](../docs/adr/ADR-0001-duck-role-in-nous.md#4-appduck-工具清單草案)）：關扭力、重開機、寫舵機設定、解除緊急停止、串流關節角度、建圖與改禁區、取得影像或錄音、放寬隱私設定。duck-link v0 的 schema 裡沒有這些操作，hub 也送不出不合 schema 的指令（有測試）。

還沒做的工具：`app.duck.announce`（要不要做取決於語音路徑，見 [`docs/voice-path.md`](docs/voice-path.md)）、`app.duck.privacy_tighten`（等 [ADR-0006](../docs/adr/ADR-0006-privacy-settings.md) 的隱私設定 schema）。

## 目錄

| 路徑 | 內容 |
|---|---|
| `hub/duck-link-hub.ts` | duck-link hub 與 `DuckLink` 介面；`start()` 獨立執行，`attach(server)` 掛到既有的 http server（AIOS 核心的接法） |
| `adapters/duck.ts` | 工具定義與 `DuckAdapter` |
| `adapters/duck-exec.ts` | 一則指令 → ack → 回讀 → `ToolResult` 的共用流程 |
| `adapters/duck-text.ts` | 結果的固定句（中文與英文） |
| `terminal/duck-terminal.ts` | 事件入口（分類、任務紀錄、sink） |
| `terminal/presence.ts` | `PresenceDriver`：語音工作階段事件 → `presence`，去抖動與節流 |
| `terminal/manual-presence-source.ts` | **開發用**的手動 presence 來源 |
| `shared/aios-integrations.ts`、`aios-schema.ts`、`aios-contracts.ts` | AIOS 契約的最小重新宣告，一個檔對應 AIOS 的一個模組（註明來源 commit；AIOS 那邊直接 import 原檔，不需要這三個檔） |
| `cli/text-command.ts` | **開發用**的文字命令規則（不是 Nous） |
| `shared/duck-link.ts`、`shared/capabilities.ts` | duck-link 訊息型別；指令 → 能力對照 |
| `shared/validator.ts` | 用 `../protocol/schemas/duck-link.v0.schema.json` 驗證（Ajv 8.20.0） |
| `mock/mock-duck.ts` | **模擬**的鴨子 |
| `cli/` | `duckctl`、hub 行程、控制通道（UNIX socket）、開發用的最小 Dispatcher |
| `scripts/duck-link-dev.sh` | 在背景啟動／停止 hub 與 SSH 通道 |
| `scripts/tunnel-probe.py` | 在 Pi 上跑的通道探測（不碰硬體） |
| `scripts/e2e-duckd.ts` | 對 A 線 duckd 的端到端檢查 |
| `tests/` | vitest 測試 |
| `docs/aios-integration-plan.md` | 搬進 AIOS 的計畫（檔案與函式層級） |
| `docs/voice-path.md` | 語音路徑設計 |
| `docs/voice-test.md` | 給使用者照做的語音實測步驟（用說的讓鴨子轉頭、點頭、搖頭；§7 是路線 2：對鴨子說「Hey 鴨子」開始對話） |

## 沿用的 AIOS 慣例

- TypeScript，無框架；`.ts` 副檔名的相對 import；設定與 AIOS 的 `tsconfig.json` 相同（少了瀏覽器的 lib）。
- 契約：AIOS `prototype/ambient-shell/server/integrations/contracts.ts` 的 `IntegrationAdapter`、`ToolDefinition`、`ExecutionContext`，以及 `shared/integrations.ts` 的 `ToolResult`（只有 `confirmed` 的 `ok` 為 true）。查閱的 commit：`c85307861f7562803fb3776407493da49cdc8a83`。
- 工具 ID `app.duck.<action>`；送給模型的名稱 `app__duck__<action>`；每個工具宣告 `effect`、`timeoutMs`（100 ms～60 s）、`supportedRoutes`（`api_key`、`live`）；參數 schema 只用 AIOS 支援的子集（平面物件、純量）。
- 工具說明有中文 `description` 與英文 `descriptionEn`；結果用固定句，英文另列。
- 對面是模擬的鴨子時，`adapter.mock` 為 true，每個結果的訊息以「（模擬）」開頭、`data.mock` 為 true。
- 文件中英雙語（AIOS `docs/BILINGUAL.md`）。

## 依賴

鎖在 `package.json` 與 `package-lock.json`：`ws` 8.22.0、`ajv` 8.20.0；開發用 `typescript` 7.0.2、`tsx` 4.23.15、`vitest` 5.0.3、`vite` 8.3.4、`@types/node` 25.9.9、`@types/ws` 8.18.1。除了 `ajv`，版本都和 AIOS 相同。`.npmrc` 設 `legacy-peer-deps=true`（npm 10.9 解析 vitest 5 的 peer 依賴時會當掉；AIOS 也是這樣設）。

## 輸入輸出

- 輸入：工具呼叫（之後來自 Nous Agent，現在來自 `duckctl`）；duck-link 收到的 `ack`、`state`、`event`；語音工作階段事件（之後來自 AIOS，現在只有開發用手動來源）。
- 輸出：duck-link `command`；AIOS `ToolResult`；整理過的鴨子事件（`TerminalEvent`）。
- 協定：[`../protocol/`](../protocol/README.md)。實作時發現的缺口與歧義寫在 [`../protocol/proposals/b-nous-readback-and-semantics.md`](../protocol/proposals/b-nous-readback-and-semantics.md)，沒有改 schema。
