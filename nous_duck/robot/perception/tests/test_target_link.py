"""D2：方位換算、選人、平滑、遺失；UDP 介面。"""

import json
import math
import socket

import pytest

from duck_perception.camera import CameraModel
from duck_perception.face_detect import FaceDetection
from duck_perception.link import UdpTargetSender, decode_target, encode_target
from duck_perception.target import FaceBearing, FaceTargetTracker, SelectPolicy, TrackerConfig, mono_distance_m, to_bearing

CAM = CameraModel.ar0144_nominal(640, 360)


def fb(yaw, pitch=0.0, width=40.0, score=0.9, dist=None):
    return FaceBearing(yaw, pitch, width, score, dist, "stereo" if dist else None)


def test_to_bearing_signs():
    b = to_bearing(FaceDetection(u=CAM.cx - 100, v=CAM.cy - 50, width_px=40, height_px=52, score=0.9), CAM)
    assert b.yaw > 0 and b.pitch > 0 and b.distance_m is None and b.distance_source is None
    assert b.yaw == pytest.approx(math.atan2(100, CAM.fx))


def test_mono_distance_is_nominal():
    assert mono_distance_m(CAM.fx * 0.15 / 2.0, CAM) == pytest.approx(2.0)
    assert mono_distance_m(0.5, CAM) is None


def test_select_largest_center_sound():
    faces = [fb(0.3, width=80), fb(-0.02, width=30), fb(-0.25, width=50)]
    assert FaceTargetTracker(TrackerConfig(policy=SelectPolicy.LARGEST)).update(0.0, faces).bearing_yaw_rad == 0.3
    assert FaceTargetTracker(TrackerConfig(policy=SelectPolicy.CENTER)).update(0.0, faces).bearing_yaw_rad == -0.02
    tr = FaceTargetTracker(TrackerConfig(policy=SelectPolicy.SOUND))
    assert tr.update(0.0, faces, sound_yaw_cam=-0.3, sound_t=0.0).bearing_yaw_rad == -0.25
    # 沒有聲源方向 → 退回最大
    assert FaceTargetTracker(TrackerConfig(policy=SelectPolicy.SOUND)).update(0.0, faces).bearing_yaw_rad == 0.3
    # 聲源方向附近沒有臉 → 不選
    assert FaceTargetTracker(TrackerConfig(policy=SelectPolicy.SOUND)).update(0.0, [fb(0.3)], sound_yaw_cam=-0.5, sound_t=0.0) is None
    # 聲源方向太舊 → 不用
    assert FaceTargetTracker(TrackerConfig(policy=SelectPolicy.SOUND)).update(10.0, faces, sound_yaw_cam=-0.3, sound_t=0.0).bearing_yaw_rad == 0.3


def test_low_score_ignored():
    assert FaceTargetTracker().update(0.0, [fb(0.1, score=0.3)]) is None


def test_sticky_does_not_jump_to_bigger_face():
    tr = FaceTargetTracker()
    tr.update(0.0, [fb(0.1, width=40)])
    obs = tr.update(0.1, [fb(0.1, width=40), fb(-0.3, width=120)])
    assert obs.bearing_yaw_rad == pytest.approx(0.1)


def test_smoothing_reduces_noise_and_converges():
    tr = FaceTargetTracker(TrackerConfig(smooth_tau_s=0.3))
    tr.update(0.0, [fb(0.0)])
    o = tr.update(0.1, [fb(0.05)])
    assert 0.0 < o.bearing_yaw_rad < 0.05  # 一步不會跳到新值
    for k in range(2, 40):
        o = tr.update(0.1 * k, [fb(0.05)])
    assert o.bearing_yaw_rad == pytest.approx(0.05, abs=1e-3)


def test_lost_coasts_then_drops():
    tr = FaceTargetTracker(TrackerConfig(lost_after_s=0.6))
    first = tr.update(0.0, [fb(0.1, dist=1.5)])
    assert first.distance_m == 1.5 and not first.coasting
    c = tr.update(0.3, [])
    assert c.coasting and c.bearing_yaw_rad == pytest.approx(0.1) and 0 < c.confidence < first.confidence
    assert tr.update(0.7, []) is None
    assert tr.lost_count == 1 and not tr.has_target
    # 遺失後可以選新的人
    assert tr.update(0.8, [fb(-0.2)]).bearing_yaw_rad == -0.2


def test_distance_unknown_stays_none_and_is_not_invented():
    tr = FaceTargetTracker()
    assert tr.update(0.0, [fb(0.1)]).distance_m is None
    assert tr.update(0.1, [fb(0.1)]).distance_m is None
    o = tr.update(0.2, [fb(0.1, dist=2.0)])
    assert o.distance_m == pytest.approx(2.0)


def test_gaze_delta_compensation_keeps_match():
    tr = FaceTargetTracker(TrackerConfig(match_gate_rad=math.radians(5)))
    tr.update(0.0, [fb(0.3)])
    # 鏡頭往左轉了 0.25 rad：同一個人現在在 0.05；不補償會超過門檻
    o = tr.update(0.1, [fb(0.05), fb(0.32, width=90)], gaze_delta=(0.25, 0.0))
    assert o.bearing_yaw_rad == pytest.approx(0.05, abs=0.01)


def test_encode_matches_agreed_schema():
    data = encode_target("face", 0.123456789, -0.2, None, 0.87654, 1234, True)
    msg = json.loads(data)
    assert msg == {"v": 1, "kind": "face", "bearing_yaw_rad": 0.12346, "bearing_pitch_rad": -0.2, "distance_m": None, "confidence": 0.877, "t_ms": 1234, "mock": True}
    assert b"\n" not in data and b" " not in data
    assert decode_target(data) == msg


@pytest.mark.parametrize(
    "kw",
    [
        dict(kind="person"),
        dict(bearing_yaw_rad=float("nan")),
        dict(distance_m=-1.0),
        dict(distance_m=float("inf")),
        dict(confidence=1.2),
        dict(mock="yes"),
    ],
)
def test_encode_rejects_bad_values(kw):
    base = dict(kind="sound", bearing_yaw_rad=0.1, bearing_pitch_rad=0.0, distance_m=1.0, confidence=0.5, t_ms=1, mock=False)
    base.update(kw)
    with pytest.raises(ValueError):
        encode_target(**base)


def test_decode_rejects_extra_fields():
    msg = json.loads(encode_target("face", 0, 0, None, 1, 0, True))
    msg["image"] = "x"
    with pytest.raises(ValueError):
        decode_target(json.dumps(msg).encode())


def test_udp_sender_loopback_only_and_roundtrip():
    with pytest.raises(ValueError):
        UdpTargetSender(host="192.168.1.10")
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(2.0)
    tx = UdpTargetSender(port=rx.getsockname()[1])
    assert tx.send("face", 0.1, 0.2, 1.5, 0.9, 42, True)
    msg = decode_target(rx.recv(2048))
    assert msg["distance_m"] == 1.5 and msg["t_ms"] == 42 and msg["mock"] is True
    tx.close()
    rx.close()


def test_udp_sender_no_listener_does_not_raise():
    tx = UdpTargetSender(port=9)  # 沒有人在聽
    tx.send("sound", 0.0, 0.0, None, 0.5, 1, True)
    tx.send("sound", 0.0, 0.0, None, 0.5, 2, True)  # 第二次可能收到 ICMP 拒絕 → 回傳 False
    assert tx.sent + tx.errors == 2
    tx.close()
