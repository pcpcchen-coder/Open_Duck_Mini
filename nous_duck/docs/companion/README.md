# 鴨子夥伴功能：總體設計

狀態：**進行中**（2026-11-25 開始）。這份文件把「鴨子要像 Nous 一樣跟人互動」拆成可以一步一步驗收的工作。每一步的現況看 [分步進度](steps.md)；每晚做了什麼看 [工作紀錄](log-2026-11-25.md)。

需求來源：使用者 2026-11-25 的要求（下面 §1），加上既有的 [R-001](../requirements/R-001-mobile-companion.md)、[R-002](../requirements/R-002-follow-me.md) 與 ADR-0001～0013。這份文件不取代那些 ADR，只負責把它們接成一條實作路線。

## 1. 要做到什麼

| 編號 | 能力 | 使用者的說法（2026-11-25） | 設計依據 |
|---|---|---|---|
| C1 | 對話互動 | 跟 Nous 一樣會對話，有 Nous 既有的互動功能 | ADR-0001、ADR-0003、ADR-0010 |
| C2 | 眼睛 | 鴨子沒螢幕，有兩個眼睛（圓螢幕） | [眼睛硬體設計](../../hardware/expression_mods/gc9a01_eyes.md)、[表情設計](../eye_expressions.md) |
| C3 | 走路移動 | 會走路移動 | ADR-0009、ADR-0015 |
| C4 | 視覺連動 | 走路、擺頭要能跟視覺連結（之後裝雙目攝影機） | [雙目視覺規劃](../stereo_vision_plan.md)、ADR-0007 |
| C5 | 說話時做動作 | 語音互動上也要鴨子做動作 | ADR-0015、本文件 §4 |
| C6 | 家中導航 | 家裡有鴨子使用的導航方法 | ADR-0002 |
| C7 | 家（充電座） | 日後有個家（充電座） | ADR-0004、[`hardware/dock/`](../../hardware/dock/README.md) |

## 2. 現在手上有什麼（2026-11-25 22:20 實測）

| 項目 | 現況 | 影響 |
|---|---|---|
| Pi 4（2 GB）＋上游 runtime | 開機、SSH 可連、`get_throttled=0x0`、CPU 49.6 °C | 可以開發與部署 |
| 14 顆 STS3215＋驅動板 | `/dev/ttyACM0` 在；舵機控制台服務在跑（未連線匯流排） | 頭部可以實機測；腿不在無人看顧時動 |
| BNO055 | 已接（讀得到；校準狀態 0、溫度讀值異常） | 跌倒偵測要等校準與裝機方向確認 |
| 足底開關 | **沒接** | 上游步態需要足底接觸，**實機走路還不能做** |
| USB 喇叭 | 已接（USB 裝置在） | 可以做播放路徑；夜間不出聲，沒有試聽 |
| 麥克風 | **沒有** | 鴨子還聽不到；對話暫時由 Mac 的 Nous 收音 |
| 鏡頭 | **沒有** | 視覺連動只能用合成資料與模擬驗證 |
| GC9A01 眼睛螢幕、天線舵機 | **沒有** | 眼睛只能輸出預覽圖；SPI 驅動等螢幕到貨 |
| 充電座、充電觸點 | 設計 v0，未列印 | 回充只能在模擬驗證 |
| Mac：Nous（AIOS）| 在跑，聽 `127.0.0.1:8787` | AIOS repo 依規則**唯讀**；要改 AIOS 的部分寫成整合計畫，不在這裡動 |

結論：今晚能**實機**驗證的只有「Mac ↔ Pi 的 duck-link 連線」與「頭部 4 顆舵機的小幅動作」。其餘能力先做到「程式＋單元測試＋模擬」，並在每一步寫明缺哪個硬體才能上實機。

## 3. 架構

