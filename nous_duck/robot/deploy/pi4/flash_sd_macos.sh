#!/bin/bash
# 在 macOS 上把 Raspberry Pi OS Lite（64-bit, Trixie）燒進 SD 卡，給鴨子的感知板 Pi 4 用。
# 首次開機由 cloud-init 設定：主機名稱、使用者、SSH 金鑰、家裡 Wi-Fi、時區、開發套件。
#
# 用法（在 Mac 的「終端機」執行，會要求輸入 Mac 登入密碼以寫入 SD 卡）：
#   bash flash_sd_macos.sh
# 只產生 cloud-init 設定檔、不碰 SD 卡（用來檢查或測試）：
#   bash flash_sd_macos.sh --render-only <輸出資料夾>
#
# 隱私：Wi-Fi 密碼與登入密碼只在執行時輸入，不寫進 repo。首次開機完成後，
# Pi 會把 SD 卡開機分割區上的設定檔清掉，並停用 cloud-init（見 user-data 的 runcmd）。
#
# 驗證層級：設定檔已用映像內附的 cloud-init 25.2 做 schema 檢查（雲端容器）；
# 燒錄流程與實際開機連網「待實機驗證」。

set -euo pipefail

# ---- 固定參數（映像鎖定版本與雜湊）-------------------------------------------
IMAGE_NAME="2026-10-06-raspios-trixie-arm64-lite.img.xz"
IMAGE_URL="https://downloads.raspberrypi.com/raspios_lite_arm64/images/raspios_lite_arm64-2026-10-06/${IMAGE_NAME}"
IMAGE_SHA256="483db18a48da399b5b7022ffae9a07bc6d99daab30e593aedac09b69ff422843"
CACHE_DIR="${HOME}/Downloads/nous-duck-pi4"

PI_HOSTNAME="${PI_HOSTNAME:-duck-pi4}"
PI_USER="${PI_USER:-duck}"
WIFI_COUNTRY="${WIFI_COUNTRY:-TW}"
TIMEZONE="${TIMEZONE:-Asia/Taipei}"
SSH_KEY="${HOME}/.ssh/nous_duck_pi4"

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die()  { printf '\n\033[31m錯誤：%s\033[0m\n' "$*" >&2; exit 1; }

