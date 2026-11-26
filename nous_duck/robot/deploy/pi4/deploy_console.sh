#!/bin/bash
# 部署舵機控制台到 Pi 4（ADR-0008）：在 Mac 上建置頁面，複製到 Pi，裝成 systemd 服務 duck-console。
#
# 用法（在 repo 的 checkout 裡）：
#   bash nous_duck/robot/deploy/pi4/deploy_console.sh [host]        # 預設 host = duck-pi4
#   bash nous_duck/robot/deploy/pi4/deploy_console.sh --uninstall [host]
#
# 前提：Pi 上已經跑過 setup_runtime.sh（~/duck/runtime-venv 有 pypot、Blinka、adafruit_bno055）。
# Mac 上要有 Node.js 22 與 uv（或已經裝好 numpy、PyYAML 的 Python 3.10+）。
#
# 預設**不需要 token**（家裡區網使用）：同一個網路裡任何人都能操作。要開：CONSOLE_REQUIRE_TOKEN=1 bash deploy_console.sh
#
# 服務開機自動啟動，但**啟動時不碰硬體**：要在頁面上按「連線匯流排」才會打開序列埠、I2C、GPIO。
# 要跑上游的腳本（例如走路）前，先在頁面按「釋放硬體」，或 sudo systemctl stop duck-console。
set -euo pipefail

UNINSTALL=0
if [ "${1:-}" = "--uninstall" ]; then
  UNINSTALL=1
  shift
fi
HOST="${1:-duck-pi4}"
PORT="${CONSOLE_PORT:-8080}"
AUTH_ARG=""
[ "${CONSOLE_REQUIRE_TOKEN:-0}" = 1 ] && AUTH_ARG=" --require-token"
REPO="$(cd "$(dirname "$0")/../../../.." && pwd)"
AV="$REPO/nous_duck/assembly_viewer"
SC="$REPO/nous_duck/robot/servo_console"
UNIT=duck-console

if [ "$UNINSTALL" = 1 ]; then
  ssh "$HOST" "sudo systemctl disable --now $UNIT 2>/dev/null || true; sudo rm -f /etc/systemd/system/$UNIT.service; sudo systemctl daemon-reload"
  echo "已停止並移除 $UNIT 服務（~/duck/console 與 token 保留）"
  exit 0
fi

echo "== 1/4 產生 3D 模型資料（assembly_viewer pipeline）"
if [ ! -f "$AV/dist/build/scene.json" ] || [ "${REBUILD:-0}" = 1 ]; then
  if command -v uv >/dev/null; then
    (cd "$AV/pipeline" && uv run --quiet --python 3.12 --with-requirements requirements.txt python -m viewer_pipeline)
  else
    (cd "$AV/pipeline" && python3 -m viewer_pipeline)
  fi
else
  echo "   沿用 $AV/dist/build（要重建：REBUILD=1）"
fi

echo "== 2/4 打包頁面"
(cd "$AV/web" && { [ -d node_modules ] || npm ci; } && npm run -s build:console)

echo "== 3/4 複製到 $HOST:~/duck/console"
PI_HOME="$(ssh "$HOST" 'echo $HOME')"
ssh "$HOST" 'test -x ~/duck/runtime-venv/bin/python' || { echo "Pi 上沒有 ~/duck/runtime-venv，先跑 setup_runtime.sh"; exit 1; }
ssh "$HOST" 'mkdir -p ~/duck/console && rm -rf ~/duck/console/servo_console'
# macOS 的 tar 會帶 xattr（Linux 的 tar 會警告），關掉
TAR_OPTS=()
[ "$(uname)" = Darwin ] && TAR_OPTS=(--no-xattrs --no-mac-metadata)
COPYFILE_DISABLE=1 tar "${TAR_OPTS[@]}" -C "$SC" --exclude '__pycache__' -cf - servo_console | ssh "$HOST" 'tar -C ~/duck/console -xf -'
scp -q "$AV/dist/duck_console.html" "$AV/dist/console_joints.json" "$HOST:duck/console/"

echo "== 4/4 安裝 systemd 服務 $UNIT"
PI_USER="$(ssh "$HOST" 'id -un')"
ssh "$HOST" "sudo tee /etc/systemd/system/$UNIT.service >/dev/null" <<EOF
[Unit]
Description=Nous Duck servo console (local dev tool, nous_duck/robot/servo_console)
After=network-online.target
Wants=network-online.target

[Service]
User=$PI_USER
WorkingDirectory=$PI_HOME/duck/console
ExecStart=$PI_HOME/duck/runtime-venv/bin/python -m servo_console --html duck_console.html --joints console_joints.json --port $PORT$AUTH_ARG
Restart=on-failure
RestartSec=3
# 結束時只釋放硬體，不改扭力狀態（避免懸空時摔下來）
KillSignal=SIGTERM
TimeoutStopSec=5

[Install]
WantedBy=multi-user.target
EOF
ssh "$HOST" "sudo systemctl daemon-reload && sudo systemctl enable --quiet $UNIT && sudo systemctl restart $UNIT"

for _ in $(seq 20); do
  if ssh "$HOST" "curl -fsS -m 2 http://127.0.0.1:$PORT/healthz >/dev/null 2>&1"; then break; fi
  sleep 0.5
done
ssh "$HOST" "systemctl is-active --quiet $UNIT" || { ssh "$HOST" "journalctl -u $UNIT -n 30 --no-pager"; exit 1; }

case "$HOST" in *.*) WEB_HOST="$HOST" ;; *) WEB_HOST="$HOST.local" ;; esac
echo
if [ -n "$AUTH_ARG" ]; then
  TOKEN="$(ssh "$HOST" 'cat ~/.config/nous-duck/console_token')"
  echo "部署完成。用瀏覽器開（網址含 token，不要貼到公開的地方）："
  echo "  http://$WEB_HOST:$PORT/#t=$TOKEN"
else
  echo "部署完成（不需要 token：同一個網路裡任何人都能操作）。用瀏覽器開："
  echo "  http://$WEB_HOST:$PORT/"
fi
