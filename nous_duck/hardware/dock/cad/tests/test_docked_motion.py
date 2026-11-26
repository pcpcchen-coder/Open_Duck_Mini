"""坐在充電座上時頭頸、天線能動多少（ADR-0018）。幾何與靜力層級，不是實機。"""

from itertools import product

import numpy as np
import pytest

from dock_cad import docked_motion as dm


def test_masses_from_upstream_model():
    mdl = dm._model()
    # 上游 CAD 的質量（不含 Pi 4、鏡頭、麥克風、觸點板）
    assert mdl.total_mass == pytest.approx(2.062, abs=0.005)
    assert mdl.moving_mass == pytest.approx(0.536, abs=0.005)


def test_support_polygon_covers_both_feet():
    poly = dm.support_polygon()
    assert poly[:, 0].min() == pytest.approx(100.5, abs=1.0)
    assert poly[:, 0].max() == pytest.approx(195.9, abs=1.0)
    assert poly[:, 1].min() < -95 and poly[:, 1].max() > 95


def test_home_pose_is_safe():
    c = dm.check_pose({})
    assert not c.collides
    assert c.clearance_mm >= dm.MIN_CLEARANCE_MM
    # 重心在腳跟邊緣前約 34 mm（離充電座那一側最近）
    assert c.com_margin_mm == pytest.approx(33.9, abs=1.0)
    assert c.ok


def test_pin_force_shifts_center_of_pressure():
    # F·h／W：4 × 0.6 N × 202.7 mm ／（2.062 kg × 9.81）
    assert dm.pin_cop_shift_mm() == pytest.approx(4 * 0.6 * 202.7 / (2.062 * 9.81), rel=0.01)


def test_strong_pins_would_push_duck_out():
    # 頂針太硬時，頭往前伸就把壓力中心推出腳尖：選頂針時要看彈力
    c = dm.check_pose({"neck_pitch": -0.34, "head_pitch": -0.78}, pin_force_n=1.5)
    assert c.com_margin_with_pins_mm < 0


def test_neck_leaning_back_hits_backrest():
    # 只有 neck_pitch 往後（正方向）時，約 0.39 rad 起離椅背不到 15 mm，0.5 rad 就碰到
    assert dm.first_unsafe("neck_pitch") == pytest.approx(0.39, abs=0.03)
    assert dm.check_pose({"neck_pitch": 0.5}).collides


def test_runtime_range_is_not_safe_when_docked():
    # 上游走路時的頭頸範圍，坐在充電座上不能全用
    assert not dm.check_pose({"neck_pitch": dm.RUNTIME_RANGE["neck_pitch"][1]}).ok


@pytest.mark.parametrize("corner", list(product(*[dm.DOCKED_HEAD_LIMITS[j] for j in dm.HEAD_JOINTS])))
def test_docked_head_limits_corners_ok(corner):
    assert dm.check_pose(dict(zip(dm.HEAD_JOINTS, corner))).ok


def test_docked_head_limits_grid_ok():
    axes = [np.linspace(*dm.DOCKED_HEAD_LIMITS[j], 3) for j in dm.HEAD_JOINTS]
    bad = [v for v in product(*axes) if not dm.check_pose(dict(zip(dm.HEAD_JOINTS, v))).ok]
    assert bad == []


def test_docked_head_limits_are_within_runtime_range():
    for j, (lo, hi) in dm.DOCKED_HEAD_LIMITS.items():
        rlo, rhi = dm.RUNTIME_RANGE[j]
        assert rlo <= lo < hi <= rhi


def test_neck_limit_is_tight():
    # 再往後 0.06 rad，就有姿勢不通過（範圍不是隨便縮的）
    box = {k: list(v) for k, v in dm.DOCKED_HEAD_LIMITS.items()}
    assert not dm._slice_ok(box, "neck_pitch", box["neck_pitch"][1] + 0.06, 3)


def test_antenna_limits():
    neutral_head = {j: 0.0 for j in dm.HEAD_JOINTS}
    # 往前（遠離椅背）全範圍都可以
    assert dm.check_pose({**neutral_head, "left_antenna": -1.5708, "right_antenna": 1.5708}).ok
    # 往後擺 1 rad 會碰到椅背
    assert dm.check_pose({"left_antenna": 1.0}).collides
    assert dm.check_pose({"right_antenna": -1.0}).collides
    # 頭頸在範圍角落時，天線在 0 仍通過
    for corner in product(*[dm.DOCKED_HEAD_LIMITS[j] for j in dm.HEAD_JOINTS]):
        pose = dict(zip(dm.HEAD_JOINTS, corner))
        for ant, (lo, hi) in dm.DOCKED_ANTENNA_LIMITS.items():
            assert dm.check_pose({**pose, ant: lo}).ok
            assert dm.check_pose({**pose, ant: hi}).ok


def test_head_accel_limit_positive_and_small():
    home = dm.check_pose({})
    a = dm.max_head_accel(home.com_margin_with_pins_mm - dm.MIN_COM_MARGIN_MM)
    assert 1.0 < a < 5.0


def test_pitch_move_times_are_short_enough_for_expressions():
    margin = dm.check_pose({}).com_margin_with_pins_mm - dm.MIN_COM_MARGIN_MM
    # 用 min-jerk、安全係數 2：頸部走完整個可用範圍（0.42 rad）也只要半秒左右，一般表情動作（0.5–1 s）不受限
    t = dm.min_move_time("neck_pitch", 0.42, margin)
    assert 0.3 < t < 0.7
    assert dm.min_move_time("head_pitch", 0.3, margin) < t


def test_max_pin_force_bounds_current_assumption():
    # 每支頂針最多約 0.8 N；目前假設的 0.6 N 在範圍內
    f = dm.max_pin_force_n()
    assert dm.PIN_FORCE_N < f < 1.0
