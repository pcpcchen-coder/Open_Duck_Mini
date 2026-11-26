# 架構決策紀錄（ADR）

重要的架構決定都寫成 ADR，編號遞增，不重用。狀態：草案（Proposed）→ 採用（Accepted）→ 被取代（Superseded by ADR-xxxx）。

| 編號 | 標題 | 狀態 | 日期 |
|---|---|---|---|
| [ADR-0001](ADR-0001-duck-role-in-nous.md) | 鴨子在 Nous 中的角色＝身體 adapter 加終端（§7 依 R-001 修訂） | 草案 | 2026-11-12 |
| [ADR-0002](ADR-0002-indoor-localization-and-navigation.md) | 室內定位與導航（AprilTag＋視覺慣性里程計，不用步數；沒開燈時紅外線補光） | 草案 | 2026-11-12 |
| [ADR-0003](ADR-0003-mobile-terminal-wake-and-find.md) | 行動終端、喚醒詞與找人（喚醒詞預設「Hey 鴨子」、可以改） | 部分採用 | 2026-11-12 |
| [ADR-0004](ADR-0004-docking-and-charging.md) | 充電座與自動回充（背後觸點） | 部分採用 | 2026-11-12 |
| [ADR-0005](ADR-0005-compute-and-sensor-upgrade.md) | 運算與感測硬體升級（AR0144 裝頭上、Flex 麥克風裝身體上；雙板部分被 ADR-0008 取代） | 部分採用 | 2026-11-12 |
| [ADR-0006](ADR-0006-privacy-settings.md) | 可開關的隱私設定（預設值已同意） | 部分採用 | 2026-11-12 |
| [ADR-0007](ADR-0007-follow-me-and-wait-here.md) | 跟著我來與在這等我（跟隨任務、本機停止句、原地等待） | 草案 | 2026-11-19 |
| [ADR-0008](ADR-0008-single-board-pi4.md) | 單板 Pi 4，取代 Pi Zero 2 W（Pi 4 裝機身、Python 3.11 跑上游 runtime、5 V 電源要重選；試用期，達不到門檻拆回雙板） | 採用（試用期） | 2026-11-22 |

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
