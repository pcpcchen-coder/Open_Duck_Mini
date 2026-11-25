# 驗證紀錄：Nous adapter（hub、DuckAdapter、DuckTerminal、duckctl）

- 日期：2026-11-25（夜間，使用者不在場）
- 範圍：[`nous_adapter/`](../../nous_adapter/README.md)，B 線（分支 `claude/duck-b-nous-a19b67`）
- 機器：Mac mini（macOS，Node.js 22.23.3、npm 10.9.9）；Pi 4（`duck-pi4`，Python 3.13.5）只用在 §4 的通道探測
- 夜間規則遵守情況：沒有讓任何喇叭出聲；沒有碰舵機匯流排、I2C、GPIO；沒有重開 Pi；沒有對執行中的 Nous（`127.0.0.1:8787`）發任何請求；沒有修改 `~/AIOS`

## 1. 結論

| 項目 | 結果 | 驗證層級 |
|---|---|---|
| duck-link v0 schema 在 TypeScript 端（Ajv 8.20.0）的判定與 Python 端一致 | 通過：共用範例 19 則合法全過、11 則不合法全拒 | 單元測試 |
| hub：連線守門、hello、心跳與往返時間、指令與 ack 配對、state、event | 通過 | 整合測試（對 TypeScript mock 鴨子，本機臨時埠） |
| DuckAdapter：17 個工具的 `ToolResult` 語意 | 通過 | 整合測試（對 TypeScript mock 鴨子） |
| DuckTerminal：事件入口、`presence` 的對應、去抖動與節流 | 通過 | 單元測試（假時鐘）＋整合測試（mock 鴨子） |
| `duckctl` 與控制通道 | 通過 | 整合測試＋手動執行（對 mock） |
| 端到端（全 mock）：本 repo 的 hub＋DuckAdapter 對 A 線 `duckd`（Python，mock 身體） | 通過：雙向 0 則不合 schema 的訊息；18 個工具呼叫 10 個 `confirmed`、8 個 `refused`（都是預期中的拒絕） | 端到端，兩端都在 Mac，**身體是 mock** |
| SSH 通道（Mac → Pi，`ssh -R`）與 hub | 通過：Pi 上的探測程式完成 hello 並回應心跳 | **實機網路**（Mac ↔ Pi 的 Wi-Fi＋SSH）；沒有碰鴨子的任何硬體，對面是探測程式不是 duckd |
| 端到端（實機頭部） | **沒有做**：A 線還沒把 duckd 部署到 Pi（A 線進度檔 2026-11-25 寫「還沒在 Pi 上執行」） | — |
| 整合進 AIOS | **沒有做**（AIOS 唯讀）；只有計畫 | — |

沒有任何一項是在真的鴨子身上驗證的。

## 2. 單元與整合測試

```bash
cd nous_duck/nous_adapter
npm ci
npm run typecheck    # tsc --noEmit，無錯誤
npm test             # vitest run
```

結果（2026-11-25 23:00 前後）：5 個檔案、**137 項全部通過**，約 4 秒。

| 檔案 | 項數 | 內容 |
|---|---|---|
| `tests/validator.test.ts` | 33 | `protocol/examples/valid.jsonl` 19 行逐行通過、`invalid.jsonl` 11 行逐行被拒；錯誤訊息指出欄位、不回顯內容 |
| `tests/hub.test.ts` | 23 | 只綁 127.0.0.1；路徑不對 404；帶 `Origin` 403；`Host` 不對 403；一般 HTTP 404；hello 順序與逾時；版本不合關閉；新連線取代舊的；心跳與往返時間；鴨子沒回應就關閉；租約失效（mock 鴨子回報 `link_lost`）；不合 schema 的訊息丟棄並計數；schema 沒有的操作（關扭力）送不出去；ack 配對、不回 ack、斷線、中止；event 去重；`waitFor` |
| `tests/duck-adapter.test.ts` | 50 | 工具定義符合 AIOS 契約（ID、effect、時限、路徑、參數 schema 子集、中英說明、「confirmed 不代表做完」的字句）；接受並回讀 → `confirmed`；夾限；各種拒絕原因 → `refused`；能力 `unsupported` 不送出並如實回報；不回 ack／斷線／中止 → `unknown`；沒有連線 → `failed`；接受但沒有回讀 → `unconfirmed`；任務的進度、完成、失敗、取消；每個工具的 `data` 小於 4 096 bytes |
| `tests/terminal.test.ts` | 18 | `PresenceDriver`（假時鐘）：phase 對應、去抖動、`wake` 與 `error` 的維持時間、`working`、`sleeping`、`speech_level` 的正規化與節流、送出期間狀態改變只補送最後一個、重連後重送、開發用手動來源的標示；`DuckTerminal`：事件分類、任務紀錄、斷線與重連由 hub 端回報 |
| `tests/cli.test.ts` | 13 | `duckctl` 參數解析（別名、負數、`--deg`、位置參數）；開發用 Dispatcher（參數驗證、時限 → `unknown`、Adapter 丟錯 → `failed`）；控制通道（執行工具、`link`、`presence`、`events --follow`、沒有鴨子時回 `failed`、不能啟動第二個 hub） |

