#!/usr/bin/env bash
# 鴨子終端 spike：本機探測（在 Pi 上執行）。不連 Nous、不出聲。
#
# 做的事：
#   1. 在 127.0.0.1 起一個只給本機用的靜態網頁伺服器（python3 -m http.server），放 probe/index.html
#   2. 起無螢幕顯示（--display headless：Chromium 自己的 --headless=new；--display xvfb：Xvfb＋一般視窗模式）
#   3. 用 kiosk 終端的旗標開 Chromium，載入探測頁，從 DevTools 的 /json/list（只綁 127.0.0.1）讀頁面標題裡的 JSON
#   4. 頁面閒置時用 measure.sh 取樣 CPU／記憶體／負載／溫度
#   5. 全部收掉，印出摘要；結果留在 ~/duck/terminal-spike/runs/<時間>-<變體>/
#
# 用法：
#   bash run_local_probe.sh [--display headless|xvfb] [--fake-media] [--loopback]
#                           [--duration 60] [--interval 5] [--settle 10] [--label 名稱]
#
#   --fake-media   加 --use-fake-device-for-media-stream --use-fake-ui-for-media-stream：
#                  用 Chromium 內建的「假麥克風」（合成嗶聲）並自動同意權限。只證明瀏覽器管線通，
#                  **不是真的麥克風**，結果一律標 fake。
#   --enumerate-only   只做權限查詢、裝置列舉與 getUserMedia，不建立 AudioContext、不播放；這時不加
#                  --disable-audio-output，用來看「真的執行時」Chromium 列得出幾個輸出裝置。沒有輸出串流會被打開。
#   --loopback     取得音軌後在頁面內做 WebRTC 迴路（Opus 編解碼），估通話中的 CPU。要配 --fake-media
#                  或真麥克風才有音軌。收到的音軌接在靜音的元素上。
#
# 不出聲的三層保險（只有這支探測腳本加；真的要出聲的 run_nous_terminal.sh 不加）：
#   --disable-audio-output（Chromium 改用內建的假輸出串流，照真實時間消耗資料、不開任何音訊裝置）、
#   --mute-audio、--alsa-output-device=null（前一項萬一沒生效時的備援）、頁面只播數位靜音。
#   （只用 ALSA null 裝置不行：它不照真實時間消耗資料，AudioContext 的時鐘會暴衝，CPU 量測會失真。）
#   執行期間每 0.5 秒檢查 /proc/asound/*/pcm*p/*/status，任何播放裝置被打開都會記下來並在摘要裡報告。
#
# 不做的事：不連 127.0.0.1:8787、不開通道、不碰舵機匯流排／I2C／GPIO、不動 systemd、不改 /etc 與音訊設定。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"

DISPLAY_MODE=headless
FAKE_MEDIA=0
LOOPBACK=0
ENUM_ONLY=0
DURATION=60
INTERVAL=5
SETTLE=10
LABEL=""
HTTP_PORT="${PROBE_HTTP_PORT:-8931}"
DEBUG_PORT="${PROBE_DEBUG_PORT:-9333}"
RESULT_TIMEOUT="${PROBE_RESULT_TIMEOUT:-120}"

while [ $# -gt 0 ]; do
  case "$1" in
    --display) DISPLAY_MODE="$2"; shift 2 ;;
    --fake-media) FAKE_MEDIA=1; shift ;;
    --loopback) LOOPBACK=1; shift ;;
    --enumerate-only) ENUM_ONLY=1; shift ;;
    --duration) DURATION="$2"; shift 2 ;;
    --interval) INTERVAL="$2"; shift 2 ;;
    --settle) SETTLE="$2"; shift 2 ;;
    --label) LABEL="$2"; shift 2 ;;
    -h|--help) sed -n '2,31p' "$0"; exit 0 ;;
    *) echo "不認得的參數：$1" >&2; exit 2 ;;
  esac
done

CHROMIUM="$(find_chromium)"
[ -f "$HERE/probe/index.html" ] || { echo "找不到 $HERE/probe/index.html" >&2; exit 1; }
for port in "$HTTP_PORT" "$DEBUG_PORT"; do
  if ss -ltn 2>/dev/null | awk '{print $4}' | grep -q ":$port\$"; then
    echo "埠 $port 已經有人在聽；換一個（PROBE_HTTP_PORT／PROBE_DEBUG_PORT）" >&2; exit 1
  fi
done

