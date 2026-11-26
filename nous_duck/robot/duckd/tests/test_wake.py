"""喚醒詞：感知埠收到 `wake_word` → duck-link 事件；presence 送回喚醒服務。

喚醒與方位都是測試合成的（mock），沒有麥克風、沒有音訊。
"""
import json
import math
import socket

import pytest
from conftest import make_harness

from duckd.percept import PerceptInput, parse_wake
from duckd.voice_out import PresenceRelay


def wake(keyword="HELLO_YAZI", doa=None, mock=True, **over):
    d = {"v": 1, "kind": "wake_word", "keyword_id": keyword, "doa_deg": doa, "t_ms": 1, "mock": mock}
    d.update(over)
    return json.dumps(d).encode()


def sound(yaw, frame=None):
    d = {"v": 1, "kind": "sound", "bearing_yaw_rad": yaw, "bearing_pitch_rad": 0.0, "distance_m": None, "confidence": 0.9, "t_ms": 1, "mock": True}
    if frame:
        d["frame"] = frame
    return json.dumps(d).encode()


class Rig:
    def __init__(self, **kw):
        self.t = [100.0]
        self.p = PerceptInput(lambda: self.t[0])
        self.h = make_harness(percept=self.p, **kw)

    def feed(self, data):
        self.t[0] = self.h.t
        self.p.feed(data)

    def run(self, seconds):
        out = self.h.run(seconds)
        self.t[0] = self.h.t
        return out


def test_the_exact_datagram_duck_voice_sends_parses():
    # robot/audio/duck_audio/voice_service.py 的 send_wake 送的格式
    w = parse_wake(b'{"v":1,"kind":"wake_word","keyword_id":"HEY_YAZI","doa_deg":null,"t_ms":123,"mock":false}', 5.0)
    assert (w.keyword_id, w.doa_deg, w.mock, w.received) == ("HEY_YAZI", None, False, 5.0)


@pytest.mark.parametrize(
    "data",
    [wake(v=2), wake(keyword=""), wake(keyword="bad id"), wake(keyword=7), wake(mock="no"), wake(doa="left"), wake(doa=999), wake(doa=float("nan")), wake(doa=True), b"[]"],
)
def test_bad_wake_datagrams_are_dropped(data):
    p = PerceptInput(lambda: 0.0)
    p.feed(data)
    assert parse_wake(data, 0.0) is None and p.dropped == 1 and p.take_wakes() == []


def test_wake_becomes_one_duck_link_event_and_a_local_wake_presence():
    r = Rig()
    r.feed(wake())
    r.run(0.1)
    ev = r.h.events("wake_word")
    assert len(ev) == 1
    assert ev[0]["data"] == {"keyword_id": "HELLO_YAZI", "doa_deg": None, "mock": True}
    assert r.h.core.presence.state == "wake" and r.h.last_state()["presence"] == "wake"
    assert r.h.core.wake_stats == {"received": 1, "forwarded": 1, "dropped_no_link": 0, "dropped_stale": 0}
    r.run(1.5)
    assert r.h.body.head["head_pitch"] == pytest.approx(0.10, abs=0.01)  # 抬頭
    assert r.h.body.head["head_yaw"] == pytest.approx(0.0, abs=0.005)  # 沒有方位就不轉
    assert len(r.h.events("wake_word")) == 1  # 同一則不會送第二次


def test_local_wake_falls_back_to_idle_when_nous_does_not_take_over():
    r = Rig()
    r.feed(wake())
    r.run(7.5)
    assert r.h.core.presence.state == "wake"
    r.run(1.0)
    assert r.h.core.presence.state == "idle"
    r.run(1.5)
    assert r.h.body.head["head_pitch"] == pytest.approx(0.0, abs=0.01)


def test_nous_presence_takes_over_and_is_not_timed_out_locally():
    r = Rig()
    r.feed(wake())
    r.run(0.5)
    assert r.h.cmd("presence", {"state": "listening"})["status"] == "accepted"
    r.run(10.0)
    assert r.h.core.presence.state == "listening"


def test_wake_during_a_conversation_is_forwarded_but_does_not_change_presence():
    r = Rig()
    r.h.cmd("presence", {"state": "speaking"})
    r.feed(wake())
    r.run(0.1)
    assert len(r.h.events("wake_word")) == 1 and r.h.core.presence.state == "speaking"
    r.run(9.0)
    assert r.h.core.presence.state == "speaking"