協定自己的測試（整合線寫的）也重跑了一次：`uv run --no-project --with jsonschema --with pytest python -m pytest nous_duck/protocol/tests -q` → 32 項通過。

這些測試的對面都是 [`nous_adapter/mock/mock-duck.ts`](../../nous_adapter/mock/mock-duck.ts)：**標示為 mock 的 TypeScript 鴨子**，`hello` 與 `state` 帶 `mock: true`。它的夾限範圍、速度、地點都是測試用的固定值（頭部範圍取自 ADR-0009 §2.5 的初始值，未經實機驗證；地點是合成的 fixture）。

## 3. 端到端（全 mock）：對 A 線的 duckd

目的：確認兩個各自照 schema 寫的實作（TypeScript 的 hub＋DuckAdapter、Python 的 duckd）真的講得通。

- 鴨子端：A 線分支 `claude/duck-a-body-8fca8a` 的 commit `b1f21ce`，`robot/duckd`，**只執行、沒有修改**。在 Mac 上以 mock 身體啟動（不碰硬體）：

  ```bash
  python -m duckd --body mock --engage --allow-unverified-gestures --eyes-panel <暫存檔> --no-percept \
      --ctl-socket <暫存 socket> --url ws://127.0.0.1:18792/duck-link
  ```

- Nous 端：`npx tsx scripts/e2e-duckd.ts --port 18792`（用 18792，不占用開發約定的 8791）。
- 時間：2026-11-25 22:55～23:00，跑了 4 次（第 1 次 duckd 沒有開放動作清單與眼睛；第 2～4 次有）。以下是第 4 次的結果。

鴨子的自我描述：`duckd 0.1.0`、`duck_id=duck1`、**`mock=true`**；能力 `head: mock`、`eyes: mock`、`battery: mock`，其餘 11 項 `unsupported`；動作 `look_around`、`nod`、`shake`、`tilt`；表情 15 個。

| 步驟 | 結果 | 耗時 | 備註 |
|---|---|---|---|
| `status` | `confirmed` | 2 ms | `data` 1 098 bytes |
| `look` head_yaw 0.1 rad／1 s | `confirmed` | 約 1.0 s | `reached: true`（等到回讀角度進入 ±0.06 rad） |
| `look` head_yaw 1.5 rad（超出範圍） | `confirmed` | 約 1.0 s | `clamped: true`，`applied.head_yaw = 0.5` |
| `look` 四軸回正 | `confirmed` | 約 1.0 s | `reached: true` |
| `gesture look_around` | `confirmed` | 16 ms | 證據是 `state.control_source = duck_link`（弱證據，見提案 §1） |
| `gesture`（不在清單上的名稱） | `refused` | 0 ms | Nous 端依 hello 的清單擋下，沒有送出 |
| `express confused` | `confirmed` | 18 ms | 回讀 `state.expression` |
| `antennas` | `refused` | 0 ms | 鴨子回報 `antennas: unsupported`，沒有送出 |
| `track face` | `refused` | 0 ms | `tracking_face: unsupported`，沒有送出 |
| `track none` | `confirmed` | 13 ms | |
| `walk` | `refused` | 0 ms | `walk: unsupported`（原因：gait host not integrated; feet switches not wired…），沒有送出 |
| `where`、`places`、`go_to` | `refused` | 0 ms | `navigation: unsupported`，沒有送出 |
| `mission_status` | `confirmed` | 4 ms | duckd 回 `rejected: no_mission`；Nous 端視為「讀到了：沒有任務」 |
| `cancel_mission` | `confirmed` | 3 ms | 同上 |
| `wait_here` | `refused` | 3 ms | duckd 回 `rejected: unsupported`（見提案 §5） |
| `stop` | `confirmed` | 23 ms | |
| `presence` × 8（wake、listening、thinking、speaking＋level 0.5、working、error、sleeping、idle） | 全部 `confirmed` | — | 回讀 `state.presence`；由測試腳本直接送，不是 Nous 的事件 |

hub 的計數：`connections 1`、`rxInvalid 0`、`txInvalid 0`、`unmatchedAcks 0`、`commands 19`（18 個工具呼叫裡有 7 個在 Nous 端就擋下、沒有送出，所以送出 11 則；加上 8 則 presence）。收到的事件：`capability_changed`、`gesture_done`（`reason: stop`）。

過程中發現並處理的事：

1. `status` 的 `data` 第一版把 duckd 的 `ack.data`（整份 state）也放進去，量到 **2 750 bytes**，離 AIOS Dispatcher 的 4 096 bytes 上限太近（超過會整個被丟掉）。已改成不放 `ack.data`，現在 1 098 bytes。
2. `mission_status` 在沒有任務時，duckd 回 `rejected: no_mission`，TypeScript mock 回 `accepted`。兩種都合 schema；DuckAdapter 已改成兩種都當成成功的讀取。
3. `gesture_done` 帶 `reason: stop`：動作被下一個指令打斷也會送 `gesture_done`，所以它不能當成「做完」的證據。
4. duckd 的本機控制 socket 路徑太長會啟動失敗（macOS 的 UNIX socket 路徑上限），和 B 線無關；用短路徑就好。已在這裡記下，A 線自己的預設路徑沒有這個問題。

