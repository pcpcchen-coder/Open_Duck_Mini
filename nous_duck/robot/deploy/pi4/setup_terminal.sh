#!/bin/bash
# T6 spike 準備（語音路線 A）：在 Pi 4 上裝 Chromium 與無螢幕顯示（Xvfb），並複製 spike 腳本。可重複執行。
#
# 用法（在 Mac 上、repo 的 checkout 裡）：
#   bash nous_duck/robot/deploy/pi4/setup_terminal.sh [host]              # 安裝＋複製；預設 host = duck-pi4
#   bash nous_duck/robot/deploy/pi4/setup_terminal.sh --check [host]      # 只看狀態，不改任何東西
#   bash nous_duck/robot/deploy/pi4/setup_terminal.sh --uninstall [host]  # 移除這支腳本裝的套件與 ~/duck/terminal-spike
#
# 做的事：
#   1. apt 安裝 chromium、xvfb、fonts-noto-cjk（中文字型，頁面與設定畫面的中文才不會變方塊；--no-install-recommends）。安裝前後各記一次套件清單，
#      把「這次新裝的套件」寫到 Pi 的 ~/duck/terminal-spike/apt-installed.txt，--uninstall 就照這份清單移除。
#   2. 把 terminal/（探測頁、run_local_probe.sh、measure.sh、run_nous_terminal.sh）複製到 Pi 的 ~/duck/terminal-spike/。
#   3. 印出版本、佔用空間、目前有沒有麥克風。
#
# 不做的事：不啟動 Chromium、不連 Nous、不開通道、不播放聲音、不新增 systemd 服務、不改 /etc（apt 套件自己的檔案除外）、
#           不改 ~/.asoundrc 與預設音訊裝置、不碰舵機匯流排／I2C／GPIO、不動 duckd／duck-console、不重開機。
#
# 驗證紀錄：nous_duck/docs/validation/duck-terminal-spike-2026-11-26.md
set -euo pipefail

MODE=install
case "${1:-}" in
  --check) MODE=check; shift ;;
  --uninstall) MODE=uninstall; shift ;;
  -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
  --*) echo "不認得的參數：$1" >&2; exit 2 ;;
esac
HOST="${1:-duck-pi4}"
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/terminal"
PACKAGES="chromium xvfb fonts-noto-cjk"

report() {
  ssh "$HOST" bash -s <<'REMOTE'
set -u
SPIKE="$HOME/duck/terminal-spike"
echo "-- 套件"
for p in chromium chromium-common xvfb; do
  if dpkg -s "$p" >/dev/null 2>&1; then dpkg-query -W -f='   ${Package} ${Version}（安裝後 ${Installed-Size} KiB）\n' "$p"; else echo "   $p：沒有安裝"; fi
done
if [ -s "$SPIKE/apt-installed.txt" ]; then
  n="$(wc -l < "$SPIKE/apt-installed.txt")"
  kb="$(xargs -r dpkg-query -W -f='${Installed-Size}\n' < "$SPIKE/apt-installed.txt" 2>/dev/null | awk '{ s += $1 } END { print s + 0 }')"
  echo "   這支腳本新裝的套件：$n 個，Installed-Size 合計 $kb KiB（清單：$SPIKE/apt-installed.txt）"
fi
echo "-- 檔案"
if [ -d "$SPIKE" ]; then du -sh "$SPIKE" | sed 's/^/   /'; ls "$SPIKE" | sed 's/^/   /'; else echo "   $SPIKE 不存在"; fi
echo "-- 磁碟"
df -h / | tail -1 | awk '{ print "   / 已用 " $3 "，可用 " $4 }'
echo "-- 麥克風（唯讀）"
if lsusb | grep -qi 'ID 2886:'; then echo "   lsusb 有 VID 2886（Seeed／XVF3800）"; else echo "   lsusb 沒有 VID 2886（XVF3800 沒有接）"; fi
arecord -l 2>&1 | sed 's/^/   /' | head -5
echo "-- 服務（唯讀）"
echo "   duckd: $(systemctl is-active duckd 2>/dev/null)　duck-console: $(systemctl is-active duck-console 2>/dev/null)"
echo "-- 還在跑的 spike 行程"
pgrep -af 'terminal-spike' | grep -v pgrep | sed 's/^/   /' || echo "   沒有"
REMOTE
}

