"""啟動 duckd。

在電腦上用模擬身體（不碰硬體），另一個終端機先開假 hub（`python -m duckd.mock_hub`）：
    python -m duckd --body mock --engage --eyes-panel /tmp/duck_eyes.png

在 Pi 上（部署腳本裝成 systemd 服務 duckd；**啟動時不碰硬體**，要 `python -m duckd.ctl engage` 才連匯流排）：
    python -m duckd --body head
"""
from __future__ import annotations

import argparse
import logging
import math
import signal
import sys
import threading
import time
from pathlib import Path

from .arbiter import SafetyArbiter
from .body import EngageError, MockBody
from .core import Duckd
from .gestures import GestureLibrary
from .limits import Limits
from .link import DEFAULT_URL, LinkRunner
from .localctl import LocalControl
from .protocol import Protocol

WALK_REASON = "gait host not integrated; feet switches not wired; needs attended bring-up"


def build(args) -> tuple[Duckd, LinkRunner]:
    limits = Limits(
        head_max_speed=math.radians(args.head_speed_deg),
        head_window=None if args.head_window_deg is None else math.radians(args.head_window_deg),
    )
    arbiter = SafetyArbiter(limits, walk_supported=False, walk_unsupported_reason=WALK_REASON)
    if args.body == "mock":
        body = MockBody()
    else:
        from .head_real import HeadBody

        body = HeadBody.real(limits, args.serial, args.duck_config)
    eyes = None
    if not args.no_eyes:
        try:
            from .eyes_out import EyesOutput

            eyes = EyesOutput(args.eyes_panel, fps=args.eyes_fps)
        except ImportError as exc:
            logging.warning("眼睛渲染不能用（%s）；capabilities.eyes 會回報 unsupported", exc)
    percept = None
    if not args.no_percept:
        from .percept import PerceptInput

        percept = PerceptInput(time.monotonic, ("127.0.0.1", args.percept_port))
    head_reason = "direct head control; full range not verified on hardware"
    if args.head_window_deg is not None:
        head_reason = f"direct head control limited to +/-{args.head_window_deg:g} deg, {args.head_speed_deg:g} deg/s"
    core = Duckd(
        Protocol(args.schema),
        body,
        arbiter,
        GestureLibrary(limits),
        eyes=eyes,
        percept=percept,
        duck_id=args.duck_id,
        hardware_profile=args.hardware_profile,
        allow_unverified_gestures=args.allow_unverified_gestures,
        head_reason=head_reason,
    )
    return core, LinkRunner(core, args.url)


def main() -> int:
    p = argparse.ArgumentParser(description="duckd：鴨子端常駐程式（duck-link v0）")
    p.add_argument("--url", default=DEFAULT_URL, help="Nous 端 hub（經 SSH 通道的本機 loopback）")
    p.add_argument("--body", choices=["mock", "head"], default="mock", help="mock＝模擬身體；head＝實機頭頸 4 顆（ID 30–33）")
    p.add_argument("--engage", action="store_true", help="啟動後直接接手硬體（預設不碰硬體，等 `duckd.ctl engage`）")
    p.add_argument("--serial", default="/dev/ttyACM0")
    p.add_argument("--duck-config", type=Path, default=Path.home() / "duck_config.json", help="上游 duck_config.json（只讀偏移）")
    p.add_argument("--head-speed-deg", type=float, default=30.0, help="頭部角速度上限（°/s，最高 90）")
    p.add_argument("--head-window-deg", type=float, default=None, help="每軸只能在接手位置 ± 這個角度內")
    p.add_argument("--eyes-panel", type=Path, default=None, help="虛擬面板：把兩眼畫面寫成這個 PNG")
    p.add_argument("--eyes-fps", type=float, default=5.0)
    p.add_argument("--no-eyes", action="store_true")
    p.add_argument("--percept-port", type=int, default=8793, help="感知輸入的 UDP 埠（只綁 127.0.0.1）")
    p.add_argument("--no-percept", action="store_true")
    p.add_argument("--allow-unverified-gestures", action="store_true", help="開發用：把還沒實機驗證的動作也列給 Nous")
    p.add_argument("--hardware-profile", default="stock_head_direct_hold")
    p.add_argument("--duck-id", default="duck1")
    p.add_argument("--schema", type=Path, default=None)
    p.add_argument("--ctl-socket", type=Path, default=None)
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args()
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    core, link = build(args)
    if core.library.rejected:
        logging.warning("被拒絕載入的動作：%s", core.library.rejected)
    ctl = LocalControl(core, link, args.ctl_socket)
    ctl.start()
    if core.percept:
        try:
            core.percept.start()
        except OSError as exc:
            logging.warning("感知輸入埠開不了（%s），track 不能用", exc)
            core.percept = None
    if core.eyes:
        core.eyes.start()
    link.start_control()
    if args.engage:
        try:
            actual = core.engage(time.monotonic())
            logging.info("已接手：%s", {k: round(math.degrees(v), 2) for k, v in actual.items()})
        except EngageError as exc:
            logging.error("接手失敗，維持不碰硬體：%s", exc)

    def shutdown(*_):
        threading.Thread(target=link.link_stop.set, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGUSR1, lambda *_: threading.Thread(target=core.local_estop, args=("SIGUSR1", time.monotonic()), daemon=True).start())
    logging.info("duckd 啟動（body=%s，hub=%s，本機控制 %s）", args.body, args.url, ctl.path)

    # 連線迴圈在主執行緒跑到收到結束訊號；結束前先把頭送回原位、恢復扭力、放開匯流排
    link_thread = threading.Thread(target=link.run, name="duckd-link", daemon=True)
    link_thread.start()
    while not link.link_stop.wait(0.2):
        pass
    link_thread.join(timeout=3.0)
    # 控制迴圈還在跑：把釋放做完再停
    if core.begin_release(time.monotonic()):
        end = time.monotonic() + 10.0
        while core.engaged and time.monotonic() < end:
            time.sleep(0.05)
        if core.engaged:
            logging.error("釋放逾時；直接放開匯流排（扭力狀態可能沒恢復）")
            core.body.release()
    link.stop()
    if core.eyes:
        core.eyes.stop()
    if core.percept:
        core.percept.stop()
    ctl.stop()
    logging.info("duckd 結束")
    return 0


if __name__ == "__main__":
    sys.exit(main())
