"""安全仲裁器的規則（ADR-0009 §2.5）。純邏輯，時間用假時鐘；感測輸入是假的（mock）。"""
import math

import pytest

from duckd.arbiter import SafetyArbiter, clamp_velocity
from duckd.limits import HEAD_JOINTS, Limits

ZERO = {n: 0.0 for n in HEAD_JOINTS}
DT = 0.02


def arb(walk=True, **lim) -> SafetyArbiter:
    a = SafetyArbiter(Limits(**lim), walk_supported=walk, walk_unsupported_reason="feet switches not wired")
    a.enable_head(ZERO)
    a.heartbeat(0.0)
    return a


def run(a: SafetyArbiter, t0: float, seconds: float, hb: bool = True):
    """推進時間；回傳（結束時間, 每圈的輸出）。"""
    outs, t = [], t0
    for i in range(round(seconds / DT)):
        if hb and i % 25 == 0:
            a.heartbeat(t)
        outs.append(a.update(t, DT))
        t += DT
    return t, outs


def events(outs):
    return [name for o in outs for name, _ in o.events]


# ---------------------------------------------------------------- 頭
def test_look_clamps_to_range_and_reports_applied():
    a = arb()
    d = a.request_look({"head_yaw": 2.0, "head_pitch": -0.1}, 3000, 0.0)
    assert d.accepted and d.clamped
    assert d.applied["head_yaw"] == pytest.approx(0.5) and d.applied["head_pitch"] == pytest.approx(-0.1)
    d = a.request_look({"head_roll": 0.1}, 3000, 0.0)
    assert d.accepted and not d.clamped


def test_head_setpoint_is_rate_limited():
    a = arb()
    a.request_look({"head_yaw": 0.5}, 60000, 0.0)
    t, outs = run(a, 0.0, 0.5)
    step = Limits().head_max_speed * DT
    prev = 0.0
    for o in outs:
        assert o.head["head_yaw"] - prev <= step + 1e-12
        prev = o.head["head_yaw"]
    assert prev == pytest.approx(Limits().head_max_speed * 0.5, rel=1e-6)  # 30°/s × 0.5 s


def test_look_duration_slows_down_and_too_short_is_reported():
    a = arb()
    d = a.request_look({"head_yaw": 0.2, "duration_s": 2.0}, 60000, 0.0)
    assert d.accepted and not d.clamped and d.applied["duration_s"] == pytest.approx(2.0)
    t, outs = run(a, 0.0, 1.0)
    assert outs[-1].head["head_yaw"] == pytest.approx(0.1, abs=0.003)  # 一半時間走一半
    a = arb()
    d = a.request_look({"head_yaw": 0.5, "duration_s": 0.1}, 60000, 0.0)
    assert d.accepted and d.clamped  # 限速下做不到 0.1 s
    assert d.applied["duration_s"] == pytest.approx(0.5 / Limits().head_max_speed, abs=1e-3)


def test_look_ttl_expiry_freezes_head():
    a = arb()
    a.request_look({"head_yaw": 0.5}, 400, 0.0)
    t, outs = run(a, 0.0, 1.5)
    assert outs[-1].head["head_yaw"] == pytest.approx(Limits().head_max_speed * 0.4, abs=0.02)
    assert outs[-1].head == outs[-10].head  # 停住了


def test_window_limits_motion_around_engage_pose():
    a = SafetyArbiter(Limits(head_window=math.radians(15)))
    a.enable_head({**ZERO, "head_yaw": 0.1})
    a.heartbeat(0.0)
    d = a.request_look({"head_yaw": 0.5, "head_roll": -0.4}, 3000, 0.0)
    assert d.clamped
    assert d.applied["head_yaw"] == pytest.approx(0.1 + math.radians(15), abs=1e-4)
    assert d.applied["head_roll"] == pytest.approx(-math.radians(15), abs=1e-4)
    # 接手時已經在範圍外：只准回到範圍邊界，不准再往外
    a = SafetyArbiter(Limits(head_window=math.radians(15)))
    a.enable_head({**ZERO, "head_yaw": 0.9})
    a.heartbeat(0.0)
    assert a.request_look({"head_yaw": 0.9}, 3000, 0.0).applied["head_yaw"] == pytest.approx(0.5)


def test_look_rejected_without_head_or_lease():
    a = SafetyArbiter(Limits())
    a.heartbeat(0.0)
    assert a.request_look({"head_yaw": 0.1}, 3000, 0.0).reason == "unsupported"
    a.enable_head(ZERO)
    assert a.request_look({"head_yaw": 0.1}, 3000, 0.0).accepted
    b = SafetyArbiter(Limits())
    b.enable_head(ZERO)  # 沒有 heartbeat
    assert b.request_look({"head_yaw": 0.1}, 3000, 0.0).reason == "link_degraded"
    assert a.request_look({"head_yaw": float("nan")}, 3000, 0.0).reason == "invalid"


