# ADR-0014：duckd 第一版——頭部直控、單一程序、本機控制介面

- 狀態：**草案（Proposed）**；已有程式與單元測試（`robot/duckd/`），實機驗證層級見 [驗證紀錄](../validation/duckd-2026-11-25.md)
- 日期：2026-11-25
- 相關：[ADR-0001](ADR-0001-duck-role-in-nous.md)、[ADR-0008](ADR-0008-single-board-pi4.md)、[ADR-0009](ADR-0009-duck-link-transport-and-command-bridge.md)（傳輸與指令橋接）、[ADR-0015](ADR-0015-gesture-library.md)（動作庫）、[`robot/duckd/`](../../robot/duckd/README.md)、[夥伴功能總體設計](../companion/README.md)

## 1. 背景

ADR-0009 的鴨子端設計是「三個程序、一個仲裁器」，仲裁器住在上游步態主迴圈的程序裡；ADR-0015 的動作庫也假設頭部指令經步態策略送出（暫停時頭不會動）。

2026-11-25 的實際狀況：足底開關沒接、IMU 沒校準，**上游步態還不能在實機跑**；但頭頸 4 顆舵機可以動，而且使用者要先有「說話時做動作」。所以需要一條不依賴步態主迴圈的路，讓 duck-link 的 `look`、`gesture`、`presence` 現在就能讓頭動。這是 ADR-0015 §5 第 8 點留下的待決事項。

## 2. 決定

### 2.1 頭部直控後端（步態 host 沒在跑的時候）

- duckd 有一個「頭部直控」身體後端：只操作 ID 30–33，直接送位置目標給舵機，不經步態策略。
- 重用舵機控制台的控制核心（`servo_console.controller.Controller`、`bus.FeetechBus`），不改它：`Controller` 只拿到 4 個頭部關節，所以它的「全部」就是頭；匯流排再包一層白名單（`HeadOnlyBus`），帶到其他 ID 的讀寫直接丟例外。
- **腿不歸這個後端管**：不讀、不寫、不改扭力。腿是放鬆、被別的程式擺成站姿出力、還是懸空，duckd 不知道也不介入。因此這個模式下：
  - `state.mode` 回報 `holding`（頭部已接手）或 `limp`（duckd 沒有接手任何舵機；不代表舵機沒出力，見 §4 的協定提案）。
  - `capabilities.head` 回報 `degraded` 並寫明限制，不回報 `available`，直到完整範圍在實機驗證過。
  - `capabilities.walk` 是 `unsupported`。
- 頭部直控與步態 host **互斥**（同一條匯流排）。之後步態 host 接進來時，頭部指令改走 ADR-0009 的 7 維指令向量；兩種模式的切換流程另外設計（待決）。

### 2.2 仲裁器獨立於後端

`SafetyArbiter` 是純邏輯的類別，不屬於任何程序或後端：頭部直控模式由 duckd 的控制迴圈每圈呼叫；步態 host 模式由 `ArbiterCommandSource`（取代上游的 `XBoxController`）每圈呼叫。兩邊用同一份規則與同一份測試。ADR-0009 §2.5 的規則全部寫在裡面，包括現在還沒有輸入可餵的（跌倒、手把接管、足底著地才暫停）。

### 2.3 第一版是單一程序（暫時不拆成三個）

- 第一版 duckd 是**一個程序**：WebSocket（asyncio）、50 Hz 控制迴圈、眼睛渲染各一個執行緒。ADR-0009 §2.3 拆程序的理由是保護 50 Hz 步態迴圈的時間預算；頭部直控的一圈只有 4 顆舵機的讀寫，預算寬鬆得多，先用一個程序把功能做完。
- 控制迴圈不依賴連線執行緒：連線卡住或斷掉，迴圈照跑，租約到期就停。
- **步態 host 接進來時要照 ADR-0009 拆開**：步態主迴圈自己一個程序（仲裁器在裡面），duckd 經本機通道（UNIX datagram，latest-wins）送意圖。這個通道還沒做。
- 已知的代價：眼睛渲染和控制迴圈搶 GIL。實測的迴圈超時次數寫在驗證紀錄；上實體螢幕（要 30 fps）之前，眼睛渲染要移到獨立程序。

### 2.4 `ttl_ms` 的解讀

