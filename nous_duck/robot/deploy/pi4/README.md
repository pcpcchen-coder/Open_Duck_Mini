# 感知板 Pi 4：SD 卡燒錄與首次開機

狀態：**腳本完成，待實機驗證**。設定檔已在雲端容器用映像內附的 cloud-init 與 netplan 檢查過（見 [驗證紀錄](../../../docs/validation/pi4-sd-image-2026-11-22.md)）；在 Mac 上燒錄、Pi 4 開機連上 Wi-Fi 還沒實測。

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
| 清理 | 裝完後清掉開機分割區上的明文密碼與 cloud-init 快取，並停用 cloud-init |

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

## 常見問題

- **`ssh duck-pi4` 找不到主機**：先 `ping duck-pi4.local`；不行就到路由器的 DHCP 清單找 `duck-pi4` 的 IP，用 `ssh duck@<IP> -i ~/.ssh/nous_duck_pi4`。
- **Wi-Fi 沒連上**：接網路線（`eth0` 會自動 DHCP）登入後用 `nmcli` 檢查；SSID 大小寫要完全一致。只支援 WPA2-PSK（WPA2/WPA3 混合模式可以；純 WPA3 的路由器要另外設定）。
- **想重來**：重新執行腳本即可；每次會產生新的 cloud-init `instance-id`。

## 可調整的環境變數

`PI_HOSTNAME`（預設 `duck-pi4`）、`PI_USER`（`duck`）、`WIFI_COUNTRY`（`TW`）、`TIMEZONE`（`Asia/Taipei`），例如 `PI_HOSTNAME=duck-pi4b bash flash_sd_macos.sh`。
