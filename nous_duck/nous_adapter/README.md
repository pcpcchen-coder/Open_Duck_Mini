> [繁體中文](README.md) | [English](README.en.md)

# ④ Nous adapter（nous_adapter）

狀態：**規劃中**（尚無程式）。

## 職責

這個目錄放**之後要搬回 AIOS** 的程式：讓 Nous 透過 duck-link 使用鴨子。依 [ADR-0001](../docs/adr/ADR-0001-duck-role-in-nous.md)，鴨子在 Nous 中有兩個角色：

1. **DuckAdapter**（身體 adapter）：AIOS `IntegrationAdapter`，`service = "duck"`，提供 `app.duck.*` 工具給 Nous 的 Agent。
2. **DuckTerminal**（終端）：會走路的 Nous 終端（麥克風、喇叭、雙目鏡頭，沒有螢幕）；把鴨子的事件送進 Nous，並把 Nous 的語音與表情輸出送給鴨子。

## 子目錄

| 路徑 | 內容 | 狀態 |
|---|---|---|
| `adapters/` | `duck.ts`：DuckAdapter（工具定義、`health()`、`execute()`，ack／state 對應 `ToolResult`） | 規劃中 |
| `shared/` | duck-link 訊息型別（由 `protocol/schemas` 產生或對照），以及從 AIOS 契約最小化重新宣告的型別（註明來源 commit） | 規劃中 |
| `terminal/` | DuckTerminal：語音工作階段、事件入口（含任務進度與喚醒）、表情輸出 | 規劃中 |
| `tests/` | 用 **mock 鴨子**（必須標示 mock）測 adapter 的工具定義、結果對應、逾時與斷線 | 規劃中 |

## 必須沿用的 AIOS 慣例

- TypeScript，風格比照 AIOS `prototype/ambient-shell`（無框架）。
- 契約：AIOS `prototype/ambient-shell/server/integrations/contracts.ts` 的 `IntegrationAdapter`、`ToolDefinition`、`ExecutionContext`；結果用 `shared/integrations.ts` 的 `ToolResult`（只有 `confirmed` 的 `ok` 為 true）。
- 工具 ID：`app.<service>.<action>`，本專案為 `app.duck.<action>`；service 與 action 為小寫英數、可用單一底線分段；送給模型的函式名稱為 `app__duck__<action>`。
- 每個工具宣告 `effect`（`read`／`reversible_write`／`external_commit`）、`timeoutMs`（100 ms～60 s）、`supportedRoutes`。
- mock 版 adapter 要把 `mock` 設為 `true`，狀態與結果一律標示 mock。
- 文件中英雙語（AIOS `docs/BILINGUAL.md`）；工具說明提供 `description`（中文）與 `descriptionEn`。

## 工具清單（草案）

| 工具 ID | effect |
|---|---|
| `app.duck.status` | read |
| `app.duck.walk` | reversible_write |
| `app.duck.stop` | reversible_write |
| `app.duck.look` | reversible_write |
| `app.duck.gesture` | reversible_write |
| `app.duck.antennas` | reversible_write |
| `app.duck.express` | reversible_write（沒有表情硬體時為 `unsupported`） |
| `app.duck.where` | read（R-001 新增） |
| `app.duck.places` | read（R-001 新增） |
| `app.duck.mission_status` | read（R-001 新增） |
| `app.duck.go_to` | reversible_write（R-001 新增，非同步任務） |
| `app.duck.find_person` | reversible_write（R-001 新增，非同步任務） |
| `app.duck.return_home` | reversible_write（R-001 新增，非同步任務） |
| `app.duck.cancel_mission` | reversible_write（R-001 新增） |
| `app.duck.announce` | reversible_write（R-001 新增，是否需要待定） |
| `app.duck.privacy_tighten` | reversible_write（只能收緊隱私設定，見 ADR-0006） |

參數、確認方式、刻意不提供的操作見 [ADR-0001 §4](../docs/adr/ADR-0001-duck-role-in-nous.md#4-appduck-工具清單草案) 與 [§7.3](../docs/adr/ADR-0001-duck-role-in-nous.md#73-工具清單修訂後草案)。導航類工具走**非同步任務**：工具回 `confirmed` 代表「鴨子已出發」，完成與失敗以事件回到 Nous（[§7.2](../docs/adr/ADR-0001-duck-role-in-nous.md#72-長時間任務mission)）。

R-001（2026-11-12）後，DuckTerminal 改為完整的行動終端（麥克風、喇叭、雙目鏡頭），見 [ADR-0003](../docs/adr/ADR-0003-mobile-terminal-wake-and-find.md)。

## 輸入輸出

- 輸入：Nous Agent 的工具呼叫；duck-link 收到的 ack、state、event。
- 輸出：duck-link command；AIOS `ToolResult`；送進 Nous 的鴨子事件。

## 依賴

- `../protocol/schemas`（規劃中）。
- AIOS 的整合層契約（AIL-1）；本目錄不複製大段 AIOS 程式。

## 搬回 AIOS 的方式（預計）

在 AIOS repo 開獨立批次：把 `adapters/duck.ts` 放進 `prototype/ambient-shell/server/integrations/adapters/`，加入已審核 adapter 清單，以 `NOUS_AIL_SERVICES` 啟用。這件事在 AIOS 完成並驗證前，不在任何文件中宣稱已整合。
