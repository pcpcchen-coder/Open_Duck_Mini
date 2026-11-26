# A 線（身體）進度

分支：`claude/duck-a-body-8fca8a`（只有本機提交）。程式：[`robot/duckd/`](../../../robot/duckd/README.md)。驗證：[duckd-2026-11-25](../../validation/duckd-2026-11-25.md)。設計：[ADR-0014](../../adr/ADR-0014-duckd-head-direct-and-single-process.md)。最後更新：2026-11-26 11:50。

| Step | 狀態 | 驗證層級 |
|---|---|---|
| A1 核心 | 完成 | 單元測試（Mac、Pi）；Mac↔Pi 真實通道端到端（模擬身體） |
| A2 安全仲裁 | 完成 | 單元測試；租約在真實通道上測過（模擬身體） |
| A3 頭部實機後端 | 程式完成，**實機沒測** | 單元測試（模擬匯流排，含「不寫腿」）；Pi 上只驗了「啟動不碰硬體」與「控制台占用時拒絕接手」 |
| A4 動作庫 | 程式完成，實機沒測 | 單元測試；真實通道（模擬身體）播過 `nod` |
| A5 presence 編排 | 程式完成，實機沒測 | 單元測試；真實通道（模擬身體） |
| A6 眼睛 | 完成（虛擬面板）；SPI 驅動卡硬體 | 單元測試；Pi 上出圖並量渲染時間（兩眼約 124 ms） |
| A7 步態 host | 載入測試完成；實機走路**等你** | Pi 上對鎖定 commit 的真上游腳本，假硬體 |
| A8 Pi 部署 | 完成 | 實機（Pi）：部署、服務啟動／停止、互斥檢查 |

怎麼執行、安全規則、還沒做的：看 duckd 的 README。測試：Mac 107 通過、3 略過。

## 桌上互動（2026-11-26）

驗證：[duckd-head-2026-11-26](../../validation/duckd-head-2026-11-26.md)。

| Step | 狀態 | 驗證層級 |
|---|---|---|
| T1 實機頭部 | **等你**：舵機沒有電（11:42、11:46 掃描 14 顆都不回應）。程式、部署、檢查腳本都備好 | 沒有實機。B 線正式 hub＋`duckctl` 經真實通道對 Pi 上的 duckd（模擬身體）：`look`、`gesture`、`presence` 都 `confirmed` |
| T4 XVF3800 DOA | 程式、部署腳本完成；實機**等你**（麥克風還沒接上 Pi） | 單元測試（模擬裝置，20 項）；Pi 上模擬角度 → duckd |
| T5 聽聲辨位轉頭 | 程式完成；實機等 T1、T4 | 單元測試；真實通道上 `duckctl track sound` 讓模擬的頭轉到模擬聲源的 25° |

做了什麼：

- duckd：`track sound`（死區 8°、0.8 s 內兩筆一致才採用、頭在動與停下 0.5 s 內不聽、8 s 沒聲音回正、超出範圍轉到極限並在事件註明、坐著不轉身）；感知來源的存活訊息；`capabilities.tracking_sound` 依來源實際狀態回報。
- `robot/audio/duck_audio/doa.py`：USB 控制介面讀 XVF3800 的角度與語音旗標（沿用 FamilyRecorder 的讀法，MIT），環狀分群、正前方校準，只在有語音時送方位；不占用音訊串流。
- 麥克風位置做成設定 `mount: head｜body｜desk`（原本預設 `desk`；2026-11-26 使用者決定麥克風放頭頂，設定檔改為 `head`）。`head` 時 duckd 會把頭部 yaw 加回去（ADR-0003 §4.1 的簡化式）。
- Pi 上：`duckd`、`duck-doa` 兩個服務與 udev 規則已部署，**都沒有 enable、沒有在跑**。舵機控制台 11:42 已釋放序列埠（服務照舊在跑、未連線）。
- 沒有出聲。動作庫的 `verification` 沒有改（沒有實機跑過）。頭部視窗沒有放寬。

### 要你親手做的

1. **舵機電源**：充電、接上，讓 14 顆有電。腿保持放鬆、鴨子坐穩。
2. 跑頭部檢查（約 2 分鐘，頭會在 ±12° 內慢慢動；任何一項前置檢查不過就不會碰匯流排）：

   ```bash
   bash nous_duck/robot/duckd/tools/head_check.sh
   ```

   想測完讓 duckd 留著給 Nous 用（正式埠 8791、頭部接手）：前面加 `KEEP=1`。停止：`ssh duck-pi4 'sudo systemctl stop duckd'`。這個腳本接手之後的步驟**還沒在實機跑過**。