# ---------------------------------------------------------------- 租約
def test_lease_loss_stops_within_1_5_s_and_does_not_resume():
    a = arb()
    a.request_look({"head_yaw": 0.5, "duration_s": 10.0}, 60000, 0.0)
    t, outs = run(a, 0.0, 0.3)  # 最後一次 heartbeat 在 t=0
    t, outs = run(a, t, 2.0, hb=False)
    assert events(outs) == ["link_lost"]
    lost_at = next(i for i, o in enumerate(outs) if o.events) * DT + 0.3
    assert 1.5 <= lost_at <= 1.5 + 2 * DT
    frozen = outs[-1].head["head_yaw"]
    assert frozen < 0.5 and outs[-1].head == outs[-5].head
    assert not a.lease_ok
    assert a.request_look({"head_yaw": 0.0}, 3000, t).reason == "link_degraded"
    # 恢復：只回報，不繼續之前的動作
    a.heartbeat(t)
    t, outs = run(a, t, 1.0)
    assert events(outs) == ["link_restored"]
    assert outs[-1].head["head_yaw"] == pytest.approx(frozen)


def test_link_down_is_immediate_and_reported_once():
    a = arb()
    a.request_look({"head_yaw": 0.5}, 60000, 0.0)
    t, _ = run(a, 0.0, 0.2)
    a.link_down(t)
    a.link_down(t)
    t, outs = run(a, t, 0.5, hb=False)
    assert events(outs) == ["link_lost"]
    assert outs[0].head == outs[-1].head


def test_first_heartbeat_is_not_a_restore():
    a = SafetyArbiter(Limits())
    a.heartbeat(0.0)
    assert a.update(0.0, DT).events == []


# ---------------------------------------------------------------- stop／緊急停止
def test_stop_is_always_accepted():
    a = arb()
    a.request_look({"head_yaw": 0.5}, 60000, 0.0)
    t, _ = run(a, 0.0, 0.2)
    assert a.stop(t).accepted
    t, outs = run(a, t, 0.3)
    assert outs[0].head == outs[-1].head
    a.estop("test", t)
    assert a.stop(t).accepted  # 鎖定中
    b = SafetyArbiter(Limits())  # 沒有租約、沒有頭
    assert b.stop(0.0).accepted


def test_estop_latches_until_local_clear():
    a = arb()
    a.request_look({"head_yaw": 0.5}, 60000, 0.0)
    t, _ = run(a, 0.0, 0.2)
    a.estop("operator", t)
    t, outs = run(a, t, 0.5)
    assert events(outs) == ["estop"] and outs[0].head == outs[-1].head
    assert a.request_look({"head_yaw": 0.0}, 3000, t).reason == "estop_latched"
    assert a.request_walk({"vx": 0.05, "duration_s": 1}, 3000, t).reason == "estop_latched"
    assert a.resume(t).reason == "estop_latched"
    assert a.stream_head(ZERO, t) == (False, False)
    assert not a.local_head_goal(ZERO)
    assert a.clear_estop_local()
    assert a.request_look({"head_yaw": 0.0}, 3000, t).accepted
    assert events([a.update(t, DT)]) == ["estop_cleared"]


def test_block_refuses_new_motion_and_halts():
    a = arb()
    a.request_look({"head_yaw": 0.5}, 60000, 0.0)
    t, _ = run(a, 0.0, 0.2)
    a.set_block("overheat", "head servo 56 C")
    t, outs = run(a, t, 0.3)
    assert outs[1].head == outs[-1].head
    assert a.request_look({"head_yaw": 0.0}, 3000, t).reason == "overheat"
    a.set_block(None)
    assert a.request_look({"head_yaw": 0.0}, 3000, t).accepted


# ---------------------------------------------------------------- 走路
def test_velocity_clamp_upstream_then_indoor():
    assert clamp_velocity(1.0, -1.0, 5.0, Limits()) == ((0.10, -0.10, 0.6), True)
    assert clamp_velocity(0.05, 0.0, 0.2, Limits()) == ((0.05, 0.0, 0.2), False)


def test_walk_unsupported_and_starts_paused():
    a = arb(walk=False)
    d = a.request_walk({"vx": 0.05, "duration_s": 1}, 3000, 0.0)
    assert d.reason == "unsupported" and "feet switches" in d.detail
    a = arb()
    assert a.request_walk({"vx": 0.05, "duration_s": 1}, 3000, 0.0).reason == "paused"
    assert a.resume(0.0).accepted
    assert a.request_walk({"vx": 0.05, "duration_s": 1}, 3000, 0.0).accepted


