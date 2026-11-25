# 架構決策紀錄（ADR）

重要的架構決定都寫成 ADR，編號遞增，不重用。狀態：草案（Proposed）→ 採用（Accepted）→ 被取代（Superseded by ADR-xxxx）。

| 編號 | 標題 | 狀態 | 日期 |
|---|---|---|---|
| [ADR-0001](ADR-0001-duck-role-in-nous.md) | 鴨子在 Nous 中的角色＝身體 adapter 加終端（§7 依 R-001 修訂） | 草案 | 2026-11-12 |
| [ADR-0002](ADR-0002-indoor-localization-and-navigation.md) | 室內定位與導航（AprilTag＋視覺慣性里程計，不用步數；沒開燈時紅外線補光） | 草案 | 2026-11-12 |
| [ADR-0003](ADR-0003-mobile-terminal-wake-and-find.md) | 行動終端、喚醒詞與找人 | 草案 | 2026-11-12 |
| [ADR-0004](ADR-0004-docking-and-charging.md) | 充電座與自動回充（背後觸點） | 部分採用 | 2026-11-12 |
| [ADR-0005](ADR-0005-compute-and-sensor-upgrade.md) | 運算與感測硬體升級（AR0144 裝頭上、Flex 麥克風裝身體上；雙板部分被 ADR-0008 取代） | 部分採用 | 2026-11-12 |
| [ADR-0006](ADR-0006-privacy-settings.md) | 可開關的隱私設定（預設值已同意；鏡頭預設由 ADR-0013 改為常開） | 部分採用 | 2026-11-12 |
| [ADR-0007](ADR-0007-follow-me-and-wait-here.md) | 跟著我來與在這等我（跟隨任務、本機停止句、原地等待） | 草案 | 2026-11-19 |
| [ADR-0008](ADR-0008-single-board-pi4.md) | 單板 Pi 4，取代 Pi Zero 2 W（Pi 4 裝機身、Python 3.11 跑上游 runtime、5 V 電源要重選；試用期，達不到門檻拆回雙板） | 採用（試用期） | 2026-11-22 |
| [ADR-0009](ADR-0009-duck-link-transport-and-command-bridge.md) | duck-link 傳輸（SSH 通道＋WebSocket）與鴨子端指令橋接（原 PR #9 的「ADR-0007」） | 草案 | 2026-11-13 |
| [ADR-0010](ADR-0010-duck-voice.md) | 鴨子的語音（Nous 的聲音加變聲、本機音效、回音消除、喇叭）（原 PR #14 的「ADR-0007」） | 部分採用 | 2026-11-15 |
| [ADR-0011](ADR-0011-gesture-library.md) | 動作庫：先用現有步態策略編排具名動作，動態動作另開訓練批次（原 PR #13 的「ADR-0008」） | 草案 | 2026-11-15 |
| [ADR-0012](ADR-0012-duck-memory.md) | 鴨子的記憶系統（沿用 Nous 記憶層；鴨子只補身體、空間、任務記憶）（原 PR #19 的「ADR-0007」） | 草案 | 2026-11-17 |
| [ADR-0013](ADR-0013-camera-always-on-and-home-monitoring.md) | 鏡頭常開（已決定）與家庭監控（提議）（原 PR #21 的「ADR-0007」） | 部分採用 | 2026-11-18 |
| [ADR-0014](ADR-0014-duckd-head-direct-and-single-process.md) | duckd 第一版：頭部直控、單一程序、本機控制介面 | 草案 | 2026-11-25 |
| [ADR-0016](ADR-0016-navigation-core-and-sim-findings.md) | 導航核心的作法，以及模擬對既有 ADR 的回饋（起步門檻、速度為 0 不踏步、走路時頭回正） | 草案 | 2026-11-25 |
| [ADR-0017](ADR-0017-audio-playback-path-v1.md) | 音訊播放路徑第一版：直接寫 ALSA，暫不裝 PipeWire | 草案 | 2026-11-25 |

ADR-0015 保留給 Nous 端（B 線），2026-11-25 沒有用到。

**2026-11-25 重新編號**：PR #9、#13、#14、#19、#21 各自在分支上用了 ADR-0007／0008，和已合併的 ADR-0007（跟著我來）、ADR-0008（單板 Pi 4）撞號。整合分支 `claude/duck-companion-overnight` 把它們改成 ADR-0009～0013（對照見上表）。連結已全部改到新檔名；內文裡沒有連結的「ADR-0007」字樣，若出自這五份文件或 PR #21 帶進來的眼睛文件，指的可能是舊編號，以連結為準。

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
