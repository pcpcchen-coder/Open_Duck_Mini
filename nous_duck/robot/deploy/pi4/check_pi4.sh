#!/bin/bash
# 感知板 Pi 4 首次開機檢查：在 Mac（或任何有 ssh 的電腦）上執行，SSH 進 Pi 收集狀態，
# 產生一份可以直接貼進 nous_duck/docs/validation/ 的 Markdown 報告。
#
# 用法：
#   bash check_pi4.sh                 # 檢查 duck-pi4（~/.ssh/config 裡的 Host）
#   bash check_pi4.sh duck-pi4b       # 指定其他 Host
#   bash check_pi4.sh --clean         # 清掉 cloud-init 快取裡殘留的明文密碼後再檢查一次
#
# 隱私：報告不含 Wi-Fi 名稱、IP、MAC 位址或任何密碼；明文檢查只列「哪個檔案還有」，不印內容。
# 報告存到 ~/Downloads/nous-duck-pi4/，macOS 上也會複製到剪貼簿。
#
# 驗證層級：本腳本在雲端容器（非 Pi）測過語法與「指令不存在時不會中斷」；
# 檢查結果本身才是實機驗證。

set -euo pipefail

CLEAN=false
HOST="duck-pi4"
for a in "$@"; do
  case "$a" in
    --clean) CLEAN=true ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    -*) echo "不認得的選項：$a" >&2; exit 2 ;;
    *) HOST=$a ;;
  esac
done
EXPECT_USER="${PI_USER:-duck}"
EXPECT_TZ="${TIMEZONE:-Asia/Taipei}"
EXPECT_COUNTRY="${WIFI_COUNTRY:-TW}"
OUT_DIR="${HOME}/Downloads/nous-duck-pi4"
SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=15"

# ---- 在 Pi 上執行的部分 ---------------------------------------------------------
# 參數：預期主機名稱、使用者、時區、Wi-Fi 國碼
remote_check() {
  cat <<'REMOTE'
set -u
EXP_HOST=$1 EXP_USER=$2 EXP_TZ=$3 EXP_COUNTRY=$4
NOK=0 NWARN=0 NFAIL=0
row() { # 狀態 項目 說明
  local s
  case $1 in
    ok)   s="✅ 通過"; NOK=$((NOK+1)) ;;
    warn) s="⚠️ 注意"; NWARN=$((NWARN+1)) ;;
    fail) s="❌ 失敗"; NFAIL=$((NFAIL+1)) ;;
    *)    s="— 資訊" ;;
  esac
  printf '| %s | %s | %s |\n' "$2" "$s" "$3"
}
have() { command -v "$1" >/dev/null 2>&1; }
SECRET_RE='plain_text_passwd|password'

echo "| 項目 | 結果 | 說明 |"
echo "|---|---|---|"

# 1. 硬體與系統
h=$(hostname)
[ "$h" = "$EXP_HOST" ] && row ok "主機名稱" "\`$h\`" || row fail "主機名稱" "是 \`$h\`，預期 \`$EXP_HOST\`"
model=$(tr -d '\0' 2>/dev/null </proc/device-tree/model || echo "?")
mem=$(awk '/MemTotal/{printf "%.1f GiB", $2/1048576}' /proc/meminfo)
case "$model" in *"Raspberry Pi 4"*) row ok "板子" "$model，記憶體 $mem" ;; *) row warn "板子" "$model，記憶體 $mem（預期 Pi 4）" ;; esac
. /etc/os-release
arch=$(uname -m)
if [ "${VERSION_CODENAME:-}" = "trixie" ] && [ "$arch" = "aarch64" ]; then
  row ok "作業系統" "$PRETTY_NAME，$arch，kernel $(uname -r)"
else
  row warn "作業系統" "$PRETTY_NAME，$arch（預期 trixie／aarch64）"
fi
[ -r /etc/rpi-issue ] && row info "映像" "$(head -n1 /etc/rpi-issue)"
row info "開機時間" "$(uptime -p)"

# 2. 儲存空間（分割區有沒有自動擴充）
rootdev=$(findmnt -no SOURCE /)
disk=/dev/$(lsblk -no PKNAME "$rootdev" 2>/dev/null | head -n1)
dsz=$(lsblk -bdno SIZE "$disk" 2>/dev/null || echo 0)
rsz=$(df -B1 --output=size / | tail -n1 | tr -d ' ')
avail=$(df -h --output=avail / | tail -n1 | tr -d ' ')
if [ "${dsz:-0}" -gt 0 ] && [ "$rsz" -gt $((dsz * 8 / 10)) ]; then
  row ok "根分割區擴充" "$(numfmt --to=iec "$rsz") / SD 卡 $(numfmt --to=iec "$dsz")，剩 $avail"
