# 晨間報告：2026-11-26

整合線寫於 02:40，03:30 更新（C 線收尾完成）。細節在 [分步進度](steps.md)、[工作紀錄](log-2026-11-25.md) 與各線的進度檔。

## 一句話

鴨子夥伴功能的**程式骨架五條線都有了，全部通過各自的測試，Nous 端與鴨子端用模擬身體講得通**；但**真的鴨子昨晚一顆舵機都沒有因為這些新程式而動過**，Nous 也還不能呼叫鴨子（AIOS 沒有動）。

## 先處理：電池

- 14 顆舵機昨晚一直出力，電壓靜置 7.6 V，出力時掉到 6.4～6.5 V，舵機控制台出現過低電壓警告，之後還有匯流排逾時。
- 02:28 我唯讀查看時，14 顆都已經放鬆、溫度 29～32 °C、Pi 沒有降頻。
- 所以我**沒有**在無人看顧下重新出力做頭部測試。請先充電，並確認電池與線材能不能供 14 顆同時出力。

## 各線成果

| 線 | 分支 | 做到哪 | 驗證層級 |
|---|---|---|---|
| 整合 | `claude/duck-companion-overnight` | 併入 6 個舊設計 PR 的分支、ADR 重新編號（0009～0013）、duck-link 協定 v0、總體設計、進度表 | 協定 32 項單元測試 |
| A 身體 | `claude/duck-a-body-8fca8a` | `duckd`：連線與租約、安全仲裁、頭部後端（程式上不會對腿部舵機寫入）、動作庫（點頭、搖頭、歪頭、環顧）、`presence` 編排、眼睛虛擬面板、步態 host 載入測試、Pi 部署 | 107 項單元測試；Mac↔Pi 通道端到端（模擬身體）；**實機頭部沒測** |
| B Nous 端 | `claude/duck-b-nous-a19b67` | hub、17 個 `app.duck.*` 工具、DuckTerminal、`duckctl`、AIOS 整合計畫、語音路徑設計（中英雙語） | 137 項測試；對 duckd 的全 mock 端到端 |
| C 模擬與導航 | `claude/duck-c-sim-nav-2e1cfa` | MuJoCo 全身走路模擬（上游步態策略）、走停轉量測、地圖格式與合成的家、AprilTag 定位、`go_to`、`return_home`、禁區保護 | 模擬：60 趟來回 60 趟成功；導航 65 項、模擬 29 項測試；文件已補齊（驗證紀錄、ADR-0016、協定提案） |
| D 感知與音訊 | `claude/duck-d-percept-audio-eae98e` | 鏡頭抽象、人臉到擺頭、轉身靠近控制器、雙目估距；21 個自製音效、播放路徑、變聲與喚醒詞的 Pi 4 量測 | 感知 67 項、音訊 75 項測試；全部是合成資料；**沒有人聽過任何聲音** |

整合線在 02:29 重跑過 A、B、D 的測試與全 mock 端到端，數字相符（[紀錄](../validation/companion-e2e-2026-11-26.md)）。C 線的預設測試我在 03:28 重跑過（29、65 項通過）；60 趟來回與 `--runslow` 的數字是它自己回報的。

## 對照你要的七件事

| 能力 | 現在的實際狀態 | 還缺什麼 |
|---|---|---|
| 對話互動 | 設計與 Nous 端程式有了；Nous 還叫不到鴨子 | AIOS 加 `/duck-link` 端點並註冊 adapter（計畫在 B 線）；鴨子的麥克風 |
| 眼睛（圓螢幕） | 表情渲染接進 duckd，輸出到虛擬面板（PNG）；Pi 上兩眼一幀約 124 ms | GC9A01 螢幕與 SPI 驅動；124 ms 太慢，要做局部更新或加速 |
| 走路 | 模擬裡會走；實機的步態 host 只做了載入測試 | 足底開關、IMU 校準、你在場的落地測試 |
| 視覺連動 | 控制器用合成資料跑通（頭 0.4～1.8 秒內對到人臉 5° 內） | 雙目鏡頭；接進 duckd 的 `track` |
| 說話時做動作 | `presence` 八種狀態在模擬身體上會驅動頭與眼睛 | 實機頭部測試；AIOS 送出真實的語音事件 |
| 家中導航 | 合成的家裡，充電座到房間再回來 60／60 | 鏡頭、AprilTag、實機走路、你家的地圖 |
| 充電座 | 模擬回充：第一次就進捕捉範圍 50／60，其餘重試成功 | 充電座與觸點；倒退進座目前是盲退 |

