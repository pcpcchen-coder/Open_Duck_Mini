# ③ 機上程式（robot）

狀態：**規劃中**（尚無程式）。目標平台：身體板 Raspberry Pi Zero 2 W；R-001 後另加感知板（型號待定，見 [ADR-0005](../docs/adr/ADR-0005-compute-and-sensor-upgrade.md)）。語言：Python。

## 職責

在鴨子上執行，負責步態、動作與安全；透過 duck-link 接收 Nous 的意圖、回報狀態與事件。即時控制迴圈留在本機。

## 子目錄

| 路徑 | 職責 | 狀態 |
|---|---|---|
| `nous_link/` | duck-link 端點：收發訊息、依 `../protocol/schemas` 驗證、心跳、ack | 規劃中 |
| `behaviors/` | 把意圖轉成上游 runtime 的 7 維指令向量；預錄動作（點頭、搖頭）、天線、表情 | 規劃中 |
| `safety/` | **最後一道關卡**：速度與角度上限、指令 TTL（deadman）、跌倒、過熱、低電壓、斷線處理、緊急停止 | 規劃中 |
| `config/` | 鴨子設定（對應上游 `example_config.json` 的 `expression_features`、`joints_offsets`）、safety 上限 | 規劃中 |
| `deploy/` | 安裝與部署：pip 從 git 安裝上游 runtime 並鎖 commit、systemd 服務 | 規劃中 |
| `navigation/` | （感知板）定位融合（VIO＋AprilTag，**不用步數**）、拓撲與柵格路徑規劃、避障、回充對位（[ADR-0002](../docs/adr/ADR-0002-indoor-localization-and-navigation.md)、[ADR-0004](../docs/adr/ADR-0004-docking-and-charging.md)） | 規劃中 |
| `perception/` | （感知板）雙目擷取、深度、AprilTag 偵測、人臉偵測與特徵（[ADR-0003](../docs/adr/ADR-0003-mobile-terminal-wake-and-find.md)） | 規劃中 |
| `audio/` | （感知板）喚醒詞（sherpa-onnx KWS）、聲源方向、語音串流、喇叭（ADR-0003） | 規劃中 |
| `tests/` | 單元測試（safety 規則、意圖轉換、schema 驗證）；不需要硬體的部分可在雲端跑 | 規劃中 |

`nous_link/`、`behaviors/`、`safety/` 在身體板執行；`navigation/`、`perception/`、`audio/` 在感知板執行。若 ADR-0005 改採單板，全部在同一片，但 safety 仍要與感知工作隔離。

## 輸入輸出

- 輸入：duck-link command（來自 Nous）、本機手把、IMU、足底開關、舵機回讀（電壓、溫度、位置）。
- 輸出：給上游 runtime 的指令；duck-link 的 ack、state、event。

## 依賴

- [apirrone/Open_Duck_Mini_Runtime](https://github.com/apirrone/Open_Duck_Mini_Runtime)（`v2`），以 `pip install git+https://github.com/apirrone/Open_Duck_Mini_Runtime@<commit>` 安裝並**鎖定 commit**，暫時不 fork。2026-11-12 查閱時 `v2` 的最新 commit 是 `376de65`，尚未決定要鎖哪一個。
- 上游 runtime 的指令來源是 `XBoxController.get_last_command()`（7 維：lin_vel_x、lin_vel_y、ang_vel、neck_pitch、head_pitch、head_yaw、head_roll）。規劃以相同介面的指令來源包裝接入，不改 runtime；做不到時先寫 ADR。

## 安全原則

- safety 判斷全部在本機，不依賴 Nous 或網路。
- Nous 不能關閉 safety、不能寫入舵機 ID／offset、不能關扭力或關機（見 ADR-0001 §4）。
- 斷線或 TTL 逾時：停止步態、站好，不自動恢復斷線前的動作。
- 任何上限與門檻數值都要有模擬或實機依據，寫進 `../docs/validation/`。

## 驗證

只在雲端通過單元測試的能力，不能宣稱實機可用；實機驗證紀錄放 `../docs/validation/`。