else
  row warn "根分割區擴充" "根分割區 $(numfmt --to=iec "$rsz")，SD 卡 $(numfmt --to=iec "${dsz:-0}")，可能沒擴充"
fi

# 3. 電源與溫度（5V 3A 電源夠不夠）
if have vcgencmd; then
  t=$(vcgencmd get_throttled 2>/dev/null | sed 's/.*=//')
  v=$((t))
  now=""; past=""
  [ $((v & 0x1)) -ne 0 ] && now="$now 電壓不足"
  [ $((v & 0x2)) -ne 0 ] && now="$now 降頻"
  [ $((v & 0x4)) -ne 0 ] && now="$now 節流"
  [ $((v & 0x8)) -ne 0 ] && now="$now 溫度上限"
  [ $((v & 0x10000)) -ne 0 ] && past="$past 電壓不足"
  [ $((v & 0x20000)) -ne 0 ] && past="$past 降頻"
  [ $((v & 0x40000)) -ne 0 ] && past="$past 節流"
  [ $((v & 0x80000)) -ne 0 ] && past="$past 溫度上限"
  if [ -n "$now" ]; then row fail "電源（get_throttled）" "\`$t\`，現在：$now"
  elif [ -n "$past" ]; then row warn "電源（get_throttled）" "\`$t\`，開機後發生過：$past（換電源或線材）"
  else row ok "電源（get_throttled）" "\`$t\`，開機後沒有電壓不足或降頻"; fi
  temp=$(vcgencmd measure_temp 2>/dev/null | sed 's/temp=//; s/.C$//')
  case "$temp" in
    ''|*[!0-9.]*) row warn "CPU 溫度" "讀不到" ;;
    *) if [ "${temp%.*}" -ge 70 ]; then row warn "CPU 溫度" "$temp °C（偏高）"; else row ok "CPU 溫度" "$temp °C（閒置）"; fi ;;
  esac
else
  row warn "電源（get_throttled）" "沒有 vcgencmd，無法檢查"
fi

# 4. cloud-init 與首次開機腳本
if [ -r /var/lib/cloud/data/result.json ]; then
  errs=$(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));e=d.get("v1",{}).get("errors",[]);print(len(e))' /var/lib/cloud/data/result.json 2>/dev/null || echo "?")
  [ "$errs" = "0" ] && row ok "cloud-init 結果" "沒有錯誤" || row fail "cloud-init 結果" "errors：$errs（看 \`sudo cat /var/lib/cloud/data/result.json\`）"
else
  row fail "cloud-init 結果" "找不到 /var/lib/cloud/data/result.json（cloud-init 可能沒跑）"
fi
LOG=/var/log/nous-duck-firstboot.log
if sudo -n test -r "$LOG"; then
  if sudo -n grep -q "apt 安裝失敗" "$LOG"; then row warn "首次開機腳本" "apt 安裝失敗過（看 $LOG）"
  elif sudo -n grep -q "firstboot done" "$LOG"; then row ok "首次開機腳本" "$(sudo -n grep 'firstboot done' "$LOG" | tail -n1 | sed 's/^\[\([^]]*\)\].*/完成於 \1/')"
  else row fail "首次開機腳本" "有紀錄但沒有完成（看 $LOG）"; fi
else
  row fail "首次開機腳本" "找不到 $LOG"
fi
[ -e /etc/cloud/cloud-init.disabled ] && row ok "cloud-init 已停用" "/etc/cloud/cloud-init.disabled 存在" \
  || row fail "cloud-init 已停用" "沒有 /etc/cloud/cloud-init.disabled，下次開機會再跑"

# 5. 明文密碼有沒有清乾淨（只列檔名，不印內容）
if [ -e /boot/firmware/user-data ] && [ -e /boot/firmware/network-config ]; then
  boot_left=$(grep -lE "$SECRET_RE" /boot/firmware/user-data /boot/firmware/network-config 2>/dev/null | tr '\n' ' ')
  [ -z "$boot_left" ] && row ok "開機分割區明文" "user-data、network-config 已清空" || row fail "開機分割區明文" "還有：$boot_left"
else
  row warn "開機分割區明文" "找不到 /boot/firmware/user-data 或 network-config"
fi
cache_left=$(sudo -n grep -rlE "$SECRET_RE" /var/lib/cloud 2>/dev/null | sed 's#/var/lib/cloud/instances/[^/]*/#instances/<id>/#' | sort -u | tr '\n' ' ')
[ -z "$cache_left" ] && row ok "cloud-init 快取明文" "/var/lib/cloud 沒有殘留" \
  || row fail "cloud-init 快取明文" "還有（root 才讀得到）：$cache_left→ 用 \`bash check_pi4.sh --clean\` 清掉"
