"""感知輸入（UDP 8793 的 JSON）與 track：資料是測試合成的（mock）。"""
import json
import socket
import time

import pytest
from conftest import make_harness

from duckd.percept import PerceptInput, parse


def obs(kind="face", yaw=0.2, pitch=0.0, mock=True, **over):
    d = {"v": 1, "kind": kind, "bearing_yaw_rad": yaw, "bearing_pitch_rad": pitch, "distance_m": None, "confidence": 0.9, "t_ms": 1, "mock": mock}
    d.update(over)
    return json.dumps(d).encode()


@pytest.mark.parametrize(
    "data",
    [b"", b"not json", obs(v=2), obs(kind="person"), obs(yaw=9.0), obs(confidence=1.5), obs(mock="yes"), json.dumps({"v": 1, "kind": "face"}).encode(), obs(yaw=float("nan"))],
)
def test_bad_datagrams_are_dropped(data):
    assert parse(data, 0.0) is None


def test_good_datagram_parses():
    o = parse(obs(distance_m=1.5), 3.0)
    assert (o.kind, o.yaw, o.distance_m, o.mock, o.received) == ("face", 0.2, 1.5, True, 3.0)


def make(percept_clock):
    p = PerceptInput(percept_clock)
    h = make_harness(percept=p)
    return h, p


def test_track_needs_a_perception_source(h):
    assert h.cmd("track", {"target": "face"})["reason"] == "unsupported"
    assert h.cmd("track", {"target": "none"})["status"] == "accepted"


def test_track_face_turns_head_toward_bearing_and_reports_mock():
    t = [100.0]
    p = PerceptInput(lambda: t[0])
    h = make_harness(percept=p)
    p.feed(obs(yaw=0.3))
    assert h.core.capabilities()["tracking_face"]["status"] == "mock"
    ack = h.cmd("track", {"target": "face", "body": True})
    assert ack["status"] == "accepted" and ack["applied"] == {"target": "face", "body": False} and ack["clamped"] is True
    target_yaw = 0.3  # 人在身體座標的方位（假的）
    for _ in range(150):
        t[0] = h.t
        if _ % 5 == 0:  # 10 Hz 的觀測：方位＝目標−目前頭部角度
            p.feed(obs(yaw=target_yaw - h.body.head["head_yaw"]))
        h.run(0.02)
    assert h.body.head["head_yaw"] == pytest.approx(0.3, abs=0.02)
    assert h.events("tracking_acquired")[0]["data"] == {"target": "face", "mock": True}
    assert h.last_state()["tracking"] == "face"
    # 觀測停了：2 s 後回報 tracking_lost，頭不亂動
    before = h.body.head["head_yaw"]
    for _ in range(150):
        t[0] = h.t
        h.run(0.02)
    assert h.events("tracking_lost") and h.core.tracking == "none"
    assert h.body.head["head_yaw"] == pytest.approx(before, abs=0.01)


def test_track_sound_uses_body_frame_and_is_clamped():
    t = [100.0]
    p = PerceptInput(lambda: t[0])
    h = make_harness(percept=p)
    p.feed(obs(kind="sound", yaw=1.2))
    assert h.cmd("track", {"target": "sound", "timeout_s": 1.0})["status"] == "accepted"
    for _ in range(100):
        t[0] = h.t
        if _ % 10 == 0:
            p.feed(obs(kind="sound", yaw=1.2))
        h.run(0.02)
    assert h.body.head["head_yaw"] == pytest.approx(0.5, abs=0.03)  # 夾在頭部範圍
    assert h.core.tracking == "none"  # timeout_s 到了


def test_udp_listener_binds_loopback_only():
    p = PerceptInput(time.monotonic, ("127.0.0.1", 0))
    p.start()
    try:
        host, port = p._sock.getsockname()
        assert host == "127.0.0.1"
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(obs(), (host, port))
            s.sendto(b"garbage", (host, port))
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and (p.get("face", 5) is None or p.dropped == 0):
            time.sleep(0.01)
        assert p.get("face", 5).yaw == 0.2 and p.dropped == 1
    finally:
        p.stop()
