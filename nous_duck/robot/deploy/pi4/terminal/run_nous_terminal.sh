#!/usr/bin/env bash
# 鴨子終端 spike：真的開 Nous 頁面（在 Pi 上執行）。**會出聲、會開麥克風，要有人在場。**
#
# 狀態：還沒有執行過（2026-11-26 只做了不連 Nous、不出聲的本機探測）。
# 步驟與通過標準見 nous_duck/docs/validation/duck-terminal-spike-2026-11-26.md 的「等你」一節。
#
# 用法（先在 Mac 上開好通道，讓 Pi 的 localhost:<埠> 通到 Mac 的 Nous）：
#   I_AM_PRESENT_AND_OK_WITH_SOUND=yes bash run_nous_terminal.sh [--display headless|xvfb]
#                                                               [--auto-accept-mic] [--debug-port 9333]
#                                                               [--alsa-config 檔案] [--mic 裝置] [--speaker 裝置]
#
# 環境變數：
#   AIOS_PORT          Nous 的埠，預設 8787。Nous 核心會檢查 Host 標頭，所以 Pi 這邊的埠要和 Nous 的埠相同。
#   DUCK_TERMINAL_ID   終端 ID，預設 duck。規則 /^[a-z0-9][a-z0-9-]{0,31}$/，不能是 main。
#
# 選項：
#   --display          headless（預設）或 xvfb。2026-11-26 的本機探測裡兩種的結果相同（假麥克風、自動播放、
#                      WebRTC 迴路），headless 少一個 Xvfb 行程、PSS 少約 15 MB。Nous 頁面在 headless 下行為
#                      不對時（例如頁面或雲端服務認 User-Agent 裡的 HeadlessChrome），改用 xvfb。
#   --auto-accept-mic  加 --use-fake-ui-for-media-stream：自動同意麥克風權限提示（裝置仍是真的）。
#                      鴨子沒有螢幕，沒有人能按「允許」；不加的話，頁面第一次要麥克風時可能卡住。
#                      預設不加，要明講才加。這支腳本**不會**加 --use-fake-device-for-media-stream。
#   --debug-port N     在 127.0.0.1:N 開 DevTools（Mac 上用 ssh -L N:127.0.0.1:N duck-pi4 再開 chrome://inspect）。
#                      Pi 上任何行程都能透過這個埠操控瀏覽器，用完就關。預設不開。
#   --alsa-config F    額外載入一份 ALSA 設定檔（只對這個 Chromium 行程：設
#                      ALSA_CONFIG_PATH=/usr/share/alsa/alsa.conf:F；不改 ~/.asoundrc、不改 /etc）。
#   --mic NAME         Chromium 的輸入裝置（--alsa-input-device=NAME）。
#   --speaker NAME     Chromium 的輸出裝置（--alsa-output-device=NAME）。NAME 是 auto 時用 D 線的
#                      duck_audio.speaker 自動找喇叭（~/duck/voice，deploy_voice.sh 裝的；喇叭重插後卡名可能會變）。
#                      路線 2 要和鴨子本機的喚醒偵測共用麥克風時，用 D 線的共用裝置（dsnoop）：
#                        --alsa-config "$HOME/duck/voice/alsa/duck-audio.conf" --mic duck_mic \
#                        --speaker "$(cd ~/duck/voice && ~/duck/audio-venv/bin/python -m duck_audio.speaker)"
#                        （喇叭的名稱自動找；2026-11-27 換喇叭後是 plughw:CARD=CD002AUDIO,DEV=0）
#                      不要直接開 hw:Array（會和喚醒偵測搶麥克風）。
#                      驗證層級：D 線 2026-11-26 在 Pi 上用 run_local_probe.sh --enumerate-only 確認過
#                      duck_mic 能被 Chromium 開啟、同時喚醒偵測照常；這支腳本帶這三個選項**還沒有執行過**，
#                      --speaker 那個值也還沒有實際出聲驗證。
#
# 不做的事：不開通道（通道由你在 Mac 上開）、不碰舵機匯流排／I2C／GPIO、不動 systemd、不改 /etc 與音訊設定。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"

DISPLAY_MODE=headless
AUTO_ACCEPT=0
DEBUG_PORT=""
ALSA_CONFIG=""
MIC_DEVICE=""
SPEAKER_DEVICE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --display) DISPLAY_MODE="$2"; shift 2 ;;
    --auto-accept-mic) AUTO_ACCEPT=1; shift ;;
    --debug-port) DEBUG_PORT="$2"; shift 2 ;;
    --alsa-config) ALSA_CONFIG="$2"; shift 2 ;;
    --mic) MIC_DEVICE="$2"; shift 2 ;;
    --speaker) SPEAKER_DEVICE="$2"; shift 2 ;;
    -h|--help) sed -n '2,38p' "$0"; exit 0 ;;
    *) echo "不認得的參數：$1" >&2; exit 2 ;;
  esac
done

PORT="${AIOS_PORT:-8787}"
TERMINAL_ID="${DUCK_TERMINAL_ID:-duck}"

if [ "${I_AM_PRESENT_AND_OK_WITH_SOUND:-}" != "yes" ]; then
  cat >&2 <<MSG
