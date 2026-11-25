"""D3：視覺連動走路控制器。單元測試＋純運動學模擬（差速模型，不是步態模擬）。"""

import math

import pytest

from duck_perception.follow import FollowConfig, FollowController, FollowMode, FollowObservation, FollowState
from duck_perception.follow_sim import KinematicWorld, run

DT = 0.02


def ctrl(mode=FollowMode.APPROACH, **kw):
    c = FollowController(FollowConfig(**kw), mode)
    c.activate()
    return c


def obs(t, yaw=0.0, dist=2.0, conf=0.9):
    return FollowObservation(t, yaw, 0.0, dist, conf)


# ---------------------------------------------------------------- 單元


def test_inactive_outputs_zero():
    c = FollowController()
    cmd = c.step(0.0, obs(0.0), 0.0)
    assert (cmd.vx, cmd.yaw_rate, cmd.state) == (0.0, 0.0, FollowState.IDLE)


@pytest.mark.parametrize(
    "o,reason",
    [(None, "lost"), (FollowObservation(-1.0, 0, 0, 2.0), "stale"), (FollowObservation(0.0, 0, 0, 2.0, 0.1), "low_confidence")],
)
def test_no_usable_observation_stops(o, reason):
    c = ctrl()
    cmd = c.step(0.0, o, 0.0)
    assert (cmd.vx, cmd.yaw_rate, cmd.state, cmd.reason) == (0.0, 0.0, FollowState.LOST, reason)


def test_losing_target_while_moving_stops_immediately():
    c = ctrl()
    t = 0.0
    for _ in range(100):
        cmd = c.step(t, obs(t, yaw=0.1, dist=2.5), 0.0)
        t += DT
    assert cmd.vx > 0.05
    cmd = c.step(t, None, 0.0)
    assert cmd.vx == 0.0 and cmd.yaw_rate == 0.0
    # 觀測回來之後要重新受加速度限制，不能直接跳回原速度
    cmd = c.step(t + DT, obs(t + DT, dist=2.5), 0.0)
    assert 0.0 < cmd.vx <= FollowConfig().max_accel_vx * DT + 1e-12


def test_distance_unknown_never_advances_but_still_turns():
    c = ctrl()
    t = 0.0
    for _ in range(200):
        cmd = c.step(t, obs(t, yaw=0.3, dist=None), head_yaw=0.3)
        assert cmd.vx == 0.0
        t += DT
    assert cmd.reason == "distance_unknown" and cmd.yaw_rate > 0 and cmd.state is FollowState.TURNING


def test_untrusted_far_distance_is_treated_as_unknown():
    c = ctrl()
    cmd = None
    for i in range(50):
        cmd = c.step(i * DT, obs(i * DT, dist=4.0), 0.0)
    assert cmd.vx == 0.0 and cmd.reason == "distance_unknown"


def test_face_mode_never_advances():
    c = ctrl(mode=FollowMode.FACE)
    for i in range(100):
        cmd = c.step(i * DT, obs(i * DT, yaw=0.0, dist=3.0), 0.0)
        assert cmd.vx == 0.0
    assert cmd.reason == "face_mode" and cmd.state is FollowState.HOLDING


def test_turn_hysteresis_and_sign():
    c = ctrl(mode=FollowMode.FACE)
    assert c.step(0.0, obs(0.0, yaw=0.0), head_yaw=0.2).yaw_rate == 0.0  # 0.2 < turn_start：只動頭
    assert c.step(DT, obs(DT, yaw=0.1), head_yaw=0.3).yaw_rate > 0.0  # 0.4 > turn_start：往左轉
    assert c.step(2 * DT, obs(2 * DT, yaw=0.0), head_yaw=0.2).yaw_rate > 0.0  # 回到 0.2 仍在轉（遲滯）
    assert c.step(3 * DT, obs(3 * DT, yaw=0.0), head_yaw=0.05).yaw_rate == 0.0  # < turn_stop：停
    c2 = ctrl(mode=FollowMode.FACE)
    c2.step(0.0, obs(0.0, yaw=-0.1), head_yaw=-0.4)  # 第一步 dt＝0，受加速度限制還沒有輸出
    assert c2.step(DT, obs(DT, yaw=-0.1), head_yaw=-0.4).yaw_rate < 0.0  # 右邊 → 往右轉


def test_head_target_points_at_person_and_is_clamped():
    c = ctrl(mode=FollowMode.FACE)
    cmd = c.step(0.0, FollowObservation(0.0, 0.1, 0.2, 2.0), head_yaw=0.1, head_pitch=0.3)
    assert cmd.head_yaw_target == pytest.approx(0.2) and cmd.head_pitch_target == pytest.approx(0.5)
    cmd = c.step(DT, FollowObservation(DT, 0.4, 0.5, 2.0), head_yaw=0.4, head_pitch=0.6)
    assert cmd.head_yaw_target == 0.5 and cmd.head_pitch_target == 0.9


def test_limits_and_acceleration():
    cfg = FollowConfig()
    c = ctrl()
    prev_v = prev_w = 0.0
    for i in range(400):
        cmd = c.step(i * DT, obs(i * DT, yaw=0.2, dist=2.9), head_yaw=0.0)
        assert 0.0 <= cmd.vx <= cfg.max_vx + 1e-12 and abs(cmd.yaw_rate) <= cfg.max_yaw_rate + 1e-12
        assert cmd.vx - prev_v <= cfg.max_accel_vx * DT + 1e-9
        assert abs(cmd.yaw_rate) - abs(prev_w) <= cfg.max_accel_yaw * DT + 1e-9
        prev_v, prev_w = cmd.vx, cmd.yaw_rate
    assert cmd.vx == pytest.approx(cfg.max_vx)


