#!/usr/bin/env bash
# D 線：在 Pi 4 上建立感知用的 venv 並下載模型（可重複執行）。
#
# 做的事（只在使用者家目錄，不裝系統套件、不用 sudo）：
#   1. 建 ~/duck/perception-venv（系統 python3 的 venv；不動 ~/duck/runtime-venv）
#   2. 依 ~/duck/d-line/perception/requirements.txt 安裝 numpy、opencv-python-headless（鎖版本，PyPI 的 aarch64 wheel）
#   3. 執行 tools/fetch_models.py 下載 YuNet（MIT）並核對 SHA-256
#
# 前提：先把 nous_duck/robot/perception/ 與 nous_duck/robot/behaviors/ 同步到 Pi：
#   rsync -a --delete --exclude .venv --exclude models --exclude __pycache__ --exclude .pytest_cache \
#     nous_duck/robot/perception/ duck-pi4:duck/d-line/perception/
#   （D 線的檔案都放 ~/duck/d-line/ 底下，不和 A 線的部署目錄混在一起）
#   rsync -a --delete --exclude __pycache__ nous_duck/robot/behaviors/ duck-pi4:duck/d-line/behaviors/
# 然後在 Pi 上執行：（由 Mac）ssh duck-pi4 bash -s < nous_duck/robot/deploy/pi4/setup_perception.sh
#
# 不碰：舵機匯流排、I2C、GPIO、鏡頭（還沒有）、任何 systemd 服務。
set -euo pipefail

DUCK="${DUCK_HOME:-$HOME/duck}"
VENV="$DUCK/perception-venv"
SRC="$DUCK/d-line/perception"

[ -f "$SRC/requirements.txt" ] || { echo "找不到 $SRC/requirements.txt；先 rsync（見檔頭）" >&2; exit 1; }
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -r "$SRC/requirements.txt"
"$VENV/bin/python" "$SRC/tools/fetch_models.py"
"$VENV/bin/python" - <<'PY'
import cv2, numpy, sys
print("perception-venv OK：python", sys.version.split()[0], "numpy", numpy.__version__, "opencv", cv2.__version__)
PY
