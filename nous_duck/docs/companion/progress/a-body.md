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

## 需要你處理

- **實機頭部測試還沒做**：舵機控制台整晚連著匯流排。控制台按「釋放硬體」後：`sudo systemctl start duckd`、`~/duck/duckd/duckd-ctl engage`，Mac 開通道與 `python -m duckd.mock_hub --e2e`（服務預設 ±15°、30°/s）。
- 14 顆舵機整晚出力，電壓掉到 7.6 V，出現過 6.5 V 警告。
- 動作都還是 `verification: none`，要加 `--allow-unverified-gestures` 才列給 Nous。
- 要你決定：`idle` 要不要自己做小動作；頭部速度上限與視窗；`presence` 各狀態的幅度。
- 協定缺口：[`protocol/proposals/a-duckd-gaps.md`](../../../protocol/proposals/a-duckd-gaps.md)。
- Pi 上留下：`~/duck/duckd/`、`~/duck/duckd-venv/`、服務 `duckd`（disabled、已停止）。`duck-console` 沒動過。