def test_bearing_is_filled_from_the_latest_sound_and_head_turns_toward_it():
    r = Rig()
    r.feed(sound(0.2))
    r.run(0.5)
    r.feed(wake())
    r.run(0.1)
    data = r.h.events("wake_word")[0]["data"]
    assert data == {"keyword_id": "HELLO_YAZI", "doa_deg": pytest.approx(11.5, abs=0.05), "doa_frame": "body", "doa_source": "duck_doa", "doa_mock": True, "mock": True}
    r.run(1.5)
    assert r.h.body.head["head_yaw"] == pytest.approx(0.2, abs=0.01)
    # 對話期間維持朝向；結束後回正
    r.h.cmd("presence", {"state": "listening"})
    r.run(1.5)
    assert r.h.body.head["head_yaw"] == pytest.approx(0.2, abs=0.01)
    r.h.cmd("presence", {"state": "idle"})
    r.run(1.5)
    assert r.h.body.head["head_yaw"] == pytest.approx(0.0, abs=0.01)


def test_head_mounted_mic_bearing_adds_the_head_yaw():
    r = Rig()
    assert r.h.cmd("look", {"head_yaw": 0.1, "duration_s": 0.5})["status"] == "accepted"
    r.run(1.5)
    r.feed(sound(0.1, frame="head"))
    r.feed(wake())
    r.run(0.1)
    data = r.h.events("wake_word")[0]["data"]
    assert data["doa_frame"] == "body" and data["doa_deg"] == pytest.approx(math.degrees(0.2), abs=0.3)


def test_head_mounted_mic_without_engaged_head_reports_head_frame_and_does_not_move():
    r = Rig(engage=False)
    r.feed(sound(0.3, frame="head"))
    r.feed(wake())
    r.run(0.1)
    data = r.h.events("wake_word")[0]["data"]
    assert data["doa_frame"] == "head" and data["doa_deg"] == pytest.approx(17.2, abs=0.05)
    assert r.h.core.presence.state == "wake" and r.h.core.presence.face_yaw == 0.0


def test_old_sound_bearing_is_not_used():
    r = Rig()
    r.feed(sound(0.2))
    r.run(2.5)
    r.feed(wake())
    r.run(0.1)
    assert r.h.events("wake_word")[0]["data"]["doa_deg"] is None


def test_bearing_from_the_wake_service_wins_and_turning_respects_the_setting():
    r = Rig()
    r.h.core.apply_settings({"features.track_sound": False})
    r.feed(sound(-0.2))
    r.feed(wake(doa=20.0))
    r.run(0.1)
    data = r.h.events("wake_word")[0]["data"]
    assert (data["doa_deg"], data["doa_frame"], data["doa_source"]) == (20.0, "body", "wake_service")
    assert r.h.core.presence.face_yaw == 0.0  # 聽聲轉頭關掉：照樣回報方位，但頭不轉向聲源


def test_wake_is_dropped_not_queued_when_nous_is_unreachable():
    r = Rig()
    r.h.heartbeats = False
    r.run(2.0)  # 租約過期
    assert not r.h.arbiter.lease_ok
    r.feed(wake())
    r.run(0.1)
    assert r.h.core.wake_stats["dropped_no_link"] == 1 and r.h.core.presence.state == "idle"
    r.h.heartbeats = True
    r.run(1.0)
    assert r.h.events("wake_word") == []  # 連回來也不補送

    r2 = Rig(connect=False)
    r2.feed(wake())
    r2.run(0.1)
    assert r2.h.core.wake_stats["dropped_no_link"] == 1
    r2.h.open()
    r2.run(0.5)
    assert r2.h.events("wake_word") == []


def test_stale_wake_is_dropped():
    r = Rig()
    r.p.feed(wake())  # 收到的時間是 100.0
    r.h.t += 5.0
    r.h._next_hb = r.h.t
    r.h.heartbeat()
    r.h.run(0.1)
    assert r.h.core.wake_stats["dropped_stale"] == 1 and r.h.events("wake_word") == []


class FakeSock:
    def __init__(self):
        self.sent = []

    def setblocking(self, flag):
        pass

    def sendto(self, data, addr):
        self.sent.append((json.loads(data), addr))

    def close(self):
        pass


