# Pi 4：SD 卡燒錄、首次開機與 runtime 安裝

狀態：**實機通過（第一版腳本＋`--clean`）**。設定檔已在雲端容器用映像內附的 cloud-init 與 netplan 檢查過（見 [靜態檢查紀錄](../../../docs/validation/pi4-sd-image-2026-11-22.md)）。2026-11-22 用第一版腳本在 Mac 上燒卡，Pi 4 開機連上 Wi-Fi，`check_pi4.sh --clean` 後重開機，27 項全部通過（見 [實機紀錄](../../../docs/validation/pi4-firstboot-2026-11-22.md)）。修正後的腳本（首次開機就清掉全部快取明文）還沒有燒過實機。

## 做什麼

[`flash_sd_macos.sh`](flash_sd_macos.sh) 在 macOS 上：

1. 問家裡 Wi-Fi 名稱／密碼與 Pi 的登入密碼（只在執行時輸入，不進 repo）。
2. 建立專用 SSH 金鑰 `~/.ssh/nous_duck_pi4`，並在 `~/.ssh/config` 加入 `Host duck-pi4`。
3. 下載鎖定版本的 Raspberry Pi OS Lite 64-bit（Trixie，2026-10-06），檢查 SHA-256。
4. 列出外接磁碟，讓你選 SD 卡（拒絕內建磁碟與不像 SD 卡的容量，要輸入 `YES` 才寫）。
5. 寫入映像，再把 cloud-init 設定（`user-data`、`network-config`、`meta-data`）寫進開機分割區。

首次開機時 Pi 會：

| 項目 | 設定 |
|---|---|
| 主機名稱 | `duck-pi4`（區網用 `duck-pi4.local`） |
| 使用者 | `duck`，SSH 只收金鑰；sudo 免密碼（方便遠端開發） |
| 網路 | Wi-Fi（NetworkManager，國碼 TW）；有線 `eth0` DHCP 當備援 |
| 時區 | Asia/Taipei |
| 套件 | git、python3-venv、python3-pip、python3-dev、tmux、htop、i2c-tools |
| 清理 | 裝完後清掉開機分割區上的明文密碼，以及 cloud-init 快取裡的三份副本（`user-data.txt`、`cloud-config.txt`、`network-config.json`），並停用 cloud-init。Wi-Fi 密碼只留在 `/etc/netplan/`（600 root，連線需要） |

紀錄寫在 Pi 上的 `/var/log/nous-duck-firstboot.log`。

## 怎麼用

在 Mac 的「終端機」：

```bash
curl -fsSLO https://raw.githubusercontent.com/pcpcchen-coder/Open_Duck_Mini/v2/nous_duck/robot/deploy/pi4/flash_sd_macos.sh
```

```bash
bash flash_sd_macos.sh
```

寫入時會要 Mac 的登入密碼（`sudo dd`）。寫完 macOS 可能跳出「無法讀取此磁碟」，那是 Linux 分割區，按「忽略」即可。

SD 卡插進 Pi 4、接 5V 3A 電源，等 3–5 分鐘（會自動擴充分割區並重開一次），然後：

```bash
ssh duck-pi4
```

## 開機後檢查

連得上之後，在 Mac 上跑 [`check_pi4.sh`](check_pi4.sh)。它會 SSH 進 Pi 檢查約 30 項，產生一份 Markdown 報告：

```bash
curl -fsSLO https://raw.githubusercontent.com/pcpcchen-coder/Open_Duck_Mini/v2/nous_duck/robot/deploy/pi4/check_pi4.sh
```

```bash
bash check_pi4.sh
```

| 類別 | 檢查 |
|---|---|
| 系統 | 主機名稱、板子型號與記憶體、OS（trixie／aarch64）、根分割區有沒有自動擴充 |
| 電源 | `vcgencmd get_throttled`（電壓不足、降頻）、CPU 溫度 |
| 首次開機 | cloud-init 有沒有錯、`/var/log/nous-duck-firstboot.log` 有沒有跑完、cloud-init 是否已停用 |
| 明文 | 開機分割區、`/var/lib/cloud`、`/run/cloud-init` 還有沒有密碼（只列檔名、不印內容）；`/etc/netplan` 權限 |
| 網路 | Wi-Fi 是否連線、訊號、國碼、IPv4、mDNS、DNS 與 HTTPS、NTP、時區 |
| 帳號 | SSH 只收金鑰、sudo 免密碼、使用者群組（gpio、i2c、spi…） |
| 開發 | 套件是否裝齊、能不能建立 Python venv、有沒有失敗的 systemd 服務 |

