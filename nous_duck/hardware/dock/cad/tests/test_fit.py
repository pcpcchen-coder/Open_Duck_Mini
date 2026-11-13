"""鴨子（上游 CAD、home 站姿）與充電座的干涉與觸點對位（幾何層級，非實機）。"""

import numpy as np
import pytest

from dock_cad import fit
from dock_cad import params as P
from dock_cad.duck import HOME_POSE, load_duck


def test_duck_floor_and_strip_height():
    duck = load_duck()
    feet = [p for p in duck.parts if p.name.startswith("foot_bottom_tpu")]
    assert len(feet) == 2
    assert min(f.vertices[:, 2].min() for f in feet) == pytest.approx(0.0, abs=1e-6)
    # 觸片中心高度（站姿下）約 203 mm；這個數字會寫進 README，改了要同步
    res = fit.load_fit().result
    assert res.contact_z == pytest.approx(202.7, abs=0.1)
    assert set(HOME_POSE) >= {"left_knee", "right_knee"}


def test_no_collision_when_docked():
    assert fit.collisions() == []


def test_clearances_when_docked():
    # 凸台離 V 形牆 ≥ 1 mm（沿法向；沿 X 是 CRADLE_CLEAR）
    assert fit.min_clearance("dock_cradle") >= 0.9
    # 鴨子其他部位離 V 形座 ≥ 10 mm
    assert fit.min_clearance("dock_cradle", exclude_duck=("body_back_dock",)) >= 10.0
    # 扶手離鴨子 ≥ 光靠 V 形座就能修正的側向偏移
    for arm in ("dock_arm_left", "dock_arm_right"):
        assert fit.min_clearance(arm) >= fit.full_capture_half_width()


def test_pins_land_on_strips_with_margin():
    m = fit.contact_margins()
    assert m["+"] >= 3.9 and m["-"] >= 3.9
    # 左右：凸台坐進 V 形槽後只剩 CRADLE_CLEAR 的晃動，頂針仍在觸片上
    assert fit.seated_lateral_play() < fit.y_tolerance()
    for dy in (-fit.seated_lateral_play(), fit.seated_lateral_play()):
        mm = fit.contact_margins(dy=dy)
        assert mm["+"] > 0 and mm["-"] > 0
        assert fit.cross_pole_safe(dy)


def test_height_tolerance():
    tol = fit.z_tolerance()
    assert tol["both_pins"][0] <= -9.0 and tol["both_pins"][1] >= 9.0
    assert tol["one_pin"][0] <= -30.0 and tol["one_pin"][1] >= 30.0
    # 再加上 V 形座 ±15 mm 的安裝調整，可以吸收實機站高與 home 姿態的差異
    assert P.CRADLE_ADJUST >= 15.0
    for pitch in (-3.0, 3.0):
        m = fit.contact_margins(pitch_deg=pitch)
        assert m["+"] > 0 and m["-"] > 0


def test_cross_pole_needs_large_offset():
    """要偏到 10 mm 以上，頂針才可能碰到另一極；V 形槽坐好時只剩 2 mm。"""
    assert fit.cross_pole_safe(0.0)
    assert fit.cross_pole_safe(4.0) and fit.cross_pole_safe(-4.0)
    assert not fit.cross_pole_safe(20.0)  # 反接要靠電路保護（README 電氣章節）


@pytest.mark.parametrize("dy,yaw", [(34.0, 0.0), (-34.0, 0.0), (0.0, 5.0), (0.0, -5.0)])
def test_first_contact_is_boss_on_cradle(dy, yaw):
    """從前方 50 mm 慢慢倒退：第一個碰到的只能是背殼凸台與 V 形座，其他部位都還沒碰到。"""
    dx, hits = fit.first_contact(dy=dy, yaw_deg=yaw, start=50.0, step=4.0)
    assert not np.isnan(dx), "應該要碰到 V 形座"
    assert {(a, b) for a, b, _ in hits} == {("body_back_dock", "dock_cradle")}
