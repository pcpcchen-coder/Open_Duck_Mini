"""C7：安全規則。每條規則一個以上的測試。驗證層級：單元測試（運動學 mock 身體＋mock 感測器）。

MuJoCo 物理層級的同類測試在 `nous_duck/sim/tests/test_nav_sim.py`。
"""

import math

import pytest

from duck_nav.geometry import Pose2D, rect_distance
from duck_nav.mock_sensors import MockCameraConfig
from duck_nav.navigator import NavConfig
from duck_nav.testing import make_kinematic_loop
from duck_nav.types import NavOutput

DOOR_BROTHER = ("door_leaf_brother", (1.2, 3.97, 2.0, 4.03), 1.0)  # 關著的門板，剛好填滿門口
DOOR_STUDY = ("door_leaf_study", (5.0, 3.97, 5.8, 4.03), 1.0)


def _run(loop, place, max_s=500.0):
    ack = loop.nav.go_to(place) if place != "home" else loop.nav.return_home()
    assert ack["status"] == "accepted", ack
    n0 = len(loop.result.events)
    loop.run_until_idle(max_s)
    return loop.result.events[n0:]


# ---------------------------------------------------------------- 禁區與樓梯
@pytest.mark.parametrize("seed", range(6))
def test_never_enters_forbidden_zone_on_normal_missions(home, seed):
    """去離樓梯最近的書房再回來：真實位置離任何禁區都有距離。"""
    loop = make_kinematic_loop(home, seed=seed)
    ev = _run(loop, "study_room")
    assert ev[-1]["event"] == "mission_done", ev[-1]
    _run(loop, "hallway")
    assert loop.result.min_zone_dist_m > 0.35
    assert loop.body.collisions == 0


def test_goal_inside_zone_margin_fails_forbidden_without_moving(home, validate_event):
    import copy

    m = copy.deepcopy(home)
    from duck_nav.mapfile import Place

    m.places["near_stairs"] = Place("near_stairs", "hallway", 5.95, 3.5)  # 離樓梯禁區 0.25 m
    loop = make_kinematic_loop(m, seed=0, docked=False, start=Pose2D(3.2, 3.5, 0.0))
    loop.nav.loc.set_pose(Pose2D(3.2, 3.5, 0.0))
    start = loop.body.true_pose
    ev = _run(loop, "near_stairs")
    assert ev[-1]["event"] == "mission_failed" and ev[-1]["reason"] == "forbidden"
    validate_event(ev[-1])
    assert math.hypot(loop.body.true_pose.x - start.x, loop.body.true_pose.y - start.y) < 0.02


def test_guard_stops_when_estimate_is_near_zone(home):
    """定位說「已經在樓梯邊界內」就立刻停下並失敗，不管任務要去哪裡。"""
    start = Pose2D(5.9, 3.5, math.pi)  # 離樓梯禁區 0.3 m，背對樓梯
    loop = make_kinematic_loop(home, seed=0, docked=False, start=start)
    loop.nav.loc.set_pose(Pose2D(6.05, 3.5, math.pi), 0.05, 0.05)  # 估計位置更靠近樓梯
    ev = _run(loop, "hallway")
    assert ev[-1]["event"] == "mission_failed" and ev[-1]["reason"] == "forbidden"
    assert ev[-1]["data"]["zone"] == "stairs_hall_east" and ev[-1]["data"]["zone_kind"] == "stairs"
    assert loop.step().velocity == (0.0, 0.0, 0.0)
    assert math.hypot(loop.body.true_pose.x - start.x, loop.body.true_pose.y - start.y) < 0.02


def test_guard_margin_grows_with_uncertainty(home):
    """同一個估計位置，不確定度大就提早判定太靠近禁區。"""
    def run(sigma):
        loop = make_kinematic_loop(home, seed=0, docked=False, start=Pose2D(5.85, 3.5, math.pi))
        loop.camera.cfg = MockCameraConfig(max_range_m=0.0)  # 看不到標籤，不確定度不會被修正
        loop.nav.loc.set_pose(Pose2D(5.85, 3.5, math.pi), sigma, 0.05)
        return _run(loop, "hallway", 30.0)[-1]

    assert run(0.25)["reason"] == "forbidden"  # 0.35 m − (0.20 + 0.25) < 0
    ok = run(0.02)
    assert not (ok["event"] == "mission_failed" and ok["reason"] == "forbidden")


