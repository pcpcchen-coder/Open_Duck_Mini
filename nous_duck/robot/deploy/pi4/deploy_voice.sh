#!/bin/bash
# 安裝鴨子端語音服務到 Pi 4：nous_duck/robot/audio/duck_audio/voice_service.py → systemd 服務 duck-voice。
#
# 用法（在 repo 的 checkout 裡）：
#   bash nous_duck/robot/deploy/pi4/deploy_voice.sh [host]            # 預設 host = duck-pi4
#   bash nous_duck/robot/deploy/pi4/deploy_voice.sh --uninstall [host]
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
"${R[@]}" "$ROBOT/audio/alsa/" "$HOST:duck/voice/alsa/"
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
# 路線 2（預設）：只做喚醒偵測，把 wake_word 丟給 duckd（UDP 127.0.0.1:8793）；對話由 Chromium 語音終端做。
# 麥克風用 dsnoop 的共用裝置 duck_mic，Chromium 才能同時開（--alsa-input-device=duck_mic）。
Environment=ALSA_CONFIG_PATH=/usr/share/alsa/alsa.conf:$PI_HOME/duck/voice/alsa/duck-audio.conf
Environment=DUCK_MIC_DEVICE=duck_mic
ExecStart=$PI_HOME/duck/audio-venv/bin/python -m duck_audio.voice_service --mode wake --settings-dir $PI_HOME/duck/settings --models-dir $PI_HOME/duck/voice/models
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
ssh "$HOST" 'sudo systemctl daemon-reload; systemctl is-enabled duck-voice 2>/dev/null || true; arecord -l | grep -i "XVF3800" >/dev/null && echo "   麥克風在（XVF3800）" || echo "   （找不到 XVF3800 的收音裝置）"
  cd ~/duck/voice && S=$(~/duck/audio-venv/bin/python -m duck_audio.speaker) && echo "   喇叭：$S（自動找到）" || echo "   （找不到喇叭；見上一行的原因）"'

cat <<MSG

安裝完成。服務沒有 enable、沒有啟動。模式：wake（只做喚醒偵測；不連 Nous，音訊不離開這個行程）。
  啟動並看 log： ssh $HOST 'sudo systemctl start duck-voice && journalctl -u duck-voice -f'
                 然後對鴨子說「Hello 鴨子」或「Hey 鴨子」：應該聽到往上的「嘟嘟」，log 出現「喚醒詞 …」。
  不出聲地手動觸發一次（測事件有沒有送出）： ssh $HOST 'sudo systemctl kill -s USR1 duck-voice'
  停止：         ssh $HOST 'sudo systemctl stop duck-voice'
  喚醒詞、門檻倍數、提示音音量：在設定頁改（http://duck-pi4.local:8081/ 的「語音與聲音」），幾秒內生效。
  Chromium 語音終端要和它共用麥克風：啟動 Chromium 時設
     ALSA_CONFIG_PATH=/usr/share/alsa/alsa.conf:\$HOME/duck/voice/alsa/duck-audio.conf
     並加 --alsa-input-device=duck_mic --alsa-output-device=<上面印出的喇叭名稱>
  喇叭名稱：ssh $HOST "cd ~/duck/voice && ~/duck/audio-venv/bin/python -m duck_audio.speaker"
MSG
