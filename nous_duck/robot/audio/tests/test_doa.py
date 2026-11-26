"""XVF3800 DOA：解碼、環狀分群、正前方校準、只在有語音時送方位。

裝置是**模擬的**（`MockDoaReader`，或測試自己做的假 USB 物件）；沒有真的麥克風參與。
"""
import json
import math

import pytest

from duck_audio import doa
from duck_audio.doa import DoaConfig, DoaError, DoaEstimator, DoaService, MockDoaReader


def test_decode_doa():
    assert doa.decode_doa(bytes([0]) + (359).to_bytes(2, "little") + (1).to_bytes(2, "little")) == (359.0, True)
    assert doa.decode_doa(bytes([0, 90, 0, 0, 0])) == (90.0, False)
    assert doa.decode_doa(bytes([0]) + (365).to_bytes(2, "little") + b"\x00\x00")[0] == 5.0
    with pytest.raises(DoaError, match="長度"):
        doa.decode_doa(b"\x00\x01")
    with pytest.raises(DoaError, match="狀態"):
        doa.decode_doa(bytes([3, 0, 0, 0, 0]))


class FakeUsbDevice:
    """假的 USB 裝置（mock）：記錄 ctrl_transfer 的參數，前兩次回「重試」。"""

    idVendor, idProduct, bcdDevice = 0x2886, 0x001A, 0x0201
    manufacturer, product = "fake", "fake xvf3800 (mock)"

    def __init__(self):
        self.calls = []

    def ctrl_transfer(self, *args):
        self.calls.append(args)
        if len(self.calls) <= 2:
            return bytes([64, 0, 0, 0, 0])
        return bytes([0]) + (270).to_bytes(2, "little") + (1).to_bytes(2, "little")


class FakeUsbCore:
    def __init__(self, dev):
        self.dev, self.find_kwargs = dev, None

    def find(self, **kw):
        self.find_kwargs = kw
        return self.dev


def test_reader_uses_vendor_control_request_and_retries():
    dev = FakeUsbDevice()
    core = FakeUsbCore(dev)
    reader = doa.XVF3800Reader(usb_core=core)
    assert core.find_kwargs == {"idVendor": 0x2886}  # 不限定 PID：別的版本也先找得到，再照實記錄
    assert reader.read() == (270.0, True)
    assert len(dev.calls) == 3
    assert dev.calls[0][:5] == (0xC0, 0, 0x80 | 18, 20, 5)  # vendor IN、resource 20、command 18、5 bytes
    d = reader.describe()
    assert d["vid"] == "2886" and d["pid"] == "001a" and d["bcdDevice"] == "2.01" and d["known_pid"]
    assert reader.verified_product and reader.mock is False


def test_unknown_pid_is_accepted_but_flagged_and_missing_device_is_an_error():
    dev = FakeUsbDevice()
    dev.idProduct = 0x0099
    reader = doa.XVF3800Reader(usb_core=FakeUsbCore(dev))
    assert not reader.verified_product and reader.describe()["known_pid"] is None
    with pytest.raises(DoaError, match="找不到"):
        doa.XVF3800Reader(usb_core=FakeUsbCore(None))


def test_circular_helpers():
    assert doa.angular_distance_deg(358, 2) == 4
    assert doa.circular_mean_deg([358, 2]) == pytest.approx(0, abs=1e-6) or doa.circular_mean_deg([358, 2]) == pytest.approx(360, abs=1e-6)
    clusters = doa.cluster_angles([358, 2, 0, 5, 180, 175, 356], 25)
    assert len(clusters) == 2 and len(clusters[0]) == 5 and sorted(clusters[1]) == [175, 180]


@pytest.mark.parametrize(
    "raw, front, ccw, expect_deg",
    [(0, 0, True, 0), (45, 0, True, 45), (315, 0, True, -45), (45, 0, False, -45), (100, 90, True, 10), (80, 90, True, -10), (270, 90, True, 180), (10, 350, True, 20)],
)
def test_to_bearing(raw, front, ccw, expect_deg):
    cfg = DoaConfig(front_angle_deg=front, counterclockwise=ccw)
    assert math.degrees(doa.to_bearing_rad(raw, cfg)) == pytest.approx(expect_deg, abs=1e-6)


def test_estimator_needs_speech_and_picks_the_main_cluster():
    est = DoaEstimator(DoaConfig(front_angle_deg=90))
    t = 0.0
    for a in (10, 200, 300, 40):  # 沒有語音：角度是雜訊，不能用
        est.add(t, a, False)
        t += 0.05
    assert est.estimate(t) is None
    for a in (120, 118, 122, 119, 300):
        est.add(t, a, True)
        t += 0.05
    raw, bearing, conf = est.estimate(t)
    assert raw == pytest.approx(119.75, abs=0.1) and math.degrees(bearing) == pytest.approx(29.75, abs=0.1) and conf == 0.8
    assert est.estimate(t + 1.0) is None  # 視窗過了


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def run(service, clock, seconds):
    for _ in range(round(seconds * 20)):
        service.step()
        clock.t += 0.05