```text
┌──────────────── Mac mini ────────────────┐
│ Nous（AIOS，唯讀）                        │
│   └─ 之後：DuckAdapter 註冊進 AIOS         │
│ nous_adapter/（本 repo，TypeScript）       │
│   DuckAdapter：app.duck.* → duck-link      │
│   DuckTerminal：事件、presence             │
│   duck-link hub：ws://127.0.0.1:<port>     │
└───────────────┬───────────────────────────┘
                │ SSH 通道（Mac → Pi 的反向轉送；兩邊都不對區網開 port）
┌───────────────┴────────── Pi 4（鴨子）─────┐
│ duckd（robot/duckd，Python）                │
│   nous_link：WebSocket client、schema 驗證、租約、ack／state／event │
│   behaviors：look、gesture、presence 編排、track（視覺連動）        │
│   eyes：duck_eyes 渲染 → 面板（虛擬面板／之後 GC9A01）             │
│   safety 仲裁：夾限、限速、期限、租約、緊急停止（最後一關）         │
│   body 後端：mock ｜ 頭部直控（沿用舵機控制台的控制核心）｜ 步態 host（上游 RLWalk） │
│ navigation（定位、路徑、任務、回充）  perception（鏡頭、人臉、深度）  audio（喇叭、音效、變聲、喚醒詞） │
└────────────────────────────────────────────┘
        模擬：sim/（MuJoCo：上游步態策略、合成鏡頭、合成的家）可以代替整個身體
```

### 3.1 這次定下來的事

| 決定 | 內容 | 理由 |
|---|---|---|
| 協定 | [duck-link v0](../../protocol/README.md)：一個 schema 檔、六種訊息 | 先讓兩端有同一份契約，再各自實作 |
| 傳輸 | 照 ADR-0009：鴨子是 WebSocket client，連本機 loopback。**通道方向暫時由 Mac 發起**（`ssh -R`，用現有的 `duck-pi4` 金鑰） | ADR-0009 的 autossh 是 Pi → Mac，要在 Mac 開「遠端登入」並放 Pi 的金鑰，屬於改 Mac 的安全設定，留給使用者決定。對鴨子端程式來說兩種方向沒有差別 |
| Nous 端的落腳處 | AIOS 核心加 `/duck-link` 端點之前，用 `nous_adapter/` 裡的獨立 hub 行程 | AIOS 唯讀；hub 之後整段搬進 AIOS |
| 硬體歸屬 | 舵機匯流排同一時間只給一個程式：舵機控制台、duckd、上游腳本三者互斥 | 控制台已有衝突檢查；duckd 沿用同一個檢查 |
| `presence` | Nous 語音工作階段的真實狀態經 duck-link 給鴨子，鴨子本機決定怎麼演 | 動作要跟語音同步，但不讓 Nous 串流關節角度（ADR-0001） |
| `track` | 視覺／聲音連動在鴨子本機閉迴路；Nous 只開關 | Wi-Fi 延遲不能進控制迴路 |
| 能力回報 | `capabilities` 逐項回報 `available`／`degraded`／`unsupported`／`mock` | 硬體沒到的能力，工具要回 `unsupported`，不能假裝 |

### 3.2 各能力怎麼接起來

| 能力 | Nous 端 | duck-link | 鴨子端 | 缺的硬體 |
|---|---|---|---|---|
| C1 對話 | Nous 語音工作階段（Mac 收音） | `presence`；之後語音走媒體通道（ADR-0010） | 喇叭播放、變聲、本機音效 | 麥克風陣列（鴨子自己聽）、AIOS 把語音指定到終端 |
| C2 眼睛 | `app.duck.express` | `express`、`presence` | `duck_eyes` 渲染、狀態環（真實裝置狀態） | GC9A01 × 2 |
| C3 走路 | `app.duck.walk`、`stop` | `walk`、`stop`、`resume` | 步態 host＋仲裁器 | 足底開關、落地測試要人在場 |
| C4 視覺連動 | `app.duck.look`、開關 `track` | `look`、`track` | 人臉偵測 → `look_at` → 頭；頭轉到底再轉身 | 雙目鏡頭 |
| C5 說話時做動作 | 語音工作階段事件 → `presence`、`app.duck.gesture` | `presence`、`gesture` | 編排器：眼睛＋頭＋天線＋音效 | 天線舵機、眼睛螢幕（頭部現在就能動） |
| C6 導航 | `app.duck.go_to`、`where`、`places` | 任務指令與 `mission_*` 事件 | 定位（AprilTag＋里程）、規劃、避障、禁區 | 雙目鏡頭、AprilTag、實機走路 |
| C7 回家 | `app.duck.return_home` | `return_home`、`docked`、`charging_started` | 對位、電氣確認充電 | 充電座、觸點、充電板 |

