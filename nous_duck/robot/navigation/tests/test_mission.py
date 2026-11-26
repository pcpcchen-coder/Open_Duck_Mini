"""C5／C6：任務狀態機、事件形狀、回充。驗證層級：單元測試（運動學 mock 身體＋mock 感測器）。"""

import math

import pytest

from duck_nav.geometry import to_body, wrap
from duck_nav.navigator import BASE_TO_CONTACT_M, FAIL_REASONS, NavConfig
from duck_nav.testing import make_kinematic_loop


def _go(loop, place, max_s=400.0):
    ack = loop.nav.go_to(place)
    assert ack["status"] == "accepted", ack
    n0 = len(loop.result.events)
    loop.run_until_idle(max_s)
    return ack, loop.result.events[n0:]


def test_go_to_reaches_place_and_events_validate(home, validate_event):
    loop = make_kinematic_loop(home, seed=0)
    ack, events = _go(loop, "brother_room")
    names = [e["event"] for e in events]
    assert names[0] == "mission_progress" or names[0] == "undocked"
    assert names[-1] == "mission_done"
    assert "mission_failed" not in names
    for e in events:
        validate_event(e)
        assert e["mission_id"] == ack["mission_id"]
        assert e["data"]["mock"] is True  # mock 身體與感測器：事件要標示
    p = home.places["brother_room"]
    tp = loop.body.true_pose
    assert math.hypot(tp.x - p.x, tp.y - p.y) < 0.25
    assert loop.body.collisions == 0
    progress = [e["data"]["progress"] for e in events if e["event"] == "mission_progress"]
    assert progress == sorted(progress) and 0 <= progress[0] and progress[-1] <= 1
    # 任務結束後不再要求控制權，速度為 0。
    out = loop.step()
    assert out.active is False and out.velocity == (0.0, 0.0, 0.0)


def test_final_heading_for_places_with_yaw(home):
    loop = make_kinematic_loop(home, seed=1)
    _, events = _go(loop, "brother_bedside")
    assert events[-1]["event"] == "mission_done"
    assert abs(wrap(loop.body.true_pose.yaw - home.places["brother_bedside"].yaw)) < 0.35


def test_one_mission_at_a_time_and_unknown_place(home):
    loop = make_kinematic_loop(home, seed=0)
    assert loop.nav.go_to("garage") == {"status": "rejected", "reason": "unknown_name"}
    assert loop.nav.cancel() == {"status": "rejected", "reason": "no_mission"}
    assert loop.nav.mission_status() == {"status": "rejected", "reason": "no_mission"}
    a = loop.nav.go_to("study_room")
    b = loop.nav.go_to("brother_room")
    assert b == {"status": "rejected", "reason": "busy_mission", "mission_id": a["mission_id"]}
    assert loop.nav.return_home()["reason"] == "busy_mission"


def test_cancel_stops_and_reports(home, validate_event):
    loop = make_kinematic_loop(home, seed=0)
    ack = loop.nav.go_to("study_room")
    loop.run_for(12.0)
    assert loop.nav.mission_state()["mission_id"] == ack["mission_id"]
    assert loop.nav.cancel(ack["mission_id"])["status"] == "accepted"
    out = loop.step()
    assert out.velocity == (0.0, 0.0, 0.0) and out.active is False
    ev = out.events[-1]
    validate_event(ev)
    assert ev["event"] == "mission_failed" and ev["reason"] == "cancelled"
    st = loop.nav.mission_status(ack["mission_id"])["data"]
    assert st["state"] == "failed" and st["reason"] == "cancelled"
    # 取消之後可以接新的任務。
    assert loop.nav.go_to("living_room")["status"] == "accepted"