if [ "$MODE" = check ]; then
  report
  exit 0
fi

if [ "$MODE" = uninstall ]; then
  ssh "$HOST" bash -s <<'REMOTE'
set -euo pipefail
SPIKE="$HOME/duck/terminal-spike"
pkill -f -- "--user-data-dir=$SPIKE/" 2>/dev/null || true
pkill -f "http.server.*$SPIKE" 2>/dev/null || true
if [ -s "$SPIKE/apt-installed.txt" ]; then
  echo "移除 $(wc -l < "$SPIKE/apt-installed.txt") 個套件（清單來自安裝時的紀錄）"
  # shellcheck disable=SC2046
  sudo DEBIAN_FRONTEND=noninteractive apt-get purge -y -qq $(cat "$SPIKE/apt-installed.txt")
else
  echo "沒有 $SPIKE/apt-installed.txt，不知道當初裝了哪些套件；沒有移除任何套件。"
  echo "要手動移除：sudo apt-get purge chromium chromium-common xvfb && sudo apt-get autoremove --purge（先看清單再同意）"
fi
rm -rf "$SPIKE"
echo "已刪除 $SPIKE"
df -h / | tail -1 | awk '{ print "/ 已用 " $3 "，可用 " $4 }'
REMOTE
  exit 0
fi

[ -f "$SRC/run_local_probe.sh" ] || { echo "找不到 $SRC/run_local_probe.sh" >&2; exit 1; }

echo "== 1/3 apt 安裝：$PACKAGES（--no-install-recommends）"
ssh "$HOST" bash -s -- $PACKAGES <<'REMOTE'
set -euo pipefail
SPIKE="$HOME/duck/terminal-spike"
mkdir -p "$SPIKE"
need=""
for p in "$@"; do dpkg -s "$p" >/dev/null 2>&1 || need="$need $p"; done
if [ -z "$need" ]; then
  echo "   都已經安裝，略過"
else
  before="$(mktemp)"; after="$(mktemp)"
  dpkg-query -W -f='${Package}\n' | sort -u > "$before"
  used_before="$(df -k --output=used / | tail -1)"
  echo "   要裝：$need"
  sudo apt-get update -qq
  # shellcheck disable=SC2086
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends $need >/dev/null
  dpkg-query -W -f='${Package}\n' | sort -u > "$after"
  # 累加：之前記過的也保留，重跑不會弄丟清單
  { comm -13 "$before" "$after"; cat "$SPIKE/apt-installed.txt" 2>/dev/null || true; } | sort -u > "$SPIKE/apt-installed.txt.new"
  mv "$SPIKE/apt-installed.txt.new" "$SPIKE/apt-installed.txt"
  used_after="$(df -k --output=used / | tail -1)"
  echo "   新裝 $(comm -13 "$before" "$after" | wc -l) 個套件；根分割區多用 $(( (used_after - used_before) / 1024 )) MiB（含 apt 下載快取）"
  echo "$(date +%Y-%m-%dT%H:%M:%S%z) installed:$need; root_used_delta_kb=$(( used_after - used_before ))" >> "$SPIKE/apt-install.log"
  rm -f "$before" "$after"
fi
REMOTE

echo "== 2/3 複製 terminal/ 到 $HOST:~/duck/terminal-spike/"
TAR_OPTS=()
[ "$(uname)" = Darwin ] && TAR_OPTS=(--no-xattrs --no-mac-metadata)
COPYFILE_DISABLE=1 tar "${TAR_OPTS[@]}" -C "$SRC" -cf - . | ssh "$HOST" 'tar -C ~/duck/terminal-spike -xf - && chmod +x ~/duck/terminal-spike/*.sh'

echo "== 3/3 狀態"
report
cat <<MSG

下一步（在 Pi 上，不連 Nous、不出聲）：
  ssh $HOST 'bash ~/duck/terminal-spike/run_local_probe.sh --display headless'
  ssh $HOST 'bash ~/duck/terminal-spike/run_local_probe.sh --display xvfb --fake-media'
移除：bash $0 --uninstall $HOST
MSG
