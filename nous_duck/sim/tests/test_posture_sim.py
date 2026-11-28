"""原地蹲低／起立（posture_sim）的測試。驗證層級：模擬（MuJoCo），不是實機。"""

import math

import pytest

from posture_sim.poses import CROUCH, CROUCH_HEAD_DOWN, CROUCH_HEAD_PITCH, JOINTS, SIT3, STAND
from posture_sim.sim import PostureSim, Segment, crouch_cycle, head_level_offset, partial
from walk_sim.model import ModelOptions, build_model

#: 舵機控制台的關節上限（上游 URDF 限位往內縮 2°），實機上目標超過會被夾住。
CONSOLE_MARGIN = math.radians(2.0)


def test_crouch_within_console_limits():
    m = build_model()
    for pose in (STAND, CROUCH):
        assert set(pose) == set(JOINTS)
        for n in JOINTS:
            lo, hi = m.jnt_range[m.joint(n).id]
            assert lo + CONSOLE_MARGIN <= pose[n] <= hi - CONSOLE_MARGIN, n
    # 左右對稱：右腿 hip_pitch 取負，膝、踝同號。
    assert CROUCH["right_hip_pitch"] == -CROUCH["left_hip_pitch"]
    assert CROUCH["right_knee"] == CROUCH["left_knee"]
    assert CROUCH["right_ankle"] == CROUCH["left_ankle"]


def test_crouch_round_trip_stays_on_feet():
    r = PostureSim().run(crouch_cycle())
    assert not r.fell
    assert 3.0 <= r.base_drop_cm <= 4.0  # 身體下降約 3.4 cm
    down, hold, up, settle = r.segments
    assert 25 <= hold.trunk_pitch_deg <= 31  # 前傾約 28°
    assert abs(settle.trunk_pitch_deg) < 2  # 站回來
    assert abs(settle.base_z - r.stand_base_z) < 0.005
    assert r.min_support_margin_cm > 2.5  # 全程重心都在鞋底內，至少 2.5 cm
    assert r.foot_slip_cm < 1.0  # 原地
    assert r.max_torque_nm < 1.0  # 模擬舵機上限 3.23 N·m


@pytest.mark.parametrize("fraction", [0.25, 0.5, 0.75, 1.0])
def test_freeze_anywhere_is_stable(fraction):
    """收手方案「停在目前目標」：蹲到任何位置停住都不會倒，之後能站回來。"""
    segs = [
        Segment(partial(fraction), 3.0 * fraction, "down"),
        Segment(None, 10.0, "hold"),
        Segment(STAND, 3.0, "up"),
        Segment(None, 2.0, "settle"),
    ]
    r = PostureSim().run(segs)
    assert not r.fell
    assert r.min_support_margin_cm > 2.5
    assert abs(r.segments[-1].trunk_pitch_deg) < 2


def test_limp_is_not_a_safe_abort():
    """放鬆（kp 0.5）會往前倒：收手不能只靠放鬆。"""
    r = PostureSim().run(crouch_cycle(), limp_at=1.5)
    assert r.fell
    assert r.min_support_margin_cm < 0


def test_stall_pause_avoids_torque_spike():
    """控制迴圈卡 1 秒：目標直接跳會打到力矩上限；時間軸暫停就不會。"""
    jump = PostureSim().run(crouch_cycle(), stall=(1.5, 1.0))
    pause = PostureSim().run(crouch_cycle(), stall=(1.5, 1.0), stall_mode="pause")
    assert not jump.fell and not pause.fell
    assert jump.max_torque_nm > 3.0
    assert pause.max_torque_nm < 1.0


@pytest.mark.parametrize(
    "opts",
    [
        ModelOptions(kp=13.37 * 0.7),
        ModelOptions(kp=13.37 * 0.7, force_limit=2.0),
        ModelOptions(floor_friction=0.4),
        ModelOptions(solver="playground"),
    ],
    ids=["kp70", "kp70_f2", "mu04", "playground"],
)
def test_crouch_robust_to_parameters(opts):
    r = PostureSim(opts).run(crouch_cycle(duration=1.5))
    assert not r.fell
    assert r.min_support_margin_cm > 2.5
    assert abs(r.segments[-1].trunk_pitch_deg) < 4


def test_head_pitch_keeps_head_level():
    offset = head_level_offset()
    assert abs(offset - CROUCH_HEAD_PITCH) < 0.03
    assert CROUCH_HEAD_DOWN["head_pitch"] == STAND["head_pitch"]


def test_sit3_direct_tips_forward():
    """對照：使用者的「坐下3」從站姿直接過去，模擬裡會往前撲（所以不拿來當動作）。"""
    r = PostureSim().run([Segment(SIT3, 3.0, "down"), Segment(None, 3.0, "hold")])
    assert r.fell
    assert r.segments[-1].trunk_pitch_deg > 60


# --------------------------------------------------------------------------- duckd 的姿勢引擎
import json  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

from posture_sim.poses import DUCKD_POSTURES, duckd_postures  # noqa: E402
from posture_sim.sim import run_controller  # noqa: E402

DUCKD_DIR = Path(__file__).resolve().parents[2] / "robot" / "duckd"


def test_duckd_postures_file_matches_sim_poses():
    """duckd 讀的姿勢檔要和這裡的數字一致（改了 poses.py 要跑 `python -m posture_sim.poses`）。"""
    assert json.loads(DUCKD_POSTURES.read_text(encoding="utf-8")) == duckd_postures()


def _duckd_motion():
    if str(DUCKD_DIR) not in sys.path:
        sys.path.insert(0, str(DUCKD_DIR))
    from duckd.posture import PostureMotion  # 純 Python，不需要 servo_console

    return PostureMotion()


def _driver(motion, plan):
    """plan：[(時間, 'crouch'|'stand'|'stop')]。回傳給 run_controller 的函式。"""
    pending = list(plan)
    legs_names = list(motion.stand)

    def ctl(dt, actual, t):
        legs_actual = {n: actual[n] for n in legs_names}
        if motion.state == "unknown":
            motion.attach(legs_actual)
        while pending and t >= pending[0][0]:
            _, what = pending.pop(0)
            if what == "stop":
                motion.hold()
            else:
                assert motion.start(what, legs_actual) is None, what
        legs = motion.step(dt, legs_actual, t)
        return None if legs is None else {**STAND, **legs}

    return ctl


def test_duckd_motion_in_mujoco_round_trip():
    m = _duckd_motion()
    r = run_controller(PostureSim(), _driver(m, [(0.5, "crouch"), (5.0, "stand")]), 9.0)
    assert not r["fell"]
    assert m.state == "standing"
    assert 3.0 <= r["base_drop_cm"] <= 4.0
    assert r["min_support_margin_cm"] > 2.5
    assert r["foot_slip_cm"] < 1.0
    assert r["max_torque_nm"] < 1.0
    assert m.last_fault is None  # 模擬裡跟隨誤差沒有超過 20°


def test_duckd_motion_overrun_and_abort_in_mujoco():
    """控制迴圈卡 1 秒、再中途收手、慢慢站回來：都不倒、力矩不爆。"""
    m = _duckd_motion()
    plan = [(0.5, "crouch"), (2.0, "stop"), (4.0, "stand")]
    r = run_controller(PostureSim(), _driver(m, plan), 12.0, overrun_at=1.2, overrun_s=1.0)
    assert not r["fell"]
    assert m.state == "standing"
    assert r["max_torque_nm"] < 1.0
    assert r["min_support_margin_cm"] > 2.5
