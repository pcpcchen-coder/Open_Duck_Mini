import json

import numpy as np

from test_geometry import quat_xyzw_to_matrix
from viewer_pipeline import SCENE_SCHEMA
from viewer_pipeline.geometry import read_binary_stl
from viewer_pipeline.scene import build


def test_schema_and_frame(scene):
    assert scene["schema"] == SCENE_SCHEMA
    assert scene["units"] == "mm"
    assert scene["frame"]["up"] == "+Y" and scene["frame"]["front"] == "+Z" and scene["frame"]["left"] == "+X"


def test_build_is_deterministic(result, repo_root):
    again = build(repo_root)
    assert again.scene_json() == result.scene_json()
    assert again.mesh_bin == result.mesh_bin


def test_json_round_trips(result):
    assert json.loads(result.scene_json()) == json.loads(json.dumps(result.scene, ensure_ascii=False))


def test_height_matches_author(scene):
    """原作者說腿伸直約 42 cm；CAD 零位不含天線 430.1 mm。"""
    s = scene["summary"]
    assert abs(s["height_without_antennas_mm"] - 430.1) < 0.5
    assert abs(s["height_mm"] - 518.5) < 0.5
    assert s["bbox_min_mm"][1] == 0.0


def test_part_transforms_reproduce_bboxes(scene, repo_root):
    """用輸出的 position 與 quaternion（three.js 順序）重新擺放每個網格，外框中心要等於 center_mm。"""
    for p in scene["parts"]:
        mesh = scene["meshes"][p["mesh"]]
        q = np.array(p["quaternion_xyzw"])
        assert abs(np.linalg.norm(q) - 1) < 1e-7, p["id"]
        local = read_binary_stl(repo_root / mesh["source"]).reshape(-1, 3) * (1000.0 if mesh["source_units"] == "m" else 1.0)
        world = local @ quat_xyzw_to_matrix(q).T + np.array(p["position_mm"])
        center = (world.min(0) + world.max(0)) / 2
        assert np.allclose(center, p["center_mm"], atol=0.01), p["id"]


def test_feet_touch_floor(scene):
    feet = [p for p in scene["parts"] if p["mesh"] in ("foot_bottom_tpu", "foot_bottom_pla")]
    assert len(feet) == 4
    assert min(p["center_mm"][1] for p in feet) < 10


def test_explode_vectors(scene):
    parts = scene["parts"]
    for p in parts:
        assert all(np.isfinite(p["explode_mm"])), p["id"]
    # 同一顆舵機的 5 個網格一起移動
    by_servo = {}
    for p in parts:
        if p["servo_id"] is not None:
            by_servo.setdefault(p["servo_id"], set()).add(tuple(p["explode_mm"]))
    assert all(len(v) == 1 for v in by_servo.values())
    # 腳在腿的最下層，爆炸時要往下（−Y）且往外側移
    for side, sign in (("left", 1), ("right", -1)):
        body = "foot_assembly" if side == "left" else "foot_assembly_2"
        foot = [p for p in parts if p["body"] == body and p["mesh"] == "foot_top"]
        assert len(foot) == 1
        dx, dy, _ = foot[0]["explode_mm"]
        assert dy < 0 and sign * dx >= 0, (side, foot[0]["explode_mm"])
    # 腿上的零件都會移動
    leg_bodies = {"hip_roll_assembly", "left_roll_to_pitch_assembly", "knee_and_ankle_assembly", "knee_and_ankle_assembly_2", "foot_assembly"}
    for p in parts:
        if p["body"] in leg_bodies:
            assert np.linalg.norm(p["explode_mm"]) > 1, p["id"]


def test_ids_unique(scene):
    ids = [p["id"] for p in scene["parts"]]
    assert len(ids) == len(set(ids)) == 138