VARIANT="$DISPLAY_MODE"
[ "$FAKE_MEDIA" = 1 ] && VARIANT="$VARIANT-fake" || VARIANT="$VARIANT-real"
[ "$LOOPBACK" = 1 ] && VARIANT="$VARIANT-loopback"
[ "$ENUM_ONLY" = 1 ] && VARIANT="$VARIANT-enumonly"
[ -n "$LABEL" ] && VARIANT="$VARIANT-$LABEL"
RUN="$SPIKE_HOME/runs/$(date +%Y%m%d-%H%M%S)-$VARIANT"
UDD="$SPIKE_HOME/profile-probe"
mkdir -p "$RUN"
rm -rf "$UDD"   # 每次用乾淨的設定檔，權限狀態才不會被上一輪影響
mkdir -p "$UDD" "$SPIKE_HOME/xdg-config" "$SPIKE_HOME/xdg-cache" "$SPIKE_HOME/xdg-data"
# Chromium 的雜項設定、快取與憑證資料庫（NSS 的 pki/）留在 spike 目錄裡，不寫進 ~/.config、~/.cache、~/.local/share
export XDG_CONFIG_HOME="$SPIKE_HOME/xdg-config" XDG_CACHE_HOME="$SPIKE_HOME/xdg-cache" XDG_DATA_HOME="$SPIKE_HOME/xdg-data"

HTTP_PID=""; ALSA_PID=""
cleanup() {
  stop_browser "$UDD"
  [ -n "$ALSA_PID" ] && kill "$ALSA_PID" 2>/dev/null || true
  [ -n "$HTTP_PID" ] && kill "$HTTP_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT TERM

mem_avail() { awk '/^MemAvailable:/ { print $2 }' /proc/meminfo; }
MEM_BEFORE="$(mem_avail)"
LOAD_BEFORE="$(cut -d' ' -f1 /proc/loadavg)"

echo "== 變體：$VARIANT"
if [ "$FAKE_MEDIA" = 1 ]; then
  echo "!! --fake-media：用的是 Chromium 內建的假麥克風（合成訊號）＋自動同意權限。這不是真的麥克風。"
fi
echo "   結果目錄：$RUN"

# 1. 本機靜態伺服器
python3 -m http.server "$HTTP_PORT" --bind 127.0.0.1 --directory "$HERE/probe" >"$RUN/http.log" 2>&1 &
HTTP_PID=$!

# 不出聲的檢查：有播放裝置被打開就記一筆
( while :; do o="$(alsa_playback_open)"; [ -n "$o" ] && echo "$(date +%T) $o" >>"$RUN/alsa-opened.log"; sleep 0.5; done ) &
ALSA_PID=$!

# 2. 顯示
start_display "$DISPLAY_MODE"

# 3. Chromium
kiosk_flags "$UDD"
EXTRA=(--mute-audio --alsa-output-device=null --remote-debugging-port="$DEBUG_PORT")
[ "$ENUM_ONLY" = 1 ] || EXTRA+=(--disable-audio-output)
[ -n "${PROBE_EXTRA_FLAGS:-}" ] && read -r -a MORE <<<"$PROBE_EXTRA_FLAGS" && EXTRA+=("${MORE[@]}")
if [ "$FAKE_MEDIA" = 1 ]; then
  EXTRA+=(--use-fake-device-for-media-stream --use-fake-ui-for-media-stream)
fi
URL="http://localhost:$HTTP_PORT/index.html"
[ "$LOOPBACK" = 1 ] && URL="$URL?loopback=1"
[ "$ENUM_ONLY" = 1 ] && URL="$URL?enumerate_only=1"
printf '%s\n' "$CHROMIUM" "${KIOSK_FLAGS[@]}" "${DISPLAY_FLAGS[@]}" "${EXTRA[@]}" "$URL" >"$RUN/command.txt"
T_START="$(date +%s.%N)"
"$CHROMIUM" "${KIOSK_FLAGS[@]}" "${DISPLAY_FLAGS[@]}" "${EXTRA[@]}" "$URL" >"$RUN/chromium.log" 2>&1 &

read_title() {  # 印出探測頁目前的標題
  curl -s --max-time 3 "http://127.0.0.1:$DEBUG_PORT/json/list" 2>/dev/null | python3 -c '
import html, json, sys
try:
    targets = json.load(sys.stdin)
except Exception:
    sys.exit(1)
for t in targets:
    if t.get("type") == "page" and t.get("title", "").startswith("PROBE_"):
        print(html.unescape(t["title"])); sys.exit(0)  # /json/list 會把標題做 HTML 跳脫
sys.exit(1)'
}

echo "== 等探測頁回報（最多 ${RESULT_TIMEOUT}s）"
TITLE=""; GOT=0
for _ in $(seq 1 "$RESULT_TIMEOUT"); do
  if TITLE="$(read_title)" && [ "${TITLE%% *}" = "PROBE_RESULT" ]; then GOT=1; break; fi
  sleep 1
done
T_RESULT="$(date +%s.%N)"
if [ "$GOT" = 1 ]; then
  echo "${TITLE#PROBE_RESULT }" >"$RUN/result.json"
else
  echo "!! 時限內沒有拿到完整結果；最後看到的標題：${TITLE:0:200}"
  case "$TITLE" in PROBE_PARTIAL\ *) echo "${TITLE#PROBE_PARTIAL }" >"$RUN/result.json" ;; *) echo '{"done": false, "fatal": {"name": "NoResult"}}' >"$RUN/result.json" ;; esac
fi