schema 寫「動作指令在 `ttl_ms` 到期且沒有續期時停止」，ADR-0009 §2.2 只對 `walk` 寫了三重期限。duckd 的做法：

| 指令 | `ttl_ms` 的作用 |
|---|---|
| 全部 | 收到後超過 `ttl_ms` 才開始處理 → 拒絕（`expired`） |
| `walk` | 到期就停（和 `duration_s`、租約取最早的） |
| `look` | 到期時頭停在目前位置（還沒到目標也停） |
| `gesture` | 只管能不能開始；開始後由鴨子自己計時到結束（長度上限 10 s，載入時檢查），`stop`、租約失效、緊急停止可以中斷 |
| `presence`、`track`、`express` | 只管能不能開始；之後跟著租約（斷線就回到 `idle`、停止追蹤） |

### 2.5 誰可以蓋過誰（頭部）

釋放中 ＞ 動作（gesture）＞ 追蹤（track）＞ `presence` 的頭部編排。明確的 `look` 會中斷進行中的動作與追蹤，並暫停 `presence` 的頭部編排，直到 `presence` 的**狀態改變**（同一狀態的 `speech_level` 更新不算）。動作進行中再收到另一個動作：拒絕（ADR-0015 §2.4 第 4 點）。

### 2.6 本機控制介面

接手／釋放硬體、緊急停止、解除緊急停止**不在 duck-link 上**（ADR-0001 §4），放在只有同一個使用者能連的 UNIX socket（`duckd-ctl`）。服務啟動時不碰硬體；要有人（或部署腳本）在 Pi 上明確 `engage`。這也是和舵機控制台互斥的方式：誰先開匯流排誰用，另一個接手前檢查到就拒絕，不搶。

### 2.7 待機時不自己做小動作

總體設計 §4 的表寫 `idle` 時「偶爾小幅看別處」。這是 ADR-0015 §5 第 10 點的待決事項，第一版**不做**：`idle` 只回正。要不要做、多常做，由使用者決定。

## 3. 理由

- 使用者現在就要看到「說話時頭會動」；等步態能跑再做，會卡在足底開關與 IMU。
- 重用舵機控制台已經在實機跑過的核心，比另寫一套匯流排程式風險低；白名單讓「不碰腿」是程式結構保證的，不是靠呼叫端自律。
- 仲裁器做成與後端無關，之後換成步態 host 不用重寫安全規則。

## 4. 後果

- ADR-0015 的動作庫在頭部直控模式下也能播；定義檔的 `allowed_modes: ["standing"]` 目前被當成「頭部可動」。動作的實機驗證要註明是在哪個模式（`hardware_profile`，目前是 `stock_head_direct_hold`）做的；**站著（步態策略在跑）時動頭會不會影響平衡，這個模式沒有驗證到**。
- 協定的缺口另寫提案（[`protocol/proposals/a-duckd-gaps.md`](../../protocol/proposals/a-duckd-gaps.md)）：`busy` 原因代碼、`mode` 沒有「未接手」、`gesture_interrupted`。
- `robot/nous_link/`、`robot/safety/`、`robot/config/` 的內容實際放在 `robot/duckd/`（對應表在 duckd 的 README）。

## 5. 待決

1. 頭部直控與步態 host 的切換流程（誰釋放匯流排、頭部目標怎麼交接）。
2. duckd ↔ 步態 host 的本機通道。
3. 頭部直控時腿的狀態要不要由 duckd 管（例如開機後由 duckd 擺站姿），或維持現在「不管腿」。
4. 頭部角速度上限 30°/s、視窗 ±15° 是無人看顧時的保守值；使用者看過實機後決定平常用多少。
5. `idle` 要不要自己做小動作（§2.7）。

## 補充（2026-11-28）：對話時讓頭出力、聽聲轉頭只在對話中

背景：使用者說對話時的頭部互動「好像沒有體驗到」。整合線唯讀查到 duckd 常駐後一直是 `engaged: false`：頭部的程式都在，但**從來沒有人接手頭部**。原本的設計是只有本機 `duckd-ctl engage` 才接手（§2.6），而無人看顧時不准出力。驗證層級：單元測試＋mock（[紀錄](../validation/duckd-head-auto-engage-2026-11-28.md)），**實機沒有驗證**。

### §A 對話時讓頭出力（`features.head_auto_engage`，預設關）