## 模擬裡發現、會影響設計的事

1. **步態策略有起步門檻**：前進指令要 ≥ 0.10 m/s 才會起步，原地轉要 ≥ 0.6 rad/s。ADR-0009 訂的室內上限（vx 0.10、yaw 0.6）剛好卡在門檻上，要重訂。
2. **速度指令為 0 時不踏步**（模擬）。ADR-0009 的停下規則假設會原地踏步，要改。
3. **走路時頭轉大角度會讓步態停下，甚至跌倒**（模擬）。實機驗證前，走路時頭要回正。
4. 實際速度只有指令的 0.72～0.79 倍；指令積分走 4 m 後誤差 0.19～0.53 m，印證不能靠步數定位。

這些都是模擬值，實機能走之後要重量。

## 早上可以親手試的

**不需要鴨子（在 B 線的 worktree）**，三個終端機分頁：

```bash
cd /Users/georgechen/NousDuck/.claude/worktrees/duck-b-nous-a19b67/nous_duck/nous_adapter && bin/duckctl hub
```

```bash
cd /Users/georgechen/NousDuck/.claude/worktrees/duck-b-nous-a19b67/nous_duck/nous_adapter && bin/duckctl mock-duck
```

```bash
cd /Users/georgechen/NousDuck/.claude/worktrees/duck-b-nous-a19b67/nous_duck/nous_adapter && bin/duckctl gesture nod
```

**真的頭（電池充好、你在場）**：舵機控制台按「釋放硬體」，然後照 A 線 [`robot/duckd/README.md`](../../robot/duckd/README.md)（在 A 線分支）的部署一節：Pi 上啟動 `duckd` 服務並 `duckd-ctl engage`，Mac 開通道後用 `duckctl look`。服務預設每軸 ±15°、30°/s。也可以叫我來做，我會先唯讀確認電壓與溫度。

**試聽**（D 線的 worktree）：`nous_duck/robot/audio/sounds/*.wav`（21 個音效）、`nous_duck/docs/validation/media/voice-2026-11-25-*.wav`（變聲比較，建議先聽 `pv_formant112_p5`）。

## 要你決定的事

| 事項 | 我的建議 |
|---|---|
| 五個分支怎麼合併、要不要推送與開 PR | 先合 A、B（互相需要），再 D、C；一條線一個 PR。我沒有合併也沒有推送 |
| 開著的 PR #9、#13、#14、#18、#19、#21 | 整合分支已包含並重新編號 ADR；可以關掉改用整合分支，或逐一合併後我再對齊編號 |
| AIOS 批次要不要開 | B 線建議先做三個：`/duck-link` 端點、註冊 adapter、粗略的 `presence`。做完加上實機頭部，就能用語音叫鴨子轉頭點頭 |
| 協定提案（A、B、C、D 各一份） | 多數是補回讀欄位與原因代碼；我建議收進 v0.2，一次改 schema 再改兩端 |
| 變聲參數、音效、喚醒詞、音量上限 | 等你試聽；中文喚醒詞在這個模型上可能不好認 |
| Pi 上多的東西 | `~/duck/duckd/`、`~/duck/duckd-venv/`、服務 `duckd`（disabled、已停止）、音訊與感知的 venv、apt 的 `rubberband-cli` 與 `sox` |

## 沒做到的

- 實機頭部端到端（I2）。
- README、路線圖、ADR 索引、驗證索引還沒反映各線成果（要等合併，免得索引指向不存在的檔）。
- 導航、感知還沒接進 duckd；CI 還沒加新模組的測試。
