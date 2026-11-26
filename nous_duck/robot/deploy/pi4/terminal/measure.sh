#!/usr/bin/env bash
# 取樣 Chromium 的資源用量，CSV 印到 stdout。只讀 /proc、vcgencmd、systemctl is-active；不改任何東西。
#
# 用法（在 Pi 上）：
#   bash measure.sh [-i 取樣間隔秒，預設 5] [-d 總秒數，預設 60]
#
# 欄位：
#   ts                 取樣時刻（ISO 8601，Pi 的時區）
#   elapsed_s          從開始算的秒數
#   chromium_procs     Chromium 行程數（comm 是 chromium／chrome／chrome_crashpad／headless_shell）
#   chromium_cpu_pct   這段間隔內所有 Chromium 行程的 CPU 時間 ÷ 間隔 ×100（100 = 一顆核心滿載；Pi 4 有 4 顆）
#   chromium_rss_kb    各行程 RSS 加總（共用分頁會重複算，偏高）
#   chromium_pss_kb    各行程 PSS 加總（共用分頁按比例分，較接近實際佔用）
#   display_cpu_pct／display_rss_kb   Xvfb 或 cage（沒有就是 0）
#   mem_available_kb   /proc/meminfo 的 MemAvailable
#   load1              1 分鐘負載
#   temp_c             SoC 溫度（vcgencmd measure_temp；沒有 vcgencmd 就讀 thermal_zone0）
#   duckd／duck_console   systemctl is-active 的結果（唯讀）
set -u

INTERVAL=5
DURATION=60
while getopts "i:d:h" opt; do
  case "$opt" in
    i) INTERVAL="$OPTARG" ;;
    d) DURATION="$OPTARG" ;;
    h) sed -n '2,20p' "$0"; exit 0 ;;
    *) exit 2 ;;
  esac
done
case "$INTERVAL$DURATION" in *[!0-9]*) echo "-i 與 -d 要是正整數" >&2; exit 2 ;; esac
[ "$INTERVAL" -ge 1 ] && [ "$DURATION" -ge "$INTERVAL" ] || { echo "-i 至少 1，-d 不能小於 -i" >&2; exit 2; }

CHROMIUM_PATTERN="${MEASURE_CHROMIUM_PATTERN:-chromium|chrome|chrome_crashpad|headless_shell}"
DISPLAY_PATTERN="${MEASURE_DISPLAY_PATTERN:-Xvfb|cage}"
TCK="$(getconf CLK_TCK)"
PAGE_KB=$(( $(getconf PAGESIZE) / 1024 ))

pids_of() { pgrep -x "$1" 2>/dev/null | tr '\n' ' '; }

ticks_of() {  # utime+stime 的加總（jiffies）
  local files="" p
  for p in "$@"; do files="$files /proc/$p/stat"; done
  [ -n "$files" ] || { echo 0; return; }
  # shellcheck disable=SC2086
  awk '{ sub(/^.*\) /, ""); s += $12 + $13 } END { print s + 0 }' $files 2>/dev/null || true
}

rss_of() {
  local files="" p
  for p in "$@"; do files="$files /proc/$p/statm"; done
  [ -n "$files" ] || { echo 0; return; }
  # shellcheck disable=SC2086
  awk -v k="$PAGE_KB" '{ s += $2 } END { print s * k }' $files 2>/dev/null || true
}

pss_of() {
  local files="" p
  for p in "$@"; do files="$files /proc/$p/smaps_rollup"; done
  [ -n "$files" ] || { echo 0; return; }
  # shellcheck disable=SC2086
  awk '/^Pss:/ { s += $2 } END { print s + 0 }' $files 2>/dev/null || true
}

temp_c() {
  local t
  if command -v vcgencmd >/dev/null 2>&1 && t="$(vcgencmd measure_temp 2>/dev/null)"; then
    t="${t#temp=}"; echo "${t%\'C}"
  elif [ -r /sys/class/thermal/thermal_zone0/temp ]; then
    awk '{ printf "%.1f", $1 / 1000 }' /sys/class/thermal/thermal_zone0/temp
  else
    echo ""
  fi
}

svc() { local s; s="$(systemctl is-active "$1" 2>/dev/null)"; echo "${s:-unknown}"; }

echo "ts,elapsed_s,chromium_procs,chromium_cpu_pct,chromium_rss_kb,chromium_pss_kb,display_cpu_pct,display_rss_kb,mem_available_kb,load1,temp_c,duckd,duck_console"

# shellcheck disable=SC2046
prev_c="$(ticks_of $(pids_of "$CHROMIUM_PATTERN"))"
# shellcheck disable=SC2046
prev_d="$(ticks_of $(pids_of "$DISPLAY_PATTERN"))"
prev_t="$(date +%s.%N)"
start_t="$prev_t"
n=$(( DURATION / INTERVAL ))
i=0
while [ "$i" -lt "$n" ]; do
  sleep "$INTERVAL"
  i=$(( i + 1 ))
  cp="$(pids_of "$CHROMIUM_PATTERN")"
  dp="$(pids_of "$DISPLAY_PATTERN")"
  # shellcheck disable=SC2086
  now_c="$(ticks_of $cp)"; now_d="$(ticks_of $dp)"
  now_t="$(date +%s.%N)"
  # shellcheck disable=SC2086
  rss="$(rss_of $cp)"; pss="$(pss_of $cp)"; drss="$(rss_of $dp)"
  procs="$(echo $cp | wc -w)"
  mem="$(awk '/^MemAvailable:/ { print $2 }' /proc/meminfo)"
  load="$(cut -d' ' -f1 /proc/loadavg)"
  awk -v ts="$(date +%Y-%m-%dT%H:%M:%S%z)" -v t0="$start_t" -v t1="$prev_t" -v t2="$now_t" \
      -v c1="$prev_c" -v c2="$now_c" -v d1="$prev_d" -v d2="$now_d" -v tck="$TCK" \
      -v procs="$procs" -v rss="$rss" -v pss="$pss" -v drss="$drss" -v mem="$mem" -v load="$load" \
      -v temp="$(temp_c)" -v s1="$(svc duckd)" -v s2="$(svc duck-console)" 'BEGIN {
        dt = t2 - t1; if (dt <= 0) dt = 1
        c = (c2 - c1) / tck / dt * 100; if (c < 0) c = 0   # 行程結束時 jiffies 加總會變小
        d = (d2 - d1) / tck / dt * 100; if (d < 0) d = 0
        printf "%s,%.0f,%d,%.1f,%d,%d,%.1f,%d,%d,%s,%s,%s,%s\n", ts, t2 - t0, procs, c, rss, pss, d, drss, mem, load, temp, s1, s2
      }'
  prev_c="$now_c"; prev_d="$now_d"; prev_t="$now_t"
done
