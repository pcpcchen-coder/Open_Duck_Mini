"""連線層：真的 WebSocket（loopback 的臨時埠）＋假 hub（mock）＋ MockBody。

這裡用真實時間，所以數字只是「有在合理範圍」的檢查，不是效能量測。
"""
import asyncio
import threading
import time

import pytest
from conftest import PROTOCOL

from duckd.arbiter import SafetyArbiter
from duckd.body import MockBody
from duckd.core import Duckd
from duckd.gestures import GestureLibrary
from duckd.limits import Limits
from duckd.link import LinkRunner
from duckd.localctl import LocalControl, request
from duckd.mock_hub import MockHub, run_e2e


class Rig:
    def __init__(self, port: int):
        limits = Limits()
        self.body = MockBody()
        self.core = Duckd(PROTOCOL, self.body, SafetyArbiter(limits, walk_unsupported_reason="feet switches not wired"), GestureLibrary(limits), allow_unverified_gestures=True)
        self.link = LinkRunner(self.core, f"ws://127.0.0.1:{port}/duck-link")
        self.core.engage(time.monotonic())
        self.link.start_control()
        self.thread = threading.Thread(target=self.link.run, daemon=True)
        self.thread.start()

    def stop(self):
        self.link.stop()
        self.thread.join(timeout=3)


async def _hub() -> MockHub:
    hub = MockHub(port=0, heartbeat_s=0.2, protocol=PROTOCOL)
    await hub.start()
    return hub


def test_hello_heartbeat_command_and_state_over_real_websocket():
    async def scenario():
        hub = await _hub()
        rig = Rig(hub.port)
        try:
            await asyncio.wait_for(hub.connected.wait(), 5)
            await asyncio.sleep(0.6)
            first = hub.received[0][1]
            assert first["type"] == "hello" and first["role"] == "duck" and first["mock"] is True
            assert hub.rtt_ms and max(hub.rtt_ms) < 200
            ack = await hub.command("look", {"head_yaw": 0.2, "duration_s": 0.5})
            assert ack["status"] == "accepted" and ack["_latency_ms"] < 200
            await asyncio.sleep(1.2)
            st = (await hub.command("status"))["data"]
            assert st["head"]["head_yaw"] == pytest.approx(0.2, abs=0.01)
            assert 40 <= st["loop"]["hz"] <= 55
            ack = await hub.command("gesture", {"name": "tilt"})
            done = await hub.wait_for(lambda m: m.get("event") == "gesture_done", 6)
            assert done["request_id"] == ack["request_id"] and done["data"]["completed"] is True
            states = hub.find(lambda m: m["type"] == "state")
            assert len(states) >= 3
            assert hub.schema_errors == []
        finally:
            rig.stop()
            await hub.stop()

    asyncio.run(scenario())


def test_heartbeat_pause_triggers_link_lost_then_restored():
    async def scenario():
        hub = await _hub()
        rig = Rig(hub.port)
        try:
            await asyncio.wait_for(hub.connected.wait(), 5)
            await asyncio.sleep(0.5)
            await hub.command("look", {"head_yaw": 0.5, "duration_s": 8.0}, ttl_ms=60000)
            await asyncio.sleep(0.3)
            hub.heartbeat_paused = True
            t0 = time.monotonic()
            lost = await hub.wait_for(lambda m: m.get("event") == "link_lost", 3)
            assert 1.2 <= time.monotonic() - t0 <= 2.0  # 租約 1.5 s
            frozen = rig.core.arbiter.head_cmd["head_yaw"]
            await asyncio.sleep(0.5)
            assert rig.core.arbiter.head_cmd["head_yaw"] == frozen < 0.5
            hub.heartbeat_paused = False
            await hub.wait_for(lambda m: m.get("event") == "link_restored", 2)
            await asyncio.sleep(0.3)
            assert rig.core.arbiter.head_cmd["head_yaw"] == frozen
            assert lost["type"] == "event" and hub.schema_errors == []
        finally:
            rig.stop()
            await hub.stop()

    asyncio.run(scenario())


def test_hub_restart_reconnects_and_delivers_link_lost():
    async def scenario():
        hub = await _hub()
        port = hub.port
        rig = Rig(port)
        try:
            await asyncio.wait_for(hub.connected.wait(), 5)
            await asyncio.sleep(0.5)
            await hub.command("look", {"head_yaw": 0.5, "duration_s": 8.0}, ttl_ms=60000)
            await asyncio.sleep(0.3)
            await hub.stop()
            await asyncio.sleep(0.3)
            frozen = rig.core.arbiter.head_cmd["head_yaw"]
            await asyncio.sleep(0.7)
            assert rig.core.arbiter.head_cmd["head_yaw"] == frozen  # socket 一關就停，不用等 1.5 s
            hub2 = MockHub(port=port, heartbeat_s=0.2, protocol=PROTOCOL)
            await hub2.start()
            try:
                await asyncio.wait_for(hub2.connected.wait(), 8)
                await asyncio.sleep(0.8)
                kinds = [m.get("event") or m["type"] for _, m in hub2.received]
                assert kinds[0] == "hello"
                assert "link_lost" in kinds and "link_restored" in kinds
                assert kinds.index("link_lost") < kinds.index("link_restored")
                assert rig.link.connects == 2 and hub2.schema_errors == []
            finally:
                await hub2.stop()
        finally:
            rig.stop()

    asyncio.run(scenario())


def test_e2e_script_runs_against_mock_body():
    async def scenario():
        hub = await _hub()
        rig = Rig(hub.port)
        try:
            result = await run_e2e(hub, amplitude=0.2)
            assert result["hello"]["mock"] is True and result["schema_errors"] == []
            looks = [s for s in result["steps"] if s["action"] == "look"]
            assert all(s["ack"]["status"] == "accepted" for s in looks)
            assert all(abs(s["error_rad"]) < 0.02 for s in looks)
            assert looks[4]["ack"]["clamped"] is True
            nod = next(s for s in result["steps"] if s["action"] == "gesture nod")
            assert nod["done"]["completed"] is True and nod["pitch_min"] < -0.15
        finally:
            rig.stop()
            await hub.stop()

    asyncio.run(scenario())


def test_local_control_socket():
    import shutil
    import tempfile

    tmp_path = __import__("pathlib").Path(tempfile.mkdtemp(prefix="dk", dir="/tmp"))  # UNIX socket 路徑有長度上限
    limits = Limits()
    body = MockBody()
    core = Duckd(PROTOCOL, body, SafetyArbiter(limits), GestureLibrary(limits))
    link = LinkRunner(core, "ws://127.0.0.1:9/duck-link")
    link.start_control()
    ctl = LocalControl(core, link, tmp_path / "duckd.sock")
    ctl.start()
    try:
        path = tmp_path / "duckd.sock"
        assert (path.stat().st_mode & 0o777) == 0o600
        assert request("status", path)["engaged"] is False
        assert request("engage", path)["ok"] is True and body.engaged
        assert request("estop", path)["ok"] and core.arbiter.estop_reason
        assert request("engage", path)["ok"] is False  # 緊急停止鎖定中不能接手
        assert request("clear-estop", path)["cleared"] is True
        assert request("release", path)["ok"] is True and not body.engaged
        assert request("bogus", path)["ok"] is False
    finally:
        ctl.stop()
        link.stop()
        shutil.rmtree(tmp_path, ignore_errors=True)
