# 驗證紀錄：桌上互動的 Nous 端（T2、T3）與 AIOS 分支

- 日期：2026-11-26
- 範圍：[`nous_adapter/`](../../nous_adapter/README.md)（B 線，分支 `claude/duck-b-nous-a19b67`）與 AIOS 的分支 `claude/duck-link`（[pcpcchen-coder/AIOS#156](https://github.com/pcpcchen-coder/AIOS/pull/156)）
- 前一份：[nous-adapter-2026-11-25](nous-adapter-2026-11-25.md)（hub、DuckAdapter、DuckTerminal、`duckctl`、通道實測）
- 沒有做的事：沒有啟動會連雲端模型或會出聲的 Nous；沒有重啟、切換或改動正在跑的 Nous（`127.0.0.1:8787`）；沒有動 `~/AIOS`；沒有讀出或複製任何金鑰與 `.env` 內容；沒有碰 Pi 上的 duckd、舵機匯流排、I2C、GPIO

## 1. 結論

| 項目 | 結果 | 驗證層級 |
|---|---|---|
| 本 repo 的 `nous_adapter` 測試 | 144 項全過（`validator` 33、`hub` 24、`duck-adapter` 51、`terminal` 18、`cli` 18）；`tsc --noEmit` 無錯誤 | 單元／整合測試（對標示 mock 的 TypeScript 鴨子） |
| AIOS 分支：新增的 5 個測試檔 | 122 項全過 | AIOS 的 fixture 測試（假鴨子） |
| AIOS 分支：AIOS 自己的完整檢查 `node scripts/verify-aios.mjs` | PASS（188 檔、3 582 項通過、4 項略過；含型別檢查、建置、模擬 provider 的 HTTP 流程），在 `TZ=UTC` 下 | AIOS 的自動化檢查；不含真實語音 |
| AIOS 分支的 hub＋Dispatcher 對 duckd（**模擬身體**） | 雙向 0 則不合 schema 的訊息；8 個工具呼叫與 4 個 presence 的結果見 §3 | 端到端，兩端都在 Mac，身體是模擬的 |
| `duckctl`（含 `say-command`）對 duckd（**模擬身體**） | `look`、`gesture`、`presence`、`stop` 都 `confirmed`；見 §4 | 同上 |
| 對真的鴨子 | **沒有做**：A 線的實機頭部還沒好 | — |
| 用真實語音叫鴨子 | **沒有做**：要使用者自己啟動開發實例 | — |

## 2. 怎麼重跑

```bash
# 本 repo
cd nous_duck/nous_adapter && npm ci && npm run typecheck && npm test

# AIOS 分支（獨立 clone，不是正在跑 Nous 的那個 checkout）
cd ~/AIOS-duck-link && TZ=UTC node scripts/verify-aios.mjs
cd prototype/ambient-shell && TZ=UTC npx vitest run tests/duck-link.test.ts tests/duck-link-schema.test.ts tests/integration-duck.test.ts tests/duck-presence.test.ts tests/duck-core.test.ts
```

`TZ=UTC` 的原因：AIOS 的 `tests/commands-from-catalog.test.ts` 的基準檔含當地時間，在 Asia/Taipei 直接跑會差 8 小時而失敗；AIOS 的 main 就是這樣，和鴨子無關。

## 3. AIOS 分支的 hub 與 Dispatcher 對 duckd 的模擬身體

鴨子端：本 repo 的 `robot/duckd`（commit `0574686`），`python -m duckd --body mock --engage --allow-unverified-gestures --no-eyes --no-percept --url ws://127.0.0.1:18793/duck-link`。Nous 端：用 AIOS 分支的 `DuckLinkHub`、`createIntegrations`（只啟用 `duck`）與真的 `IntegrationDispatcher`，經 `live` 路徑以模型看到的名稱呼叫。沒有啟動 Nous 核心，沒有雲端。

| 呼叫 | 結果 | Dispatcher 記的耗時 |
|---|---|---|
| `app__duck__status` | `confirmed`，`data` 844 bytes | 6 ms |
| `app__duck__look` `{head_yaw: 0.2, duration_s: 1}` | `confirmed`，回讀到位 | 1 034 ms |
| `app__duck__look` `{head_yaw: 0, duration_s: 1}` | `confirmed` | 1 023 ms |
| `app__duck__gesture` `{name: "nod"}` | `confirmed` | 18 ms |
| `app__duck__express` `{expression: "happy"}` | `refused`／`unavailable`：鴨子回報 `eyes: unsupported`，沒有送出 | 0 ms |
| `app__duck__track` `{target: "none"}` | `confirmed` | 15 ms |
| `app__duck__walk` `{duration_s: 1}` | `refused`／`disabled`（第一階段沒有啟用；沒有送到鴨子） | 0 ms |
| `app__duck__stop` | `confirmed` | 18 ms |
| presence `wake`、`listening`、`working`、`idle`（`sendDuckPresence`） | 都 `confirmed`（回讀 `state.presence`） | — |

hub 的計數：`rxInvalid 0`、`txInvalid 0`、`unmatchedAcks 0`、`commands 10`。

## 4. `duckctl` 對 duckd 的模擬身體（開發入口，不經 AIOS）

`bin/duckctl hub --port 18794`，duckd 同上連 18794。

| 指令 | 對應／結果 |
|---|---|
| `say-command "往左看"` | → `app.duck.look {"head_yaw":0.2,"duration_s":1.5}`，`confirmed`（頭已經轉到位） |
| `say-command "抬頭一點"` | → `app.duck.look {"head_pitch":0.1,"duration_s":1.5}`，`confirmed` |
| `say-command "回正"` | → `app.duck.look` 四軸 0，`confirmed` |
| `say-command "點頭"` | → `app.duck.gesture {"name":"nod"}`，`confirmed`；之後收到 `gesture_done`（`completed: true`） |
| `say-command "笑一個"` | 認不得，沒有送出（duckd 這次以 `--no-eyes` 啟動，表情清單是空的） |
| `say-command "停"` | → `app.duck.stop`，`confirmed` |
| `say-command "幫我訂披薩"` | 認不得，沒有送出 |
| `look --yaw 10 --deg --time 1` | `confirmed` |
| `gesture nod` | `confirmed` |
| `presence listening`、`presence idle` | `confirmed`（開發用手動來源，不是 Nous 的事件） |

每一則輸出都標示「（模擬）」。`say-command` 是固定關鍵字規則，**不是 Nous、不是語音辨識、不是語言模型**；它只證明「一句已經是文字的命令 → DuckAdapter → hub → duckd」這條路通。

## 5. 沒有驗證的事

- 實機頭部：`look` 的方向（`head_yaw` 正＝往左、`head_pitch` 正＝抬頭是照 duckd 的註解，沒有在實機確認）、到位的容許誤差、動作的觀感。
- 真實語音：模型會不會選對工具、參數給多大、`confirmed`／`refused` 時怎麼說。
- presence 的節奏，以及「連上之後一律 listening、沒有 speaking」實際看起來如何。
- Mac ↔ Pi 經通道連到 AIOS 核心的埠（昨天量的是連到獨立 hub 的 8791）。
- AIOS 的 macOS App（Electron）內。
