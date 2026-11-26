#!/bin/bash
# 部署「鴨子設定頁」（nous_duck/robot/settings，ADR-0019）到 Pi 4，裝成 systemd 服務 duck-settings。
#
# 用法（在 repo 的 checkout 裡）：
#   bash nous_duck/robot/deploy/pi4/deploy_settings.sh [host]              # 安裝；**不 enable、不啟動**。預設 host = duck-pi4
#   bash nous_duck/robot/deploy/pi4/deploy_settings.sh --start [host]      # 安裝後啟動（這次開機有效，重開機後不會自己起來）
#   bash nous_duck/robot/deploy/pi4/deploy_settings.sh --enable [host]     # 安裝、啟動，並設成開機自動啟動
#   bash nous_duck/robot/deploy/pi4/deploy_settings.sh --uninstall [host]
#
# 前提：先跑過 deploy_duckd.sh（用它的 ~/duck/duckd-venv：Python 3.11、numpy 與 duck_eyes 給表情預覽圖用）。
#
# 做的事：
#   1. 複製 duck_settings 到 ~/duck/settings/app/。設定資料在 ~/duck/settings/（settings.json、calibration.json、
#      history/、applied/、changes.jsonl），**已經有的不覆蓋**。
#   2. 在 ~/duck/duckd-venv 加一個 .pth，讓 duckd、duck-doa、設定頁都匯入同一份 duck_settings（不動 runtime-venv）。
#   3. 第一次：把 ~/duck/doa/config/doa.json 裡手改過的值（正前方校正值、方向、能量門檻…）搬進設定。
#   4. systemd 服務 duck-settings（埠 8081）。服務**碰不到舵機匯流排**：PrivateDevices=true，/dev/ttyACM0 對它不存在。
#
# 不做的事：不啟動、不停止、不重啟 duckd／duck-doa／duck-console；不碰舵機、I2C、GPIO；不重開機。
# duckd 與 duck-doa 要重新部署（deploy_duckd.sh、setup_doa.sh）並重啟後才會讀這份設定。
#
# 存取：預設不需要 token，只接受區網內的來源位址（比照舵機控制台 2026-11-25 的決定）。要 token：SETTINGS_REQUIRE_TOKEN=1。
set -euo pipefail

MODE=install
case "${1:-}" in
  --uninstall) MODE=uninstall; shift ;;
  --start) MODE=start; shift ;;
  --enable) MODE=enable; shift ;;
  -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
  --*) echo "不認得的參數：$1" >&2; exit 2 ;;
esac
HOST="${1:-duck-pi4}"
PORT="${SETTINGS_PORT:-8081}"
REPO="$(cd "$(dirname "$0")/../../../.." && pwd)"
SRC="$REPO/nous_duck/robot/settings"
UNIT=duck-settings

if [ "$MODE" = uninstall ]; then
  ssh "$HOST" "sudo systemctl disable --now $UNIT 2>/dev/null || true; sudo rm -f /etc/systemd/system/$UNIT.service; sudo systemctl daemon-reload; rm -f ~/duck/duckd-venv/lib/python*/site-packages/nous_duck_settings.pth"
  echo "已停止並移除 $UNIT 服務與 .pth（~/duck/settings 的設定資料保留；duckd、duck-doa 之後會退回內建預設與 doa.json）"
  exit 0
fi

ssh "$HOST" 'test -x ~/duck/duckd-venv/bin/python' || { echo "Pi 上沒有 ~/duck/duckd-venv，先跑 deploy_duckd.sh"; exit 1; }

echo "== 1/4 複製到 $HOST:~/duck/settings/app"
ssh "$HOST" 'mkdir -p ~/duck/settings/app && rm -rf ~/duck/settings/app/duck_settings'
TAR_OPTS=()
[ "$(uname)" = Darwin ] && TAR_OPTS=(--no-xattrs --no-mac-metadata)
COPYFILE_DISABLE=1 tar "${TAR_OPTS[@]}" -C "$SRC" --exclude '__pycache__' -cf - duck_settings | ssh "$HOST" 'tar -C ~/duck/settings/app -xf -'
ssh "$HOST" 'cat > ~/duck/settings/duck-settings && chmod +x ~/duck/settings/duck-settings' <<'CTL'
#!/bin/bash
# 鴨子設定的本機命令列：list／get／set／reset／import-doa（見 python -m duck_settings.cli --help）
exec "$HOME/duck/duckd-venv/bin/python" -m duck_settings.cli --dir "$HOME/duck/settings" "$@"
CTL