協定層的歧義整理在 [`protocol/proposals/b-nous-readback-and-semantics.md`](../../protocol/proposals/b-nous-readback-and-semantics.md)，沒有改 schema。

限制：兩端都在同一台 Mac 的 loopback 上，往返時間（1 ms）沒有參考價值；身體是 mock，「頭轉到位」只代表 duckd 的模擬身體回報的角度到位。

## 4. SSH 通道（實機網路，不碰硬體）

目的：確認開發用的通道腳本可用，並量 Mac ↔ Pi 經 Wi-Fi 與 SSH 的心跳往返時間（ADR-0009 §6 第 4 項要這個數字）。

```bash
cd nous_duck/nous_adapter
scripts/duck-link-dev.sh hub-start
scripts/duck-link-dev.sh tunnel-start            # ssh -N -R 127.0.0.1:8791:127.0.0.1:8791 duck-pi4
ssh duck-pi4 python3 - < scripts/tunnel-probe.py # 在 Pi 上執行探測程式（標準函式庫，不寫檔）
bin/duckctl link
scripts/duck-link-dev.sh tunnel-stop
scripts/duck-link-dev.sh hub-stop
```

探測程式（[`scripts/tunnel-probe.py`](../../nous_adapter/scripts/tunnel-probe.py)）以「不是鴨子」的身分完成 hello（`mock: true`、`software: "tunnel-probe (not a duck)"`），回應 hub 的心跳，對任何指令回 `rejected: unsupported`。它不啟動 duckd、不開序列埠、不碰任何硬體。

結果（2026-11-25 22:57，Pi 開機 2 小時 8 分、load average 0.59）：

| 量測 | 數值 | 怎麼量的 |
|---|---|---|
| 通道建立 | 成功；Pi 上 `ss -ltn` 看到 `127.0.0.1:8791`（只綁 loopback） | — |
| WebSocket 升級 | `HTTP/1.1 101 Switching Protocols`，收到 hub 的 hello | 探測程式 |
| 心跳往返時間 | n = 25：最小 3 ms、中位數 7 ms、最大 343 ms | Mac 上每 0.7 秒讀一次 `duckctl link --json` 的 `rtt_ms`（hub 用鴨子端的回聲量的最近一次） |
| Pi 收到心跳的間隔 | 32 秒內 65 次：最小 313 ms、平均 501 ms、最大 755 ms | 探測程式用 Pi 的單調時鐘記錄 |
| 對探測程式下 `status`、`look` | `refused`（`duck_reason: unsupported`），訊息標示「模擬」 | `duckctl` |
| 結束後 | Mac 與 Pi 都沒有程式在聽 8791 | `lsof`、`ss` |

解讀與限制：

- 樣本很少（25 個往返、32 秒），只能說「這段時間內連線租約（1.5 秒）沒有接近被打破」：心跳間隔最大 755 ms。不能推論整天或走動時的表現。
- 最大 343 ms 的那一筆往返只出現一次，原因沒有查（Wi-Fi 或 SSH 的重傳都有可能）。
- 量的是 hub ↔ 探測程式；真的 duckd 回聲的時間會再加上它自己的迴圈延遲。
- 通道方向是 Mac → Pi（不必開 Mac 的「遠端登入」）。要不要改成 ADR-0009 的 Pi → Mac（autossh）由使用者決定。

## 5. 手動執行 `duckctl`（對 TypeScript mock 鴨子）

在備用埠 18791 啟動 `duckctl hub` 與 `duckctl mock-duck`，執行 `link`、`status`、`look --yaw 10 --deg`、`look --yaw -0.9`（夾限到 −0.5）、`gesture nod`、`gesture backflip`（`refused`，沒有送出）、`antennas --left 0.5`（`refused`，`unsupported`）、`go_to brother_room`（`confirmed`＋`mission_id`，之後收到 `mission_progress`、`mission_done`）、`presence speaking --level 0.4`、`presence wake`、`walk --vx 0.05`（缺 `duration_s` → `refused`）、`stop`、`express happy --json`、`events`。輸出都標示「（模擬）」與「對面是模擬的鴨子」。

## 6. 沒有驗證的事

- 任何實機動作（頭、腿、眼睛、天線、喇叭）。
- 對 Pi 上執行的 duckd（即使是 mock 身體）的端到端——A 線還沒部署。
- 長時間連線的穩定度、Wi-Fi 變差時的行為、鴨子走動時的往返時間。
- 在 AIOS 裡執行（Dispatcher、頻率限制、兩條語音路徑、模型實際怎麼用這些工具）。
- `presence` 的去抖動與節流數值（120 ms、600 ms、1.5 s、200 ms、0.1）是初始值，沒有對著真的對話與真的鴨子調過。
- 頭部到位的容許誤差（0.06 rad）沒有實機依據。
