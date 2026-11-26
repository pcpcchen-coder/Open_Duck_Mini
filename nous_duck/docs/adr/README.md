# 架構決策紀錄（ADR）

重要的架構決定都寫成 ADR，編號遞增，不重用。狀態：草案（Proposed）→ 採用（Accepted）→ 被取代（Superseded by ADR-xxxx）。

| 編號 | 標題 | 狀態 | 日期 |
|---|---|---|---|
| [ADR-0001](ADR-0001-duck-role-in-nous.md) | 鴨子在 Nous 中的角色＝身體 adapter 加終端（§7 依 R-001 修訂） | 草案 | 2026-11-12 |
| [ADR-0002](ADR-0002-indoor-localization-and-navigation.md) | 室內定位與導航（AprilTag＋視覺慣性里程計，不用步數；沒開燈時紅外線補光） | 草案 | 2026-11-12 |
| [ADR-0003](ADR-0003-mobile-terminal-wake-and-find.md) | 行動終端、喚醒詞與找人 | 草案 | 2026-11-12 |
| [ADR-0004](ADR-0004-docking-and-charging.md) | 充電座與自動回充（背後觸點） | 部分採用 | 2026-11-12 |
| [ADR-0005](ADR-0005-compute-and-sensor-upgrade.md) | 運算與感測硬體升級（AR0144 裝頭上、標準版 XVF3800 麥克風裝頭上、1.28 吋眼睛螢幕；雙板部分被 ADR-0008 取代） | 部分採用 | 2026-11-12 |
| [ADR-0006](ADR-0006-privacy-settings.md) | 可開關的隱私設定（預設值已同意；鏡頭提示改用眼睛螢幕，2026-11-17） | 部分採用 | 2026-11-12 |
| [ADR-0007](ADR-0007-follow-me-and-wait-here.md) | 跟著我來與在這等我（跟隨任務、本機停止句、原地等待） | 草案 | 2026-11-19 |
| [ADR-0008](ADR-0008-single-board-pi4.md) | 單板 Pi 4，取代 Pi Zero 2 W（Pi 4 裝機身、Python 3.11 跑上游 runtime、5 V 電源要重選；試用期，達不到門檻拆回雙板） | 採用（試用期） | 2026-11-22 |
| [ADR-0009](ADR-0009-duck-link-transport-and-command-bridge.md) | duck-link 傳輸（SSH 通道＋WebSocket）與鴨子端指令橋接（緊急停止、暫停時讀電壓） | 部分採用 | 2026-11-13 |
| [ADR-0010](ADR-0010-duck-voice.md) | 鴨子的語音（Nous 的聲音加變聲、本機音效、回音消除、喇叭） | 部分採用 | 2026-11-15（2026-11-26 依 ADR-0008 與標準版 XVF3800 修訂） |
| [ADR-0011](ADR-0011-duck-memory.md) | 鴨子的記憶系統（沿用 Nous 記憶層，不另做 Hermes 式記憶；鴨子只補身體、空間、任務記憶；可以在鴨子旁邊說「記住」） | 採用 | 2026-11-26 |
| [ADR-0012](ADR-0012-low-battery-return-interaction.md) | 低電量時的回家互動與「直接回家」的條件（L0～L4 電量等級；L1、L2 由 Nous 商量，L3 起鴨子本機直接回家） | 草案 | 2026-11-26 |

編號說明：本序列只屬於本 repo 的 `nous_duck/docs/adr/`，與 AIOS repo 的 `docs/adr/`（ADR-0001 本機家人辨識等）是不同的序列。

## 範本

```markdown
# ADR-NNNN：標題

- 狀態：草案（Proposed）
- 日期：YYYY-MM-DD
- 相關：

## 1. 背景
## 2. 決定
## 3. 理由
## 4. 後果
## 5. 待決
```