run_left=$(sudo -n grep -rlE "$SECRET_RE" /run/cloud-init 2>/dev/null | tr '\n' ' ')
[ -z "$run_left" ] && row ok "/run/cloud-init 明文" "沒有殘留" \
  || row warn "/run/cloud-init 明文" "還有：$run_left（記憶體檔案系統，重開機就消失）"
np_bad="" np_n=0
for f in /etc/netplan/*.yaml; do
  [ -e "$f" ] || continue
  np_n=$((np_n+1))
  p=$(sudo -n stat -c '%a %U' "$f")
  [ "$p" = "600 root" ] || np_bad="$np_bad $(basename "$f")=$p"
done
[ "$np_n" -eq 0 ] && np_bad="沒有 /etc/netplan/*.yaml"
[ -z "$np_bad" ] && row ok "netplan 權限" "Wi-Fi 密碼只存在 /etc/netplan（600 root，連線需要）" || row warn "netplan 權限" "$np_bad"

# 6. 網路
if have nmcli; then
  wst=$(nmcli -t -f DEVICE,STATE device status | awk -F: '$1=="wlan0"{print $2}')
  [ "$wst" = "connected" ] && row ok "Wi-Fi（wlan0）" "已連線" || row fail "Wi-Fi（wlan0）" "狀態：${wst:-找不到 wlan0}"
  sig=$(nmcli -t -f IN-USE,SIGNAL,FREQ,SECURITY device wifi list --rescan no 2>/dev/null | awk -F: '$1=="*"{print "訊號 "$2"%，"$3"，"$4; exit}')
  [ -n "$sig" ] && row info "Wi-Fi 連線品質" "$sig"
  est=$(nmcli -t -f DEVICE,STATE device status | awk -F: '$1=="eth0"{print $2}')
  row info "有線（eth0）" "${est:-找不到 eth0}"
else
  row fail "Wi-Fi（wlan0）" "沒有 nmcli"
fi
cc=""
have iw && cc=$(iw reg get 2>/dev/null | awk '/^country/{sub(":","",$2); print $2; exit}')
[ -z "$cc" ] && have raspi-config && cc=$(sudo -n raspi-config nonint get_wifi_country 2>/dev/null || true)
[ "$cc" = "$EXP_COUNTRY" ] && row ok "Wi-Fi 國碼" "$cc" || row warn "Wi-Fi 國碼" "是 ${cc:-讀不到}，預期 $EXP_COUNTRY"
v4=$(ip -4 -o addr show scope global 2>/dev/null | awk '{print $2}' | sort -u | tr '\n' ' ')
[ -n "$v4" ] && row ok "IPv4" "有位址的介面：$v4（位址不列出）" || row fail "IPv4" "沒有任何介面拿到 IPv4"
systemctl is-active --quiet avahi-daemon 2>/dev/null && row ok "mDNS（avahi）" "\`$EXP_HOST.local\` 可以被找到" || row warn "mDNS（avahi）" "avahi-daemon 沒在跑"
if getent hosts deb.debian.org >/dev/null; then
  if have curl && curl -fs -o /dev/null -m 15 https://github.com; then row ok "對外連線" "DNS 與 HTTPS（github.com）正常"
  else row warn "對外連線" "DNS 正常，HTTPS 連 github.com 失敗"; fi
else
  row fail "對外連線" "DNS 查不到 deb.debian.org"
fi
ntp=$(timedatectl show -p NTPSynchronized --value 2>/dev/null || echo "?")
tz=$(timedatectl show -p Timezone --value 2>/dev/null || echo "?")
[ "$ntp" = "yes" ] && row ok "時間同步" "NTP 已同步" || row warn "時間同步" "NTPSynchronized=$ntp"
[ "$tz" = "$EXP_TZ" ] && row ok "時區" "$tz" || row warn "時區" "是 $tz，預期 $EXP_TZ"

# 7. 帳號與 SSH
[ "$(id -un)" = "$EXP_USER" ] && row ok "登入使用者" "\`$EXP_USER\`（SSH 金鑰登入成功）" || row warn "登入使用者" "是 $(id -un)"
sudo -n true 2>/dev/null && row ok "sudo 免密碼" "可以" || row fail "sudo 免密碼" "不行"
pa=$(sudo -n sshd -T 2>/dev/null | awk '$1=="passwordauthentication"{print $2}')
pr=$(sudo -n sshd -T 2>/dev/null | awk '$1=="permitrootlogin"{print $2}')
[ "$pa" = "no" ] && row ok "SSH 密碼登入" "關閉（只收金鑰），root 登入：${pr:-?}" || row fail "SSH 密碼登入" "passwordauthentication=${pa:-讀不到}"
miss=""
for g in sudo gpio i2c spi dialout video audio render; do id -nG | tr ' ' '\n' | grep -qx "$g" || miss="$miss $g"; done
[ -z "$miss" ] && row ok "使用者群組" "$(id -nG)" || row warn "使用者群組" "缺少：$miss"

# 8. 開發套件
miss=""
for p in git python3-venv python3-pip python3-dev tmux htop i2c-tools; do
  dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q "install ok installed" || miss="$miss $p"
done
[ -z "$miss" ] && row ok "開發套件" "git、python3-venv、python3-pip、python3-dev、tmux、htop、i2c-tools" || row fail "開發套件" "缺少：$miss"
tmpv=$(mktemp -d)
if python3 -m venv "$tmpv/v" >/dev/null 2>&1 && "$tmpv/v/bin/python" -m pip --version >/dev/null 2>&1; then
  row ok "Python venv" "$(python3 --version)，可以建立 venv"
else
  row fail "Python venv" "$(python3 --version 2>&1)，建立 venv 失敗"
fi
rm -rf "$tmpv"
have git && row info "git" "$(git --version)"

# 9. 失敗的服務
failed=$(systemctl --failed --no-legend --plain 2>/dev/null | awk '{print $1}' | tr '\n' ' ')
[ -z "$failed" ] && row ok "systemd 服務" "沒有失敗的服務" || row warn "systemd 服務" "失敗：$failed"

echo
echo "合計：通過 $NOK、注意 $NWARN、失敗 $NFAIL"
REMOTE
}

# ---- 清掉 cloud-init 快取裡的明文（給已經開過機、用舊版燒錄腳本的卡） ----------
remote_clean() {
  cat <<'REMOTE'
set -eu
# 整段用 root 展開萬用字元（一般使用者不一定能列出 instances/ 底下的檔案）
sudo -n sh -c 'for d in /var/lib/cloud/instances/*/; do
  rm -fv "$d"user-data.txt* "$d"obj.pkl "$d"cloud-config.txt "$d"vendor-cloud-config.txt \
    "$d"vendor2-cloud-config.txt "$d"network-config.json
