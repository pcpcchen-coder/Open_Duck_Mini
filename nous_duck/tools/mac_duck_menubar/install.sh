#!/bin/bash
# 安裝／移除「鴨子 Nous」選單列 App。
#
#   bash nous_duck/tools/mac_duck_menubar/install.sh              # 建置、裝到 ~/Applications、登入 Mac 時自動開啟、現在打開
#   bash nous_duck/tools/mac_duck_menubar/install.sh --status     # 看裝了沒、在不在跑，並印出 App 看到的狀態
#   bash nous_duck/tools/mac_duck_menubar/install.sh --uninstall  # 結束 App、移除 App 與它的 LaunchAgent
#
# 寫入的東西（只有這些）：
#   ~/Applications/Nous Duck.app
#   ~/Library/LaunchAgents/com.nousduck.menubar.plist（登入 Mac 時打開 App；結束後不會自己重開）
#   App 自己的偏好（鴨子的位址）：~/Library/Preferences/com.nousduck.menubar.plist；網頁資料：~/Library/WebKit/com.nousduck.menubar 等
# 不動：/Applications/Nous.app 與 8787、8791 的兩個 LaunchAgent（com.nousduck.nous-dev、com.nousduck.duck-tunnel）、
#       ~/.config/nous-duck-dev、任何金鑰與 .env、系統設定。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="Nous Duck.app"
DEST_DIR="$HOME/Applications"
DEST="$DEST_DIR/$APP_NAME"
LABEL=com.nousduck.menubar
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

quit_app() {
  # 只找從安裝位置或 build 資料夾跑的這個 App
  pkill -TERM -f "/$APP_NAME/Contents/MacOS/NousDuck" 2>/dev/null && sleep 1 || true
}

case "${1:-}" in
  --status)
    [ -d "$DEST" ] && echo "App：$DEST" || echo "App：沒有安裝"
    if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then echo "LaunchAgent $LABEL：已載入（登入時打開）"; else echo "LaunchAgent $LABEL：沒有載入"; fi
    pgrep -f "/$APP_NAME/Contents/MacOS/NousDuck" >/dev/null && echo "選單列圖示：在跑" || echo "選單列圖示：沒在跑"
    [ -x "$DEST/Contents/MacOS/NousDuck" ] && { echo "--- App 看到的狀態"; "$DEST/Contents/MacOS/NousDuck" --status; }
    exit 0 ;;
  --uninstall)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    quit_app
    rm -rf "$DEST"
    echo "已移除 $DEST 與 $LABEL。"
    echo "App 自己的偏好與網頁資料留著；要一起清掉："
    echo "  defaults delete $LABEL; rm -rf ~/Library/WebKit/$LABEL ~/Library/Caches/$LABEL"
    exit 0 ;;
  -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
  "") ;;
  *) echo "不認得的參數：$1" >&2; exit 2 ;;
esac

echo "== 1/3 建置"
bash "$HERE/build.sh" --test
bash "$HERE/build.sh"

echo "== 2/3 安裝到 $DEST"
quit_app
mkdir -p "$DEST_DIR"
rm -rf "$DEST"
cp -R "$HERE/build/$APP_NAME" "$DEST"

echo "== 3/3 登入 Mac 時自動開啟（$PLIST）"
mkdir -p "$(dirname "$PLIST")"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>/usr/bin/open</string><string>-a</string><string>$DEST</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><false/>
</dict>
</plist>
EOF
plutil -lint "$PLIST" | sed 's/^/   /'
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"   # RunAtLoad：現在就打開一次

cat <<MSG

裝好了：選單列上的鴨子圖示（實心＝鴨子已連線，空心＝沒有連線）。
第一次打開「鴨子設定…」時 macOS 可能會問「允許尋找區域網路上的裝置」，請按允許。
移除：bash $HERE/install.sh --uninstall
MSG
