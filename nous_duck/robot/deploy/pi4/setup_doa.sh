#!/bin/bash
# 安裝 XVF3800 聲源方向（DOA）讀取服務到 Pi 4：nous_duck/robot/audio/duck_audio/doa.py → systemd 服務 duck-doa。
#
# 用法（在 repo 的 checkout 裡）：
#   bash nous_duck/robot/deploy/pi4/setup_doa.sh [host]            # 預設 host = duck-pi4
#   bash nous_duck/robot/deploy/pi4/setup_doa.sh --uninstall [host]
#
# 前提：先跑過 deploy_duckd.sh（用它的 ~/duck/duckd-venv；pyusb 1.3.1 沿用 runtime-venv 的，不另外裝）。
#
# 做的事：
#   1. 複製 duck_audio/doa.py 到 ~/duck/doa/（和 D 線的 ~/duck/d-line/ 分開）。設定檔 ~/duck/doa/config/doa.json
#      已經存在就不覆蓋（裡面有你校準過的正前方角度）。
#   2. udev 規則：讓使用者 duck（plugdev 群組）可以對 Seeed（VID 2886）的 USB 裝置送控制請求。
#      只給控制端點的存取；程式不 claim 介面、不動 snd-usb-audio，收音與播放照常給別的程式用。
#   3. systemd 服務 duck-doa：**不 enable、不啟動**。啟動後麥克風沒接就每秒回報「不在」並等著，接上後自動開始。
#      服務只送方位（UDP 127.0.0.1:8793），不讀也不存任何聲音。
set -euo pipefail

MODE=deploy
if [ "${1:-}" = "--uninstall" ]; then MODE=uninstall; shift; fi
HOST="${1:-duck-pi4}"
REPO="$(cd "$(dirname "$0")/../../../.." && pwd)"
AUDIO="$REPO/nous_duck/robot/audio"
UNIT=duck-doa
RULE=/etc/udev/rules.d/60-nous-duck-xvf3800.rules

if [ "$MODE" = uninstall ]; then
  ssh "$HOST" "sudo systemctl disable --now $UNIT 2>/dev/null || true; sudo rm -f /etc/systemd/system/$UNIT.service $RULE; sudo systemctl daemon-reload; sudo udevadm control --reload"
  echo "已移除 $UNIT 服務與 udev 規則（~/duck/doa 保留）"
  exit 0
fi

ssh "$HOST" 'test -x ~/duck/duckd-venv/bin/python' || { echo "Pi 上沒有 ~/duck/duckd-venv，先跑 deploy_duckd.sh"; exit 1; }
echo "== 1/3 複製到 $HOST:~/duck/doa"
ssh "$HOST" 'mkdir -p ~/duck/doa/duck_audio ~/duck/doa/config'
scp -q "$AUDIO/duck_audio/doa.py" "$HOST:duck/doa/duck_audio/doa.py"
ssh "$HOST" 'test -f ~/duck/doa/duck_audio/__init__.py || echo "\"\"\"部署在 Pi 上的 duck_audio（只有 doa）。\"\"\"" > ~/duck/doa/duck_audio/__init__.py'
if ssh "$HOST" 'test -f ~/duck/doa/config/doa.json'; then
  echo "   保留既有的 ~/duck/doa/config/doa.json"
else
  scp -q "$AUDIO/config/doa.json" "$HOST:duck/doa/config/doa.json"
fi
ssh "$HOST" 'cd ~/duck/doa && ~/duck/duckd-venv/bin/python -c "import usb, duck_audio.doa as d; print(\"   pyusb\", usb.__version__, \"；doa 模組可載入\")"'

echo "== 2/3 udev 規則 $RULE"
ssh "$HOST" "sudo tee $RULE >/dev/null" <<'RULES'
# Nous Duck：Seeed reSpeaker XVF3800（VID 2886）的 USB 控制介面，給 duck-doa 讀聲源方向用。
SUBSYSTEM=="usb", ATTR{idVendor}=="2886", MODE="0660", GROUP="plugdev"
RULES
ssh "$HOST" 'sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=usb --attr-match=idVendor=2886 || true; id -nG | tr " " "\n" | grep -qx plugdev && echo "   使用者在 plugdev 群組" || echo "   注意：使用者不在 plugdev 群組，請執行 sudo usermod -aG plugdev $USER 後重新登入"'

echo "== 3/3 systemd 服務 $UNIT（不 enable、不啟動）"
PI_USER="$(ssh "$HOST" 'id -un')"
PI_HOME="$(ssh "$HOST" 'echo $HOME')"
ssh "$HOST" "sudo tee /etc/systemd/system/$UNIT.service >/dev/null" <<EOF2
[Unit]
Description=Nous Duck XVF3800 direction of arrival -> duckd (nous_duck/robot/audio/duck_audio/doa.py)

[Service]
User=$PI_USER
WorkingDirectory=$PI_HOME/duck/doa
ExecStart=$PI_HOME/duck/duckd-venv/bin/python -m duck_audio.doa --run --config $PI_HOME/duck/doa/config/doa.json
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF2
ssh "$HOST" 'sudo systemctl daemon-reload; lsusb | grep -i "2886" || echo "   （目前 lsusb 沒有 VID 2886：麥克風還沒接上）"'

cat <<'MSG'

安裝完成。服務沒有 enable、沒有啟動。麥克風接上後：
  看裝置：      ssh duck-pi4 'cd ~/duck/doa && ~/duck/duckd-venv/bin/python -m duck_audio.doa --probe'
  校準正前方：  ssh duck-pi4 'cd ~/duck/doa && ~/duck/duckd-venv/bin/python -m duck_audio.doa --calibrate 5 --write-config --config ~/duck/doa/config/doa.json'
                （執行後 5 秒內，站在鴨子正前方約 1 m 處說話）
  啟動：        ssh duck-pi4 'sudo systemctl start duck-doa'
  麥克風裝在哪（head／body／desk）改 ~/duck/doa/config/doa.json 的 "mount"，改完重啟服務。
MSG