- **開關**：鴨子設定頁「對話時讓頭出力」，**預設關**。關著時跟以前完全一樣：duckd 不會自己打開匯流排（單元測試 `test_default_off_never_opens_the_bus`：送完一整輪 presence，匯流排打開次數為 0）。
- **什麼時候接手**：開著時，presence 進入對話狀態（`wake`／`listening`／`thinking`／`speaking`）就接手。最早是鴨子本機聽到喚醒詞的那一刻：duckd 轉送 `wake_word` 時本機先設 `wake`。**不是一直接著**，原因有三：
  1. 舵機控制台要用匯流排時不用先關開關。
  2. 無人看顧的時間不出力。
  3. 頭部舵機不會整天出力發熱。
- **什麼時候放開**：對話結束（presence 回到 `idle`／`sleeping`／`error`）`AUTO_RELEASE_IDLE_S`＝120 秒後放開。等 2 分鐘是因為常常講完又馬上接著講，每次重新接手都要開匯流排、會慢一點。放開走的是原本的 `release`：頭先以限速回到**接手時的位置**，再把頭部 4 顆的扭力恢復成**接手前的狀態**。
  - 原本有出力，就還是出力，頭不會垂下。
  - 原本沒出力，就回到原本垂著的姿勢再關扭力。不會比接手前更低，所以不會垂下撞到東西。
- **接手前檢查**：
  - 緊急停止、跌倒時不接手。
  - 匯流排被別的程式占著（舵機控制台、上游腳本）時，`engage` 本來就會拒絕。
  - 接手後如果身體後端回報 block（低電壓 6.6 V、過熱 55°C、讀取失敗），就放開。
  - 以上任何一種，都過 `AUTO_RETRY_S`＝30 秒才再試，原因寫進 `duckd-ctl status` 的 `auto_engage` 與設定頁。
- **只碰頭部**：自動接手就是呼叫原本的 `engage()`。`--legs` 模式下，`engage` 也只接手頭部、不碰腿（ADR-0020），腿的規則不變。腿接手中（`--legs` 試跑）不自動放開，那時一定有人在旁邊。
- **本機 `engage` 的不自動放開**：有人手動接手時，`auto_engage.state` 是 `manual`，duckd 不會在 2 分鐘後放開它。
- **開關被關掉**：自動接手的頭立刻開始放開。

### §B 聽聲轉頭只在對話中

2026-11-26 實機發現電視開著時頭會被帶走，`duck-doa` 的門檻 2e5 也沒驗證過，所以 `duck-doa` 維持 `inactive`／`disabled`，這次沒有啟動它。duckd 這一端改成：Nous 要求的 `track sound` 只有在 presence 是對話狀態時才轉頭，對話外頭停在原地（追蹤還在，`tracking_paused: true`），回到對話才繼續。喚醒時轉向聲源（`face_yaw`）本來就只在對話中。實機驗證要等使用者在場。

### §C 誠實顯示

設定頁的「已生效」原本只表示「duckd 讀到了這個值」。現在 duckd 會一起回報「讀到了但現在不會動」的項目與原因（`inactive`），設定頁對這些項目顯示「已讀到，但現在不會動：……」：

- 頭部沒有出力：「對話時讓頭出力」關著，或自動接手失敗，影響頭部小動作、說話點頭、具名動作、聽聲轉頭。
- 沒收到說話音量（`speech_level`）：影響說話點頭。
- 沒有聲音來源（`duck-doa` 沒在跑）：影響聽聲轉頭。

### §D 還要別人補的

- **說話點頭要有 `speech_level`**：duckd 從開機到現在沒收到過（`speech_level_seen` 計數）。路線 2 的音量在 Pi 的 Chromium 頁面裡（`nous_adapter/terminal/presence.ts` 寫的來源是頁面的 `browserWatchLevel`）。要 B 線在 AIOS 的 presence（`speaking` 時）帶 `speech_level`：0～1、約 10 Hz、變化夠大才送。或者由 D 線在 `duck-voice` 從麥克風聽到的鴨子自己的聲音估計，再用 UDP 給 duckd（要新的感知訊息種類，協定要先提案）。建議前者，因為那是真的播出的聲音。
- **Nous 實際送了哪些 presence**：duckd 的 `duckd-ctl status` 加了 `commands_by_action`、`presence_log`，下一次真的對話後就看得到。