def test_presence_is_relayed_on_change_and_resent_periodically():
    sock = FakeSock()
    r = Rig(voice=PresenceRelay(("127.0.0.1", 8794), sock=sock))
    states = lambda: [m["state"] for m, _ in sock.sent]  # noqa: E731
    assert states() == ["idle"] and sock.sent[0] == ({"v": 1, "kind": "presence", "state": "idle"}, ("127.0.0.1", 8794))
    r.feed(wake())
    r.run(0.1)
    assert states() == ["idle", "wake"]  # 本機的 wake 也送：喚醒服務馬上停止偵測
    r.h.cmd("presence", {"state": "listening"})
    r.run(0.1)
    r.h.cmd("presence", {"state": "speaking", "speech_level": 0.5})
    r.run(11.0)
    assert states() == ["idle", "wake", "listening", "speaking", "speaking", "speaking"]  # 每 5 秒重送
    r.h.cmd("presence", {"state": "idle"})
    r.run(0.1)
    assert states()[-1] == "idle"


def test_link_loss_tells_the_wake_service_the_conversation_is_over():
    sock = FakeSock()
    r = Rig(voice=PresenceRelay(sock=sock))
    r.h.cmd("presence", {"state": "speaking"})
    r.run(0.1)
    r.h.heartbeats = False
    r.run(2.0)
    assert sock.sent[-1][0]["state"] == "idle"


def test_relay_only_sends_to_loopback_and_over_a_real_socket():
    with pytest.raises(ValueError):
        PresenceRelay(("192.168.1.10", 8794))
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(2.0)
    relay = PresenceRelay(rx.getsockname())
    assert relay.presence("thinking", 1.0) is True and relay.presence("thinking", 2.0) is False
    assert json.loads(rx.recvfrom(256)[0]) == {"v": 1, "kind": "presence", "state": "thinking"}
    relay.close()
    rx.close()
    # 沒有人在聽也不會出錯
    relay = PresenceRelay(("127.0.0.1", 9))
    assert relay.presence("idle", 0.0) is True and relay.errors == 0
    relay.close()


def test_wake_path_end_to_end_over_real_sockets(monkeypatch):
    """真的 WebSocket＋UDP（都在 loopback 的臨時埠）：假 hub（mock）、MockBody、手動丟的喚醒（mock）。"""
    import asyncio
    import threading
    import time

    from conftest import PROTOCOL

    from duckd import core as core_mod
    from duckd.arbiter import SafetyArbiter
    from duckd.body import MockBody
    from duckd.core import Duckd
    from duckd.gestures import GestureLibrary
    from duckd.limits import Limits
    from duckd.link import LinkRunner
    from duckd.mock_hub import MockHub, run_wake_test

    monkeypatch.setattr(core_mod, "WAKE_LOCAL_HOLD_S", 1.0)  # 不用真的等 8 秒

    def free_udp_port() -> int:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return port

    async def scenario():
        hub = MockHub(port=0, heartbeat_s=0.2, protocol=PROTOCOL)
        await hub.start()
        percept_port, voice_port = free_udp_port(), free_udp_port()
        limits = Limits()
        percept = PerceptInput(time.monotonic, ("127.0.0.1", percept_port))
        core = Duckd(PROTOCOL, MockBody(), SafetyArbiter(limits, walk_unsupported_reason="feet switches not wired"), GestureLibrary(limits),
                     percept=percept, voice=PresenceRelay(("127.0.0.1", voice_port)))
        percept.start()
        link = LinkRunner(core, f"ws://127.0.0.1:{hub.port}/duck-link")
        link.start_control()  # 不接手頭部：這條路不需要舵機
        thread = threading.Thread(target=link.run, daemon=True)
        thread.start()
        try:
            return await run_wake_test(hub, percept_port, voice_port)
        finally:
            link.stop()
            thread.join(timeout=3)
            percept.stop()
            core.voice.close()
            await hub.stop()

    out = asyncio.run(scenario())
    assert out["schema_errors"] == [] and "error" not in out
    assert out["before"]["mode"] == "limp" and "head" not in {k for k, v in out["before"].items() if v is not None}
    assert out["wake_event"]["data"] == {"keyword_id": "HELLO_YAZI", "doa_deg": None, "mock": True}
    assert out["wake_event_latency_ms"] < 500 and out["relay_wake_ms"] is not None
    assert out["presence_after_wake"] == "wake"
    assert [(s["state"], s["ack"]) for s in out["nous_presence"]] == [("listening", "accepted"), ("thinking", "accepted"), ("speaking", "accepted"), ("idle", "accepted")]
    assert all(s["relay_ms"] is not None and s["relay_ms"] < 500 for s in out["nous_presence"])
    assert out["wake_events_total"] == 2 and out["wake_event_ids_unique"]
    assert out["local_wake_back_to_idle_s"] == pytest.approx(1.0, abs=0.5)
