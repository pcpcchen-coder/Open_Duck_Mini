"""presence 編排：狀態 → 表情＋頭部；speech_level 只在有真實更新時才讓頭點動。"""
import math

import pytest
from conftest import make_harness

from duckd import presence as pr
from duckd.limits import Limits


def test_table_covers_every_protocol_state():
    from conftest import PROTOCOL

    states = PROTOCOL.schema["$defs"]["presence_params"]["properties"]["state"]["enum"]
    assert set(states) == set(pr.PRESENCE_STATES) == set(pr.EXPRESSION)


def test_head_targets_are_small_and_slow():
    lim = Limits()
    for state in pr.PRESENCE_STATES:
        p = pr.PresenceState()
        p.set(state, 1.0 if state == "speaking" else None, 0.0)
        prev, t = pr.head_target(p, 0.0), 0.0
        for _ in range(500):
            t += 0.02
            if state == "speaking":
                p.set(state, 1.0, t)
            cur = pr.head_target(p, t)
            for n, v in cur.items():
                lo, hi = lim.head_range[n]
                assert lo <= v <= hi and abs(v) <= 0.25 + 1e-9
                assert abs(v - prev[n]) / 0.02 <= lim.head_max_speed, (state, n)
            prev = cur


def test_presence_poses(h):
    assert h.cmd("presence", {"state": "listening"})["applied"] == {"state": "listening"}
    h.run(1.0)
    assert h.body.head["head_roll"] == pytest.approx(0.12, abs=0.01)
    assert h.last_state()["presence"] == "listening"
    h.cmd("presence", {"state": "sleeping"})
    h.run(1.5)
    assert h.body.head["head_pitch"] == pytest.approx(-0.25, abs=0.01) and h.body.head["head_roll"] == pytest.approx(0, abs=0.01)
    h.cmd("presence", {"state": "idle"})
    h.run(1.5)
    assert all(abs(v) < 0.01 for v in h.body.head.values())


def test_error_shakes_once_then_rests(h):
    h.cmd("presence", {"state": "error"})
    h.run(1.7)
    yaws = [s["head_yaw"] for s in h.body.setpoints]
    assert max(yaws) > 0.08 and min(yaws) < -0.08
    n = len(h.body.setpoints)
    h.run(2.0)
    assert all(abs(s["head_yaw"]) < 1e-3 for s in h.body.setpoints[n + 20 :])


def test_speaking_bobs_only_while_speech_level_is_fresh(h):
    h.cmd("presence", {"state": "speaking"})  # 沒有 speech_level：不點動
    h.run(1.0)
    assert all(abs(s["head_pitch"]) < 1e-6 for s in h.body.setpoints)
    for _ in range(20):  # 2 s，每 0.1 s 更新一次音量
        h.cmd("presence", {"state": "speaking", "speech_level": 1.0})
        h.run(0.1)
    pitches = [s["head_pitch"] for s in h.body.setpoints[-100:]]
    assert min(pitches) < -0.03 and max(pitches) > -0.01 and min(pitches) >= -pr.SPEECH_BOB_RAD - 1e-9
    h.run(1.5)  # 音量不再更新 → 0.6 s 後停止點動
    assert all(abs(s["head_pitch"]) < 1e-3 for s in h.body.setpoints[-20:])


def test_explicit_look_overrides_presence_until_state_changes(h):
    h.cmd("presence", {"state": "thinking"})
    h.run(0.5)
    h.cmd("look", {"head_yaw": 0.3})
    h.run(1.5)
    assert h.body.head["head_yaw"] == pytest.approx(0.3, abs=0.01)
    h.cmd("presence", {"state": "thinking"})  # 狀態沒變：不搶回來
    h.run(0.5)
    assert h.body.head["head_yaw"] == pytest.approx(0.3, abs=0.01)
    h.cmd("presence", {"state": "listening"})
    h.run(1.5)
    assert h.body.head["head_yaw"] == pytest.approx(0.0, abs=0.01)


def test_link_loss_drops_presence_to_idle_and_stops_motion(h):
    h.cmd("presence", {"state": "thinking"})
    h.run(1.0)
    h.heartbeats = False
    h.run(2.0)
    frozen = dict(h.arbiter.head_cmd)
    h.run(2.0)
    assert h.arbiter.head_cmd == frozen and h.core.presence.state == "idle"
    h.heartbeats = True
    h.run(1.0)
    assert h.arbiter.head_cmd == frozen  # 恢復後不自己動


def test_presence_without_head_still_accepted_for_eyes():
    h = make_harness(engage=False)
    assert h.cmd("presence", {"state": "listening"})["status"] == "accepted"
    h.tick()
    assert h.last_state()["presence"] == "listening" and h.body.setpoints == []
    assert math.isfinite(h.t)


def test_face_yaw_is_kept_through_the_conversation_and_cleared_when_it_ends():
    p = pr.PresenceState()
    p.set("wake", None, 0.0)
    p.face_yaw = 0.2
    assert pr.head_target(p, 0.5) == pytest.approx({"neck_pitch": 0.0, "head_pitch": 0.10, "head_yaw": 0.2, "head_roll": 0.0})
    # 幅度只縮小動作，不縮朝向；頭部動作整個關掉就不轉
    assert pr.head_target(p, 0.5, amplitude=0.5)["head_yaw"] == pytest.approx(0.2)
    assert pr.head_target(p, 0.5, amplitude=0.5)["head_pitch"] == pytest.approx(0.05)
    assert pr.head_target(p, 0.5, motion=False) == pr.ZERO
    p.set("listening", None, 1.0)
    assert pr.head_target(p, 1.5)["head_yaw"] == pytest.approx(0.2)
    p.set("speaking", 1.0, 2.0)
    assert pr.head_target(p, 2.1, speaking_bob=False)["head_yaw"] == pytest.approx(0.2)
    p.set("idle", None, 3.0)
    assert p.face_yaw == 0.0 and pr.head_target(p, 3.5) == pr.ZERO