報告存到 `~/Downloads/nous-duck-pi4/check-<時間>.md`，macOS 上會順便複製到剪貼簿，可以直接貼給 Claude 整理成驗證紀錄。報告**不含** Wi-Fi 名稱、IP、MAC 位址或密碼。

用 2026-11-22 早期版本燒錄的卡（cloud-init 快取裡還留著 `cloud-config.txt` 等副本），報告會在「cloud-init 快取明文」顯示失敗。用下面的指令清掉後重新檢查：

```bash
bash check_pi4.sh --clean
```

## 安裝上游 runtime（單板，ADR-0008）

Pi 4 取代 Pi Zero 2 W 之後（[ADR-0008](../../../docs/adr/ADR-0008-single-board-pi4.md)），上游 [Open_Duck_Mini_Runtime](https://github.com/apirrone/Open_Duck_Mini_Runtime) 也裝在 Pi 4。在 repo 的 checkout 裡執行（要用到根目錄的 `BEST_WALK_ONNX_2.onnx`）：

```bash
bash nous_duck/robot/deploy/pi4/setup_runtime.sh
```

[`setup_runtime.sh`](setup_runtime.sh) 透過 SSH 在 Pi 的 `~/duck/` 安裝：

| 項目 | 內容 |
|---|---|
| `Open_Duck_Mini_Runtime/` | 上游 runtime，鎖 commit `376de65`，不 fork、不改 |
| `runtime-venv/` | uv 裝的 **Python 3.11.18**（Trixie 的系統 Python 3.13 裝不了上游鎖的版本），套件版本全部鎖在 [`runtime-constraints.txt`](runtime-constraints.txt)，另加 `gpiod`（Blinka 在 Pi 4 需要） |
| `BEST_WALK_ONNX_2.onnx` | 步態策略，從 repo 根目錄複製並檢查 SHA-256 |
| I2C | 打開（BNO055 用），第一次打開要重開機 |
| `~/duck_config.json` | 不存在時從上游 `example_config.json` 複製，已存在就不覆蓋 |

最後會跑煙霧測試（模組匯入、Blinka 板子、步態策略推論速度、I2C 上有沒有 BNO055、有沒有 `/dev/ttyACM0`）。不會讓舵機動。只跑測試：

```bash
bash nous_duck/robot/deploy/pi4/setup_runtime.sh --check
```

用 runtime（在 Pi 上）：

```bash
source ~/duck/runtime-venv/bin/activate && cd ~/duck/Open_Duck_Mini_Runtime/scripts
```

之後照上游 README 的順序：`python ../mini_bdx_runtime/mini_bdx_runtime/raw_imu.py`（IMU）→ `python check_motors.py`（舵機）→ `python find_soft_offsets.py`（零點偏移）→ `python v2_rl_walk_mujoco.py --onnx_model_path ~/duck/BEST_WALK_ONNX_2.onnx`（走路）。注意：不要在 `~/duck/Open_Duck_Mini_Runtime` 根目錄直接跑 Python，同名資料夾會蓋過已安裝的套件。

驗證紀錄：[pi4-runtime-2026-11-22.md](../../../docs/validation/pi4-runtime-2026-11-22.md)（實機，沒接周邊）。

## 常見問題

- **`ssh duck-pi4` 找不到主機**：先 `ping duck-pi4.local`；不行就到路由器的 DHCP 清單找 `duck-pi4` 的 IP，用 `ssh duck@<IP> -i ~/.ssh/nous_duck_pi4`。
- **Wi-Fi 沒連上**：接網路線（`eth0` 會自動 DHCP）登入後用 `nmcli` 檢查；SSID 大小寫要完全一致。只支援 WPA2-PSK（WPA2/WPA3 混合模式可以；純 WPA3 的路由器要另外設定）。
- **想重來**：重新執行腳本即可；每次會產生新的 cloud-init `instance-id`。重燒後 Pi 的主機金鑰會變，`ssh` 會警告 `REMOTE HOST IDENTIFICATION HAS CHANGED`，先執行 `ssh-keygen -R duck-pi4.local`。

## 可調整的環境變數

`PI_HOSTNAME`（預設 `duck-pi4`）、`PI_USER`（`duck`）、`WIFI_COUNTRY`（`TW`）、`TIMEZONE`（`Asia/Taipei`），例如 `PI_HOSTNAME=duck-pi4b bash flash_sd_macos.sh`。
