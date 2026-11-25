"""啟動舵機控制台。

在 Pi 上（部署腳本會裝成 systemd 服務 duck-console）：
    ~/duck/runtime-venv/bin/python -m servo_console --html duck_console.html --joints console_joints.json

在電腦上用模擬匯流排（不碰硬體）：
    python -m servo_console --mock --html ../../assembly_viewer/dist/duck_console.html \
        --joints ../../assembly_viewer/dist/console_joints.json --token-file /tmp/duck_token
"""
from __future__ import annotations

import argparse
import logging
import math
import os
import secrets
import signal
from pathlib import Path

from .bus import FeetechBus, MockBus
from .controller import Controller, scan_port_users
from .joints import STANCE, load_joints
from .server import ConsoleApp, read_html, serve
from .system import Sensors, SoundPlayer

HOME = Path.home()


def load_token(path: Path) -> str:
    """讀 token；沒有就產生一個（權限 600）。"""
    if path.exists():
        token = path.read_text().strip()
        if len(token) >= 16:
            return token
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(18)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token + "\n")
    return token


def main() -> None:
    p = argparse.ArgumentParser(description="Nous Duck 舵機控制台")
    p.add_argument("--html", type=Path, required=True, help="duck_console.html")
    p.add_argument("--joints", type=Path, required=True, help="console_joints.json")
    p.add_argument("--bind", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--serial", default="/dev/ttyACM0")
    p.add_argument("--config", type=Path, default=HOME / "duck_config.json", help="上游 duck_config.json（讀寫偏移）")
    p.add_argument("--poses", type=Path, default=HOME / "duck" / "console_poses.json")
    p.add_argument("--token-file", type=Path, default=HOME / ".config" / "nous-duck" / "console_token")
    p.add_argument("--assets", type=Path, default=HOME / "duck" / "Open_Duck_Mini_Runtime" / "mini_bdx_runtime" / "assets")
    p.add_argument("--mock", action="store_true", help="模擬匯流排與感測器（不碰硬體）")
    p.add_argument("--connect", action="store_true", help="啟動後直接連線（預設不碰硬體，等頁面按「連線」）")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    joints = load_joints(args.joints)
    if args.mock:
        start = {j.servo_id: math.degrees(STANCE[j.name]) for j in joints}
        mock_bus = MockBus([j.servo_id for j in joints], start_deg=start)
        bus_factory = lambda: mock_bus  # noqa: E731
        port_users = lambda: []  # noqa: E731
    else:
        bus_factory = lambda: FeetechBus(args.serial)  # noqa: E731
        devices = [args.serial, "/dev/i2c-1", "/dev/gpiochip0", "/dev/gpiochip4"]
        port_users = lambda: scan_port_users(devices)  # noqa: E731

    controller = Controller(joints, bus_factory, args.config, args.poses, port_users=port_users, mock=args.mock)
    app = ConsoleApp(
        controller,
        Sensors(mock=args.mock),
        SoundPlayer(args.assets, mock=args.mock),
        load_token(args.token_file),
        read_html(args.html),
    )
    if args.connect:
        app.command("connect", {})
    app.start()
    httpd = serve(app, args.bind, args.port)
    logging.info("舵機控制台 http://%s:%d/ （%s；token 在 %s）", args.bind, args.port, "模擬匯流排" if args.mock else args.serial, args.token_file)

    def shutdown(*_):
        app.stop()
        httpd.shutdown()

    signal.signal(signal.SIGTERM, lambda *_: __import__("threading").Thread(target=shutdown).start())
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()
        # 結束時不改扭力狀態（避免懸空時摔下來），只釋放硬體
        controller.release()
        app.sensors.close()


if __name__ == "__main__":
    main()
