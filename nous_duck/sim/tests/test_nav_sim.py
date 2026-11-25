"""導航核心接上 MuJoCo 全身走路模擬的測試（C3～C7 的物理層級）。驗證層級：模擬。

導航邏輯本身的單元測試（運動學 mock）在 `nous_duck/robot/navigation/tests`。
"""

import json
import math
from pathlib import Path

import pytest

pytest.importorskip("onnxruntime")

from nav_sim.demo import run_trip, summarize
from nav_sim.loop import make_mujoco_loop, sim_dock_trim, synthetic_home
from nav_sim.scene import MujocoBody
from duck_nav.geometry import Pose2D, rect_distance, to_body, wrap
from duck_nav.navigator import BASE_TO_CONTACT_M
from duck_nav.types import NavOutput

SCHEMA = Path(__file__).resolve().parents[2] / "protocol/schemas/duck-link.v0.schema.json"
DOOR_BROTHER = ("door_leaf_brother", (1.2, 3.97, 2.0, 4.03), 1.0)


@pytest.fixture(scope="module")
def validate():
    jsonschema = pytest.importorskip("jsonschema")
    v = jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))

    def check(msg):
        errs = list(v.iter_errors(msg))
        assert not errs, [e.message for e in errs]

    return check


def test_scene_has_walls_from_the_map():
    home = synthetic_home()
    body = MujocoBody(home, seed=0)
    names = {body.sim.m.geom(i).name for i in range(body.sim.m.ngeom)}
    assert {f"map_{s.id}" for s in home.structures} <= names
    assert "dock_stop" in names and "zone_stairs_hall_east" in names
    assert {f"tag_{t}" for t in home.tags} <= names
    # 從充電座上開始：機身原點在觸點面前方 0.162 m。
    p = home.dock_base_pose(BASE_TO_CONTACT_M)
    assert math.hypot(body.true_pose.x - p.x, body.true_pose.y - p.y) < 0.03


def test_walls_stop_the_duck():
    """牆是實體：朝牆一直走，機身不會穿過去，也不會因此跌倒。"""
    home = synthetic_home()
    body = MujocoBody(home, start=Pose2D(3.4, 1.0, 0.0), seed=0)  # 面向東牆（x = 3.95），距離 0.55 m
    for _ in range(50 * 12):
        body.apply(NavOutput(vx=0.15))
    assert body.true_pose.x < 3.95 - 0.02
    assert not body.fallen


def test_round_trip_dock_to_room_and_back(validate):
    loop = make_mujoco_loop(seed=100)
    ack = loop.nav.go_to("brother_room")
    assert ack["status"] == "accepted"
    loop.run_until_idle(300)
    assert loop.result.events[-1]["event"] == "mission_done", loop.result.events[-1]
    p = loop.nav.map.places["brother_room"]
    assert math.hypot(loop.body.true_pose.x - p.x, loop.body.true_pose.y - p.y) < 0.25
    loop.dock.reset()
    loop.nav.return_home()
    loop.run_until_idle(400)
    names = [e["event"] for e in loop.result.events]
    assert names[-3:] == ["docked", "charging_started", "mission_done"], loop.result.events[-1]
    for e in loop.result.events:
        validate(e)
        assert e["data"]["mock"] is True
    assert loop.result.events[-2]["data"]["signal"] == "mock"
    tp = loop.body.true_pose
    xd, yd = to_body(loop.nav.map.dock.pose, tp.x, tp.y)
    assert xd - BASE_TO_CONTACT_M < 0.012 and abs(yd) < 0.04
    assert abs(wrap(tp.yaw - loop.nav.map.dock.pose.yaw)) < math.radians(6)  # 背對充電座
    assert not loop.body.fallen and loop.body.max_tilt_deg < 15
    assert loop.result.min_zone_dist_m > 0.5
    assert loop.result.max_est_err_m < 0.3


def test_closed_door_in_mujoco(validate):
    loop = make_mujoco_loop(seed=1, extra_boxes=[DOOR_BROTHER])
    loop.nav.go_to("brother_room")
    loop.run_until_idle(300)
    last = loop.result.events[-1]
    assert last["event"] == "mission_failed" and last["reason"] == "door_closed" and last["data"]["door"] == "door_hall_brother"
    validate(last)
    tp = loop.body.true_pose
    assert loop.nav.map.room_at(tp.x, tp.y) == "hallway"
    assert 0.25 < rect_distance(tp.x, tp.y, DOOR_BROTHER[1]) < 0.8  # 停在門前
    assert not loop.body.fallen


def test_blocked_corridor_and_detour_in_mujoco():
    loop = make_mujoco_loop(seed=1, extra_boxes=[("boxes", (3.6, 3.05, 3.9, 3.95), 0.4)])
    loop.nav.go_to("study_room")
    loop.run_until_idle(300)
    assert loop.result.events[-1]["reason"] == "blocked"
    assert not loop.body.fallen
    loop = make_mujoco_loop(seed=1, extra_boxes=[("box", (1.2, 1.9, 1.7, 2.3), 0.3)])
    loop.nav.go_to("hallway")
    loop.run_until_idle(300)
    assert loop.result.events[-1]["event"] == "mission_done"
    assert loop.nav.last_mission.replans >= 1 and not loop.body.fallen


def test_study_room_route_keeps_away_from_stairs():
    loop = make_mujoco_loop(seed=3)
    loop.nav.go_to("study_room")
    loop.run_until_idle(300)
    assert loop.result.events[-1]["event"] == "mission_done"
    assert loop.result.min_zone_dist_m > 0.45


def test_kidnapped_in_mujoco():
    loop = make_mujoco_loop(seed=1)
    loop.nav.go_to("brother_room")
    loop.run_for(15.0)
    loop.body.teleport(Pose2D(5.3, 5.6, -1.2))
    loop.run_until_idle(400)
    assert loop.result.events[-1]["event"] == "mission_done", loop.result.events[-1]
    p = loop.nav.map.places["brother_room"]
    assert math.hypot(loop.body.true_pose.x - p.x, loop.body.true_pose.y - p.y) < 0.3
    assert loop.result.min_zone_dist_m > 0.3 and not loop.body.fallen


def test_dock_trim_file_is_flagged_simulated():
    p = Path(__file__).resolve().parents[2] / "robot/navigation/duck_nav/data/dock_trim.sim.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["simulated"] is True and sim_dock_trim() == d["dock_lateral_trim_m"]


def test_real_detector_reads_dock_tag_from_rendered_camera():
    """MuJoCo 相機算圖＋OpenCV 的 tag36h11 偵測器：在預備點讀得到充電座的標籤 0，位置誤差小。"""
    pytest.importorskip("cv2")
    try:
        from nav_sim import tagcheck

        res = tagcheck.run()
    except Exception as e:  # 無法建立離螢幕 OpenGL 環境的機器
        pytest.skip(f"無法離螢幕算圖：{e}")
    row = next(r for r in res["rows"] if r["pose"] == "dock_staging_0.5m")
    assert row["detector_ids"] == [0] and row["mock_ids"] == [0]
    assert row["detections"][0]["pos_err_m"] < 0.02
    assert res["detections"] >= 10 and res["pos_err_m_max"] < 0.06


@pytest.mark.slow
def test_ten_round_trips():
    trips = [run_trip(300 + i, ["brother_room", "study_room", "brother_bedside", "living_room", "hallway"][i % 5])[0] for i in range(10)]
    s = summarize(trips)
    assert s["falls"] == 0
    assert s["go_to_ok"] == 10
    assert s["round_trip_ok"] >= 8, s["failures"]
    assert s["min_zone_distance_m"] > 0.45