@pytest.mark.parametrize("seed", range(4))
def test_drift_without_tags_stops_before_any_zone(home, seed):
    """定位漂移：把標籤全部關掉，往離樓梯最近的書房走。要在不確定度過大時停下、回報 lost，而且沒有靠近禁區。"""
    loop = make_kinematic_loop(home, seed=seed, docked=False, start=Pose2D(3.2, 3.5, 0.0))
    loop.nav.loc.set_pose(Pose2D(3.2, 3.5, 0.0), 0.03, 0.03)
    loop.camera.cfg = MockCameraConfig(max_range_m=0.0)
    ev = _run(loop, "study_room", 300.0)
    assert ev[-1]["event"] == "mission_failed" and ev[-1]["reason"] == "lost", ev[-1]
    assert loop.result.min_zone_dist_m > 0.30
    assert loop.body.collisions == 0
    assert loop.step().velocity == (0.0, 0.0, 0.0)


# ---------------------------------------------------------------- 定位不確定度
def test_stops_moving_while_not_localized(home):
    """未定位期間只會原地轉身找標籤，不會前進或後退。"""
    loop = make_kinematic_loop(home, seed=1, docked=False, start=Pose2D(2.0, 1.4, 2.0))
    loop.camera.cfg = MockCameraConfig(max_range_m=0.0)
    loop.nav.go_to("hallway")
    start = loop.body.true_pose
    for _ in range(50 * 20):
        out = loop.step()
        if loop.nav.mission is None:
            break
        assert not loop.nav.loc.localized
        assert out.vx == 0.0 and out.vy == 0.0
    assert math.hypot(loop.body.true_pose.x - start.x, loop.body.true_pose.y - start.y) < 0.25  # 只有原地轉的位移


def test_never_localized_reports_lost(home, validate_event):
    loop = make_kinematic_loop(home, seed=1, docked=False, start=Pose2D(2.0, 1.4, 2.0))
    loop.camera.cfg = MockCameraConfig(max_range_m=0.0)
    ev = _run(loop, "hallway", 120.0)
    assert ev[-1]["event"] == "mission_failed" and ev[-1]["reason"] == "lost"
    validate_event(ev[-1])
    assert loop.nav.where()["localized"] is False and loop.nav.where()["place"] is None


def test_unlocalized_start_scans_then_goes(home):
    """開機不知道自己在哪：轉頭、轉身找到標籤後才出發。"""
    loop = make_kinematic_loop(home, seed=2, docked=False, start=Pose2D(2.0, 1.4, 2.5))
    assert loop.nav.where()["localized"] is False
    ev = _run(loop, "hallway")
    assert ev[-1]["event"] == "mission_done", ev[-1]
    assert loop.body.collisions == 0


def test_kidnapped_mid_mission_relocalizes(home):
    """走到一半被抱到別的房間放下：身體端回報「被抱起來」，導航丟掉定位、原地找標籤、重新規劃後走到目的地。"""
    outcomes = []
    for seed in range(4):
        loop = make_kinematic_loop(home, seed=seed)
        loop.nav.go_to("brother_room")
        loop.run_for(15.0)
        loop.body.teleport(Pose2D(5.3, 5.6, -1.2))  # 搬到書房
        moved_blind = 0.0
        while loop.nav.mission is not None and loop.body.t < 400:
            before = loop.body.true_pose
            loop.step()
            if not loop.nav.loc.localized:
                moved_blind += math.hypot(loop.body.true_pose.x - before.x, loop.body.true_pose.y - before.y)
        last = loop.result.events[-1]
        outcomes.append(last["event"] if last["event"] == "mission_done" else last["reason"])
        assert moved_blind < 0.3  # 未定位時只有原地轉的位移
        assert loop.result.min_zone_dist_m > 0.30
        assert loop.body.collisions == 0
        if last["event"] == "mission_done":
            p = home.places["brother_room"]
            assert math.hypot(loop.body.true_pose.x - p.x, loop.body.true_pose.y - p.y) < 0.3
    assert outcomes.count("mission_done") >= 3, outcomes


def test_kidnapped_without_lift_signal_never_enters_a_zone(home):
    """身體端沒有回報被抱起來（最壞情況）：只能等標籤觀測跟估計對不上才發現。

    這段時間鴨子會照舊的估計走（已知限制，記在驗證紀錄）；仍然不能走進禁區，最後要有明確的結果。
    """
    for seed in range(4):
        loop = make_kinematic_loop(home, seed=seed)
        loop.report_lift = False
        loop.nav.go_to("brother_room")
        loop.run_for(15.0)
        loop.body.teleport(Pose2D(5.3, 5.6, -1.2))
        loop.run_until_idle(400.0)
        last = loop.result.events[-1]
        assert last["event"] in ("mission_done", "mission_failed")
        tp = loop.body.true_pose
        assert home.zone_at(tp.x, tp.y) is None
        assert loop.result.min_zone_dist_m > 0.0


