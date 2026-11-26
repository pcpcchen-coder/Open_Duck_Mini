#!/bin/bash
# 實機頭部檢查（T1）：前置檢查 → 啟動 duckd 並接手頭頸 4 顆 → 端到端與租約量測 → 釋放、停止。
# 腿部舵機不讀也不寫。前置檢查任何一項不過就停，不會碰匯流排。
#
# 用法（在 Mac 的 repo checkout 裡；Pi 已經跑過 deploy_duckd.sh）：
#   bash nous_duck/robot/duckd/tools/head_check.sh [host]        # 預設 duck-pi4
#   KEEP=1 bash .../head_check.sh                                # 測完讓 duckd 留著跑、頭部接手（給 B 線連）
#
# 用的是 duckd 自己的假 hub（mock hub，埠 8795），不占用正式 hub 的 8791。
# 輸出：$OUT（預設 /tmp/duckd-head-check）底下的 e2e.json、lease.json、preflight.txt。
set -euo pipefail
HOST="${1:-duck-pi4}"
PORT=8795
OUT="${OUT:-/tmp/duckd-head-check}"
DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="$DIR/.venv/bin/python"
[ -x "$PY" ] || { echo "先建 venv：cd $DIR && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements-dev.txt"; exit 1; }
mkdir -p "$OUT"

echo "== 1/5 前置檢查（唯讀）"
ssh "$HOST" 'bash -s' <<'REMOTE' | tee "$OUT/preflight.txt"
set -u
if systemctl is-active --quiet duckd; then echo "FAIL duckd 服務已經在跑：先 sudo systemctl stop duckd"; exit 1; fi
T=$(cat ~/.config/nous-duck/console_token 2>/dev/null || true)
C=$(curl -s -m 3 -H "X-Duck-Token: $T" http://127.0.0.1:8080/api/state | python3 -c 'import json,sys; print(json.load(sys.stdin)["connected"])' 2>/dev/null || echo unknown)
echo "舵機控制台 connected=$C"
[ "$C" = True ] && { echo "FAIL 舵機控制台連著匯流排：先在頁面按「釋放硬體」"; exit 1; }
for p in /proc/[0-9]*; do ls -l $p/fd 2>/dev/null | grep -q ttyACM0 && { echo "FAIL /dev/ttyACM0 被 $p 占用"; exit 1; }; done
~/duck/runtime-venv/bin/python - <<'PY'
import sys
from pypot.feetech import FeetechSTS3215IO
io = FeetechSTS3215IO("/dev/ttyACM0", baudrate=1000000, timeout=0.02)
try:
    head = [30, 31, 32, 33]
    found = [i for i in head if io.ping(i)]
    if found != head:
        print(f"FAIL 頭部舵機沒有回應（回應的：{found}）。舵機電源有開嗎？"); sys.exit(1)
    volt = [v / 10 for v in io.get_present_voltage(head)]
    temp = list(io.get_present_temperature(head))
    torque = [bool(v) for v in io.is_torque_enabled(head)]
    pos = [round(p, 1) for p in io.get_present_position(head)]
    print(f"頭部 4 顆：電壓 {volt} V、溫度 {temp} °C、扭力 {torque}、舵機角度 {pos}°")
    if min(volt) < 6.6: print("FAIL 電壓低於 6.6 V"); sys.exit(1)
    if max(temp) >= 55: print("FAIL 溫度 ≥ 55 °C"); sys.exit(1)
finally:
    io.close()
PY
[ $? -eq 0 ] || exit 1
echo "負載：$(uptime | sed 's/.*load/load/')；$(vcgencmd get_throttled)"
echo PREFLIGHT_OK
REMOTE
grep -q PREFLIGHT_OK "$OUT/preflight.txt" || { echo "前置檢查沒過，沒有碰匯流排。"; exit 1; }

cleanup() {
  [ -n "${TUNNEL_PID:-}" ] && kill "$TUNNEL_PID" 2>/dev/null || true
  if [ "${KEEP:-0}" != 1 ]; then ssh "$HOST" 'sudo systemctl stop duckd; sudo rm -rf /etc/systemd/system/duckd.service.d; sudo systemctl daemon-reload' || true; fi
}
trap cleanup EXIT

echo "== 2/5 啟動 duckd（連假 hub 的埠 $PORT、把還沒驗證的動作也列出）並接手頭部"
ssh "$HOST" "sudo mkdir -p /etc/systemd/system/duckd.service.d && printf '[Service]\nEnvironment=DUCKD_TEST_ARGS=\"--url ws://127.0.0.1:$PORT/duck-link --allow-unverified-gestures\"\n' | sudo tee /etc/systemd/system/duckd.service.d/head-check.conf >/dev/null && sudo systemctl daemon-reload && sudo systemctl start duckd && sleep 2 && ~/duck/duckd/duckd-ctl engage"
ssh -N -o ExitOnForwardFailure=yes -R "127.0.0.1:$PORT:127.0.0.1:$PORT" "$HOST" &
TUNNEL_PID=$!
sleep 2

echo "== 3/5 端到端（look、nod、presence；±0.2 rad 內）"
(cd "$DIR" && "$PY" -m duckd.mock_hub --port "$PORT" --e2e > "$OUT/e2e.json")
echo "== 4/5 租約（頭在動時關掉 hub）"
(cd "$DIR" && "$PY" -m duckd.mock_hub --port "$PORT" --lease > "$OUT/lease.json")
ssh "$HOST" '~/duck/duckd/duckd-ctl status; P=$(systemctl show duckd -p MainPID --value); ps -o pcpu,rss -p $P' > "$OUT/status.txt"

echo "== 5/5 收尾"
if [ "${KEEP:-0}" = 1 ]; then
  ssh "$HOST" 'sudo rm -rf /etc/systemd/system/duckd.service.d; sudo systemctl daemon-reload; sudo systemctl restart duckd; sleep 2; ~/duck/duckd/duckd-ctl engage' >/dev/null
  echo "duckd 留著跑（正式埠 8791、頭部已接手）。停止：ssh $HOST 'sudo systemctl stop duckd'"
else
  echo "duckd 已停止，頭回到接手時的位置、扭力恢復原狀。"
fi
echo "結果在 $OUT/"