## 4. 說話時的動作（C5）

`presence` 狀態對應到鴨子的表現。原則：只由**真實事件**驅動（工作階段真的在聽、真的在播），不演沒有發生的事；動作幅度小，站著時不影響平衡（ADR-0015 的限制）。

| `presence` | 眼睛 | 頭 | 天線 | 聲音 |
|---|---|---|---|---|
| `idle` | 中性、自動眨眼 | 回正，偶爾小幅看別處 | 靜止 | 無 |
| `wake` | 睜大 | 抬頭、轉向聲源（有 DOA 時） | 豎起 | 本機「來了」音效 |
| `listening` | 專注 | 微微歪頭，面向說話的人（`track face`） | 微前傾 | 無 |
| `thinking` | 往上看 | 小幅左右慢擺 | 交替擺 | 無 |
| `speaking` | 依語氣 | 隨 `speech_level` 小幅點動 | 隨音量 | Nous 的聲音（變聲後） |
| `working` | 處理中 | 靜止 | 慢擺 | 無 |
| `error` | 困惑 | 小幅搖頭一次 | 垂下 | 提示音 |
| `sleeping` | 閉眼（鏡頭開著時不閉，見 `duck_eyes.policy`） | 低頭 | 垂下 | 無 |

具體角度、時間由鴨子端的編排表定義（`robot/duckd`），這張表是意圖。

## 5. 安全與夜間規則

1. 安全判斷只在鴨子本機（ADR-0001）。duck-link 裡沒有關扭力、重開機、寫偏移、解除緊急停止。
2. 無人看顧時（包含 2026-11-25 夜間這次）：**不動腿、不改腿的扭力狀態、不讓喇叭出聲**；實機只做頭部 4 顆的小幅慢速動作（每軸 ±15° 內、30°/s 以下），做完回到原位。
3. 實機走路要等：足底開關接好、IMU 校準、使用者在場、先架高再落地（ADR-0009 §5）。
4. 模擬、mock、合成資料一律標示，不當成實機結果（`CLAUDE.md` 誠實規則）。

## 6. 工作分配（2026-11-25 夜間）

五條線，各自一個分支；彼此只靠 duck-link v0 與下表的目錄邊界配合。

| 線 | 目錄 | 內容 | 進度檔 |
|---|---|---|---|
| 整合 | `docs/companion/`、`protocol/`、共用索引 | 基礎分支、協定、總體設計、收尾 | [steps.md](steps.md) |
| A 身體 | `robot/duckd/`、`robot/deploy/pi4/`（新檔） | duckd、安全仲裁、動作、presence、眼睛輸出、步態 host、Pi 部署（**唯一能碰舵機匯流排**） | [progress/a-body.md](progress/a-body.md) |
| B Nous 端 | `nous_adapter/` | hub、DuckAdapter、DuckTerminal、開發 CLI、AIOS 整合計畫 | [progress/b-nous.md](progress/b-nous.md) |
| C 模擬與導航 | `sim/`、`robot/navigation/` | 全身走路模擬、地圖、定位、規劃、任務、回充 | [progress/c-sim-nav.md](progress/c-sim-nav.md) |
| D 感知與音訊 | `robot/perception/`、`robot/audio/` | 鏡頭抽象、人臉 → 注視、視覺連動走路、深度；喇叭路徑、音效、變聲、喚醒詞 spike | [progress/d-perception-audio.md](progress/d-perception-audio.md) |

## 7. 需要使用者決定或動手的事

見 [分步進度 §需要你處理](steps.md#需要你處理)。