done'
REMOTE
}

ssh_fail_hint() {
  local err=$1
  echo >&2
  echo "連不上 ${HOST}。ssh 的訊息：" >&2
  echo "$err" | sed 's/^/  /' >&2
  case "$err" in
    *"REMOTE HOST IDENTIFICATION HAS CHANGED"*)
      echo "→ 重新燒錄過的卡會換主機金鑰。先執行：ssh-keygen -R ${HOST}.local  然後重跑。" >&2 ;;
    *"Could not resolve"*|*"nodename nor servname"*)
      echo "→ 找不到 ${HOST}.local。Pi 可能還在第一次開機（等 3–5 分鐘），或 Wi-Fi 沒連上。" >&2
      echo "  試：ping ${HOST}.local；或到路由器的 DHCP 清單找 ${HOST} 的 IP，" >&2
      echo "  再用：ssh -i ~/.ssh/nous_duck_pi4 ${EXPECT_USER}@<IP>" >&2 ;;
    *"Permission denied"*)
      echo "→ 金鑰不對。這張卡是用這台 Mac 的 ~/.ssh/nous_duck_pi4 燒的嗎？" >&2 ;;
    *"timed out"*|*"No route"*)
      echo "→ 找到名字但連不到。確認 Mac 和 Pi 在同一個網段（訪客網路通常互相隔離）。" >&2 ;;
  esac
  exit 1
}

main() {
  local err
  if ! err=$(ssh $SSH_OPTS "$HOST" true 2>&1); then ssh_fail_hint "$err"; fi

  if $CLEAN; then
    echo "==> 清除 ${HOST} 上 cloud-init 快取的明文設定"
    remote_clean | ssh $SSH_OPTS "$HOST" "bash -s"
  fi

  mkdir -p "$OUT_DIR"
  local out
  out="$OUT_DIR/check-$(date +%Y%m%d-%H%M%S).md"
  {
    echo "## 感知板 Pi 4 首次開機檢查（$(date '+%Y-%m-%d %H:%M')）"
    echo
    echo "- 驗證層級：**實機**（${HOST}，由 check_pi4.sh 透過 SSH 收集）"
    echo "- 執行端：$(uname -s) $(uname -r)"
    $CLEAN && echo "- 檢查前已執行 \`--clean\`"
    echo
    remote_check | ssh $SSH_OPTS "$HOST" "bash -s -- '$HOST' '$EXPECT_USER' '$EXPECT_TZ' '$EXPECT_COUNTRY'"
  } | tee "$out"

  echo
  echo "報告存在：$out"
  if command -v pbcopy >/dev/null 2>&1; then
    pbcopy <"$out" && echo "也已複製到剪貼簿，可以直接貼給 Claude。"
  fi
}

main