def test_walk_clamp_accel_limit_and_duration_deadline():
    a = arb()
    a.resume(0.0)
    d = a.request_walk({"vx": 0.5, "yaw_rate": 0.3, "duration_s": 9.0}, 60000, 0.0)
    assert d.clamped and d.applied == {"vx": 0.10, "vy": 0.0, "yaw_rate": 0.3, "duration_s": 3.0}
    t, outs = run(a, 0.0, 0.5)
    vx = [o.velocity[0] for o in outs]
    assert all(b - a_ <= 0.01 + 1e-12 for a_, b in zip([0.0] + vx, vx))  # 每圈最多 0.01
    assert vx[9] == pytest.approx(0.10) and vx[4] == pytest.approx(0.05)
    t, outs = run(a, t, 3.0)
    assert "walk_done" in events(outs)
    assert outs[-1].velocity == (0.0, 0.0, 0.0)
    done_i = next(i for i, o in enumerate(outs) if o.events)
    assert 0.5 + done_i * DT == pytest.approx(3.0, abs=0.03)  # duration 上限 3 s


def test_walk_ttl_and_lease_deadlines():
    a = arb()
    a.resume(0.0)
    a.request_walk({"vx": 0.1, "duration_s": 3.0}, 500, 0.0)
    t, outs = run(a, 0.0, 1.5)
    assert outs[-1].velocity == (0.0, 0.0, 0.0)
    i = next(i for i, o in enumerate(outs) if o.events)
    assert i * DT == pytest.approx(0.5, abs=0.03)  # ttl 先到
    a = arb()
    a.resume(0.0)
    a.request_walk({"vx": 0.1, "duration_s": 3.0}, 60000, 0.0)
    t, _ = run(a, 0.0, 0.3)
    t, outs = run(a, t, 2.5, hb=False)
    assert "link_lost" in events(outs) and outs[-1].velocity == (0.0, 0.0, 0.0)
    slow = next(i for i, o in enumerate(outs) if o.velocity[0] < 0.1)
    assert 0.3 + slow * DT <= 1.5 + 2 * DT  # 1.5 s 內開始減速


def test_stop_pauses_only_after_both_feet_down_for_0_3_s():
    a = arb()
    a.resume(0.0)
    a.request_walk({"vx": 0.1, "duration_s": 3.0}, 60000, 0.0)
    t, _ = run(a, 0.0, 0.5)
    a.stop(t)
    a.paused = False  # 這裡只看停下流程
    pauses = []
    for i in range(100):
        a.heartbeat(t)
        feet = (True, not (i < 40 and i % 10 == 0))  # 右腳在第 0、10、20、30 圈離地
        a.observe(t, feet=feet)
        pauses.append(a.update(t, DT).want_pause)
        t += DT
    first = pauses.index(True)
    assert 45 <= first <= 47  # 最後一次離地是第 30 圈；兩腳持續著地 0.3 s（15 圈）之後才暫停
    assert not any(pauses[:first])


def test_stop_reports_when_feet_never_settle():
    a = arb()
    a.resume(0.0)
    a.request_walk({"vx": 0.1, "duration_s": 3.0}, 60000, 0.0)
    t, _ = run(a, 0.0, 0.5)
    a.stop(t)
    a.paused = False
    names = []
    for _ in range(150):
        a.heartbeat(t)
        a.observe(t, feet=(True, False))
        o = a.update(t, DT)
        names += [(n, f.get("reason")) for n, f in o.events]
        assert not o.want_pause
        t += DT
    assert names == [("walk_done", "stop_not_settled")]


def test_fall_latches_after_0_2_s():
    a = arb()
    a.resume(0.0)
    t = 0.0
    a.observe(t, tilt_deg=50)
    a.observe(t + 0.1, tilt_deg=10)  # 中斷：不算
    a.observe(t + 0.2, tilt_deg=50)
    assert not a.fallen
    a.observe(t + 0.45, tilt_deg=-60)
    assert a.fallen
    assert a.request_look({"head_yaw": 0.1}, 3000, 1.0).reason == "fallen"
    assert a.request_walk({"vx": 0.05, "duration_s": 1}, 3000, 1.0).reason == "fallen"
    assert events([a.update(1.0, DT)]) == ["fell"]
    assert a.reset_fallen_local()
    assert a.request_look({"head_yaw": 0.1}, 3000, 1.0).accepted


def test_controller_takeover_rejects_duck_link_for_3_s():
    a = arb()
    a.request_look({"head_yaw": 0.5}, 60000, 0.0)
    t, _ = run(a, 0.0, 0.2)
    a.controller_input(True, t)
    assert a.request_look({"head_yaw": 0.0}, 3000, t + 1.0).reason == "controller_active"
    assert events([a.update(t, DT)]) == ["controller_takeover"]
    assert a.request_look({"head_yaw": 0.0}, 3000, t + 3.01).accepted
