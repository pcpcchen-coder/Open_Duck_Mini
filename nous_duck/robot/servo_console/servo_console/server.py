"""HTTP 伺服器（只用標準函式庫）：提供頁面與 JSON API，背景執行控制迴圈。

- GET  /            頁面（duck_console.html，可 gzip）
- GET  /api/state   狀態（需要 token）
- POST /api/<動作>  指令（需要 token），body 是 JSON

token 放在 HTTP 標頭 X-Duck-Token；頁面網址用 #t=<token> 帶進去（# 後面不會送到伺服器的記錄裡）。
"""
from __future__ import annotations

import gzip
import hmac
import json
import logging
import math
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .controller import CommandError, Controller
from .system import Sensors, SoundPlayer, pi_status

log = logging.getLogger("servo_console")
MAX_BODY = 16 * 1024
LOOP_HZ = 50


class ConsoleApp:
    """把控制核心、感測器、音效、Pi 狀態包在一起，給 HTTP handler 用。"""

    def __init__(self, controller: Controller, sensors: Sensors, sound: SoundPlayer, token: str, html: bytes):
        self.controller = controller
        self.sensors = sensors
        self.sound = sound
        self.token = token
        self.html = html
        self.html_gz = gzip.compress(html, compresslevel=6)
        self._stop = threading.Event()
        self._pi: dict = {}
        self._pi_at = 0.0

    # ---- 背景執行緒
    def start(self) -> None:
        threading.Thread(target=self._loop, name="control", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        period = 1.0 / LOOP_HZ
        nxt = time.monotonic()
        while not self._stop.is_set():
            try:
                self.controller.tick()
            except Exception:  # noqa: BLE001 迴圈不能停；記下來
                log.exception("控制迴圈錯誤")
            nxt += period
            delay = nxt - time.monotonic()
            if delay < -0.5:
                nxt = time.monotonic()
            self._stop.wait(max(delay, 0.0))

    # ---- API
    def state(self) -> dict:
        now = time.monotonic()
        if now - self._pi_at > 1.0:
            self._pi = pi_status()
            self._pi_at = now
        data = self.controller.snapshot()
        data.update(self.sensors.snapshot())
        data["pi"] = self._pi
        data["sounds"] = self.sound.names()
        data["version"] = __version__
        return data

    def command(self, action: str, body: dict) -> dict:
        c = self.controller
        names = lambda: _names(c, body.get("joints"))  # noqa: E731
        if action == "connect":
            c.connect()
            self.sensors.open()
        elif action == "release":
            c.release()
            self.sensors.close()
        elif action == "estop":
            c.estop()
        elif action == "reset_estop":
            c.reset_estop()
        elif action == "torque":
            c.set_torque(names(), bool(body.get("on")))
        elif action == "targets":
            targets = body.get("targets_deg")
            if not isinstance(targets, dict):
                raise CommandError("缺少 targets_deg")
            return {"notes": c.set_targets({k: math.radians(_num(v)) for k, v in targets.items()})}
        elif action == "hold":
            c.hold()
        elif action == "speed":
            c.set_speed(_num(body.get("deg_s")))
        elif action == "kp":
            c.set_kp(names(), int(_num(body.get("kp"))))
        elif action == "offset":
            c.adjust_offset(str(body.get("joint")), _num(body.get("delta_deg")))
        elif action == "offsets_save":
            return {"backup": c.save_offsets()}
        elif action == "offsets_reload":
            c.reload_offsets()
        elif action == "pose_apply":
            return {"notes": c.apply_pose(str(body.get("key")))}
        elif action == "pose_save":
            c.save_pose(str(body.get("name", "")))
        elif action == "pose_delete":
            c.delete_pose(str(body.get("name", "")))
        elif action == "sound":
            try:
                self.sound.play(str(body.get("name")))
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
        else:
            raise KeyError(action)
        return {}


def _num(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise CommandError("參數不是數字")
    return float(value)


def _names(c: Controller, joints) -> list[str]:
    if joints == "all":
        return list(c.joints)
    if not isinstance(joints, list) or not joints or not all(isinstance(n, str) for n in joints):
        raise CommandError("joints 要是關節名稱的清單或 \"all\"")
    return joints


def make_handler(app: ConsoleApp):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"NousDuckConsole/{__version__}"

        def log_message(self, fmt, *args):  # 不記每個請求（每秒好幾次輪詢）
            pass

        def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data: dict) -> None:
            self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def _authorized(self) -> bool:
            token = self.headers.get("X-Duck-Token", "")
            if hmac.compare_digest(token.encode(), app.token.encode()):
                app.controller.client_seen()
                return True
            self._json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "token 不對或沒有帶。用部署腳本印出的網址開啟（#t=…）"})
            return False

        def do_GET(self):  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                if "gzip" in self.headers.get("Accept-Encoding", ""):
                    self._send(HTTPStatus.OK, app.html_gz, "text/html; charset=utf-8", {"Content-Encoding": "gzip"})
                else:
                    self._send(HTTPStatus.OK, app.html, "text/html; charset=utf-8")
            elif path == "/api/state":
                if self._authorized():
                    self._json(HTTPStatus.OK, {"ok": True, **app.state()})
            elif path == "/healthz":
                self._send(HTTPStatus.OK, b"ok\n", "text/plain")
            else:
                self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "找不到"})

        def do_POST(self):  # noqa: N802
            path = self.path.split("?", 1)[0]
            if not path.startswith("/api/"):
                self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "找不到"})
                return
            if not self._authorized():
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"ok": False, "error": "內容太大"})
                return
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "body 不是 JSON 物件"})
                return
            action = path[len("/api/") :]
            try:
                result = app.command(action, body)
            except KeyError:
                self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": f"沒有這個動作：{action}"})
                return
            except CommandError as exc:
                self._json(HTTPStatus.CONFLICT, {"ok": False, "error": str(exc)})
                return
            except Exception as exc:  # noqa: BLE001
                log.exception("指令 %s 失敗", action)
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": f"伺服器錯誤：{exc}"})
                return
            log.info("指令 %s 完成", action)
            self._json(HTTPStatus.OK, {"ok": True, **result})

    return Handler


def serve(app: ConsoleApp, bind: str, port: int) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((bind, port), make_handler(app))
    httpd.daemon_threads = True
    return httpd


def read_html(path: Path) -> bytes:
    return Path(path).read_bytes()
