"""HTTP 層的測試：token、狀態、指令、錯誤碼（模擬匯流排）。"""
import json
import math
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from servo_console.bus import MockBus  # noqa: E402
from servo_console.controller import Controller  # noqa: E402
from servo_console.joints import load_joints  # noqa: E402
from servo_console.server import ConsoleApp, serve  # noqa: E402
from servo_console.system import Sensors, SoundPlayer  # noqa: E402
from test_controller import config_file, joints_file  # noqa: E402,F401

TOKEN = "test-token-0123456789"


@pytest.fixture
def server(joints_file, config_file, tmp_path):  # noqa: F811
    joints = load_joints(joints_file)
    bus = MockBus([j.servo_id for j in joints])
    c = Controller(joints, lambda: bus, config_file, tmp_path / "poses.json", mock=True)
    app = ConsoleApp(c, Sensors(mock=True), SoundPlayer(None, mock=True), TOKEN, b"<!doctype html><title>t</title>")
    httpd = serve(app, "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", app, bus
    httpd.shutdown()
    app.sensors.close()


def call(base, path, body=None, token=TOKEN):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method="POST" if body is not None else "GET")
    if token:
        req.add_header("X-Duck-Token", token)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_page_without_token(server):
    base, *_ = server
    with urllib.request.urlopen(base + "/") as r:
        assert r.status == 200 and b"<title>" in r.read()


def test_api_requires_token_when_enabled(server):
    base, *_ = server
    assert call(base, "/api/state", token=None)[0] == 401
    assert call(base, "/api/state", token="wrong")[0] == 401
    assert call(base, "/api/estop", {}, token=None)[0] == 401
    assert call(base, "/api/state")[1]["auth"] is True


def test_no_token_by_default(joints_file, config_file, tmp_path):  # noqa: F811
    """預設（沒有 --require-token）不檢查 token。"""
    joints = load_joints(joints_file)
    bus = MockBus([j.servo_id for j in joints])
    c = Controller(joints, lambda: bus, config_file, tmp_path / "poses.json", mock=True)
    app = ConsoleApp(c, Sensors(mock=True), SoundPlayer(None, mock=True), None, b"<!doctype html>")
    httpd = serve(app, "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        status, state = call(base, "/api/state", token=None)
        assert status == 200 and state["auth"] is False
        assert call(base, "/api/connect", {}, token=None)[0] == 200
    finally:
        httpd.shutdown()
        app.sensors.close()


def test_state_and_commands(server):
    base, app, bus = server
    status, state = call(base, "/api/state")
    assert status == 200 and state["mock"] and not state["connected"] and len(state["joints"]) == 14
    assert call(base, "/api/targets", {"targets_deg": {"head_yaw": 10}})[0] == 409  # 沒連線
    assert call(base, "/api/connect", {})[0] == 200
    assert call(base, "/api/torque", {"joints": ["head_yaw"], "on": True})[0] == 200
    status, res = call(base, "/api/targets", {"targets_deg": {"head_yaw": 500}})
    assert status == 200 and "夾到" in res["notes"][0]
    assert call(base, "/api/speed", {"deg_s": 77})[0] == 409
    assert call(base, "/api/nope", {})[0] == 404
    assert call(base, "/api/targets", {"targets_deg": {"head_yaw": "x"}})[0] == 409
    assert call(base, "/api/estop", {})[0] == 200
    assert not bus.torque[32]
    _, state = call(base, "/api/state")
    assert state["estop"] and state["imu"]["ok"]
    assert math.isclose(state["joints"][0]["lo_deg"], -28.0)
