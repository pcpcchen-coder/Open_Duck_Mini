"""動作庫（ADR-0011）：載入時檢查、播放、完成事件。"""
import copy
import json
import math

import pytest
from conftest import make_harness

from duckd.gestures import LIBRARY_DIR, GestureError, GestureLibrary, parse_gesture
from duckd.limits import Limits

NOD = json.loads((LIBRARY_DIR / "nod.json").read_text(encoding="utf-8"))


def test_library_loads_the_four_initial_gestures_within_limits():
    lib = GestureLibrary(Limits())
    assert lib.rejected == {}
    assert set(lib.gestures) == {"nod", "shake", "tilt", "look_around"}
    for g in lib.gestures.values():
        assert g.peak_speed() <= Limits().head_max_speed * 1.001  # 30°/s
        assert g.duration_s <= 10
        assert "neck_pitch" not in g.head  # ADR-0011 §2.3：neck_pitch 固定 0
        for keys in g.head.values():
            assert max(abs(v) for _, v in keys) <= math.radians(15)  # 夜間規則：±15° 內
            assert keys[0][1] == 0 and keys[-1][1] == 0


@pytest.mark.parametrize(
    "mutate, why",
    [
        (lambda d: d["tracks"]["head"].__setitem__("head_pitch", [[0, 0], [0.7, -0.9], [1.4, 0]]), "超出允許範圍"),
        (lambda d: d["tracks"]["head"].__setitem__("head_pitch", [[0, 0], [0.1, -0.18], [0.2, 0]]), "超過上限"),
        (lambda d: d["tracks"]["head"].__setitem__("neck_pitch", [[0, 0], [1.0, 0.2], [2.0, 0]]), "超出允許範圍"),
        (lambda d: d["tracks"]["head"].__setitem__("left_knee", [[0, 0], [1.0, 0.1], [2.0, 0]]), "沒有這個頭部關節"),
        (lambda d: d["tracks"]["head"].__setitem__("head_pitch", [[0, 0], [1.0, -0.1]]), "回到中立"),
        (lambda d: d["tracks"]["head"].__setitem__("head_pitch", [[0, 0], [1.0, -0.1], [0.5, 0]]), "時間要遞增"),
        (lambda d: d["tracks"].__setitem__("vel", {"lin_vel_x": [[0, 0], [1, 0.1]]}), "只實作 head 軌"),
        (lambda d: d["tracks"].__setitem__("antennas", {"left": [[0, 0], [1, 1]]}), "只實作 head 軌"),
        (lambda d: d.__setitem__("category", "B"), "只支援 A 類"),
        (lambda d: d.__setitem__("allowed_modes", ["paused"]), "allowed_modes"),
        (lambda d: d.__setitem__("id", "Nod!"), "id 不合格"),
    ],
)
def test_bad_definitions_are_rejected_at_load_not_silently_clamped(mutate, why):
    data = copy.deepcopy(NOD)
    mutate(data)
    with pytest.raises(GestureError, match=why):
        parse_gesture(data, Limits())


def test_rejected_file_is_reported_and_not_listed(tmp_path):
    bad = copy.deepcopy(NOD)
    bad["tracks"]["head"]["head_pitch"] = [[0, 0], [0.1, -0.18], [0.2, 0]]
    (tmp_path / "nod.json").write_text(json.dumps(bad))
    lib = GestureLibrary(Limits(), tmp_path)
    assert lib.gestures == {} and "nod.json" in lib.rejected


def test_only_real_verified_gestures_are_listed_by_default():
    lib = GestureLibrary(Limits())
    levels = {g.id: (g.verification_level, g.hardware_profile) for g in lib.gestures.values()}
    expected = sorted(i for i, (lv, prof) in levels.items() if lv == "real" and prof == "stock_head_direct_hold")
    assert lib.listed("stock_head_direct_hold", allow_unverified=False) == expected
    assert lib.listed("some_other_head", allow_unverified=False) == []  # 換了硬體就不列
    assert lib.listed("some_other_head", allow_unverified=True) == sorted(lib.gestures)
    h = make_harness(allow_unverified_gestures=False, hardware_profile="some_other_head")
    assert h.sent[0]["gestures"] == []
    assert h.cmd("gesture", {"name": "nod"})["reason"] == "unsupported"
    assert h.cmd("gesture", {"name": "moonwalk"})["reason"] == "unknown_name"


def test_gesture_plays_through_arbiter_and_reports_done(h):
    ack = h.cmd("gesture", {"name": "nod"})
    assert ack["status"] == "accepted" and ack["applied"] == {"name": "nod", "duration_s": 2.8}
    h.run(3.5)
    done = h.events("gesture_done")
    assert len(done) == 1 and done[0]["request_id"] == ack["request_id"]
    assert done[0]["data"] == {"name": "nod", "completed": True, "clamped": False}
    pitches = [s["head_pitch"] for s in h.body.setpoints]
    assert min(pitches) == pytest.approx(-0.18, abs=0.005) and pitches[-1] == pytest.approx(0.0, abs=1e-6)
    step = max(abs(b - a) for a, b in zip(pitches, pitches[1:]))
    assert step <= Limits().head_max_speed * 0.02 + 1e-9  # 送給身體的設定值沒有超過限速
    assert all(s["head_yaw"] == 0 and s["neck_pitch"] == 0 for s in h.body.setpoints)


def test_second_gesture_while_playing_is_refused(h):
    assert h.cmd("gesture", {"name": "shake"})["status"] == "accepted"
    h.run(0.5)
    ack = h.cmd("gesture", {"name": "nod"})
    assert ack["status"] == "rejected" and ack["detail"].startswith("busy")
    h.run(5.0)
    assert [e["data"]["name"] for e in h.events("gesture_done")] == ["shake"]
    assert h.cmd("gesture", {"name": "nod"})["status"] == "accepted"


def test_look_interrupts_gesture(h):
    h.cmd("gesture", {"name": "look_around"})
    h.run(1.0)
    assert h.cmd("look", {"head_yaw": 0.0})["status"] == "accepted"
    ev = h.events("gesture_done")[0]
    assert ev["reason"] == "interrupted" and ev["data"]["completed"] is False


def test_gesture_is_clamped_by_window_and_says_so():
    h = make_harness(limits=Limits(head_window=math.radians(5)))
    h.cmd("gesture", {"name": "nod"})
    h.run(3.5)
    assert h.events("gesture_done")[0]["data"]["clamped"] is True
    assert min(s["head_pitch"] for s in h.body.setpoints) >= -math.radians(5) - 1e-9
