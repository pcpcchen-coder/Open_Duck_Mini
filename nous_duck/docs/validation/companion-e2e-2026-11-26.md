# 夥伴功能端到端（全 mock）：Nous 端 adapter 對鴨子端 duckd（2026-11-26）

- **驗證層級**：端到端，兩端都在 Mac 上，**身體是模擬的（`MockBody`，`mock: true`）**。沒有經過 Pi、沒有動任何舵機、沒有經過 AIOS。
- 對象：B 線 `claude/duck-b-nous-a19b67`（`ae7b635`）的 hub＋`DuckAdapter`（TypeScript）；A 線 `claude/duck-a-body-8fca8a`（`40572b2`）的 `duckd`（Python）。兩個實作互不共用程式碼，只共用 `protocol/schemas/duck-link.v0.schema.json`。
- 執行者：整合線，2026-11-26 02:29，各線的 worktree 原地執行（沒有合併分支）。

## 怎麼跑

```bash
# 鴨子端（A 線 worktree）
cd nous_duck/robot/duckd && .venv/bin/python -m duckd --body mock --engage --allow-unverified-gestures --eyes-panel /tmp/duck_eyes.png --url ws://127.0.0.1:18792/duck-link
# Nous 端（B 線 worktree）
cd nous_duck/nous_adapter && npx tsx scripts/e2e-duckd.ts --port 18792
```

## 先跑的測試

| 項目 | 結果 |
|---|---|
| `robot/duckd/tests`（A 線） | 107 通過、3 略過（49.8 秒） |
| `nous_adapter` `npm test`（B 線） | 5 檔 137 通過（3.6 秒） |
| `robot/perception/tests`、`robot/audio/tests`（D 線） | 67 通過；75 通過、2 略過（需要 `aplay`） |

## 端到端結果

鴨子自報：`duckd 0.1.0`、`mock=true`；能力 `head: mock`、`eyes: mock`、`battery: mock`，其餘（`walk`、`antennas`、`speaker`、`microphone`、`camera`、`tracking_*`、`navigation`、`dock`、`imu`、`feet`）都是 `unsupported`。

| 工具呼叫 | `ToolResult` | 說明 |
|---|---|---|
| `status` | confirmed | 2 ms |
| `look` 小角度（0.1 rad） | confirmed，`reached=true` | 約 1.0 秒到位 |
| `look` 超出範圍（1.5 rad） | confirmed，`clamped=true` | 鴨子端夾限，實際值在 `applied` |
| `look` 回正 | confirmed | |
| `gesture look_around` | confirmed | 代表已開始 |
| `gesture` 不存在的名稱 | refused | 沒有送出 |
| `express confused` | confirmed | 虛擬面板 |
| `antennas`、`track face`、`walk`、`where`、`places`、`go_to` | refused（`unsupported`） | 鴨子回報沒有這項能力，adapter 沒有送出 |
| `track none`、`mission_status`、`cancel_mission`、`stop` | confirmed | |
| `wait_here` | refused（`unsupported`） | |
| `presence` 8 種狀態 | 全部 confirmed | 由測試腳本直接送，**不是 Nous 的事件** |

計數：1 次連線、19 個指令、收到與送出不合 schema 的訊息各 0 則、沒有對不上的 ack。收到事件：`capability_changed`、`gesture_done(stop)`。

## 這次沒有驗證的

- **實機**：Pi 上的 duckd 沒有接手匯流排，真的頭沒有動過。原因：2026-11-25 夜間舵機控制台一直連著匯流排；深夜電池電壓偏低、舵機已被放鬆，整合線沒有在無人看顧下重新出力。
- 經 SSH 通道的這一組（B 的 hub 對 Pi 上的 duckd）：A 線用自己的假 hub、B 線用探測程式各自測過通道，兩邊的正式程式還沒有經通道對接。
- AIOS：adapter 還沒搬進 AIOS，Nous 的 Agent 還不能呼叫 `app.duck.*`。
- 導航（C 線）、感知（D 線）還沒接進 duckd，所以這裡的 `navigation`、`tracking_*` 都是 `unsupported`。
