import dataclasses

import numpy as np
import pytest

from viewer_pipeline.kinematics import load_robot
from viewer_pipeline.scene import CONFIGURE_MOTORS, ROBOT_DIR
from viewer_pipeline.servos import SERVO_MESHES, assign_servos
from viewer_pipeline.upstream import motor_ids


def test_upstream_id_table(repo_root):
    ids = motor_ids(repo_root / CONFIGURE_MOTORS)
    assert ids == {
        "left_hip_yaw": 20, "left_hip_roll": 21, "left_hip_pitch": 22, "left_knee": 23, "left_ankle": 24,
        "neck_pitch": 30, "head_pitch": 31, "head_yaw": 32, "head_roll": 33,
        "right_hip_yaw": 10, "right_hip_roll": 11, "right_hip_pitch": 12, "right_knee": 13, "right_ankle": 14,
    }


def test_fourteen_servos_match_upstream_ids(scene, repo_root):
    ids = motor_ids(repo_root / CONFIGURE_MOTORS)
    servos = scene["servos"]
    assert len(servos) == 14
    assert {s["joint"]: s["id"] for s in servos} == ids


def test_each_servo_has_five_distinct_meshes(scene, parts_by_id):
    seen = set()
    for s in scene["servos"]:
        meshes = sorted(parts_by_id[p]["mesh"] for p in s["parts"])
        assert meshes == sorted(SERVO_MESHES)
        for p in s["parts"]:
            assert parts_by_id[p]["servo_id"] == s["id"]
            assert p not in seen
            seen.add(p)
    assert len(seen) == 70


def test_horns_sit_on_joint_axes_unambiguously(scene):
    for s in scene["servos"]:
        assert s["horn_to_axis_mm"] < 0.01, s
        assert s["horn_to_joint_mm"] < 5.0, s
        # 分辨度：下一顆最近的舵盤離得很遠，不是勉強選出來的
        assert s["next_nearest_horn_mm"] > 40.0, s


def test_sides_are_geometrically_consistent(scene):
    """檢視器座標 +X 是鴨子的左邊。左腿舵機要在 +X、右腿在 −X。
    頸頭舵機的舵盤在頸部的一側（不在中線上），只要求落在頸部寬度內。"""
    for s in scene["servos"]:
        x = s["horn_center_mm"][0]
        if s["side"] == "left":
            assert x > 10, s
        elif s["side"] == "right":
            assert x < -10, s
        else:
            assert abs(x) < 25, s


def test_hip_servos_mirror(scene):
    by_joint = {s["joint"]: s["horn_center_mm"] for s in scene["servos"]}
    for name in ("hip_yaw", "hip_roll", "hip_pitch"):
        left, right = np.array(by_joint[f"left_{name}"]), np.array(by_joint[f"right_{name}"])
        assert np.allclose(left * [-1, 1, 1], right, atol=0.5), name


def test_knee_and_ankle_servos_are_not_mirrored(scene):
    """上游左右腿用同一套零件；右腿小腿與腳是同一組件轉 180°，不是鏡像。
    所以膝、踝舵機在左腿裝在外側、在右腿裝在內側。高度與前後位置仍相同。"""
    by_joint = {s["joint"]: s["horn_center_mm"] for s in scene["servos"]}
    hip_x = {side: abs(by_joint[f"{side}_hip_pitch"][0]) for side in ("left", "right")}
    for name in ("knee", "ankle"):
        left, right = np.array(by_joint[f"left_{name}"]), np.array(by_joint[f"right_{name}"])
        assert np.allclose(left[1:], right[1:], atol=0.5), name  # 同高度、同前後
        assert abs(left[0]) > hip_x["left"] - 5, name  # 左腿：和髖俯仰舵機同在外側
        assert abs(right[0]) < hip_x["right"] - 20, name  # 右腿：在內側


def test_antenna_joints_have_no_sts3215(scene):
    joints = {j["name"]: j for j in scene["joints"]}
    assert joints["left_antenna"]["servo_id"] is None
    assert joints["right_antenna"]["servo_id"] is None
    assert sum(j["servo_id"] is not None for j in scene["joints"]) == 14


def test_unknown_joint_in_id_table_fails(repo_root):
    robot = load_robot(repo_root / ROBOT_DIR / "robot.xml")
    ids = motor_ids(repo_root / CONFIGURE_MOTORS)
    ids["left_tail"] = ids.pop("left_knee")
    with pytest.raises(ValueError, match="left_tail"):
        assign_servos(robot, ids)


def test_moved_joint_fails(repo_root):
    """把一個關節的轉軸轉 90°，那個關節就找不到舵機，必須失敗而不是硬配。"""
    robot = load_robot(repo_root / ROBOT_DIR / "robot.xml")
    j = robot.joints["left_knee"]
    tilted = np.cross(j.axis, [1.0, 0.0, 0.0])
    if np.linalg.norm(tilted) < 1e-6:
        tilted = np.cross(j.axis, [0.0, 1.0, 0.0])
    robot.joints["left_knee"] = dataclasses.replace(j, axis=tilted / np.linalg.norm(tilted), position=j.position + 0.003 * np.cross(j.axis, tilted))
    with pytest.raises(ValueError, match="left_knee"):
        assign_servos(robot, motor_ids(repo_root / CONFIGURE_MOTORS))