# YAML 雙引號字串跳脫：\ → \\，" → \"
yq() { local s=${1//\\/\\\\}; s=${s//\"/\\\"}; printf '"%s"' "$s"; }

# ---- 產生 cloud-init 設定 ------------------------------------------------------
# 參數：輸出資料夾、SSID、Wi-Fi 密碼、是否隱藏 SSID(true/false)、登入密碼、SSH 公鑰
render_config() {
  local out=$1 ssid=$2 wifi_pw=$3 hidden=$4 login_pw=$5 pubkey=$6
  mkdir -p "$out"

  cat >"$out/meta-data" <<EOF
dsmode: local
instance-id: nous-duck-${PI_HOSTNAME}-$(date +%Y%m%d%H%M%S)
local-hostname: ${PI_HOSTNAME}
EOF

  {
    cat <<EOF
network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eth0:
      dhcp4: true
      optional: true
  wifis:
    wlan0:
      dhcp4: true
      optional: true
      regulatory-domain: $(yq "$WIFI_COUNTRY")
      access-points:
        $(yq "$ssid"):
          password: $(yq "$wifi_pw")
EOF
    if [ "$hidden" = "true" ]; then
      echo "          hidden: true"
    fi
  } >"$out/network-config"

  cat >"$out/user-data" <<EOF
#cloud-config
# 由 nous_duck/robot/deploy/pi4/flash_sd_macos.sh 產生
hostname: $(yq "$PI_HOSTNAME")
manage_etc_hosts: true
timezone: $(yq "$TIMEZONE")
keyboard:
  layout: us

users:
  - name: $(yq "$PI_USER")
    gecos: Nous Duck
    groups: [adm, dialout, cdrom, audio, users, sudo, video, plugdev, input, gpio, spi, i2c, netdev, render]
    shell: /bin/bash
    sudo: "ALL=(ALL) NOPASSWD:ALL"
    lock_passwd: false
    plain_text_passwd: $(yq "$login_pw")
    ssh_authorized_keys:
      - $(yq "$pubkey")

ssh_pwauth: false

bootcmd:
  - [sh, -c, "raspi-config nonint do_wifi_country $WIFI_COUNTRY || rfkill unblock wifi || true"]

runcmd:
  - [systemctl, enable, --now, ssh]
  - |
    set -u
    LOG=/var/log/nous-duck-firstboot.log
    exec >>"\$LOG" 2>&1
    echo "[\$(date -Is)] nous-duck firstboot start"
    for i in \$(seq 1 60); do getent hosts deb.debian.org >/dev/null && break; sleep 5; done
    export DEBIAN_FRONTEND=noninteractive
    apt-get update && apt-get install -y git python3-venv python3-pip python3-dev tmux htop i2c-tools \
      || echo "apt 安裝失敗（可能還沒連上網路），之後手動重跑"
    # 清掉開機分割區上的明文密碼與 cloud-init 快取，並停用 cloud-init
    printf '# cleared by nous_duck after first boot\n' > /boot/firmware/network-config
    printf '#cloud-config\n# cleared by nous_duck after first boot\n' > /boot/firmware/user-data
    # cloud-init 另外存了三份：原始 user-data、合併後的 cloud-config.txt（含 plain_text_passwd）、
    # network-config.json（含 Wi-Fi 密碼）。Wi-Fi 密碼只留在 /etc/netplan（600 root，連線需要）。
    for d in /var/lib/cloud/instances/*/; do
      rm -f "\$d"user-data.txt* "\$d"obj.pkl "\$d"cloud-config.txt "\$d"vendor-cloud-config.txt \\
        "\$d"vendor2-cloud-config.txt "\$d"network-config.json
    done
    touch /etc/cloud/cloud-init.disabled
    echo "[\$(date -Is)] nous-duck firstboot done"
EOF
}

ask() { # 提示文字、預設值 → 回傳輸入
  local prompt=$1 def=${2:-} ans
  if [ -n "$def" ]; then read -r -p "$prompt [$def]: " ans; echo "${ans:-$def}";
  else read -r -p "$prompt: " ans; echo "$ans"; fi
}
ask_secret() { # 輸入兩次確認
  local prompt=$1 a b
  while :; do
    read -r -s -p "$prompt: " a; echo >&2
    read -r -s -p "再輸入一次: " b; echo >&2
    [ "$a" = "$b" ] && [ -n "$a" ] && { echo "$a"; return; }
    echo "兩次不一樣或是空的，重來。" >&2
  done
}

collect_inputs() {
  say "家裡 Wi-Fi 設定"
  local cur=""
  cur=$(ipconfig getsummary en0 2>/dev/null | awk -F' SSID : ' '/ SSID : /{print $2; exit}' || true)
  case "$cur" in *redacted*|"") cur="" ;; esac
  SSID=$(ask "Wi-Fi 名稱（SSID，大小寫要對）" "$cur")
  [ -n "$SSID" ] || die "SSID 不能是空的"
  WIFI_PW=$(ask_secret "Wi-Fi 密碼")
  HIDDEN=$(ask "這個 Wi-Fi 是隱藏的嗎？(y/N)" "N")
  case "$HIDDEN" in y|Y|yes) HIDDEN=true ;; *) HIDDEN=false ;; esac
  say "Pi 的登入密碼（使用者 ${PI_USER}；平常用 SSH 金鑰，密碼是接螢幕鍵盤時的備用）"
  LOGIN_PW=$(ask_secret "登入密碼")
}

ensure_ssh_key() {
  if [ ! -f "$SSH_KEY" ]; then
    say "建立專用 SSH 金鑰 $SSH_KEY"
    mkdir -p "${HOME}/.ssh" && chmod 700 "${HOME}/.ssh"
    ssh-keygen -t ed25519 -N "" -C "nous-duck-dev" -f "$SSH_KEY" >/dev/null
  fi
  PUBKEY=$(cat "${SSH_KEY}.pub")
  local cfg="${HOME}/.ssh/config"
  if ! grep -q "^Host ${PI_HOSTNAME}\$" "$cfg" 2>/dev/null; then
    say "在 ~/.ssh/config 加入 Host ${PI_HOSTNAME}"
    cat >>"$cfg" <<EOF

Host ${PI_HOSTNAME}
  HostName ${PI_HOSTNAME}.local
  User ${PI_USER}
  IdentityFile ${SSH_KEY}
  IdentitiesOnly yes
  StrictHostKeyChecking accept-new
EOF
    chmod 600 "$cfg"
  fi
}

download_image() {
  mkdir -p "$CACHE_DIR"
  local f="$CACHE_DIR/$IMAGE_NAME"
  if [ ! -f "$f" ] || [ "$(shasum -a 256 "$f" | awk '{print $1}')" != "$IMAGE_SHA256" ]; then
    say "下載 Raspberry Pi OS Lite（約 525 MB）"
    curl -fL --retry 3 -o "$f.part" "$IMAGE_URL"
    mv "$f.part" "$f"
  fi
  [ "$(shasum -a 256 "$f" | awk '{print $1}')" = "$IMAGE_SHA256" ] || die "映像 SHA-256 不符，請刪掉 $f 重試"
  echo "映像 SHA-256 檢查通過：$f"
  IMAGE_FILE=$f
}

decompress_cmd() {
  if command -v xz >/dev/null; then echo "xz -dc"; return; fi
  if python3 -c "import lzma" 2>/dev/null; then
    echo "python3 -c 'import lzma,shutil,sys;shutil.copyfileobj(lzma.open(sys.argv[1]),sys.stdout.buffer,16<<20)'"
    return
  fi
  die "找不到 xz 解壓工具。請先執行：brew install xz"
}

pick_disk() {
  say "外接磁碟清單（請找 32 GB 左右的 SD 卡）"
  diskutil list external physical
  DISK=$(ask "SD 卡的磁碟代號（例如 disk4，不要加 s1）")
  case "$DISK" in disk[0-9]|disk[0-9][0-9]) ;; *) die "格式不對：$DISK" ;; esac
  local info; info=$(diskutil info "$DISK") || die "找不到 $DISK"
  echo "$info" | grep -E "Device / Media Name|Disk Size|Device Location|Internal|Protocol|Removable Media" || true
  echo "$info" | grep -Eq "Internal: +No|Device Location: +External" || die "$DISK 看起來是內建磁碟，停止"
  local bytes; bytes=$(echo "$info" | sed -n 's/.*Disk Size:.*(\([0-9]*\) Bytes).*/\1/p')
  [ -n "$bytes" ] || die "讀不到 $DISK 容量"
  if [ "$bytes" -lt 8000000000 ] || [ "$bytes" -gt 130000000000 ]; then
    die "$DISK 容量 $bytes bytes 不像 SD 卡，停止"
  fi
  printf '\n\033[33m%s 上的所有資料都會被清除。\033[0m\n' "$DISK"
  [ "$(ask "確定請輸入大寫 YES")" = "YES" ] || die "已取消"
}

flash() {
  local dc; dc=$(decompress_cmd)
  say "卸載 $DISK"
  diskutil unmountDisk "/dev/$DISK"
  say "寫入中（約 3–10 分鐘；按 Ctrl+T 可看進度）"
  sudo -v
  eval "$dc \"\$IMAGE_FILE\"" | sudo dd of="/dev/r$DISK" bs=4m
  sync
  say "掛載開機分割區"
  sleep 3
  diskutil mountDisk "/dev/$DISK" >/dev/null 2>&1 || true
  BOOT=""
  for _ in $(seq 1 20); do
    BOOT=$(diskutil info "${DISK}s1" 2>/dev/null | sed -n 's/^ *Mount Point: *//p')
    [ -n "$BOOT" ] && [ -f "$BOOT/cmdline.txt" ] && break
    sleep 1
  done
  [ -n "$BOOT" ] && [ -f "$BOOT/cmdline.txt" ] || die "找不到開機分割區（bootfs）"
  echo "開機分割區：$BOOT"
}

main() {
  if [ "${1:-}" = "--render-only" ]; then
    [ -n "${2:-}" ] || die "用法：$0 --render-only <輸出資料夾>"
    # 測試用：從環境變數讀值，不互動
    render_config "$2" "${SSID:?}" "${WIFI_PW:?}" "${HIDDEN:-false}" "${LOGIN_PW:?}" "${PUBKEY:?}"
    echo "已產生到 $2"; exit 0
  fi
  [ "$(uname -s)" = "Darwin" ] || die "這支腳本只在 macOS 上燒錄 SD 卡"

  collect_inputs
  ensure_ssh_key
  download_image
  pick_disk
  flash

  say "寫入 cloud-init 設定"
  render_config "$BOOT" "$SSID" "$WIFI_PW" "$HIDDEN" "$LOGIN_PW" "$PUBKEY"
  touch "$BOOT/ssh"   # sshswitch.service 看到這個檔就啟用 SSH
  rm -rf "$BOOT/.fseventsd" "$BOOT"/._* 2>/dev/null || true
  sync
  diskutil eject "/dev/$DISK"

  cat <<EOF

完成。接下來：
  1. 把 SD 卡插進 Pi 4，接上 5V 3A 電源。
  2. 第一次開機約 3–5 分鐘（會自動擴充分割區、重開一次、裝開發套件）。
  3. 在這台 Mac 執行：  ssh ${PI_HOSTNAME}
     連不上的話先試：     ping ${PI_HOSTNAME}.local
EOF
}

main "$@"
