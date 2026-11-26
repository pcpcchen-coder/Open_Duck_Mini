#!/usr/bin/env bash
# 鴨子終端 spike 共用函式（由 run_local_probe.sh、run_nous_terminal.sh source；不要直接執行）。
# 驗證層級見 nous_duck/docs/validation/duck-terminal-spike-2026-11-26.md。
#
# 這裡只做三件事：找 Chromium、組 kiosk 旗標、啟動／收掉無螢幕顯示（headless 或 Xvfb）。
# 不碰舵機匯流排、I2C、GPIO、systemd、/etc、預設音訊裝置。

SPIKE_HOME="${SPIKE_HOME:-$HOME/duck/terminal-spike}"
XVFB_DISPLAY="${XVFB_DISPLAY:-:99}"
XVFB_SCREEN="${XVFB_SCREEN:-1024x600x24}"
XVFB_PID=""

find_chromium() {
  local c
  for c in chromium chromium-browser; do
    if command -v "$c" >/dev/null 2>&1; then command -v "$c"; return 0; fi
  done
  echo "找不到 chromium；先在 Mac 上跑 setup_terminal.sh" >&2
  return 1
}

# 終端 ID 規則照 AIOS shared/terminal.ts：/^[a-z0-9][a-z0-9-]{0,31}$/，而且不能是 main。
valid_terminal_id() {
  [[ "$1" =~ ^[a-z0-9][a-z0-9-]{0,31}$ ]] && [ "$1" != "main" ]
}

# 用法：kiosk_flags <user-data-dir>；結果放進陣列 KIOSK_FLAGS。
# 預設「不」加 --use-fake-ui-for-media-stream：麥克風權限照 Chromium 平常的規則走。
#
# WebRtcPipeWireCamera 要關掉：Pi 上沒有桌面（沒有 xdg-desktop-portal／PipeWire），開著的話
# navigator.mediaDevices.enumerateDevices() 會一直不回來（2026-11-26 實測，headless 與 Xvfb 都一樣；
# 關掉後正常回來）。鴨子的鏡頭不經過瀏覽器，關掉沒有損失。要重現：KIOSK_DISABLE_FEATURES=Translate。
kiosk_flags() {
  local off="${KIOSK_DISABLE_FEATURES:-Translate,WebRtcPipeWireCamera}"
  KIOSK_FLAGS=(
    --kiosk
    --user-data-dir="$1"
    --autoplay-policy=no-user-gesture-required
    --no-first-run
    --no-default-browser-check
    --noerrdialogs
    --disable-infobars
    --disable-session-crashed-bubble
    --disable-features="$off"
    --disable-background-networking
    --disable-component-update
    --disable-sync
    --password-store=basic
    --window-size=1024,600
  )
}

# 用法：start_display headless|xvfb；結果放進陣列 DISPLAY_FLAGS，Xvfb 的話另外設 DISPLAY 與 XVFB_PID。
start_display() {
  case "$1" in
    headless)
      DISPLAY_FLAGS=(--headless=new)
      ;;
    xvfb)
      command -v Xvfb >/dev/null 2>&1 || { echo "找不到 Xvfb；先跑 setup_terminal.sh" >&2; return 1; }
      local n="${XVFB_DISPLAY#:}"
      if [ -e "/tmp/.X${n}-lock" ]; then
        echo "顯示 $XVFB_DISPLAY 已經有人在用（/tmp/.X${n}-lock）；換一個：XVFB_DISPLAY=:98" >&2
        return 1
      fi
      Xvfb "$XVFB_DISPLAY" -screen 0 "$XVFB_SCREEN" -nolisten tcp >/dev/null 2>&1 &
      XVFB_PID=$!
      local i
      for i in $(seq 1 50); do
        [ -S "/tmp/.X11-unix/X${n}" ] && break
        sleep 0.1
      done
      [ -S "/tmp/.X11-unix/X${n}" ] || { echo "Xvfb 沒有起來" >&2; return 1; }
      export DISPLAY="$XVFB_DISPLAY"
      unset WAYLAND_DISPLAY
      # Xvfb 沒有 GPU；明講用軟體繪圖，結果才可重現
      DISPLAY_FLAGS=(--ozone-platform=x11 --disable-gpu)
      ;;
    *)
      echo "不認得的顯示方式：$1（headless 或 xvfb）" >&2
      return 2
      ;;
  esac
}

# 用法：stop_browser <user-data-dir>。只收掉用這個 user-data-dir 開的 Chromium 與我們自己開的 Xvfb。
stop_browser() {
  local udd="$1" i
  pkill -TERM -f -- "--user-data-dir=$udd" 2>/dev/null || true
  for i in $(seq 1 30); do
    pgrep -f -- "--user-data-dir=$udd" >/dev/null 2>&1 || break
    sleep 0.2
  done
  pkill -KILL -f -- "--user-data-dir=$udd" 2>/dev/null || true
  if [ -n "$XVFB_PID" ]; then
    kill "$XVFB_PID" 2>/dev/null || true
    wait "$XVFB_PID" 2>/dev/null || true
    XVFB_PID=""
  fi
}

# 有沒有任何 ALSA 播放裝置正被開著（不是 closed）。只讀 /proc。
alsa_playback_open() {
  local f s
  for f in /proc/asound/card*/pcm*p/sub*/status; do
    [ -r "$f" ] || continue
    read -r s < "$f" || continue
    if [ "$s" != "closed" ]; then echo "$f"; fi
  done
}
