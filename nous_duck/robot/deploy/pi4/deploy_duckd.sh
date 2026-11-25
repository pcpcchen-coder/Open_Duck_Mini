#!/bin/bash
# 部署 duckd（鴨子端常駐程式，nous_duck/robot/duckd）到 Pi 4，裝成 systemd 服務 duckd。
#
# 用法（在 repo 的 checkout 裡）：
#   bash nous_duck/robot/deploy/pi4/deploy_duckd.sh [host]              # 預設 host = duck-pi4
#   bash nous_duck/robot/deploy/pi4/deploy_duckd.sh --test [host]       # 部署後在 Pi 上跑測試（含上游步態腳本的載入測試）
#   bash nous_duck/robot/deploy/pi4/deploy_duckd.sh --uninstall [host]
#
# 前提：Pi 上已經跑過 setup_runtime.sh（~/duck/runtime-venv、~/duck/Open_Duck_Mini_Runtime、~/duck/uv-tool）。
#
# 做的事：
#   1. 複製 duckd、它重用的 servo_console 與 duck_eyes 套件、duck-link schema 到 ~/duck/duckd/
#      （和舵機控制台的 ~/duck/console/ 分開，不動那邊）。
#   2. 建獨立的 venv ~/duck/duckd-venv，依 duckd/requirements.txt 裝 websockets、jsonschema。
#      **不動 ~/duck/runtime-venv**：pypot、numpy、onnxruntime 等用一個 .pth 把 runtime-venv 的 site-packages
#      接在後面唯讀沿用（版本就是 runtime-constraints.txt 鎖的那些）。
#   3. 安裝 systemd 服務 duckd：**不 enable、不啟動**。啟動後也**不碰硬體**，要在 Pi 上明確下
#      `~/duck/duckd/duckd-ctl engage` 才會開匯流排、讓頭部出力。
#
# 與舵機控制台（duck-console）互斥：兩個服務可以同時跑，但舵機匯流排同一時間只給一個。
# duckd 接手前會檢查 /dev/ttyACM0 有沒有被別的程式開著，有就拒絕（不搶）；控制台那邊也有同樣的檢查。
set -euo pipefail

MODE=deploy
case "${1:-}" in
  --uninstall) MODE=uninstall; shift ;;
  --test) MODE=test; shift ;;
esac
HOST="${1:-duck-pi4}"
REPO="$(cd "$(dirname "$0")/../../../.." && pwd)"
ROBOT="$REPO/nous_duck/robot"
UNIT=duckd

if [ "$MODE" = uninstall ]; then
  ssh "$HOST" "sudo systemctl disable --now $UNIT 2>/dev/null || true; sudo rm -f /etc/systemd/system/$UNIT.service; sudo systemctl daemon-reload"
  echo "已停止並移除 $UNIT 服務（~/duck/duckd 與 ~/duck/duckd-venv 保留；要刪請自己刪）"
  exit 0
fi

echo "== 1/3 複製到 $HOST:~/duck/duckd"
ssh "$HOST" 'test -x ~/duck/runtime-venv/bin/python && test -x ~/duck/uv-tool/bin/uv' || { echo "Pi 上沒有 ~/duck/runtime-venv 或 ~/duck/uv-tool，先跑 setup_runtime.sh"; exit 1; }
if ssh "$HOST" "systemctl is-active --quiet $UNIT"; then
  echo "duckd 服務正在跑：先停掉（它會把頭送回原位、恢復扭力、放開匯流排）"
  ssh "$HOST" "sudo systemctl stop $UNIT"
fi
ssh "$HOST" 'mkdir -p ~/duck/duckd && rm -rf ~/duck/duckd/duckd ~/duck/duckd/tests ~/duck/duckd/servo_console ~/duck/duckd/duck_eyes'
TAR_OPTS=()
[ "$(uname)" = Darwin ] && TAR_OPTS=(--no-xattrs --no-mac-metadata)
copy() { COPYFILE_DISABLE=1 tar "${TAR_OPTS[@]}" -C "$1" --exclude '__pycache__' --exclude '.pytest_cache' -cf - "${@:2}" | ssh "$HOST" 'tar -C ~/duck/duckd -xf -'; }
copy "$ROBOT/duckd" duckd tests requirements.txt requirements-dev.txt
copy "$ROBOT/servo_console" servo_console
copy "$ROBOT/eyes" duck_eyes
scp -q "$REPO/nous_duck/protocol/schemas/duck-link.v0.schema.json" "$HOST:duck/duckd/"
ssh "$HOST" 'cat > ~/duck/duckd/duckd-ctl && chmod +x ~/duck/duckd/duckd-ctl' <<'CTL'
#!/bin/bash
# duckd 本機控制：status／engage／release／estop／clear-estop（見 python -m duckd.ctl --help）
exec "$HOME/duck/duckd-venv/bin/python" -m duckd.ctl "$@"
CTL