3. **麥克風**：XVF3800 接上 Pi 的 USB。確認、校準、啟動的指令在 [`robot/audio` 的 README](../../../robot/audio/README.md#聲源方向doat4)。校準時站在鴨子正前方約 1 m 說話 5 秒；之後到左邊說話，看方位是不是正的。
4. 告訴我麥克風放哪（頭上／身上／桌上），改 `~/duck/doa/config/doa.json` 的 `mount`。

## 實機頭部與聽聲轉頭（2026-11-26 傍晚，分支 `claude/duck-head-hw-test`）

紀錄：[`docs/validation/duckd-head-hardware-2026-11-26.md`](../../validation/duckd-head-hardware-2026-11-26.md)。驗證層級：**實機**；哪些有人眼確認、哪些只有回讀，看紀錄 §8。

- T1：duckd 接手頭頸 4 顆（腿沒寫），`head_check.sh` 全程跑完；再用 B 線正式 hub＋`duckctl` 跑 `look` 與四個動作，都完成、沒被夾。三軸方向和預期一致（人眼確認），設定沒改。四個動作的 `verification` 改成 `real`（使用者確認「有動」，沒評論樣子）。
- T4：XVF3800（`2886:001a`、韌體 2.06）在 Pi 上讀得到；正前方原始角 176.9°（只留在 Pi）；角度是順時針為正，`counterclockwise` 改成 `false`。
- T5：第一次實測頭來回擺，原因是舵機聲被判成語音加上舊角度停留。改讀語音能量、停穩等待 1.0 s、上限用實際視窗後，電視關時通過（人眼確認）。
- 沒確認：有電視聲時頭會不會被帶走（回讀說門檻 5e4 時被帶走 4 次，使用者說沒有）；門檻 2e5 是離線重算的，沒有實機驗過。
- 給 B 線：duckd 重啟後 hub 把新事件當成重複丟掉（紀錄 §9）。
- 收尾：頭回正後放鬆，14 顆扭力全關；`duckd`、`duck-doa` 已停、沒有 enable；舵機控制台服務在跑、未連線。沒有出聲。

要你決定的：聽聲轉頭平時就開，還是只在喚醒／聆聽時才開（有背景人聲時只靠門檻不夠穩）。

## 喚醒事件轉給 Nous（2026-11-27 凌晨，分支 `claude/duckd-wake-relay`）

紀錄：[`docs/validation/duckd-wake-relay-2026-11-27.md`](../../validation/duckd-wake-relay-2026-11-27.md)。驗證層級：單元測試、對假 hub 的端到端、**Pi 實機不出力（手動觸發）**。

- duckd 收喚醒服務的 `wake_word`（UDP 8793）→ 送 duck-link 事件 `wake_word`；用最新的聲音方位補 `doa_deg`。連不上 Nous 時丟掉、不補送。
- presence 每次改變就送回喚醒服務（UDP 8794）、每 5 秒重送。Pi 上用真的喚醒服務（靜音、手動觸發）確認：對話中再觸發不會送出，回 `idle` 後恢復。
- 本機反應：先設 `presence: wake`（抬頭、有方位就轉向聲源），Nous 接手；8 秒沒人接手回 `idle`。**只在模擬身體上測過**。
- 沒做：真人喚醒、對真的 Nous、頭部出力、舵機聲會不會誤觸發喚醒詞（量法在紀錄 §5，要你在場）。
- 深夜無人看顧：沒有讓舵機出力、沒有出聲。
- 注意：舵機控制台現在是**連線**狀態，2026-11-26 20:50 因電池電壓 5.9 V 自動緊急停止，之後舵機沒有回應。動頭之前要先充電、在控制台按「釋放硬體」。

## 需要你處理

- **實機頭部測試還沒做**：舵機控制台整晚連著匯流排。控制台按「釋放硬體」後：`sudo systemctl start duckd`、`~/duck/duckd/duckd-ctl engage`，Mac 開通道與 `python -m duckd.mock_hub --e2e`（服務預設 ±15°、30°/s）。
- 14 顆舵機整晚出力，電壓掉到 7.6 V，出現過 6.5 V 警告。
- 四個動作 2026-11-26 傍晚已在實機跑過，`verification: real`，不用再加 `--allow-unverified-gestures`。
- 要你決定：`idle` 要不要自己做小動作；頭部速度上限與視窗；`presence` 各狀態的幅度。
- 協定缺口：[`protocol/proposals/a-duckd-gaps.md`](../../../protocol/proposals/a-duckd-gaps.md)。
- Pi 上留下：`~/duck/duckd/`、`~/duck/duckd-venv/`、服務 `duckd`（disabled、已停止）。`duck-console` 沒動過。
