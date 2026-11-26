"""啟動設定頁。

    python -m duck_settings --dir /tmp/duck-settings --bind 127.0.0.1 --port 8765     # 在電腦上試
    python -m duck_settings                                                          # Pi：~/duck/settings，0.0.0.0:8081
"""
from __future__ import annotations

import argparse
import logging
import secrets
import signal
import sys
import threading
from pathlib import Path

from .reader import default_dir
from .server import SettingsApp, serve
from .store import Store

DEFAULT_PORT = 8081
TOKEN_FILE = Path.home() / ".config" / "nous-duck" / "settings_token"


def load_token(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(18)
    path.touch(mode=0o600)
    path.write_text(token + "\n", encoding="utf-8")
    return token


def main() -> int:
    p = argparse.ArgumentParser(description="鴨子設定頁（ADR-0019）")
    p.add_argument("--dir", type=Path, default=None, help="設定資料夾（預設 ~/duck/settings，或環境變數 DUCK_SETTINGS_DIR）")
    p.add_argument("--bind", default="0.0.0.0", help="只接受區網內的來源位址；要只給本機用就設 127.0.0.1")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--require-token", action="store_true", help="API 要帶 X-Duck-Token（預設不用）")
    p.add_argument("--token-file", type=Path, default=TOKEN_FILE)
    p.add_argument("--allow-host", action="append", default=[], help="額外允許的 Host 名稱（預設只收 IP、localhost、*.local、本機名稱）")
    p.add_argument("--display-name", default=None, help="頁面上方顯示的名稱（預設是這台機器的主機名稱）")
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args()
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    store = Store(args.dir or default_dir())
    store.directory.mkdir(parents=True, exist_ok=True)
    view = store.load()
    for problem in view.problems:
        logging.warning("設定檔有問題：%s", problem)
    token = load_token(args.token_file) if args.require_token else None
    app = SettingsApp(store, token=token, allow_hosts=tuple(h.lower() for h in args.allow_host), display_name=args.display_name)
    httpd = serve(app, args.bind, args.port)
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=httpd.shutdown, daemon=True).start())
    logging.info("鴨子設定頁：http://%s:%d/（資料夾 %s；%s）", args.bind, args.port, store.directory,
                 "要 token" if token else "不需要 token，只收區網內的位址")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
