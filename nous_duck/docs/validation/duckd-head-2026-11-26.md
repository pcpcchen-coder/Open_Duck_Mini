# 桌上互動：實機頭部、聽聲辨位（2026-11-26）

- 分支：`claude/duck-a-body-8fca8a`；對象：[`robot/duckd/`](../../robot/duckd/README.md)（T1、T5）、[`robot/audio/duck_audio/doa.py`](../../robot/audio/README.md#聲源方向doat4)（T4）
- **驗證層級**：單元測試（Mac、Pi）；Mac↔Pi 真實 SSH 通道，用 **B 線的正式 hub 與 `duckctl`**，對 Pi 上的 duckd（**模擬身體、模擬 DOA，都是 mock**）。
- **實機頭部沒有做、真的麥克風沒有接過。** 原因在 §1。
- 同一天傍晚的實機紀錄在 [`duckd-head-hardware-2026-11-26.md`](duckd-head-hardware-2026-11-26.md)。

## 1. Pi 與硬體現況（唯讀檢查）

| 時間 | 檢查 | 結果 |
|---|---|---|
| 06:51 | 舵機控制台 `/api/state` | 已連線；14 顆扭力都關；事件紀錄顯示 81 秒前才有人「儲存姿勢：坐下」、46 秒前 ID 13 掉到 6.3 V、20 秒前匯流排連續逾時。**有人剛操作過，所以沒有釋放** |
| 11:42 | 同上 | 最後一次操作是 4.9 小時前；14 顆扭力都關；匯流排逾時警報還在（頁面上的 7.6 V 是逾時前的舊值） |
| 11:42 | `POST /api/release` | 成功：控制台變成未連線，「扭力狀態不變（0 顆出力中）」。服務沒有停用、沒有移除 |
| 11:42 | `servo_scan_readonly.py`（ID 0–60） | **沒有任何舵機回應**。驅動板的 USB 序列埠（`1a86:55d3`）在，舵機那一側沒有電 |
| 11:46 | 再 ping 14 顆 | 仍然沒有回應 |
| 11:42、11:46 | `lsusb` | 沒有 VID `2886`：XVF3800 還沒接上 |
| 11:42 | Pi | load 0.35；`get_throttled=0x0` |

所以 T1（實機頭部）卡在**舵機電源**，T4 的實機部分卡在**麥克風還沒接**。

## 2. 單元測試

| 範圍 | 結果 |
|---|---|
| `robot/duckd/tests`（Mac，Python 3.12） | 121 通過、3 略過 |
| `robot/duckd/tests`（Pi，Python 3.11，不含連線與上游載入測試） | 114 通過、2 略過 |
| `robot/audio/tests/test_doa.py`（Mac） | 20 通過 |

新增的測試都用合成方位或模擬裝置（mock）：聽聲轉頭的死區、平滑、頭在動時丟掉方位、8 s 回正、轉到極限、來源不見；麥克風裝在頭上時的換算；DOA 的解碼、USB 請求參數、環狀分群、正前方校準、只在有語音時送、裝置不在時照實回報。

## 3. 端到端：B 線 hub ↔ SSH 通道 ↔ Pi 上的 duckd（模擬身體，mock）

Mac：`nous_adapter` 的 `bin/duckctl hub`（埠 8791）＋反向通道；Pi：`python -m duckd --body mock --engage`，另開 `python -m duck_audio.doa --run --mock-angle 25`（模擬的 DOA，固定 25°、一直有語音）。當時 Pi load 約 1.1。

| `duckctl` 指令 | 結果 |
|---|---|
| `link` | 已連線，對面標示「模擬」；`health: available` |
| `look --yaw 10 --deg` | `confirmed`；`applied.head_yaw` 0.1745，回讀 0.1745 |
| `gesture nod` | `confirmed`（已開始）；`applied.duration_s` 2.8 |
| `presence listening` | `confirmed`；回讀 `presence: listening`、`expression: listening` |
| `track sound` | `confirmed`；`applied` 是 `{"target":"sound","body":false}` |
| （`track sound` 之後） | 事件 `tracking_acquired`：`bearing_rad` 0.436、`head_yaw_rad` 0.436、`at_limit` false、`mock` true——模擬的頭轉到 25° |

duckd 端：迴圈 50.0 Hz、一圈最長 20.7 ms、約 45 秒內超時 7 次；指令接受到送出第一個新設定值 14.0、15.9 ms。hub 量到的往返時間 18–83 ms（單次讀值，不是統計）。

`duckd` 服務、`duck-doa` 服務、udev 規則都已部署到 Pi；兩個服務都是 disabled、沒有在跑。`head_check.sh` 的前置檢查在 Pi 上跑過失敗路徑：偵測到頭部舵機沒回應就停，沒有開匯流排，收尾後服務停止、沒有留下 drop-in。

## 4. 沒有驗證的

- **實機頭部全部**：`look`、四個動作、`presence`、租約、延遲、回讀誤差、CPU 與記憶體。動作庫的 `verification` 因此仍是 `none`；頭部視窗維持 ±15°、30°/s，沒有放寬。
- `head_check.sh` 第 2 步以後（接手、量測、釋放）沒有在實機跑過。
- XVF3800：USB PID、韌體版本、vendor control 在 Pi（Linux）上能不能讀、不 claim 介面會不會影響 UAC、角度增加的方向、正前方偏移、不同方向說話時的讀值、舵機噪音對 DOA 的影響。
- 麥克風裝在頭上（`mount: head`）的換算只有單元測試。
- 聽聲轉頭的數值（死區 8°、0.8 s 兩筆、停下後 0.5 s 不聽、8 s 回正）都是沒有實測依據的初始值。