def test_not_aligned_does_not_walk():
    c = ctrl()
    for i in range(50):
        cmd = c.step(i * DT, obs(i * DT, yaw=0.0, dist=2.5), head_yaw=0.45)
    assert cmd.vx == 0.0 and cmd.reason == "not_aligned" and cmd.yaw_rate > 0


def test_too_close_does_not_back_up_by_default():
    c = ctrl()
    cmd = c.step(0.0, obs(0.0, dist=0.5), 0.0)
    assert cmd.vx == 0.0 and cmd.reason == "too_close"
    c2 = ctrl(allow_backward=True)
    for i in range(50):
        cmd = c2.step(i * DT, obs(i * DT, dist=0.5), 0.0)
    assert -FollowConfig().max_vx <= cmd.vx < 0.0


def test_distance_hysteresis_no_chatter():
    c = ctrl()
    walking = []
    for i in range(500):
        d = 1.0 + 0.17 + 0.06 * math.sin(i * 0.7)  # 誤差在 0.11～0.23 之間抖動：stop 與 resume 之間
        walking.append(c.step(i * DT, obs(i * DT, dist=d), 0.0).vx > 0)
    assert not any(walking)  # 從停止開始，沒超過 resume 就不會起步


# ---------------------------------------------------------------- 運動學模擬


def test_sim_approach_stops_at_target_distance_without_overshoot():
    w = KinematicWorld(person=(2.5, 0.0))
    log = run(w, ctrl(), 40.0)
    d, b = w.range_bearing()
    assert 1.0 <= d <= 1.0 + FollowConfig().distance_stop_m + 0.03
    assert min(math.hypot(2.5 - x, y) for x, y, _ in w.path) >= 0.97  # 沒有衝過頭
    assert log[-1][1].vx == 0.0 and log[-1][1].state is FollowState.HOLDING and log[-1][1].reason == "at_distance"


def test_sim_person_at_side_head_first_then_body_turns_to_face():
    w = KinematicWorld(person=(1.0 * math.cos(1.0), 1.0 * math.sin(1.0)))  # 左邊 57°，在視角外
    c = ctrl(mode=FollowMode.FACE)
    log = run(w, c, 2.0)
    assert all(cmd.state is FollowState.LOST for _, cmd in log)  # 看不到就不動（轉向聲源由 look_at 負責）
    w.head_yaw = 0.5  # 假設 look_at 已經把頭轉向聲源
    log = run(w, c, 8.0, t0=2.0)
    d, b = w.range_bearing()
    assert abs(b) < FollowConfig().turn_stop + 0.02
    assert abs(w.head_yaw) < 0.12  # 身體轉過去之後頭回到中間
    assert math.hypot(w.x, w.y) < 1e-9  # FACE 模式原地轉，不位移
    assert log[-1][1].yaw_rate == 0.0


def test_sim_person_off_axis_turn_then_walk():
    w = KinematicWorld(person=(1.8, 0.9))  # 左前 27°，在視角內
    run(w, ctrl(), 60.0)
    d, b = w.range_bearing()
    assert d == pytest.approx(1.05, abs=0.1) and abs(b) < 0.12


def test_sim_distance_unavailable_only_turns():
    w = KinematicWorld(person=(2.0, 0.9), distance_available=False)
    run(w, ctrl(), 15.0)
    assert math.hypot(w.x, w.y) < 1e-9 and abs(w.range_bearing()[1]) < 0.12


def test_sim_person_disappears_duck_stops_and_stays():
    w = KinematicWorld(person=(3.0, 0.0))

    def vanish(t, world):
        world.person_visible = t < 5.0

    log = run(w, ctrl(), 10.0, on_step=vanish)
    moving_after = [cmd for t, cmd in log if t > 5.0 + 0.5 + 0.1 and (cmd.vx != 0 or cmd.yaw_rate != 0)]
    assert not moving_after
    x_at_stop = [p for (t, _), p in zip(log, w.path) if t > 5.7][0]
    assert w.path[-1][:2] == pytest.approx(x_at_stop[:2])


def test_sim_follows_slow_person_and_gives_up_on_fast_person():
    cfg = FollowConfig()
    slow = KinematicWorld(person=(1.5, 0.0))
    run(slow, ctrl(), 40.0, on_step=lambda t, w: setattr(w, "person", (1.5 + 0.05 * t, 0.0)))
    assert 1.0 < slow.range_bearing()[0] < 1.5  # 0.05 m/s 跟得上（上限 0.10 m/s）
    fast = KinematicWorld(person=(1.5, 0.0))
    log = run(fast, ctrl(), 20.0, on_step=lambda t, w: setattr(w, "person", (1.5 + 0.5 * t, 0.0)))
    assert log[-1][1].vx == 0.0  # 人走到可信距離外（> 3 m）就停，不盲目追
    assert log[-1][1].reason in ("distance_unknown", "lost", "stale")
    assert all(cmd.vx <= cfg.max_vx + 1e-12 for _, cmd in log)


def test_sim_no_oscillation_with_observation_latency():
    """回歸：觀測有延遲時，要用拍攝當下的頭角換算；否則頭和身體會來回擺盪、永遠走不到。"""
    w = KinematicWorld(person=(1.8, 0.9))
    log = run(w, ctrl(), 30.0, latency_cycles=8)
    signs = [math.copysign(1, cmd.yaw_rate) for _, cmd in log if abs(cmd.yaw_rate) > 0.02]
    flips = sum(1 for a, b in zip(signs, signs[1:]) if a != b)
    assert flips <= 2
    assert w.range_bearing()[0] < 1.15
