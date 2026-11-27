#!/bin/bash
# 把鴨子的語音終端（Pi 上的 Chromium 開 Nous 頁面 ?terminal=duck，路線 2）裝成 systemd 服務 duck-terminal，開機常駐。
#
# 使用者 2026-11-27 決定：「把它弄成服務啊！！要開機常駐！」
#
# 用法（在 Mac 上、repo 的 checkout 裡）：
#   bash nous_duck/robot/deploy/pi4/deploy_terminal_service.sh [host]              # 安裝、enable、立刻啟動；預設 host = duck-pi4
#   bash nous_duck/robot/deploy/pi4/deploy_terminal_service.sh --status [host]     # 只看狀態
#   bash nous_duck/robot/deploy/pi4/deploy_terminal_service.sh --uninstall [host]  # 停掉、disable、刪掉服務檔
#
# 做的事：
#   1. 把 terminal/ 複製到 Pi 的 ~/duck/terminal-spike/（和 setup_terminal.sh 相同；Chromium 要先用 setup_terminal.sh 裝好）。
#   2. 停掉用 setsid／nohup 手動開的終端（同一個 Chromium 設定檔不能同時開兩個）。
#   3. 寫 /etc/systemd/system/duck-terminal.service，enable 並啟動。
#
# 服務的行為：
#   - 以 duck 使用者執行 run_nous_terminal.sh：headless、共用麥克風 duck_mic、喇叭自動找（--speaker auto）、
#     麥克風權限自動允許（--auto-accept-mic；使用者 2026-11-27 同意）。不開除錯埠。
#   - I_AM_PRESENT_AND_OK_WITH_SOUND=yes 寫在服務裡：常駐就是同意「隨時可能出聲、麥克風一直開著」。
#     麥克風的聲音只有在鴨子被叫醒、頁面開始即時語音後才會送出（頁面直接送雲端模型）。
#   - Nous 在 Mac 上，經 SSH 通道到 Pi 的 localhost:8791。通道沒開時腳本會結束，服務每 30 秒重試，通道開了就連上。
#   - 即時語音的同意存在 Chromium 設定檔（~/duck/terminal-spike/profile-nous-duck），重開不用再按。
#
# 不做的事：不開通道、不碰 Mac、不碰舵機匯流排／I2C／GPIO、不改 ~/.asoundrc 與 /etc/asound*、不重開機。
set -euo pipefail

MODE=install
case "${1:-}" in
  --status) MODE=status; shift ;;
  --uninstall) MODE=uninstall; shift ;;
  -h|--help) sed -n '2,28p' "$0"; exit 0 ;;
  --*) echo "不認得的參數：$1" >&2; exit 2 ;;
esac
HOST="${1:-duck-pi4}"
HERE="$(cd "$(dirname "$0")" && pwd)"
UNIT=duck-terminal
AIOS_PORT="${AIOS_PORT:-8791}"

if [ "$MODE" = status ]; then
  ssh "$HOST" "systemctl is-enabled $UNIT 2>/dev/null; systemctl is-active $UNIT 2>/dev/null; journalctl -u $UNIT -n 8 --no-pager -o cat 2>/dev/null || true"
  exit 0
fi
if [ "$MODE" = uninstall ]; then
  ssh "$HOST" "sudo systemctl disable --now $UNIT 2>/dev/null || true; sudo rm -f /etc/systemd/system/$UNIT.service; sudo systemctl daemon-reload"
  echo "已移除 $UNIT 服務（~/duck/terminal-spike 與 Chromium 設定檔保留）"
  exit 0
fi
case "$AIOS_PORT" in ''|*[!0-9]*) echo "AIOS_PORT 要是數字：$AIOS_PORT" >&2; exit 2 ;; esac

echo "== 1/3 複製 terminal/ 到 $HOST:~/duck/terminal-spike/"
ssh "$HOST" 'command -v chromium >/dev/null || command -v chromium-browser >/dev/null || { echo "Pi 上沒有 Chromium，先跑 setup_terminal.sh"; exit 1; }
  test -r ~/duck/voice/alsa/duck-audio.conf || { echo "缺 ~/duck/voice/alsa/duck-audio.conf，先跑 deploy_voice.sh"; exit 1; }
  mkdir -p ~/duck/terminal-spike'
TAR_OPTS=()
[ "$(uname)" = Darwin ] && TAR_OPTS=(--no-xattrs --no-mac-metadata)
COPYFILE_DISABLE=1 tar "${TAR_OPTS[@]}" -C "$HERE/terminal" -cf - . | ssh "$HOST" 'tar -C ~/duck/terminal-spike -xf - && chmod +x ~/duck/terminal-spike/*.sh'

echo "== 2/3 停掉手動開的終端（如果有）"
# 比對 [.] 避免比對到這個 ssh 自己的指令列
ssh "$HOST" "systemctl is-active --quiet $UNIT && exit 0; pkill -TERM -f 'run_nous_terminal[.]sh' && sleep 4 || true; pgrep -c chromium >/dev/null && echo '   注意：還有 Chromium 在跑' || echo '   沒有其他 Chromium 在跑'"

echo "== 3/3 systemd 服務 $UNIT（enable、啟動）"
PI_USER="$(ssh "$HOST" 'id -un')"
PI_HOME="$(ssh "$HOST" 'echo $HOME')"
ssh "$HOST" "sudo tee /etc/systemd/system/$UNIT.service >/dev/null" <<EOF2
[Unit]
Description=Nous Duck voice terminal: Chromium opens the Nous page ?terminal=duck (route 2; nous_duck/robot/deploy/pi4/terminal/run_nous_terminal.sh)
After=network-online.target sound.target duckd.service duck-voice.service
Wants=network-online.target

[Service]
User=$PI_USER
SupplementaryGroups=audio video
WorkingDirectory=$PI_HOME/duck/terminal-spike
Environment=AIOS_PORT=$AIOS_PORT
Environment=DUCK_TERMINAL_ID=duck
# 使用者 2026-11-27 決定開機常駐：服務本身就是「同意出聲、同意麥克風開著」。
Environment=I_AM_PRESENT_AND_OK_WITH_SOUND=yes
ExecStart=/bin/bash $PI_HOME/duck/terminal-spike/run_nous_terminal.sh --display headless --auto-accept-mic --alsa-config $PI_HOME/duck/voice/alsa/duck-audio.conf --mic duck_mic --speaker auto
# 通道沒開（Mac 關機或 Nous 沒跑）時腳本會結束；等一下再試。
Restart=always
RestartSec=30
# 先只送 TERM 給腳本，讓它自己收掉 Chromium；逾時再全部砍掉。
KillMode=mixed
TimeoutStopSec=20
Nice=5

[Install]
WantedBy=multi-user.target
EOF2
ssh "$HOST" "sudo systemctl daemon-reload && sudo systemctl enable --now $UNIT && sleep 12 && systemctl is-enabled $UNIT && systemctl is-active $UNIT && pgrep -c chromium | sed 's/^/   Chromium 行程數：/'"
cat <<MSG

狀態：bash $0 --status $HOST
log： ssh $HOST 'journalctl -u $UNIT -f'（Chromium 自己的輸出在 ~/duck/terminal-spike/nous-terminal.log）
停止：ssh $HOST 'sudo systemctl stop $UNIT'　　移除：bash $0 --uninstall $HOST
MSG