def test_service_sends_sound_only_while_speech_and_status_every_second():
    clock, sent = Clock(), []
    reader = MockDoaReader(angle_deg=30, speech=False)
    svc = DoaService(reader, DoaConfig(), sent.append, clock=clock)
    run(svc, clock, 3.0)
    msgs = [json.loads(m) for m in sent]
    assert [m["kind"] for m in msgs] == ["status"] * 3  # 安靜：只有「我還在」
    assert all(m["ok"] and m["mock"] and m["source"] == "sound" for m in msgs)
    sent.clear()
    reader.speech = True
    run(svc, clock, 2.0)
    sounds = [json.loads(m) for m in sent if b'"sound"' in m and b'"kind": "sound"' in m]
    assert 12 <= len(sounds) <= 20  # 最多 10 Hz
    s = sounds[-1]
    assert s["mock"] is True and s["frame"] == "body" and s["bearing_pitch_rad"] == 0.0 and s["distance_m"] is None
    assert s["bearing_yaw_rad"] == pytest.approx(math.radians(30), abs=1e-3) and s["confidence"] == 1.0
    assert set(s) == {"v", "kind", "frame", "bearing_yaw_rad", "bearing_pitch_rad", "distance_m", "confidence", "t_ms", "mock"}
    sent.clear()
    reader.speech = False
    run(svc, clock, 2.0)
    assert all(json.loads(m)["kind"] == "status" for m in sent[5:])  # 視窗清空後不再送方位


def test_head_mount_marks_frame_and_bad_mount_is_rejected(tmp_path):
    clock, sent = Clock(), []
    svc = DoaService(MockDoaReader(10), DoaConfig(mount="head"), sent.append, clock=clock)
    run(svc, clock, 1.0)
    assert {json.loads(m).get("frame") for m in sent if b'"kind": "sound"' in m} == {"head"}
    bad = tmp_path / "doa.json"
    bad.write_text(json.dumps({"mount": "ceiling"}))
    with pytest.raises(DoaError):
        DoaConfig.load(bad)
    assert DoaConfig.load(tmp_path / "missing.json") == DoaConfig()


def test_read_failure_reports_not_ok_and_sends_no_bearing():
    clock, sent = Clock(), []
    reader = MockDoaReader(30)
    svc = DoaService(reader, DoaConfig(), sent.append, clock=clock)
    run(svc, clock, 1.0)
    sent.clear()
    reader.fail = "usb unplugged"
    run(svc, clock, 2.0)
    msgs = [json.loads(m) for m in sent]
    statuses = [m for m in msgs if m["kind"] == "status"]
    assert statuses and all(not m["ok"] and "usb unplugged" in m["detail"] for m in statuses)
    assert not [m for m in msgs if m["kind"] == "sound"]
    assert svc.read_errors == 40


def test_real_uncalibrated_source_says_so():
    class Real(MockDoaReader):
        mock = False

    clock, sent = Clock(), []
    DoaService(Real(0, speech=False), DoaConfig(), sent.append, clock=clock).step()
    assert json.loads(sent[0])["detail"] == "front angle not calibrated" and json.loads(sent[0])["mock"] is False


def test_calibrate():
    clock = Clock()

    def sleep(dt):
        clock.t += dt

    out = doa.calibrate(MockDoaReader(137), 2.0, DoaConfig(), clock=clock, sleep=sleep)
    assert out["ok"] and out["front_angle_deg"] == 137.0 and out["share"] == 1.0
    out = doa.calibrate(MockDoaReader(137, speech=False), 2.0, DoaConfig(), clock=clock, sleep=sleep)
    assert not out["ok"]


def test_messages_are_accepted_by_duckd_percept():
    """和 duckd 的接收端對一次格式（兩個程式不共用程式碼，只共用這個本機格式）。"""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "duckd"))
    percept = pytest.importorskip("duckd.percept")
    o = percept.parse(doa.sound_message(0.3, 0.9, True, "head"), 1.0)
    assert (o.kind, o.yaw, o.frame, o.mock) == ("sound", 0.3, "head", True)
    st = percept.parse_status(doa.status_message(True, False, "x"), 1.0)
    assert (st.source, st.ok, st.mock, st.detail) == ("sound", True, False, "x")


def test_run_forever_reports_missing_device_then_starts_when_plugged_in():
    import socket
    import threading
    import time as _time

    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(3.0)
    attempts = []

    def open_reader():
        attempts.append(1)
        if len(attempts) < 2:
            raise DoaError("找不到 XVF3800")
        return MockDoaReader(45)  # 模擬「後來接上了」

    done = threading.Event()
    th = threading.Thread(target=doa.run_forever, args=(DoaConfig(), rx.getsockname()), kwargs={"open_reader": open_reader, "retry_s": 0.2, "stop": done.is_set}, daemon=True)
    th.start()
    first = json.loads(rx.recvfrom(2048)[0])
    assert first == {"v": 1, "kind": "status", "source": "sound", "ok": False, "mock": False, "detail": "XVF3800 not found"}
    deadline, got_sound = _time.monotonic() + 5, False
    while _time.monotonic() < deadline and not got_sound:
        got_sound = json.loads(rx.recvfrom(2048)[0])["kind"] == "sound"
    done.set()
    th.join(timeout=3)
    assert got_sound and len(attempts) >= 2
