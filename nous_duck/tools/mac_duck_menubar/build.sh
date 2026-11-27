#!/bin/bash
# 建置「鴨子 Nous」選單列 App（不安裝）。
#   bash nous_duck/tools/mac_duck_menubar/build.sh          # 產生 build/Nous Duck.app
#   bash nous_duck/tools/mac_duck_menubar/build.sh --test   # 只跑 Status.swift 的自我測試
# 需要 Xcode 或 Command Line Tools 的 swiftc（macOS 13 以上）。簽章是 ad-hoc（只在這台 Mac 用）。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="$HERE/build"
mkdir -p "$OUT"
SWIFTC=(xcrun -sdk macosx swiftc)
FLAGS=(-swift-version 5 -target "$(uname -m)-apple-macos13.0")

if [ "${1:-}" = --test ]; then
  "${SWIFTC[@]}" "${FLAGS[@]}" -o "$OUT/selftest" "$HERE/Sources/Status.swift" "$HERE/Tests/main.swift"
  exec "$OUT/selftest"
fi

APP="$OUT/Nous Duck.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
"${SWIFTC[@]}" "${FLAGS[@]}" -O -o "$APP/Contents/MacOS/NousDuck" \
  -framework AppKit -framework WebKit \
  "$HERE/Sources/Status.swift" "$HERE/Sources/main.swift"
cp "$HERE/Info.plist" "$APP/Contents/Info.plist"
plutil -lint "$APP/Contents/Info.plist" >/dev/null
codesign --force --sign - "$APP" 2>&1 | sed 's/^/   /' || true
echo "建好了：$APP"
