"""設定服務的測試共用工具。全部不需要硬體；服務用真的 HTTP 伺服器（綁 127.0.0.1 的臨時埠）。"""
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROBOT = ROOT.parent
for extra in (ROOT, ROBOT / "eyes", ROBOT / "audio"):
    sys.path.insert(0, str(extra))

from duck_settings.server import SettingsApp, serve  # noqa: E402
from duck_settings.store import Store  # noqa: E402


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "settings")


class Client:
    def __init__(self, port: int, token: str | None = None):
        self.base = f"http://127.0.0.1:{port}"
        self.token = token

    def call(self, path: str, body=None, headers: dict | None = None, raw: bool = False):
        h = {"X-Duck-Settings": "1", "Content-Type": "application/json"} if body is not None else {}
        if self.token:
            h["X-Duck-Token"] = self.token
        h.update(headers or {})
        data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        req = urllib.request.Request(self.base + path, data=data, headers=h, method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                payload, status = r.read(), r.status
        except urllib.error.HTTPError as e:
            payload, status = e.read(), e.code
        return status, (payload if raw else json.loads(payload))


@pytest.fixture
def served(store):
    """（Client, SettingsApp）。systemd 狀態用假的回答（測試機沒有這些服務）。"""
    servers = []

    def start(token=None, services=None, duckd_sockets=()):
        app = SettingsApp(store, token=token, service_runner=lambda unit: (services or {}).get(unit, "inactive"), duckd_sockets=duckd_sockets)
        httpd = serve(app, "127.0.0.1", 0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        servers.append(httpd)
        return Client(httpd.server_address[1], token), app

    yield start
    for httpd in servers:
        httpd.shutdown()
        httpd.server_close()
