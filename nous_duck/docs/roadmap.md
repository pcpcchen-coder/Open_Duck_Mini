# 路線圖

狀態：**草案**（2026-11-12）。每個階段要通過 gate 才算完成；gate 要有驗證紀錄（`docs/validation/`）並標明驗證層級。順序依相依關係排列，可以視需要調整。

| 階段 | 內容 | 主要模組 | Gate（通過條件，草案） |
|---|---|---|---|
| P0 | 離線 3D 組裝檢視器 | `assembly_viewer/` | Playwright 截圖驗證三種模式、14 顆舵機 ID 正確、單一 HTML 離線可開 |
| P1 | 原版組裝完成；上游步態在實機能走；手把控制；本機安全（跌倒、低電壓） | `robot/`、`hardware/` | 實機平地行走與停止；跌倒時停止並記錄 |
| P2 | 硬體升級決策與上機：感知板、雙目鏡頭、麥克風陣列、喇叭（[ADR-0005](adr/ADR-0005-compute-and-sensor-upgrade.md)）；更新模擬質量、必要時重新訓練步態 | `hardware/`、`sim/` | 加裝後實機行走穩定；步態迴圈抖動在可接受範圍（數字待定） |
| P3 | duck-link 協定與 DuckAdapter 基本工具（status、walk、stop、look）；鴨子當行動終端可對話（[ADR-0003](adr/ADR-0003-mobile-terminal-wake-and-find.md) §2） | `protocol/`、`robot/nous_link/`、`nous_adapter/` | mock 測試通過；實機上 Nous 能讓鴨子動並回讀確認；在鴨子旁邊能對話 |
| P4 | 帶看建圖、AprilTag 定位、`go_to` 房間（單一樓層）（[ADR-0002](adr/ADR-0002-indoor-localization-and-navigation.md)） | `robot/navigation/`、`robot/perception/`、`sim/` | 從客廳到指定房間連續 N 次成功（N 待定）；迷路、門關、禁區處理正確；樓梯口不靠近 |
| P5 | 充電座與自動回充（[ADR-0004](adr/ADR-0004-docking-and-charging.md)） | `hardware/dock/`、`robot/navigation/` | 從家中任一點回充、電氣確認充電，連續 N 次成功 |
| P6 | 鴨子喚醒詞與找人（[ADR-0003](adr/ADR-0003-mobile-terminal-wake-and-find.md) §3–4） | `robot/audio/`、`robot/perception/`、`nous_adapter/` | 同房間與隔壁房間的喚醒找人成功率（目標待定）；找不到時誠實回報 |
| P7 | 情境任務：叫人起床、排程 | `nous_adapter/`、AIOS | R-001 S1 情境實機通過 |
| P8 | 視覺地圖重定位，減少 AprilTag | `robot/navigation/` | 標籤數量減少後 P4 的 gate 仍通過 |

## 需要使用者先決定的事

| 事項 | 影響階段 | 文件 |
|---|---|---|
| 雙板或單板運算、感知板型號 | P2 起全部 | ADR-0005 §4 |
| 雙目鏡頭型號、裝頭上或身上 | P2、P4、P6 | ADR-0005 §4 |
| 麥克風陣列型號 | P3、P6 | ADR-0005 §4 |
| 充電觸點方案（影響 `body_back`、`battery_pack_lid`、`body_middle_bottom` 是否要改） | P2、P5 | ADR-0004 §6 |
| 是否接受在家裡貼 AprilTag | P4 | ADR-0002 §8 |
| 鴨子的喚醒詞 | P6 | ADR-0003 §8 |
| 臥室隱私規則 | P4、P6、P7 | ADR-0003 §6 |

## AIOS 端需要的批次（在 AIOS repo 進行）

這些不在本 repo 完成，也不在本 repo 宣稱已完成：

1. 加入 `duck` adapter 到已審核清單（P3）。
2. 長時間任務：工具回傳任務 ID，完成與進度以事件回到 Nous，Agent 能接續（P4）。
3. 把即時語音工作階段指定到某一台終端（P3、P7）。
4. 多裝置喚醒仲裁（P6）。
5. 無螢幕或非瀏覽器終端（若 ADR-0003 走路線 B）。
