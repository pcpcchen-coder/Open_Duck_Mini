# 感知板 Pi 4 首次開機：實機檢查（2026-11-22）

- 分支：`claude/focused-dijkstra-ibeto1`（commit `c507a0a`）
- 對象：[`flash_sd_macos.sh`](../../robot/deploy/pi4/flash_sd_macos.sh) 燒的 SD 卡、[`check_pi4.sh`](../../robot/deploy/pi4/check_pi4.sh)
- **驗證層級：實機**（Raspberry Pi 4 Model B Rev 1.5，1.8 GiB；檢查端是 macOS，Darwin 27.2.0）
- 接續：[SD 卡燒錄腳本的設定檔檢查](pi4-sd-image-2026-11-22.md)（雲端容器靜態檢查）

## 1. 經過

| 時間（+08:00） | 事件 |
|---|---|
| 14:35 | 使用者在 Mac 上用 `flash_sd_macos.sh` 燒卡（cloud-init `instance-id` 的時間戳） |
| 14:38:27 | Pi 上的首次開機腳本寫下 `firstboot done` |
| 14:56 | `bash check_pi4.sh --clean`：清掉快取明文，接著檢查 |
| 14:57 | `sudo systemctl reboot` |
| 14:58 | 重開機約 20 秒後 SSH 可連；等 30 秒後 `bash check_pi4.sh` |

這張卡是用**第一版**腳本燒的，runcmd 還沒有清 `cloud-config.txt` 與 `network-config.json`（[§3 的修正](pi4-sd-image-2026-11-22.md#3-補充cloud-init-快取裡的明文副本同日修正)之前）。`--clean` 實際刪掉的就是這兩個檔案，證實了靜態檢查找到的漏洞：

```
removed '/var/lib/cloud/instances/<id>/cloud-config.txt'
removed '/var/lib/cloud/instances/<id>/network-config.json'
```

## 2. 結果

| 次數 | 指令 | 通過 | 注意 | 失敗 |
|---|---|---|---|---|
| 1 | `check_pi4.sh --clean` | 26 | 1 | 0 |
| 2（重開機後） | `check_pi4.sh` | **27** | **0** | **0** |

第一次的「注意」是 `/run/cloud-init/` 的 `instance-data-sensitive.json`、`combined-cloud-config.json` 還有明文。這個目錄在記憶體檔案系統上，重開機後第二次檢查通過，與靜態檢查的預期一致。

第二次檢查的重點數字：

| 項目 | 結果 |
|---|---|
| 作業系統 | Debian 13（trixie）、aarch64、kernel `6.18.50+rpt-rpi-v8`，映像 Raspberry Pi reference 2026-10-06 |
| 根分割區 | 29G／SD 卡 30G，已自動擴充 |
| 電源 | `get_throttled=0x0`（開機後沒有電壓不足或降頻）；5V 3A 電源，閒置 |
| CPU 溫度 | 47.7 °C（重開機後 1 分鐘內，閒置）；第一次 43.3 °C（開機 19 分鐘，閒置） |
| cloud-init | 沒有錯誤；已停用（`/etc/cloud/cloud-init.disabled`） |
| 明文 | 開機分割區、`/var/lib/cloud`、`/run/cloud-init` 都沒有殘留；Wi-Fi 密碼只在 `/etc/netplan`（600 root） |
| 網路 | wlan0 連線（2.4 GHz、WPA2，訊號 97%）、國碼 TW、`duck-pi4.local` 可解析、DNS 與 HTTPS（github.com）正常、NTP 已同步、時區 Asia/Taipei |
| 帳號 | `duck` 用 SSH 金鑰登入；密碼登入關閉；sudo 免密碼；群組含 `gpio`、`i2c`、`spi`、`dialout` |
| 開發 | 7 個套件都裝了；Python 3.13.5 可以建立 venv；git 2.47.3；沒有失敗的 systemd 服務 |

報告原檔在使用者 Mac 的 `~/Downloads/nous-duck-pi4/`（`check-20261122-145640.md`、`check-20261122-145828.md`），不進 repo；上表已摘錄所有判斷結果。

## 3. 檢查之外看到的狀態（同日，手動 SSH）

| 項目 | 狀態 |
|---|---|
| I2C、SPI、UART | 都還沒開（沒有 `/dev/i2c-1`、`/dev/spidev*`，`config.txt` 沒有 `dtparam=i2c_arm=on`、`enable_uart=1`）。IMU 照原版接身體板，Pi 4 目前用不到 |
| USB | 沒接裝置（`2109:3431` 是 Pi 4 板上的 VL805 USB 3 hub） |
| 音訊 | 只有板載耳機輸出；還沒有麥克風 |
| USB 序列驅動 | kernel 有 `cdc-acm`、`ch341` 模組（`CONFIG_USB_ACM=m`） |

## 4. 舵機 ID 設定工具（Pi 4 當設定站）

上游 [`docs/configure_motors.md`](../../../docs/configure_motors.md) 允許用任何電腦或 Pi 設定舵機 ID。Pi 4 上的做法：

- `~/duck/Open_Duck_Mini_Runtime`：clone 上游 runtime，`git checkout 376de65`（2026-11-22 時 `v2` 的最新 commit），**沒有**安裝整套。
- `~/duck/servo-venv`：只裝 `pypot @ git+https://github.com/pollen-robotics/pypot@support-feetech-sts3215`（當時分支 commit `f6d305e`），帶入 numpy 2.5.5、pyserial 3.5、scipy 1.18.1 等；版本清單存在 `~/duck/servo-venv-freeze.txt`。

為什麼不裝整套：runtime 的 `setup.cfg` 鎖了 `onnxruntime==1.18.1`、`numpy==1.26.4`、`pygame==2.6.0`。依目前所知，這幾版沒有 Python 3.13 的 wheel，Trixie 預設是 Python 3.13。**這是推論，沒有在 Pi 上試裝整套。**（同日後續：改成 Pi 4 單板，整套 runtime 用 uv 裝的 Python 3.11 裝在 Pi 4 上，見 [ADR-0008](../adr/ADR-0008-single-board-pi4.md) 與 [runtime 驗證紀錄](pi4-runtime-2026-11-22.md)。）

| 測試 | 結果 |
|---|---|
| `from pypot.feetech import FeetechSTS3215IO` | 成功 |
| `configure_motor.py --help` | 正常 |
| `configure_motor.py --id 14`（沒接驅動板） | `SerialException: could not open port /dev/ttyACM0`，符合預期 |

使用者回報 14 顆舵機的 ID 與零位已經設定完成。**這次紀錄沒有回讀驗證**：檢查時 Pi 4 上沒有接驅動板。（2026-11-25 補充：唯讀掃描回讀到的 ID 正好是上游的 14 個，見 [runtime 紀錄 §4.4](pi4-runtime-2026-11-22.md#44-舵機匯流排唯讀掃描2026-11-25)；零位還沒驗證。）

## 5. 限制

- 只量了閒置狀態。負載下的溫度、功耗與降頻（雙目、喚醒詞等）要等 P2 的 spike。
- 只測了 2.4 GHz WPA2 的家用 Wi-Fi。
- `flash_sd_macos.sh` 修正後的版本（runcmd 會清 `cloud-config.txt`、`network-config.json`）**還沒有燒過實機**；這次是第一版加 `--clean`。
- 舵機與驅動板經 Pi 4 的通訊沒有驗證。