echo "== 2/4 把 duck_settings 接進 ~/duck/duckd-venv（.pth；不動 runtime-venv）"
ssh "$HOST" 'bash -s' <<'REMOTE'
set -euo pipefail
PY="$HOME/duck/duckd-venv/bin/python"
SITE="$("$PY" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
printf '%s\n' "$HOME/duck/settings/app" > "$SITE/nous_duck_settings.pth"
"$PY" - <<'PY'
import duck_settings, duck_settings.schema as s
try:
    import numpy, duck_eyes
    preview = f"表情預覽可用（numpy {numpy.__version__}）"
except ImportError as exc:
    preview = f"表情預覽不能用：{exc}"
print(f"   duck_settings {duck_settings.__version__}：{len(s.SETTINGS)} 項設定，其中 {sum(x.writable for x in s.SETTINGS)} 項可以設定；{preview}")
PY
REMOTE

echo "== 3/4 搬移既有的 doa.json（只在還沒有 calibration.json 時做一次）"
ssh "$HOST" 'bash -s' <<'REMOTE'
set -euo pipefail
if [ -f ~/duck/settings/calibration.json ] || [ -f ~/duck/settings/settings.json ]; then
  echo "   已經有設定資料，不搬移"
elif [ -f ~/duck/doa/config/doa.json ]; then
  ~/duck/settings/duck-settings import-doa ~/duck/doa/config/doa.json
else
  echo "   沒有 ~/duck/doa/config/doa.json，全部用預設值"
fi
REMOTE

echo "== 4/4 systemd 服務 $UNIT"
PI_USER="$(ssh "$HOST" 'id -un')"
PI_HOME="$(ssh "$HOST" 'echo $HOME')"
AUTH_ARG=""
RW="$PI_HOME/duck/settings"
if [ "${SETTINGS_REQUIRE_TOKEN:-0}" = 1 ]; then
  AUTH_ARG=" --require-token"
  ssh "$HOST" 'mkdir -p ~/.config/nous-duck'
  RW="$RW $PI_HOME/.config/nous-duck"
fi
ssh "$HOST" "sudo tee /etc/systemd/system/$UNIT.service >/dev/null" <<EOF2
[Unit]
Description=Nous Duck settings page (nous_duck/robot/settings, ADR-0019)
After=network-online.target
Wants=network-online.target

[Service]
User=$PI_USER
WorkingDirectory=$PI_HOME/duck/settings
ExecStart=$PI_HOME/duck/duckd-venv/bin/python -m duck_settings --dir $PI_HOME/duck/settings --port $PORT$AUTH_ARG
Restart=on-failure
RestartSec=3
# 這個服務只讀寫設定檔：看不到任何硬體裝置（舵機匯流排、I2C、GPIO、USB），也不能改系統。
PrivateDevices=true
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=$RW
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF2
ssh "$HOST" "sudo systemctl daemon-reload"

case "$HOST" in *.*) WEB_HOST="$HOST" ;; *) WEB_HOST="$HOST.local" ;; esac
URL="http://$WEB_HOST:$PORT/"
if [ "$MODE" = install ]; then
  cat <<MSG

安裝完成。服務沒有 enable、沒有啟動。
  啟動：        ssh $HOST 'sudo systemctl start $UNIT'      然後開 $URL
  開機自動啟動：ssh $HOST 'sudo systemctl enable --now $UNIT'
  本機指令：    ssh $HOST '~/duck/settings/duck-settings list'
MSG
  exit 0
fi

if [ "$MODE" = enable ]; then
  ssh "$HOST" "sudo systemctl enable --quiet $UNIT && sudo systemctl restart $UNIT"
else
  ssh "$HOST" "sudo systemctl restart $UNIT"
fi
for _ in $(seq 20); do
  if ssh "$HOST" "curl -fsS -m 2 http://127.0.0.1:$PORT/healthz >/dev/null 2>&1"; then break; fi
  sleep 0.5
done
ssh "$HOST" "systemctl is-active --quiet $UNIT" || { ssh "$HOST" "journalctl -u $UNIT -n 30 --no-pager"; exit 1; }
echo
if [ -n "$AUTH_ARG" ]; then
  TOKEN="$(ssh "$HOST" 'cat ~/.config/nous-duck/settings_token')"
  echo "設定頁已啟動（網址含 token，不要貼到公開的地方）：$URL#t=$TOKEN"
else
  echo "設定頁已啟動（不需要 token；只接受區網內的裝置）：$URL"
fi
[ "$MODE" = enable ] && echo "已設成開機自動啟動。" || echo "沒有設成開機自動啟動：Pi 重開機後要再啟動一次（或改用 --enable）。"