echo "== 2/3 venv ~/duck/duckd-venv（不動 runtime-venv）"
ssh "$HOST" 'bash -s' <<'REMOTE'
set -euo pipefail
UV="$HOME/duck/uv-tool/bin/uv"
RT_PY="$HOME/duck/runtime-venv/bin/python"
VENV="$HOME/duck/duckd-venv"
before="$("$UV" pip freeze --python "$RT_PY" | sha256sum)"
[ -x "$VENV/bin/python" ] || "$UV" venv --quiet --python "$("$RT_PY" -c 'import sys; print(sys._base_executable)')" "$VENV"
"$UV" pip install --quiet --python "$VENV/bin/python" -r "$HOME/duck/duckd/requirements.txt" pytest==9.2.0
SITE="$("$VENV/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
RT_SITE="$("$RT_PY" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
# 一行一個：duckd 的部署目錄；再把 runtime-venv 的 site-packages（含它的 editable 安裝）接在後面
printf '%s\nimport site; site.addsitedir(%s)\n' "$HOME/duck/duckd" "'$RT_SITE'" > "$SITE/nous_duck_duckd.pth"
after="$("$UV" pip freeze --python "$RT_PY" | sha256sum)"
[ "$before" = "$after" ] || { echo "runtime-venv 的套件變了，不應該發生"; exit 1; }
"$VENV/bin/python" - <<'PY'
import duckd, websockets, jsonschema, numpy, pypot, servo_console, duck_eyes, mini_bdx_runtime
print(f"   duckd {duckd.__version__}；websockets {websockets.__version__}、jsonschema {jsonschema.__version__}（duckd-venv）；"
      f"numpy {numpy.__version__}、pypot（runtime-venv，唯讀沿用）")
PY
REMOTE

echo "== 3/3 systemd 服務 $UNIT（不 enable、不啟動）"
PI_USER="$(ssh "$HOST" 'id -un')"
PI_HOME="$(ssh "$HOST" 'echo $HOME')"
ssh "$HOST" "sudo tee /etc/systemd/system/$UNIT.service >/dev/null" <<EOF2
[Unit]
Description=Nous Duck duckd (duck-link client, head only; nous_duck/robot/duckd)
After=network-online.target
Wants=network-online.target

[Service]
User=$PI_USER
WorkingDirectory=$PI_HOME/duck/duckd
RuntimeDirectory=duckd
RuntimeDirectoryMode=0700
# 啟動時不碰硬體：要在 Pi 上執行 ~/duck/duckd/duckd-ctl engage 才會開匯流排。
# --head-window-deg 15 --head-speed-deg 30 是 2026-11-25 無人看顧時的規定（初始值，使用者看過實機後再放寬）。
ExecStart=$PI_HOME/duck/duckd-venv/bin/python -m duckd --body head --head-window-deg 15 --head-speed-deg 30 --ctl-socket /run/duckd/duckd.sock --eyes-panel /run/duckd/eyes.png ${DUCKD_EXTRA_ARGS:-}
Restart=on-failure
RestartSec=3
# 結束時：頭以限速回到接手時的位置、恢復接手前的扭力狀態、放開匯流排
KillSignal=SIGTERM
TimeoutStopSec=15

[Install]
WantedBy=multi-user.target
EOF2
ssh "$HOST" "sudo systemctl daemon-reload"

if [ "$MODE" = test ]; then
  echo "== 在 Pi 上跑測試（不碰硬體；上游步態腳本用假的硬體介面載入）"
  ssh "$HOST" 'cd ~/duck/duckd && DUCK_RUNTIME_DIR=~/duck/Open_Duck_Mini_Runtime DUCK_ONNX=~/duck/BEST_WALK_ONNX_2.onnx ~/duck/duckd-venv/bin/python -m pytest tests -q -s -p no:cacheprovider'
fi

cat <<'MSG'

部署完成。服務沒有 enable、沒有啟動。
  啟動：        ssh duck-pi4 'sudo systemctl start duckd'
  接手頭部：    ssh duck-pi4 '~/duck/duckd/duckd-ctl engage'     # 先確認舵機控制台沒有連線匯流排
  看狀態：      ssh duck-pi4 '~/duck/duckd/duckd-ctl status'
  釋放並停止：  ssh duck-pi4 'sudo systemctl stop duckd'
  通道（Mac）： ssh -N -R 127.0.0.1:8791:127.0.0.1:8791 duck-pi4
MSG