def test_read_actions_shapes(home, validate_event):
    loop = make_kinematic_loop(home, seed=0)
    w = loop.nav.where()
    assert w["place"] == "dock" and w["on_dock"] is True and w["localized"] is True and w["mock"] is True
    assert "x" not in w and "pose" not in w  # 不把座標交給 Nous
    places = loop.nav.places()
    assert places["synthetic_map"] is True
    assert {"place": "dock", "room": "living_room", "is_dock": True} in places["places"]
    loop.nav.go_to("hallway")
    loop.run_for(8.0)
    # where／mission 的資料可以直接放進 duck-link 的 state。
    state = {
        "protocol_version": "0.1",
        "type": "state",
        "sent_at_ms": 1,
        "mock": True,
        "mode": "walking",
        "control_source": "mission",
        "capabilities": {"navigation": {"status": "mock"}, "dock": {"status": "mock"}},
        "faults": [],
        "mission": loop.nav.mission_state(),
        "location": loop.nav.location_state(),
    }
    validate_event(state)
    assert state["mission"]["kind"] == "go_to" and state["location"]["on_dock"] is False


def test_mission_timeout(home, validate_event):
    loop = make_kinematic_loop(home, seed=0, config=NavConfig(mission_timeout_s=6.0))
    _, events = _go(loop, "study_room")
    assert events[-1]["event"] == "mission_failed" and events[-1]["reason"] == "timeout"
    validate_event(events[-1])
    assert loop.step().velocity == (0.0, 0.0, 0.0)


def test_fail_reasons_are_fixed_codes():
    assert set(FAIL_REASONS) >= {"door_closed", "lost", "blocked", "forbidden", "timeout", "fell"}


def test_return_home_docks_backwards_with_mock_charging(home, validate_event):
    loop = make_kinematic_loop(home, seed=0)
    _go(loop, "living_room")
    loop.dock.reset()
    assert loop.nav.return_home()["status"] == "accepted"
    n0 = len(loop.result.events)
    loop.run_until_idle()
    events = loop.result.events[n0:]
    names = [e["event"] for e in events]
    assert names[-3:] == ["docked", "charging_started", "mission_done"], (names, events[-1])
    for e in events:
        validate_event(e)
    done = events[-1]
    assert done["data"]["charging_signal_mock"] is True  # 模擬裡的充電訊號是 mock
    assert events[-2]["data"]["signal"] == "mock"
    # 背對充電座（面朝外）停在座上：觸點面貼著停止面。
    tp = loop.body.true_pose
    xd, yd = to_body(home.dock.pose, tp.x, tp.y)
    assert abs(wrap(tp.yaw - home.dock.pose.yaw)) < math.radians(6)
    assert xd - BASE_TO_CONTACT_M < 0.01 and abs(yd) < 0.04
    assert loop.nav.where()["on_dock"] is True
    # 第一次進導引座開口時在 CAD 的捕捉範圍內。
    assert loop.dock.entries[-1]["captured"]
    # 下一個任務會先離開充電座。
    ack, events = _go(loop, "hallway")
    assert events[0]["event"] == "undocked" or "undocked" in [e["event"] for e in events]
    assert events[-1]["event"] == "mission_done"


def test_go_to_dock_place_is_return_home(home):
    loop = make_kinematic_loop(home, seed=3)
    _go(loop, "living_room")
    ack = loop.nav.go_to("dock")
    assert ack["status"] == "accepted"
    assert loop.nav.mission.kind == "return_home"


def test_without_charging_signal_docking_is_not_confirmed(home):
    """沒有電氣訊號就不能說「開始充電」：倒退到底仍沒有訊號，最後回報 dock_failed。"""
    loop = make_kinematic_loop(home, seed=4)
    _go(loop, "living_room")
    loop.dock = None  # 沒有充電訊號來源（frame.charging 會是 None）
    loop.nav.return_home()
    n0 = len(loop.result.events)
    loop.run_until_idle(600.0)
    events = loop.result.events[n0:]
    assert events[-1]["event"] == "mission_failed" and events[-1]["reason"] == "dock_failed"
    assert "charging_started" not in [e["event"] for e in events]


@pytest.mark.slow
def test_docking_success_rate_kinematic(home):
    """運動學 mock、30 個種子：含重試的成功率。數字記在驗證紀錄。"""
    ok = 0
    for seed in range(30):
        loop = make_kinematic_loop(home, seed=seed)
        _go(loop, "living_room")
        loop.nav.return_home()
        loop.run_until_idle(600.0)
        d = loop.result.last("mission_done")
        ok += bool(d and d["data"]["kind"] == "return_home")
    assert ok >= 18, ok
