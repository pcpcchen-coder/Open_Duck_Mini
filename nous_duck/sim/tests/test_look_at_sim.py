"""V3「說話時看著對方」的 MuJoCo 模擬測試。

層級：模擬（上游 robot.xml 固定機身、合成人臉偵測、運動學轉身）。門檻是依 2026-11-16 的模擬結果
留餘裕訂的回歸檢查，不是實機規格；見 docs/validation/look-at-sim-2026-11-16.md。
"""

import math

import pytest

from look_at_sim import SCENARIOS, SimOptions, run_scenario
from look_at_sim.sim import _Duck

SEEDS = (0, 1, 2)


@pytest.fixture(scope="module")
def results():
    return {(n, s): run_scenario(sc, SimOptions(seed=s)) for n, sc in SCENARIOS.items() for s in SEEDS}


def test_camera_height_matches_plan():
    duck = _Duck()
    h = duck.camera()[0][2] - duck.floor
    assert 0.34 <= h <= 0.40  # 雙目視覺規劃 §1 假設 0.37 m


def test_joint_signs_positive_pitch_looks_up_positive_yaw_looks_left():
    """控制器的正負號約定要和上游模型一致。"""
    import mujoco

    duck = _Duck()
    m, d = duck.m, duck.d
    base = duck.camera()[1][:, 0].copy()
    for name, axis, sign in (("neck_pitch", 2, 1), ("head_pitch", 2, 1), ("head_yaw", 1, 1)):
        d.qpos[m.jnt_qposadr[m.joint(name).id]] = 0.2
        mujoco.mj_kinematics(m, d)
        fwd = duck.camera()[1][:, 0]
        assert (fwd[axis] - base[axis]) * sign > 0.1, name
        d.qpos[m.jnt_qposadr[m.joint(name).id]] = 0.0
        mujoco.mj_kinematics(m, d)


def test_all_commands_within_limits_and_speed(results):
    for (name, seed), r in results.items():
        assert r.limits_ok, name
        assert r.head_qvel_max < 3.0, (name, r.head_qvel_max)


@pytest.mark.parametrize("name", ["adult_1p5m", "child_1m"])
def test_standing_person_acquired_and_centered(results, name):
    for s in SEEDS:
        r = results[(name, s)]
        T = SCENARIOS[name].duration
        assert r.settle_time() is not None and r.settle_time() < 2.5
        med, mx = r.error_stats(T - 2, T)
        assert med < 2.0 and mx < 3.0
        assert r.body_yaw_final == pytest.approx(0.0, abs=1e-6)


def test_too_close_keeps_face_in_view_and_flags_saturation(results):
    for s in SEEDS:
        r = results[("adult_too_close_0p7m", s)]
        assert r.pitch_saturated_any
        assert r.in_view_ratio(4, 6) == 1.0
        assert r.error_stats(4, 6)[1] < 6.0


def test_walking_person_tracked_with_body_turn(results):
    for s in SEEDS:
        r = results[("walk_across_2m", s)]
        assert r.error_stats(4, 9)[1] < 8.0
        assert r.in_view_ratio(4, 11) == 1.0
        assert math.degrees(r.body_yaw_final) < -15  # 人走到右邊，身體跟著往右轉


def test_called_from_side_turns_and_finds(results):
    for s in SEEDS:
        r = results[("called_from_side", s)]
        assert r.settle_time() is not None and r.settle_time() < 5.0
        assert 75 < math.degrees(r.body_yaw_final) < 100
        assert abs(r.head_cmd[-1][2]) < 0.35  # 身體轉過去後，頭回到中間附近
        assert r.states[-1] == "tracking"


def test_switches_to_new_speaker(results):
    for s in SEEDS:
        r = results[("two_people_switch", s)]
        t_settle = r.settle_time(t_from=5.0)
        assert t_settle is not None and t_settle < 3.0
        assert 1 <= r.switch_count <= 2  # A 開口前可能先看到 B，所以最多 2 次
        assert r.error_stats(10, 12)[0] < 4.0


def test_person_leaves_then_rest(results):
    for s in SEEDS:
        r = results[("leaves_view", s)]
        assert r.states[-1] == "idle"
        neck, head, yaw, _ = r.head_cmd[-1]
        assert abs(yaw) < 0.02
        assert neck + head == pytest.approx(0.4, abs=0.02)  # rest_pitch
