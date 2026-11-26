#!/bin/bash
# 安裝鴨子端語音服務到 Pi 4：nous_duck/robot/audio/duck_audio/voice_service.py → systemd 服務 duck-voice。
#
# 用法（在 repo 的 checkout 裡）：
#   bash nous_duck/robot/deploy/pi4/deploy_voice.sh [host]            # 預設 host = duck-pi4
#   bash nous_duck/robot/deploy/pi4/deploy_voice.sh --uninstall [host]
#   DUCK_VOICE_URL=ws://127.0.0.1:8791/duck-voice bash …               # Nous 端的端點（只能是 loopback；預設如左）
#
# 做的事：
#   1. 複製 duck_audio/、sounds/、config/、fetch_models.py 到 ~/duck/voice/；另外放一份 duck_settings（只用它的讀取端）。
#      和 D 線的量測目錄 ~/duck/d-line/、duck-doa 的 ~/duck/doa/ 分開。
#   2. ~/duck/audio-venv（沒有就建；不動 runtime-venv、duckd-venv）：numpy、sherpa-onnx 2.0.1、websockets（鎖版本）。
#   3. 下載喚醒詞模型到 ~/duck/voice/models/ 並核對 SHA-256（已存在且雜湊相符就跳過）。
#   4. systemd 服務 duck-voice：**不 enable、不啟動**。
#      服務單元用 systemd 把紅線再擋一層：整個檔案系統唯讀（只有 ~/duck/settings/applied 可寫，用來回報生效的設定）、
#      網路只允許 loopback。所以就算程式有錯，聲音也寫不進磁碟、送不出這片板子（除了經你開的 SSH 通道到 Mac）。
#
# 不做的事：不啟動服務、不播放聲音、不改 ~/.asoundrc 與混音器、不碰舵機匯流排／I2C／GPIO、不動 duckd 與 duck-doa。
set -euo pipefail

MODE=deploy
if [ "${1:-}" = "--uninstall" ]; then MODE=uninstall; shift; fi
HOST="${1:-duck-pi4}"
REPO="$(cd "$(dirname "$0")/../../../.." && pwd)"
ROBOT="$REPO/nous_duck/robot"
UNIT=duck-voice
URL="${DUCK_VOICE_URL:-ws://127.0.0.1:8791/duck-voice}"

if [ "$MODE" = uninstall ]; then
  ssh "$HOST" "sudo systemctl disable --now $UNIT 2>/dev/null || true; sudo rm -f /etc/systemd/system/$UNIT.service; sudo systemctl daemon-reload"
  echo "已移除 $UNIT 服務（~/duck/voice 與 ~/duck/audio-venv 保留）"
  exit 0
fi

echo "== 1/4 複製到 $HOST:~/duck/voice"
ssh "$HOST" 'mkdir -p ~/duck/voice/tools'
R=(rsync -a --delete --exclude __pycache__)
"${R[@]}" "$ROBOT/audio/duck_audio/" "$HOST:duck/voice/duck_audio/"
"${R[@]}" "$ROBOT/audio/sounds/" "$HOST:duck/voice/sounds/"
"${R[@]}" "$ROBOT/audio/config/" "$HOST:duck/voice/config/"
"${R[@]}" --exclude web "$ROBOT/settings/duck_settings/" "$HOST:duck/voice/duck_settings/"
rsync -a "$ROBOT/audio/tools/fetch_models.py" "$HOST:duck/voice/tools/"
rsync -a "$ROBOT/audio/requirements.txt" "$ROBOT/audio/requirements-kws.txt" "$ROBOT/audio/requirements-voice.txt" "$HOST:duck/voice/"
# 語音服務只需要一句回話用的合成語音給模擬的 Nous（mock）測試用
ssh "$HOST" 'mkdir -p ~/duck/voice/fixtures'
rsync -a "$ROBOT/audio/fixtures/speech_zh_synthetic_fixture.wav" "$HOST:duck/voice/fixtures/"

echo "== 2/4 ~/duck/audio-venv"
ssh "$HOST" 'set -e; command -v aplay >/dev/null && command -v arecord >/dev/null || { echo "缺 alsa-utils"; exit 1; }
  test -x ~/duck/audio-venv/bin/python || python3 -m venv ~/duck/audio-venv
  ~/duck/audio-venv/bin/python -m pip install --quiet -r ~/duck/voice/requirements-voice.txt
  cd ~/duck/voice && ~/duck/audio-venv/bin/python -c "import numpy, sherpa_onnx, websockets, duck_settings.reader, duck_audio.voice_service; print(\"   numpy\", numpy.__version__, \"sherpa-onnx\", sherpa_onnx.__version__, \"websockets\", websockets.__version__)"'

echo "== 3/4 喚醒詞模型"
ssh "$HOST" 'cd ~/duck/voice && ~/duck/audio-venv/bin/python tools/fetch_models.py kws-zh-en --dest ~/duck/voice/models | sed "s/^/   /"'

echo "== 4/4 systemd 服務 $UNIT（不 enable、不啟動）"
PI_USER="$(ssh "$HOST" 'id -un')"
PI_HOME="$(ssh "$HOST" 'echo $HOME')"
ssh "$HOST" "mkdir -p $PI_HOME/duck/settings/applied; sudo tee /etc/systemd/system/$UNIT.service >/dev/null" <<EOF2
[Unit]
Description=Nous Duck voice: wake word, capture, speaker playback (nous_duck/robot/audio/duck_audio/voice_service.py)
After=sound.target network.target

[Service]
User=$PI_USER
SupplementaryGroups=audio
WorkingDirectory=$PI_HOME/duck/voice
ExecStart=$PI_HOME/duck/audio-venv/bin/python -m duck_audio.voice_service --url $URL --settings-dir $PI_HOME/duck/settings --models-dir $PI_HOME/duck/voice/models
Restart=on-failure
RestartSec=5
Nice=5
# ---- 紅線再擋一層（ADR-0003 §6）：聲音寫不進磁碟、送不出這片板子 ----
ProtectSystem=strict
ReadWritePaths=$PI_HOME/duck/settings/applied
PrivateTmp=yes
NoNewPrivileges=yes
IPAddressDeny=any
IPAddressAllow=localhost

[Install]
WantedBy=multi-user.target
EOF2
ssh "$HOST" 'sudo systemctl daemon-reload; systemctl is-enabled duck-voice 2>/dev/null || true; arecord -l | grep -i "XVF3800" >/dev/null && echo "   麥克風在（XVF3800）" || echo "   （找不到 XVF3800 的收音裝置）"'

cat <<MSG

安裝完成。服務沒有 enable、沒有啟動。它連的是 $URL（Mac 上 Nous 端的端點，要先開 SSH 通道）。
  先不接 Nous、用模擬的 Nous（mock，回一句固定的合成語音）試：
    ssh $HOST 'cd ~/duck/voice && ~/duck/audio-venv/bin/python -m duck_audio.mock_nous --port 8791 --listen-s 4'   # 分頁 1
    ssh $HOST 'sudo systemctl start duck-voice && journalctl -u duck-voice -f'                              # 分頁 2，然後對鴨子說喚醒詞
  停止：        ssh $HOST 'sudo systemctl stop duck-voice'
  喚醒詞、音量、變聲、逾時：在設定頁改（http://duck-pi4.local:8081/ 的「語音與聲音」），幾秒內生效。
MSG
