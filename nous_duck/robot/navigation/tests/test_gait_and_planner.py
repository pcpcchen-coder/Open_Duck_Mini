"""步態反應表與規劃（C5 的規劃部分）。驗證層級：單元測試。"""

import math

import numpy as np
import pytest

from duck_nav.gait import GaitModel, ramp
from duck_nav.geometry import rect_distance
from duck_nav.planner import CostMap, PlanError, astar, plan_path, topo_route


def test_gait_table_is_flagged_simulated():
    g = GaitModel.load()
    assert g.simulated is True
    vx, vy, w = g.response(0.15, 0.0)
    assert 0.09 < vx < 0.13 and abs(w) < 0.05
    assert g.response(0.0, 0.0) == (0.0, 0.0, 0.0)
    assert g.response(-0.15, 0.0)[0] < -0.03
    assert 0.7 < g.response(0.0, 1.0)[2] < 1.0


def test_nav_only_uses_commands_that_start():
    g = GaitModel.load()
    assert g.will_start(g.FWD_CMD, 0.0) and g.will_start(g.BACK_CMD, 0.0)
    assert g.will_start(0.0, g.TURN_CMD) and g.will_start(0.0, -g.TURN_CMD)
    assert g.will_start(0.0, g.TURN_CMD_FINE) and g.will_start(0.0, -g.TURN_CMD_FINE)
    assert not g.will_start(0.0, -0.3)  # 模擬量到：原地 −0.3 rad/s 不會起步
    assert not g.will_start(0.0, 0.0)


def test_ramp_is_adr0009_limit():
    assert ramp((0, 0, 0), (0.15, 0, -1.0)) == pytest.approx((0.01, 0.0, -0.05))
    assert ramp((0.15, 0, 0), (0.0, 0, 0)) == pytest.approx((0.14, 0.0, 0.0))


def test_topo_route(home):
    r = topo_route(home, "living_room", "brother_room")
    assert [d.id for d in r] == ["door_living_hall", "door_hall_brother"]
    assert topo_route(home, "living_room", "living_room") == []
    assert topo_route(home, "living_room", "brother_room", {"door_hall_brother"}) is None


def _clearances(home, pts):
    occ_min, zone_min = math.inf, math.inf
    g = home.grid
    rows, cols = np.nonzero(g.occ)
    centers = np.array([g.center(r, c) for r, c in zip(rows, cols)])
    for a, b in zip(pts, pts[1:]):
        n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 0.02))
        for i in range(n + 1):
            x, y = a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n
            occ_min = min(occ_min, float(np.hypot(centers[:, 0] - x, centers[:, 1] - y).min()))
            for z in home.zones.values():
                zone_min = min(zone_min, rect_distance(x, y, z.rect))
    return occ_min, zone_min


@pytest.mark.parametrize("goal", ["brother_room", "brother_bedside", "study_room", "hallway", "living_room"])
def test_paths_keep_clearance(home, goal):
    cm = CostMap(home)
    start = (0.9, 1.5)
    p = home.places[goal]
    plan = plan_path(cm, start, (p.x, p.y))
    assert plan.points[0] == start
    assert math.hypot(plan.points[-1][0] - p.x, plan.points[-1][1] - p.y) < 0.08
    occ_min, zone_min = _clearances(home, plan.points)
    assert occ_min >= cm.cfg.robot_radius_m - 0.04  # 一格（5 cm）以內的離散誤差
    assert zone_min >= cm.cfg.zone_margin_m - 0.05


def test_study_route_stays_away_from_stairs(home):
    """去書房的門離樓梯禁區最近（門中心到禁區 0.8 m）：路徑要留在保留邊界外。"""
    cm = CostMap(home)
    p = home.places["study_room"]
    plan = plan_path(cm, (3.2, 3.5), (p.x, p.y))
    _, zone_min = _clearances(home, plan.points)
    assert zone_min > 0.40


def test_goal_in_forbidden_margin_is_refused(home):
    cm = CostMap(home)
    with pytest.raises(PlanError) as e:
        plan_path(cm, (3.2, 3.5), (6.0, 3.5))  # 離樓梯禁區 0.2 m
    assert e.value.reason == "forbidden"


def test_closed_door_reason(home):
    cm = CostMap(home)
    p = home.places["brother_room"]
    with pytest.raises(PlanError) as e:
        plan_path(cm, (0.9, 1.5), (p.x, p.y), {"door_hall_brother"})
    assert e.value.reason == "door_closed"


def test_dynamic_obstacle_forces_detour_and_expires(home):
    cm = CostMap(home)
    a, b = (0.9, 1.5), (1.6, 2.6)
    direct = astar(cm, a, b)
    for y in np.arange(1.7, 2.3, 0.05):
        for x in np.arange(0.9, 1.7, 0.05):
            cm.add_obstacle(float(x), float(y), now=0.0)
    detour = astar(cm, a, b)
    length = lambda pts: sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(pts, pts[1:]))  # noqa: E731
    assert detour is not None and length(detour) > length(direct) + 0.2
    cm.expire(now=100.0)
    assert length(astar(cm, a, b)) == pytest.approx(length(direct))
    # 地圖上已經有的牆不會被重複當成動態障礙。
    assert cm.add_obstacle(3.0, 3.0, now=0.0) is False
