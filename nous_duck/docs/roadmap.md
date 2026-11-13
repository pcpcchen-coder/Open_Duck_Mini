# 路線圖

狀態：**草案**（2026-11-12）。每個階段要通過 gate 才算完成；gate 要有驗證紀錄（`docs/validation/`）並標明驗證層級。順序依相依關係排列，可以視需要調整。

| 階段 | 內容 | 主要模組 | Gate（通過條件，草案） |
|---|---|---|---|
| P0 | 離線 3D 組裝檢視器 | `assembly_viewer/` | Playwright 截圖驗證三種模式、14 顆舵機 ID 正確、單一 HTML 離線可開 |
| P1 | 原版組裝完成；上游步態在實機能走；手把控制；本機安全（跌倒、低電壓） | `robot/`、`hardware/` | 實機平地行走與停止；跌倒時停止並記錄 |
| P2 | 硬體升級決策與上機：感知板、雙目鏡頭（含紅外線補光燈）、麥克風陣列、喇叭（[ADR-0005](adr/ADR-0005-compute-and-sensor-upgrade.md)）；更新模擬質量、必要時重新訓練步態 | `hardware/`、`sim/` | 加裝後實機行走穩定；步態迴圈抖動在可接受範圍（數字待定） |
| P3 | duck-link 協定與 DuckAdapter 基本工具（status、walk、stop、look）；鴨子當行動終端可對話（[ADR-0003](adr/ADR-0003-mobile-terminal-wake-and-find.md) §2） | `protocol/`、`robot/nous_link/`、`nous_adapter/` | mock 測試通過；實機上 Nous 能讓鴨子動並回讀確認；在鴨子旁邊能對話 |
| P4 | 帶看建圖、AprilTag 定位、`go_to` 房間（單一樓層）（[ADR-0002](adr/ADR-0002-indoor-localization-and-navigation.md)）；沒開燈時紅外線補光（ADR-0002 §4.1） | `robot/navigation/`、`robot/perception/`、`sim/` | 從客廳到指定房間連續 N 次成功（N 待定）；迷路、門關、禁區處理正確；樓梯口不靠近；關燈時紅外線補光下能讀標籤，太暗時停下回報、不摸黑前進 |
| P5 | 充電座與自動回充（[ADR-0004](adr/ADR-0004-docking-and-charging.md)） | `hardware/dock/`、`robot/navigation/` | 從家中任一點回充、電氣確認充電，連續 N 次成功 |
| P6 | 鴨子喚醒詞與找人（[ADR-0003](adr/ADR-0003-mobile-terminal-wake-and-find.md) §3–4） | `robot/audio/`、`robot/perception/`、`nous_adapter/` | 同房間與隔壁房間的喚醒找人成功率（目標待定）；找不到時誠實回報 |
| P7 | 情境任務：叫人起床、排程 | `nous_adapter/`、AIOS | R-001 S1 情境實機通過 |
| P8 | 視覺地圖重定位，減少 AprilTag | `robot/navigation/` | 標籤數量減少後 P4 的 gate 仍通過 |

## 需要使用者先決定的事

| 事項 | 狀態 | 文件 |
|---|---|---|
| ~~雙板或單板運算、感知板型號~~ | 已決定（2026-11-12）：雙板，Pi Zero 2 W＋Pi 4 | ADR-0005 |
| ~~雙目鏡頭型號與位置~~ | 已決定：AR0144，裝在頭上（`head` 要重新設計） | ADR-0005 §2.3 |
| ~~麥克風陣列型號與位置~~ | 已決定：reSpeaker XVF3800 USB 4-Mic Array 標準版（與 FamilyRecorder 同款），裝在身體上；方向讀取沿用 FamilyRecorder 的作法 | [選型](../hardware/sensors/mic_array_selection.md) |
| ~~充電觸點方案~~ | 已決定：背後（`body_back` 要改、暫緩列印） | ADR-0004 |
| ~~是否接受在家裡貼 AprilTag~~ | 已同意 | ADR-0002 |
| ~~沒開燈時的定位備案~~ | 已決定（2026-11-13）：頭上紅外線補光燈為主，AR0144 判斷照度低於門檻就自動開。待確認：要支援的摸黑情況、AR0144 有無 IR-cut 濾片、是否加 ToF 落差感測器與藍牙房間輔助、夜間臥室是否允許紅外線 | [ADR-0002 §4.1](adr/ADR-0002-indoor-localization-and-navigation.md#41-沒開燈時的備案紅外線補光2026-11-13-使用者同意以此為主)、ADR-0006 §5 |
| ~~充電座外型~~ | 已決定（2026-11-13）：設計 v0「屋形靠背扶手椅」（外掛觸點板，不用重印 `body_back`） | [ADR-0004 §7](adr/ADR-0004-docking-and-charging.md#7-設計-v02026-11-13)、[`hardware/dock/`](../hardware/dock/README.md) |
| 鴨子的喚醒詞 | 使用者表示晚一點再取 | ADR-0003 §8 |
| ~~隱私設定的預設值~~ | 已同意建議預設值 | [ADR-0006](adr/ADR-0006-privacy-settings.md) §5 |
| ~~是否加實體隱私開關、鏡頭提示方式~~ | 已決定：加實體開關；眼燈顏色（眼燈改 RGB）。待確認：是否另加硬體直連的鏡頭電源指示燈 | ADR-0006 §4 |

## AIOS 端需要的批次（在 AIOS repo 進行）

這些不在本 repo 完成，也不在本 repo 宣稱已完成：

1. 加入 `duck` adapter 到已審核清單（P3）。
2. 長時間任務：工具回傳任務 ID，完成與進度以事件回到 Nous，Agent 能接續（P4）。
3. 把即時語音工作階段指定到某一台終端（P3、P7）。
4. 多裝置喚醒仲裁（P6）。
5. 無螢幕或非瀏覽器終端（若 ADR-0003 走路線 B）。
6. 隱私設定頁（雙語）與設定同步（ADR-0006）。