# ---------------------------------------------------------------- 門關著
@pytest.mark.parametrize("seed", range(3))
def test_closed_door_stops_at_door_and_reports(home, validate_event, seed):
    loop = make_kinematic_loop(home, seed=seed, extra_boxes=[DOOR_BROTHER])
    ev = _run(loop, "brother_room")
    assert ev[-1]["event"] == "mission_failed" and ev[-1]["reason"] == "door_closed", ev[-1]
    validate_event(ev[-1])
    tp = loop.body.true_pose
    assert home.room_at(tp.x, tp.y) == "hallway"  # 停在門外
    assert rect_distance(tp.x, tp.y, DOOR_BROTHER[1]) > 0.12  # 沒有頂到門板
    assert loop.body.collisions == 0
    assert "door_hall_brother" in loop.nav.closed_doors
    assert loop.step().velocity == (0.0, 0.0, 0.0)


def test_closed_door_does_not_block_other_destinations(home):
    loop = make_kinematic_loop(home, seed=0, extra_boxes=[DOOR_BROTHER])
    _run(loop, "brother_room")
    ev = _run(loop, "study_room")
    assert ev[-1]["event"] == "mission_done", ev[-1]


# ---------------------------------------------------------------- 被擋住
def test_obstacle_in_room_is_avoided_by_replanning(home):
    box = ("box", (1.2, 1.9, 1.7, 2.3), 0.3)  # 客廳中間、往門口的路上
    loop = make_kinematic_loop(home, seed=0, extra_boxes=[box])
    ev = _run(loop, "hallway")
    assert ev[-1]["event"] == "mission_done", ev[-1]
    assert loop.body.collisions == 0
    assert loop.nav.last_mission.replans >= 1


def test_fully_blocked_corridor_reports_blocked_after_bounded_replans(home, validate_event):
    wall = ("boxes", (3.6, 3.05, 3.9, 3.95), 0.4)  # 把走廊整個堵住（不是門）
    loop = make_kinematic_loop(home, seed=0, extra_boxes=[wall])
    ev = _run(loop, "study_room")
    assert ev[-1]["event"] == "mission_failed" and ev[-1]["reason"] == "blocked", ev[-1]
    validate_event(ev[-1])
    assert loop.nav.last_mission.replans <= loop.nav.cfg.max_replans + 1
    assert loop.body.collisions == 0
    tp = loop.body.true_pose
    assert rect_distance(tp.x, tp.y, wall[1]) > 0.12


def test_gait_that_never_starts_reports_blocked(home):
    """送了移動指令但腳一直沒動（例如被卡住、身體端拒絕）：有限次數後回報，不會一直送。"""
    loop = make_kinematic_loop(home, seed=0)

    def frozen(out: NavOutput) -> None:
        loop.body.t += 0.02

    loop.body.apply = frozen
    ev = _run(loop, "hallway", 60.0)
    assert ev[-1]["event"] == "mission_failed" and ev[-1]["reason"] == "blocked"
    assert ev[-1]["data"]["detail"] == "gait_did_not_start"


# ---------------------------------------------------------------- 跌倒
def test_fall_ends_mission_immediately(home, validate_event):
    loop = make_kinematic_loop(home, seed=0)
    loop.nav.go_to("hallway")
    loop.run_for(8.0)
    loop.body.fallen = True
    out = loop.step()
    assert out.velocity == (0.0, 0.0, 0.0) and out.active is False
    assert out.events[-1]["event"] == "mission_failed" and out.events[-1]["reason"] == "fell"
    validate_event(out.events[-1])


# ---------------------------------------------------------------- 速度指令的範圍
def test_commands_stay_inside_the_reliable_gait_set(home):
    """導航只送步態反應表裡可靠的組合：不側移、前後速度只有 0／+0.15／−0.15、轉向在 ±1.0 內。"""
    loop = make_kinematic_loop(home, seed=0)
    seen = set()
    for place in ("brother_bedside", "home"):
        loop.nav.go_to(place) if place != "home" else loop.nav.return_home()
        while loop.nav.mission is not None and loop.body.t < 400:
            out = loop.step()
            assert out.vy == 0.0
            assert out.vx in (0.0, 0.15, -0.15)
            assert abs(out.yaw_rate) <= 1.0
            if out.vx != 0.0:  # 走路時頭回正
                assert out.head.head_yaw == 0.0
            seen.add(out.vx)
    assert seen == {0.0, 0.15, -0.15}
