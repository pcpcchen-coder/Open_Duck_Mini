"""設定頁的 HTTP 伺服器（只用標準函式庫）。

- GET  /                      頁面（單一 HTML，資源全部內嵌）
- GET  /api/state             全部設定（schema、目前值、預設值、生效狀態）、系統狀態、變更紀錄
- GET  /api/expressions       表情預覽圖（第一次會花幾秒渲染）
- POST /api/save              {changes, base_revision, confirm_measurements}
- POST /api/reset             {keys, base_revision}
- POST /api/restore_previous  {}
- POST /api/preview_expression {name}   請 duckd 在眼睛上顯示幾秒（duckd 沒有這個能力就回報不能）
- GET  /healthz

存取範圍（ADR-0019 §2.4）：
- 只接受**區網內**的來源位址（loopback、私有網段、link-local）；其他一律 403。
- 寫入要帶標頭 `X-Duck-Settings: 1` 與 JSON：別的網站沒辦法叫瀏覽器跨站送出這種請求。
- `Host` 標頭要是 IP、`localhost`、`*.local` 或這台機器的名字（擋 DNS rebinding）。
- 預設不需要 token（比照舵機控制台 2026-11-25 的決定）；`--require-token` 可以開。
"""
from __future__ import annotations

import gzip
import hmac
import ipaddress
import json
import logging
import socket
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__, schema, status
from .eyes_preview import ExpressionPreviews
from .store import SaveError, Store

log = logging.getLogger("duck_settings")
MAX_BODY = 64 * 1024
WEB_DIR = Path(__file__).resolve().parent / "web"
PREVIEW_SECONDS = 5.0


def is_lan_address(text: str) -> bool:
    try:
        ip = ipaddress.ip_address(text.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_loopback or ip.is_link_local or ip.is_private


def host_allowed(host_header: str, extra: tuple[str, ...] = ()) -> bool:
    host = host_header.strip().lower()
    if host.startswith("["):  # [IPv6]:port
        host = host[1:].split("]", 1)[0]
    elif host.count(":") == 1:
        host = host.rsplit(":", 1)[0]
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    me = socket.gethostname().lower()
    return host == "localhost" or host.endswith(".local") or host in (me, me.split(".", 1)[0]) or host in extra


class SettingsApp:
    def __init__(self, store: Store, *, token: str | None = None, html: bytes | None = None, service_runner=None,
                 duckd_sockets=None, allow_hosts: tuple[str, ...] = (), display_name: str | None = None):
        self.store = store
        self.token = token
        self.html = html if html is not None else (WEB_DIR / "index.html").read_bytes()
        self.html_gz = gzip.compress(self.html, compresslevel=6)
        self.previews = ExpressionPreviews()
        self.service_runner = service_runner
        self.duckd_sockets = duckd_sockets
        self.allow_hosts = allow_hosts
        self.display_name = display_name
        self._status_lock = threading.Lock()
        self._status: tuple[float, dict, dict, dict] | None = None

    def _system(self) -> tuple[dict, dict, dict]:
        """服務狀態每秒最多查一次（systemctl 是子行程）。"""
        with self._status_lock:
            now = time.monotonic()
            if self._status is None or now - self._status[0] > 1.0:
                self._status = (now, status.service_states(self.service_runner), status.duckd_summary(self.duckd_sockets),
                                status.pi_summary())
            return self._status[1], self._status[2], self._status[3]

    def state(self) -> dict:
        view = self.store.load()
        services, duckd, pi = self._system()
        eff = status.effects(view, self.store.directory, services)
        settings = []
        for s in schema.SETTINGS:
            d = s.public()
            d["value"] = view.values[s.key]
            d["stored"] = s.key in view.stored
            d["effect"] = eff[s.key]
            settings.append(d)
        return {
            "version": __version__, "schema_version": schema.SCHEMA_VERSION,
            "sections": [{"id": i, "label": lab, "description": desc} for i, lab, desc in schema.SECTIONS],
            "settings": settings, "revision": view.revision, "problems": list(view.problems),
            "services": services, "duckd": duckd, "pi": {**pi, "hostname": self.display_name or pi["hostname"]}, "never_here": list(status.NEVER_HERE),
            "changes": self.store.changes(20), "has_previous": self.store.previous() is not None,
            "access": {"token_required": self.token is not None, "lan_only": True},
            "directory": str(self.store.directory),
        }

    def command(self, action: str, body: dict) -> dict:
        if action == "save":
            r = self.store.apply(body.get("changes"), "web", base_revision=_rev(body.get("base_revision")),
                                 confirm_measurements=body.get("confirm_measurements") is True)
        elif action == "reset":
            keys = body.get("keys")
            if not isinstance(keys, list) or not keys or not all(isinstance(k, str) for k in keys):
                raise SaveError({"_": "keys 要是設定名稱的清單"})
            r = self.store.reset(keys, "web", base_revision=_rev(body.get("base_revision")))
        elif action == "restore_previous":
            r = self.store.restore_previous("web")
        elif action == "preview_expression":
            return self._preview(body.get("name"))
        else:
            raise KeyError(action)
        return {"changed": r.changed, "skipped": r.skipped, "revision": r.revision}

    def _preview(self, name) -> dict:
        if name not in schema.EXPRESSIONS:
            raise SaveError({"_": f"沒有這個表情：{name!r}"})
        reply = status.duckd_request({"cmd": "express", "name": name, "duration_s": PREVIEW_SECONDS}, self.duckd_sockets)
        if reply is None:
            raise SaveError({"_": "duckd 沒在跑（或連不上它的本機控制介面），不能在鴨子上預覽"}, code="unavailable")
        if not reply.get("ok"):
            raise SaveError({"_": f"duckd 拒絕：{reply.get('error', '沒有說明原因')}"}, code="unavailable")
        return {"shown": name, "seconds": PREVIEW_SECONDS, "panel": reply.get("panel", "unknown")}


def _rev(value) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict) or not all(isinstance(v, int) and not isinstance(v, bool) for v in value.values()):
        raise SaveError({"_": "base_revision 的格式不對"})
    return value


