#!/bin/bash
# Mac 這一半的開機常駐（路線 2）：Nous 開發實例＋到鴨子的 SSH 通道，裝成使用者的 launchd LaunchAgent。
#
# 使用者 2026-11-27 決定：「Mac 也要常駐」（Pi 那一半是 duck-terminal 服務，見 robot/deploy/pi4/deploy_terminal_service.sh）。
#
# 用法（在 Mac 上）：
#   bash nous_duck/tools/mac_launch_agents.sh             # 安裝並啟動（會先停掉手動開的同一個開發實例與通道）
#   bash nous_duck/tools/mac_launch_agents.sh --status    # 只看狀態
#   bash nous_duck/tools/mac_launch_agents.sh --uninstall # 停掉並移除兩個 LaunchAgent（不動設定目錄與 clone）
#
# 兩個 LaunchAgent（登入 Mac 後啟動；掛掉就重開，間隔至少 30 秒）：
#   com.nousduck.nous-dev    在 AIOS 的 clone（預設 ~/AIOS-duck-link/prototype/ambient-shell）執行 npm start，
#                            PORT=8791、NOUS_DUCK=on、NOUS_AIL=on、NOUS_AIL_SERVICES=duck、
#                            NOUS_CONFIG_DIR=~/.config/nous-duck-dev、NOUS_OAUTH_PORT=1456。不寫 .env。
#   com.nousduck.duck-tunnel ssh -N -R 127.0.0.1:8791:127.0.0.1:8791 duck-pi4（鴨子連回 Nous 用；BatchMode，不問密碼）
#   log：~/Library/Logs/nous-duck-dev/{nous.log,tunnel.log}
#
# 不做的事：不動 /Applications/Nous.app（8787）與 ~/AIOS、不讀也不寫金鑰與 .env、不改系統設定（只寫 ~/Library/LaunchAgents）。
# 注意：LaunchAgent 在「使用者登入後」才跑；Mac 開機停在登入畫面時不會跑。
set -euo pipefail

MODE=install
case "${1:-}" in
  --status) MODE=status ;;
  --uninstall) MODE=uninstall ;;
  -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
  "") ;;
  *) echo "不認得的參數：$1" >&2; exit 2 ;;
esac

APP_DIR="${NOUS_DUCK_AIOS_DIR:-$HOME/AIOS-duck-link/prototype/ambient-shell}"
PORT="${NOUS_DUCK_PORT:-8791}"
PI_HOST="${NOUS_DUCK_PI_HOST:-duck-pi4}"
AGENTS="$HOME/Library/LaunchAgents"
LOGS="$HOME/Library/Logs/nous-duck-dev"
NOUS=com.nousduck.nous-dev
TUNNEL=com.nousduck.duck-tunnel
DOMAIN="gui/$(id -u)"

status() {
  for l in $NOUS $TUNNEL; do
    if launchctl print "$DOMAIN/$l" >/dev/null 2>&1; then
      echo "$l：$(launchctl print "$DOMAIN/$l" | awk -F'= ' '/^\tstate =/{s=$2} /^\tpid =/{p=$2} END{print s (p ? "，pid " p : "")}')"
    else
      echo "$l：沒有載入"
    fi
  done
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1 && echo "Nous 在聽 127.0.0.1:$PORT" || echo "沒有人在聽 $PORT"
}

if [ "$MODE" = status ]; then status; exit 0; fi
if [ "$MODE" = uninstall ]; then
  for l in $NOUS $TUNNEL; do
    launchctl bootout "$DOMAIN/$l" 2>/dev/null || true
    rm -f "$AGENTS/$l.plist"
  done
  echo "已移除兩個 LaunchAgent（設定目錄、clone 與 log 保留）"
  exit 0
fi

