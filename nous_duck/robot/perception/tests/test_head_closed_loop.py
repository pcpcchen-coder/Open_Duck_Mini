"""D2：合成畫面 → 偵測 → look_at 控制器的閉迴路（模擬；頭是一階延遲模型，不是實機）。"""

import math
import socket

import pytest

from conftest import needs_model
from duck_perception.camera import StereoRig
from duck_perception.closed_loop import simulate_head_tracking
from duck_perception.face_detect import ModelMissing, YuNetDetector
from duck_perception.link import UdpTargetSender, decode_target
from duck_perception.pipeline import FacePipeline
from duck_perception.synthetic import SyntheticPerson, SyntheticStereoSource, TruthDetector

DEG = math.radians(1)


def make(people, noise_px=0.0, dropout=0.0, sender=None):
    src = SyntheticStereoSource(people=people)
    return src, FacePipeline(src, TruthDetector(src, noise_px=noise_px, dropout=dropout), sender=sender)


def test_head_converges_on_face_synthetic_detections():
    src, pipe = make([SyntheticPerson(yaw=0.30, pitch=0.25, distance_m=1.5)])
    log = simulate_head_tracking(src, pipe, duration_s=4.0)
    assert log.final_error() < 3 * DEG
    st = log.settle_time(5 * DEG)
    assert st is not None and st < 1.5
    assert log.state[-1] == "tracking"


def test_head_converges_with_noise_and_dropout():
    src, pipe = make([SyntheticPerson(yaw=-0.25, pitch=0.3, distance_m=2.0)], noise_px=2.0, dropout=0.2)
    log = simulate_head_tracking(src, pipe, duration_s=5.0)
    tail = [math.hypot(a, b) for a, b in zip(log.yaw_err[-50:], log.pitch_err[-50:])]
    assert max(tail) < 5 * DEG


def test_head_follows_moving_person():
    person = SyntheticPerson(yaw=-0.3, pitch=0.2, distance_m=1.5)
    src, pipe = make([person])

    def move(t, source):
        person.yaw = -0.3 + 0.15 * t  # 0.15 rad/s 往左走，4 秒到 +0.3

    log = simulate_head_tracking(src, pipe, duration_s=4.0, on_step=move)
    tail = [abs(e) for e in log.yaw_err[100:]]
    assert max(tail) < 6 * DEG  # 有延遲所以會落後一點，但臉一直在畫面中央附近


def test_person_disappears_then_head_holds_and_reports_no_target():
    person = SyntheticPerson(yaw=0.2, pitch=0.2, distance_m=1.5)
    src, pipe = make([person])

    def vanish(t, source):
        person.visible = t < 2.0

    log = simulate_head_tracking(src, pipe, duration_s=3.5, on_step=vanish)
    assert log.state[90] == "tracking"
    assert log.state[-1] in ("hold", "search")
    assert not pipe.tracker.has_target and pipe.tracker.lost_count == 1


def test_pipeline_sends_face_messages_with_mock_flag_and_stereo_distance():
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(2.0)
    tx = UdpTargetSender(port=rx.getsockname()[1])
    src, pipe = make([SyntheticPerson(yaw=0.1, pitch=0.1, distance_m=1.2)], sender=tx)
    simulate_head_tracking(src, pipe, duration_s=1.0)
    msgs = []
    rx.setblocking(False)
    while True:
        try:
            msgs.append(decode_target(rx.recv(2048)))
        except BlockingIOError:
            break
    assert len(msgs) == 10  # 10 Hz × 1 秒
    assert all(m["kind"] == "face" and m["mock"] is True for m in msgs)
    assert msgs[-1]["distance_m"] == pytest.approx(1.2, rel=0.08)  # 合成雙目估距
    assert abs(msgs[-1]["bearing_yaw_rad"]) < 0.05  # 頭轉過去之後，臉在光軸附近
    tx.close()
    rx.close()


def test_missing_model_raises_instead_of_fake_detections(tmp_path):
    with pytest.raises(ModelMissing):
        YuNetDetector((640, 360), model_path=tmp_path / "nope.onnx")


@needs_model
def test_yunet_smoke_on_synthetic_faces():
    """煙霧測試：YuNet 在**合成示意臉**上有輸出、位置對得上真值。不代表對真人的偵測率。"""
    rig = StereoRig.ar0144_nominal(640, 360)
    src = SyntheticStereoSource(rig=rig, people=[SyntheticPerson(0.1, 0.05, 1.0, seed=1), SyntheticPerson(-0.2, -0.05, 2.0, seed=2)])
    dets = YuNetDetector((640, 360)).detect(src.read().left)
    assert len(dets) == 2
    for ft in src.truth():
        d = min(dets, key=lambda d: abs(d.u - ft.u))
        assert abs(d.u - ft.u) < 0.15 * ft.width_px and abs(d.v - ft.v) < 0.25 * ft.width_px
        assert 0.75 < d.width_px / ft.width_px < 1.1
    assert YuNetDetector((640, 360)).detect(SyntheticStereoSource(rig=rig).read().left) == []


@needs_model
def test_closed_loop_with_real_detector_on_synthetic_frames():
    src = SyntheticStereoSource(people=[SyntheticPerson(yaw=0.28, pitch=0.22, distance_m=1.5, seed=4)])
    pipe = FacePipeline(src, YuNetDetector((640, 360)))
    log = simulate_head_tracking(src, pipe, duration_s=3.0)
    assert log.final_error() < 4 * DEG
    assert log.frames_with_target >= log.frames - 2