# 4. 閒置取樣
echo "== 靜置 ${SETTLE}s 後取樣 ${DURATION}s（每 ${INTERVAL}s）"
sleep "$SETTLE"
bash "$HERE/measure.sh" -i "$INTERVAL" -d "$DURATION" | tee "$RUN/measure.csv" | sed 's/^/   /'
if [ "$LOOPBACK" = 1 ] && T2="$(read_title)"; then
  echo "${T2#PROBE_* }" >"$RUN/result-final.json"
fi
MEM_DURING="$(mem_avail)"

# 5. 收掉
cleanup
trap - EXIT
sleep 3
MEM_AFTER="$(mem_avail)"

python3 - "$RUN" "$VARIANT" "$DISPLAY_MODE" "$FAKE_MEDIA" "$LOOPBACK" "$MEM_BEFORE" "$MEM_DURING" "$MEM_AFTER" "$LOAD_BEFORE" "$T_START" "$T_RESULT" <<'PY' | tee "$RUN/summary.json"
import csv, json, os, sys
run, variant, display, fake, loopback, mb, md, ma, lb, t0, t1 = sys.argv[1:]
res = json.load(open(os.path.join(run, "result.json")))
final = os.path.join(run, "result-final.json")
if os.path.exists(final):
    try:
        res["webrtc_loopback"] = json.load(open(final)).get("webrtc_loopback", res.get("webrtc_loopback"))
    except Exception:
        pass
rows = list(csv.DictReader(open(os.path.join(run, "measure.csv"))))
def col(name, cast=float):
    return [cast(r[name]) for r in rows if r.get(name) not in (None, "")]
def stat(v):
    return {"mean": round(sum(v) / len(v), 1), "max": round(max(v), 1), "min": round(min(v), 1)} if v else None
alsa_log = os.path.join(run, "alsa-opened.log")
gum = res.get("get_user_media", {})
ac = res.get("audio_context", {})
out = {
    "variant": variant,
    "display": display,
    "fake_media": fake == "1",
    "note": "假麥克風（Chromium 內建合成訊號），不是真的裝置" if fake == "1" else "真實裝置路徑（這次沒有接麥克風）",
    "page_result_seconds": round(float(t1) - float(t0), 1),
    "probe_done": res.get("done", False),
    "get_user_media": ("ok" if gum.get("ok") else (gum.get("error") or {}).get("name", "?")),
    "get_user_media_message": (gum.get("error") or {}).get("message"),
    "get_user_media_elapsed_ms": gum.get("elapsed_ms"),
    "track_labels": [t.get("label") for t in gum.get("tracks", [])],
    "track_settings": [t.get("settings") for t in gum.get("tracks", [])],
    "mic_permission": [res.get("mic_permission_before"), res.get("mic_permission_after")],
    "devices_before": res.get("devices_before"),
    "devices_after": res.get("devices_after"),
    "input_level_1s": res.get("input_level_1s"),
    "audio_context": {k: ac.get(k) for k in ("state_initial", "state_after_1s", "sample_rate", "base_latency", "output_latency", "current_time_advanced_s", "autoplay_allowed")},
    "audio_element_autoplay": res.get("audio_element_autoplay"),
    "has_set_sink_id": res.get("has_set_sink_id"),
    "webrtc_loopback": res.get("webrtc_loopback"),
    "user_agent": res.get("user_agent"),
    "samples": len(rows),
    "chromium_procs": stat(col("chromium_procs")),
    "chromium_cpu_pct": stat(col("chromium_cpu_pct")),
    "chromium_rss_mb": stat([v / 1024 for v in col("chromium_rss_kb")]),
    "chromium_pss_mb": stat([v / 1024 for v in col("chromium_pss_kb")]),
    "display_cpu_pct": stat(col("display_cpu_pct")),
    "display_rss_mb": stat([v / 1024 for v in col("display_rss_kb")]),
    "mem_available_mb": {"before": round(int(mb) / 1024), "during_end": round(int(md) / 1024), "after_cleanup": round(int(ma) / 1024),
                         "min_during": round(min(col("mem_available_kb")) / 1024) if rows else None},
    "load1": {"before": float(lb), **(stat(col("load1")) or {})},
    "temp_c": stat(col("temp_c")),
    "duckd": sorted(set(col("duckd", str))),
    "duck_console": sorted(set(col("duck_console", str))),
    "alsa_playback_device_opened": os.path.exists(alsa_log),
}
print(json.dumps(out, ensure_ascii=False, indent=2))
PY

LEFT="$(pgrep -f -- "--user-data-dir=$UDD" || true)"
[ -z "$LEFT" ] || echo "!! 還有 Chromium 行程沒收掉：$LEFT"
if [ -f "$RUN/alsa-opened.log" ]; then
  echo "!! 執行期間有 ALSA 播放裝置被打開（見 $RUN/alsa-opened.log）"
else
  echo "== 執行期間沒有任何 ALSA 播放裝置被打開"
fi
echo "== 完成：$RUN"
