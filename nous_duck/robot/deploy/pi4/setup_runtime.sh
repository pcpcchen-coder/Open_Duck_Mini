#!/bin/bash
# 單板 Pi 4（ADR-0008）：在 Pi 4 上安裝上游 Open_Duck_Mini_Runtime v2，鎖定 commit 與全部套件版本。
# 在 Mac（或任何有 ssh 的電腦）上執行，SSH 進 Pi 安裝；可以重複執行，已裝好的部分會沿用。
#
# 用法：
#   bash setup_runtime.sh               # 裝到 duck-pi4（~/.ssh/config 裡的 Host）
#   bash setup_runtime.sh duck-pi4b     # 指定其他 Host
#   bash setup_runtime.sh --check       # 不安裝，只跑煙霧測試
#
# 為什麼用 Python 3.11：Pi 4 的 Trixie 預設是 Python 3.13，上游鎖的 onnxruntime 1.18.1、numpy 1.26.4、
# pygame 2.6.0 沒有 3.13 版；上游 Pi Zero 2 W 的環境是 Bookworm（Python 3.11）。用 uv 另外裝 3.11，不動系統 Python。
#
# 安裝到 Pi 的 ~/duck/：Open_Duck_Mini_Runtime/（git，鎖 commit）、uv-tool/（uv）、runtime-venv/（Python 3.11）、
# BEST_WALK_ONNX_2.onnx（步態策略，從本 repo 根目錄複製）。~/duck_config.json 不存在時從上游範例複製。
# 會打開 I2C（BNO055 IMU 用），第一次打開要重開機。不會動舵機：煙霧測試只檢查裝置是否存在。

set -euo pipefail

CHECK_ONLY=0
HOST="duck-pi4"
for a in "$@"; do
  case "$a" in
    --check) CHECK_ONLY=1 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    -*) echo "不認得的選項：$a" >&2; exit 2 ;;
    *) HOST=$a ;;
  esac
done

RUNTIME_COMMIT="376de65435c93486347cd601a31aa96951799896"
UV_VERSION="0.13.9"
PY_VERSION="3.11.18"
ONNX_NAME="BEST_WALK_ONNX_2.onnx"
ONNX_SHA256="3c606f9381a1710cc8fecdb7442787dcbfce3ee9bc02a6f1224774ab2b3a1067"
DUCK_DIR="${DUCK_DIR:-duck}"   # 相對於 Pi 上的家目錄
SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=15"

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../../../.." && pwd)
CONSTRAINTS="$HERE/runtime-constraints.txt"

remote_setup() {
  cat <<'REMOTE'
set -euo pipefail
DUCK_DIR=$HOME/$1 COMMIT=$2 UV_VERSION=$3 PY=$4
mkdir -p "$DUCK_DIR"
cd "$DUCK_DIR"

echo "==> 上游 runtime（commit ${COMMIT:0:7}）"
if [ ! -d Open_Duck_Mini_Runtime/.git ]; then
  git clone -q https://github.com/apirrone/Open_Duck_Mini_Runtime.git
fi
if ! git -C Open_Duck_Mini_Runtime cat-file -e "$COMMIT^{commit}" 2>/dev/null; then
  git -C Open_Duck_Mini_Runtime fetch -q origin
fi
git -C Open_Duck_Mini_Runtime checkout -q "$COMMIT"

echo "==> uv $UV_VERSION 與 Python $PY"
[ -x uv-tool/bin/pip ] || python3 -m venv uv-tool
uv-tool/bin/pip install -q --disable-pip-version-check "uv==$UV_VERSION"
UV=$DUCK_DIR/uv-tool/bin/uv
"$UV" python install -q "$PY"
if [ ! -x runtime-venv/bin/python ] || [ "$(runtime-venv/bin/python -c 'import platform;print(platform.python_version())')" != "$PY" ]; then
  rm -rf runtime-venv
  "$UV" venv -q --python "$PY" runtime-venv
fi

echo "==> 安裝 runtime 與鎖定的套件（第一次約 1–2 分鐘）"
# gpiod：Blinka 在 Pi 4 的新 kernel 上需要它才能用 board 模組，上游 setup.cfg 沒有列
"$UV" pip install -q --python runtime-venv/bin/python -c runtime-constraints.txt -e ./Open_Duck_Mini_Runtime gpiod

echo "==> I2C（BNO055）"
if grep -q '^dtparam=i2c_arm=on' /boot/firmware/config.txt; then
  echo "已開啟"
else
  sudo -n raspi-config nonint do_i2c 0
  echo "剛打開，要重開機才會有 /dev/i2c-1：sudo reboot"
fi

if [ -e "$HOME/duck_config.json" ]; then
  echo "==> ~/duck_config.json 已存在，不覆蓋"
else
  cp Open_Duck_Mini_Runtime/example_config.json "$HOME/duck_config.json"
  echo "==> 已從上游範例建立 ~/duck_config.json（joints_offsets 全是 0，之後用 find_soft_offsets.py 校正）"
fi
REMOTE
}