case "$PORT" in ''|*[!0-9]*) echo "NOUS_DUCK_PORT 要是數字" >&2; exit 2 ;; esac
[ "$PORT" = 8787 ] && { echo "8787 是平常用的 Nous，不能用" >&2; exit 2; }
[ -f "$APP_DIR/package.json" ] || { echo "找不到 AIOS 的 clone：$APP_DIR" >&2; exit 1; }
[ -d "$APP_DIR/node_modules" ] || { echo "$APP_DIR 還沒 npm ci" >&2; exit 1; }
NPM="$(command -v npm)" || { echo "找不到 npm" >&2; exit 1; }
NODE_BIN="$(dirname "$(command -v node)")"
SSH="$(command -v ssh)"
mkdir -p "$AGENTS" "$LOGS" "$HOME/.config/nous-duck-dev"

echo "== 1/3 停掉手動開的同一個開發實例與通道（如果有）"
for l in $NOUS $TUNNEL; do launchctl bootout "$DOMAIN/$l" 2>/dev/null || true; done
# 只找「在 $APP_DIR 跑、聽 $PORT 的 node」與「轉 $PORT 到 $PI_HOST 的 ssh」；8787 的 Nous 不會被比對到
for pid in $(lsof -nP -t -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null); do
  if [ "$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')" = "$APP_DIR" ]; then
    parent="$(ps -o ppid= -p "$pid" | tr -d ' ')"
    echo "   停掉開發實例 pid $pid"
    kill -TERM "$pid" "$parent" 2>/dev/null || true
  else
    echo "   $PORT 被別的程式占著（pid $pid），不動它；請先自己關掉" >&2; exit 1
  fi
done
pkill -TERM -f "ssh .*-R 127\.0\.0\.1:$PORT:127\.0\.0\.1:$PORT $PI_HOST" 2>/dev/null && echo "   停掉手動開的通道" || true
sleep 3

echo "== 2/3 寫 LaunchAgent"
cat > "$AGENTS/$NOUS.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$NOUS</string>
  <key>ProgramArguments</key><array><string>$NPM</string><string>start</string></array>
  <key>WorkingDirectory</key><string>$APP_DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$NODE_BIN:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>PORT</key><string>$PORT</string>
    <key>NOUS_DUCK</key><string>on</string>
    <key>NOUS_AIL</key><string>on</string>
    <key>NOUS_AIL_SERVICES</key><string>duck</string>
    <key>NOUS_CONFIG_DIR</key><string>$HOME/.config/nous-duck-dev</string>
    <key>NOUS_OAUTH_PORT</key><string>1456</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>$LOGS/nous.log</string>
  <key>StandardErrorPath</key><string>$LOGS/nous.log</string>
</dict>
</plist>
EOF
cat > "$AGENTS/$TUNNEL.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$TUNNEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$SSH</string><string>-N</string>
    <string>-o</string><string>BatchMode=yes</string>
    <string>-o</string><string>ExitOnForwardFailure=yes</string>
    <string>-o</string><string>ServerAliveInterval=30</string>
    <string>-o</string><string>ServerAliveCountMax=3</string>
    <string>-o</string><string>ConnectTimeout=15</string>
    <string>-R</string><string>127.0.0.1:$PORT:127.0.0.1:$PORT</string>
    <string>$PI_HOST</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>$LOGS/tunnel.log</string>
  <key>StandardErrorPath</key><string>$LOGS/tunnel.log</string>
</dict>
</plist>
EOF
plutil -lint "$AGENTS/$NOUS.plist" "$AGENTS/$TUNNEL.plist" | sed 's/^/   /'

echo "== 3/3 載入並啟動"
launchctl bootstrap "$DOMAIN" "$AGENTS/$NOUS.plist"
launchctl bootstrap "$DOMAIN" "$AGENTS/$TUNNEL.plist"
for _ in $(seq 1 60); do
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1 && break
  sleep 2
done
status
cat <<MSG

log：$LOGS/nous.log、$LOGS/tunnel.log
移除：bash $0 --uninstall
MSG