拒絕啟動：這一步會讓鴨子的喇叭出聲、打開麥克風，並連到 Mac 上的 Nous。
要有人在場才能做。確認後這樣執行：

  I_AM_PRESENT_AND_OK_WITH_SOUND=yes bash $0 $*
MSG
  exit 3
fi
case "$PORT" in ''|*[!0-9]*) echo "AIOS_PORT 要是數字：$PORT" >&2; exit 2 ;; esac
if ! valid_terminal_id "$TERMINAL_ID"; then
  echo "DUCK_TERMINAL_ID 不合規則（/^[a-z0-9][a-z0-9-]{0,31}\$/，且不能是 main）：$TERMINAL_ID" >&2
  exit 2
fi
case "$DEBUG_PORT" in *[!0-9]*) echo "--debug-port 要是數字" >&2; exit 2 ;; esac
if [ -n "$ALSA_CONFIG" ] && [ ! -r "$ALSA_CONFIG" ]; then
  echo "--alsa-config 指的檔案不存在或讀不到：$ALSA_CONFIG" >&2
  exit 2
fi
if [ "$SPEAKER_DEVICE" = auto ]; then
  if ! SPEAKER_DEVICE="$(cd "$HOME/duck/voice" 2>/dev/null && python3 -m duck_audio.speaker)"; then
    echo "--speaker auto：找不到喇叭（~/duck/voice 的 duck_audio.speaker）" >&2
    exit 5
  fi
fi
for dev in "$MIC_DEVICE" "$SPEAKER_DEVICE"; do
  case "$dev" in *[!A-Za-z0-9_:=,.-]*) echo "--mic／--speaker 的裝置名稱有不允許的字元：$dev" >&2; exit 2 ;; esac
done

CHROMIUM="$(find_chromium)"
# 只看本機有沒有人在聽這個埠，不送任何請求
if ! ss -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "^(127\.0\.0\.1|\[::1\]):$PORT\$"; then
  cat >&2 <<MSG
Pi 的 localhost:$PORT 沒有人在聽——通道還沒開。在 Mac 上（另一個終端機視窗）執行：

  ssh -N -R 127.0.0.1:$PORT:127.0.0.1:$PORT duck-pi4

注意：通道開著的時候，Pi 上任何行程都能呼叫 Nous 的整套 HTTP API。用完按 Ctrl-C 關掉。
MSG
  exit 4
fi

UDD="$SPIKE_HOME/profile-nous-$TERMINAL_ID"
mkdir -p "$UDD" "$SPIKE_HOME/xdg-config" "$SPIKE_HOME/xdg-cache" "$SPIKE_HOME/xdg-data"
export XDG_CONFIG_HOME="$SPIKE_HOME/xdg-config" XDG_CACHE_HOME="$SPIKE_HOME/xdg-cache" XDG_DATA_HOME="$SPIKE_HOME/xdg-data"

cleanup() { stop_browser "$UDD"; }
trap cleanup EXIT
trap 'exit 130' INT TERM

start_display "$DISPLAY_MODE"
kiosk_flags "$UDD"
EXTRA=()
if [ "$AUTO_ACCEPT" = 1 ]; then
  EXTRA+=(--use-fake-ui-for-media-stream)
  echo "!! --auto-accept-mic：麥克風權限提示會被自動同意（裝置是真的，不是假裝置）。"
fi
[ -n "$DEBUG_PORT" ] && EXTRA+=(--remote-debugging-port="$DEBUG_PORT")
[ -n "$MIC_DEVICE" ] && EXTRA+=(--alsa-input-device="$MIC_DEVICE")
[ -n "$SPEAKER_DEVICE" ] && EXTRA+=(--alsa-output-device="$SPEAKER_DEVICE")
# 只影響這個 Chromium 行程；系統的 ALSA 設定不動
[ -n "$ALSA_CONFIG" ] && export ALSA_CONFIG_PATH="/usr/share/alsa/alsa.conf:$ALSA_CONFIG"
URL="http://localhost:$PORT/?terminal=$TERMINAL_ID"

cat <<MSG
== 開啟 $URL
   顯示：$DISPLAY_MODE　設定檔：$UDD
   麥克風：${MIC_DEVICE:-系統預設}　喇叭：${SPEAKER_DEVICE:-系統預設（~/.asoundrc）}　額外 ALSA 設定：${ALSA_CONFIG:-無}
   這支腳本沒有靜音。

量測（另開一個 ssh 視窗）：
   bash $HERE/measure.sh -i 5 -d 300 | tee $SPIKE_HOME/runs/nous-\$(date +%H%M%S).csv
   分三段各量一次：頁面閒置、通話中（你說話＋Nous 回話）、通話中同時讓 duckd 做動作。
結束：在這個視窗按 Ctrl-C（會收掉 Chromium 與 Xvfb），再關 Mac 上的通道。
MSG

"$CHROMIUM" "${KIOSK_FLAGS[@]}" "${DISPLAY_FLAGS[@]}" "${EXTRA[@]}" "$URL" >"$SPIKE_HOME/nous-terminal.log" 2>&1 &
wait $! || true
echo "Chromium 已結束（紀錄：$SPIKE_HOME/nous-terminal.log）"
