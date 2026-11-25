#!/usr/bin/env bash
# D 線：在 Pi 4 上準備音訊用的環境（可重複執行）。
#
# 做的事：
#   1. 建 ~/duck/audio-venv（系統 python3 的 venv；不動 ~/duck/runtime-venv），裝 numpy（鎖版本）
#   2. 加 --kws：另外裝 sherpa-onnx（Apache-2.0，PyPI aarch64 wheel），給喚醒詞 spike（D7）用
#   3. 加 --system：用 apt 裝變聲 spike（D6）要比較的系統工具：
#        rubberband-cli（Rubber Band，GPL-2.0-or-later）、sox（GPL-2.0-or-later／LGPL）
#      這兩個只當系統套件安裝與呼叫，**不放進 repo、不連結進我們的程式**。會用到 sudo。
#
# 不做的事：不改 ~/.asoundrc、不改混音器音量、不裝 PipeWire、不播放任何聲音、
#           不碰舵機匯流排／I2C／GPIO、不新增 systemd 服務。
#
# 前提：先把 nous_duck/robot/audio/ 同步到 Pi（D 線的檔案都在 ~/duck/d-line/）：
#   rsync -a --delete --exclude models --exclude build --exclude __pycache__ --exclude .pytest_cache \
#     nous_duck/robot/audio/ duck-pi4:duck/d-line/audio/
# 然後（由 Mac）：ssh duck-pi4 bash -s -- [--kws] [--system] < nous_duck/robot/deploy/pi4/setup_audio.sh
set -euo pipefail

DUCK="${DUCK_HOME:-$HOME/duck}"
VENV="$DUCK/audio-venv"
SRC="$DUCK/d-line/audio"
WANT_KWS=0
WANT_SYSTEM=0
for arg in "$@"; do
  case "$arg" in
    --kws) WANT_KWS=1 ;;
    --system) WANT_SYSTEM=1 ;;
    *) echo "不認得的參數：$arg" >&2; exit 2 ;;
  esac
done

[ -f "$SRC/requirements.txt" ] || { echo "找不到 $SRC/requirements.txt；先 rsync（見檔頭）" >&2; exit 1; }
command -v aplay >/dev/null || { echo "找不到 aplay（alsa-utils）" >&2; exit 1; }

if [ "$WANT_SYSTEM" = 1 ]; then
  need=""
  for pkg in rubberband-cli sox; do
    dpkg -s "$pkg" >/dev/null 2>&1 || need="$need $pkg"
  done
  if [ -n "$need" ]; then
    echo "apt 安裝：$need"
    sudo apt-get update -qq
    # shellcheck disable=SC2086
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends $need
  fi
  dpkg-query -W -f='${Package} ${Version}\n' rubberband-cli sox
fi

if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --quiet --upgrade pip
if [ "$WANT_KWS" = 1 ]; then
  "$VENV/bin/python" -m pip install --quiet -r "$SRC/requirements-kws.txt"
else
  "$VENV/bin/python" -m pip install --quiet -r "$SRC/requirements.txt"
fi
"$VENV/bin/python" - <<'PY'
import numpy, sys
msg = f"audio-venv OK：python {sys.version.split()[0]} numpy {numpy.__version__}"
try:
    import sherpa_onnx
    msg += f" sherpa-onnx {sherpa_onnx.__version__}"
except ImportError:
    pass
print(msg)
PY
