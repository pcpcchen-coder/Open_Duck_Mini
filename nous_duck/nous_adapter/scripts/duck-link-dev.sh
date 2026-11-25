#!/bin/sh
# duck-link 開發用：在背景啟動／停止 hub 與 SSH 通道。
#
#   scripts/duck-link-dev.sh hub-start            啟動 hub（只聽 Mac 的 127.0.0.1:8791）
#   scripts/duck-link-dev.sh tunnel-start [主機]   開 SSH 通道（預設主機 duck-pi4）
#   scripts/duck-link-dev.sh status
#   scripts/duck-link-dev.sh tunnel-stop
#   scripts/duck-link-dev.sh hub-stop
#
# 通道：ssh -N -R 127.0.0.1:8791:127.0.0.1:8791 <主機>
#   由 Mac 發起；Pi 上的 127.0.0.1:8791 會接到 Mac 的 127.0.0.1:8791。鴨子（WebSocket client）連它自己的 loopback。
#   兩邊都只綁 loopback，不對區域網路開埠。
# 這個腳本不改 Mac 或 Pi 的任何系統設定、不安裝常駐服務、不重開任何東西；行程 ID 與紀錄放在 .run/（不進版控）。
# Mac 重開機或登出後要重新執行。要常駐（launchd／autossh）或改成 Pi → Mac 的方向，是使用者要決定的事。
set -eu

DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$DIR/.run"
PORT="${DUCK_HUB_PORT:-8791}"
mkdir -p "$RUN"

alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

stop() {
  if alive "$1"; then
    kill "$(cat "$1")" 2>/dev/null || true
    echo "$2 已停止。"
  else
    echo "$2 沒有在執行。"
  fi
  rm -f "$1"
}

case "${1:-status}" in
  hub-start)
    if alive "$RUN/hub.pid"; then echo "hub 已經在執行（PID $(cat "$RUN/hub.pid")）。"; exit 0; fi
    nohup "$DIR/bin/duckctl" hub --port "$PORT" >"$RUN/hub.log" 2>&1 &
    echo $! >"$RUN/hub.pid"
    sleep 2
    if alive "$RUN/hub.pid"; then
      echo "hub 已啟動（PID $(cat "$RUN/hub.pid")），紀錄：$RUN/hub.log"
    else
      echo "hub 啟動失敗：" >&2; tail -5 "$RUN/hub.log" >&2; rm -f "$RUN/hub.pid"; exit 1
    fi
    ;;
  hub-stop)
    stop "$RUN/hub.pid" "hub"
    ;;
  tunnel-start)
    HOST="${2:-duck-pi4}"
    if alive "$RUN/tunnel.pid"; then echo "通道已經開著（PID $(cat "$RUN/tunnel.pid")）。"; exit 0; fi
    # BatchMode：不問密碼（只用已設定的金鑰）；ExitOnForwardFailure：Pi 上的埠被占用就直接失敗，不留一條沒用的連線。
    nohup ssh -N \
      -o BatchMode=yes -o ExitOnForwardFailure=yes \
      -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
      -R "127.0.0.1:$PORT:127.0.0.1:$PORT" "$HOST" >"$RUN/tunnel.log" 2>&1 &
    echo $! >"$RUN/tunnel.pid"
    sleep 3
    if alive "$RUN/tunnel.pid"; then
      echo "通道已開（PID $(cat "$RUN/tunnel.pid")）：$HOST 的 127.0.0.1:$PORT → 這台 Mac 的 127.0.0.1:$PORT"
    else
      echo "通道開不起來：" >&2; tail -5 "$RUN/tunnel.log" >&2; rm -f "$RUN/tunnel.pid"; exit 1
    fi
    ;;
  tunnel-stop)
    stop "$RUN/tunnel.pid" "通道"
    ;;
  status)
    if alive "$RUN/hub.pid"; then echo "hub：執行中（PID $(cat "$RUN/hub.pid")）"; else echo "hub：沒有由這個腳本啟動的 hub"; fi
    if alive "$RUN/tunnel.pid"; then echo "通道：開著（PID $(cat "$RUN/tunnel.pid")）"; else echo "通道：沒有開"; fi
    "$DIR/bin/duckctl" link --port "$PORT" 2>/dev/null || echo "（連不到 hub 的控制通道）"
    ;;
  *)
    sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
    ;;
esac