def make_handler(app: SettingsApp):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"NousDuckSettings/{__version__}"

        def log_message(self, fmt, *args):  # 不記每個請求
            pass

        def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, data: dict) -> None:
            self._send(code, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def _gate(self, api: bool) -> bool:
            if not is_lan_address(self.client_address[0]):
                self._json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "設定頁只給家裡區網內的裝置用"})
                return False
            if not host_allowed(self.headers.get("Host", ""), app.allow_hosts):
                self._json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "請用鴨子的 IP 或 duck-pi4.local 開這個頁面"})
                return False
            if api and app.token is not None:
                if not hmac.compare_digest(self.headers.get("X-Duck-Token", "").encode(), app.token.encode()):
                    self._json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "token 不對或沒有帶。用部署腳本印出的網址開啟（#t=…）"})
                    return False
            return True

        def do_GET(self):  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/healthz":
                self._send(HTTPStatus.OK, b"ok\n", "text/plain")
            elif path in ("/", "/index.html"):
                if not self._gate(api=False):
                    return
                csp = {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; connect-src 'self'; base-uri 'none'; form-action 'none'"}
                if "gzip" in self.headers.get("Accept-Encoding", ""):
                    self._send(HTTPStatus.OK, app.html_gz, "text/html; charset=utf-8", {"Content-Encoding": "gzip", **csp})
                else:
                    self._send(HTTPStatus.OK, app.html, "text/html; charset=utf-8", csp)
            elif path == "/api/state":
                if self._gate(api=True):
                    self._json(HTTPStatus.OK, {"ok": True, **app.state()})
            elif path == "/api/expressions":
                if self._gate(api=True):
                    self._json(HTTPStatus.OK, {"ok": True, **app.previews.get()})
            else:
                self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "找不到"})

        def do_POST(self):  # noqa: N802
            path = self.path.split("?", 1)[0]
            if not path.startswith("/api/"):
                self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "找不到"})
                return
            if not self._gate(api=True):
                return
            if self.headers.get("X-Duck-Settings") != "1" or "application/json" not in self.headers.get("Content-Type", ""):
                self._json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "只接受設定頁自己送出的請求"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY:
                self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"ok": False, "error": "內容太大"})
                return
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "body 不是 JSON 物件"})
                return
            action = path[len("/api/"):]
            try:
                result = app.command(action, body)
            except KeyError:
                self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": f"沒有這個動作：{action}"})
                return
            except SaveError as exc:
                code = {"conflict": HTTPStatus.CONFLICT, "io": HTTPStatus.INTERNAL_SERVER_ERROR,
                        "unavailable": HTTPStatus.SERVICE_UNAVAILABLE}.get(exc.code, HTTPStatus.BAD_REQUEST)
                self._json(code, {"ok": False, "error": str(exc), "errors": exc.errors, "code": exc.code})
                return
            except Exception as exc:  # noqa: BLE001
                log.exception("%s 失敗", action)
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": f"伺服器錯誤：{exc}"})
                return
            if action != "preview_expression":
                log.info("%s：改了 %s", action, sorted(result.get("changed", {})))
            self._json(HTTPStatus.OK, {"ok": True, **result})

    return Handler


def serve(app: SettingsApp, bind: str, port: int) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((bind, port), make_handler(app))
    httpd.daemon_threads = True
    return httpd