remote_check() {
  cat <<'REMOTE'
set -u
DUCK_DIR=$HOME/$1 ONNX_SHA=$2 ONNX_NAME=$3
cd "$HOME"   # 不在 runtime 目錄裡跑，避免同名資料夾蓋過已安裝的套件
PY=$DUCK_DIR/runtime-venv/bin/python
echo
echo "| 項目 | 結果 |"
echo "|---|---|"
if [ ! -x "$PY" ]; then echo "| runtime-venv | ❌ 不存在，先跑 setup_runtime.sh |"; exit 1; fi
echo "| Python | $("$PY" --version 2>&1) |"
echo "| runtime commit | \`$(git -C "$DUCK_DIR/Open_Duck_Mini_Runtime" rev-parse --short HEAD)\` |"
"$PY" - "$DUCK_DIR/$ONNX_NAME" "$ONNX_SHA" <<'PYEOF' 2>&1 | grep -v -iE 'warning|pygame|^Hello'
import hashlib, importlib, os, sys, time
mods = ["mini_bdx_runtime.rustypot_position_hwi", "mini_bdx_runtime.onnx_infer",
        "mini_bdx_runtime.xbox_controller", "mini_bdx_runtime.duck_config",
        "mini_bdx_runtime.poly_reference_motion", "mini_bdx_runtime.rl_utils",
        "mini_bdx_runtime.sounds", "mini_bdx_runtime.imu", "mini_bdx_runtime.feet_contacts",
        "mini_bdx_runtime.antennas", "mini_bdx_runtime.eyes", "mini_bdx_runtime.projector",
        "board", "adafruit_bno055", "pypot.feetech", "rustypot"]
bad = []
for m in mods:
    try:
        importlib.import_module(m)
    except Exception as e:
        bad.append(f"{m}（{type(e).__name__}: {str(e)[:80]}）")
print(f"| 匯入 {len(mods)} 個模組 | " + ("✅ 全部成功" if not bad else "❌ 失敗：" + "；".join(bad)) + " |")
try:
    import board
    print(f"| Blinka 板子 | {board.board_id} |")
except Exception as e:
    print(f"| Blinka 板子 | ❌ {type(e).__name__} |")
path, want = sys.argv[1], sys.argv[2]
if not os.path.exists(path):
    print(f"| 步態策略 | ❌ 沒有 {os.path.basename(path)} |")
else:
    got = hashlib.sha256(open(path, "rb").read()).hexdigest()
    if got != want:
        print(f"| 步態策略 | ❌ SHA-256 不符：{got[:12]}… |")
    else:
        import numpy as np, onnxruntime as ort
        s = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        i = s.get_inputs()[0]
        x = np.zeros([d if isinstance(d, int) else 1 for d in i.shape], dtype=np.float32)
        for _ in range(20):
            s.run(None, {i.name: x})
        ts = []
        for _ in range(500):
            t = time.perf_counter(); s.run(None, {i.name: x}); ts.append((time.perf_counter() - t) * 1000)
        ts.sort()
        print(f"| 步態策略推論（500 次，閒置） | 輸入 {i.shape}，p50 {ts[250]:.2f} ms、p99 {ts[495]:.2f} ms、最大 {ts[-1]:.2f} ms（50 Hz 每步 20 ms） |")
PYEOF
if [ -e /dev/i2c-1 ]; then
  found=$(/usr/sbin/i2cdetect -y 1 2>/dev/null | awk 'NR>1{for(i=2;i<=NF;i++) if($i!="--") printf "0x%s ", $i}')
  case " $found" in
    *" 0x28 "*|*" 0x29 "*) echo "| I2C／BNO055 | ✅ /dev/i2c-1，找到 $found |" ;;
    *) echo "| I2C／BNO055 | ⚠️ /dev/i2c-1 有，但沒看到 BNO055（0x28／0x29）${found:+；有 $found} |" ;;
  esac
else
  echo "| I2C／BNO055 | ⚠️ 沒有 /dev/i2c-1（剛打開的話要重開機） |"
fi
if [ -e /dev/ttyACM0 ]; then echo "| 舵機驅動板 | ✅ /dev/ttyACM0 |"
else echo "| 舵機驅動板 | ⚠️ 沒有 /dev/ttyACM0（Waveshare 板沒接 USB） |"; fi
[ -e "$HOME/duck_config.json" ] && echo "| duck_config.json | ✅ ~/duck_config.json |" || echo "| duck_config.json | ⚠️ 沒有 |"
REMOTE
}

main() {
  if ! ssh $SSH_OPTS "$HOST" true; then
    echo "連不上 ${HOST}，先用 check_pi4.sh 排查。" >&2
    exit 1
  fi
  if [ "$CHECK_ONLY" = 0 ]; then
    [ -r "$CONSTRAINTS" ] || { echo "找不到 $CONSTRAINTS" >&2; exit 1; }
    ssh $SSH_OPTS "$HOST" "mkdir -p ~/'$DUCK_DIR'"
    scp -q $SSH_OPTS "$CONSTRAINTS" "$HOST:$DUCK_DIR/runtime-constraints.txt"
    if [ -r "$REPO_ROOT/$ONNX_NAME" ]; then
      scp -q $SSH_OPTS "$REPO_ROOT/$ONNX_NAME" "$HOST:$DUCK_DIR/$ONNX_NAME"
    else
      echo "⚠️ 本機找不到 $REPO_ROOT/$ONNX_NAME，略過複製步態策略" >&2
    fi
    remote_setup | ssh $SSH_OPTS "$HOST" "bash -s -- '$DUCK_DIR' '$RUNTIME_COMMIT' '$UV_VERSION' '$PY_VERSION'"
  fi
  remote_check | ssh $SSH_OPTS "$HOST" "bash -s -- '$DUCK_DIR' '$ONNX_SHA256' '$ONNX_NAME'"
}

main
