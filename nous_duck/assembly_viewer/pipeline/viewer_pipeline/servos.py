"""把 STS3215 的網格組成 14 顆舵機，並對到關節與上游 ID。

上游 CAD 裡每顆 STS3215 由 5 個網格組成（中殼、上殼、下殼、主動舵盤、被動舵盤），
放在同一個 body、共用同一個安裝位置。

對應方法（幾何條件，不靠 body 的上下層關係）：
主動舵盤的中心必須落在關節轉軸上（垂直距離 ≤ AXIS_TOLERANCE_M），而且離關節點夠近
（≤ JOINT_TOLERANCE_M）。左右腿的髖俯仰、膝、踝轉軸剛好共線，只看「在轉軸上」會分不出
左右，所以兩個條件都要。每個關節必須剛好一顆候選、每顆舵機只能用一次，否則失敗。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .geometry import read_binary_stl, transform_points
from .kinematics import Geom, Robot

DRIVE_HORN = "drive_palonier"
PASSIVE_HORN = "passive_palonier"
CASE_MESHES = (
    "wj-wk00-0123middlecase_56",
    "wj-wk00-0124bottomcase_45",
    "wj-wk00-0122topcabinetcase_95",
)
SERVO_MESHES = (DRIVE_HORN, PASSIVE_HORN, *CASE_MESHES)

AXIS_TOLERANCE_M = 0.0001  # 0.1 mm
JOINT_TOLERANCE_M = 0.010  # 10 mm
GROUP_TOLERANCE_M = 0.005  # 同一顆舵機的網格原點彼此相距 ≤ 5 mm


@dataclass(frozen=True)
class ServoUnit:
    servo_id: int
    joint: str
    body: str
    geom_indices: tuple[int, ...]  # robot.geoms 的索引，5 個
    horn_center: np.ndarray  # 主動舵盤中心（MuJoCo 世界座標，公尺）
    axis_distance_m: float  # 舵盤中心到轉軸的垂直距離
    joint_distance_m: float  # 舵盤中心到關節點的距離
    runner_up_distance_m: float  # 下一顆最近的舵機舵盤到這個關節點的距離（分辨度）


def horn_center(geom: Geom) -> np.ndarray:
    verts = read_binary_stl(geom.mesh_file).reshape(-1, 3)
    world = transform_points(verts, geom.rotation, geom.position)
    return (world.min(axis=0) + world.max(axis=0)) / 2


def group_servo_geoms(robot: Robot) -> list[tuple[int, ...]]:
    """回傳每顆舵機的 geom 索引（主動舵盤排第一個），依 robot.geoms 中主動舵盤出現的順序。"""
    drives = [i for i, g in enumerate(robot.geoms) if g.mesh == DRIVE_HORN]
    units: dict[int, list[int]] = {i: [i] for i in drives}
    for i, g in enumerate(robot.geoms):
        if g.mesh not in SERVO_MESHES or g.mesh == DRIVE_HORN:
            continue
        same_body = [d for d in drives if robot.geoms[d].body == g.body]
        if not same_body:
            raise ValueError(f"{g.body} 的 {g.mesh} 找不到同一個 body 裡的主動舵盤")
        nearest = min(same_body, key=lambda d: np.linalg.norm(robot.geoms[d].position - g.position))
        gap = np.linalg.norm(robot.geoms[nearest].position - g.position)
        if gap > GROUP_TOLERANCE_M:
            raise ValueError(f"{g.body} 的 {g.mesh} 離最近的主動舵盤 {gap * 1000:.1f} mm，超過 {GROUP_TOLERANCE_M * 1000} mm")
        units[nearest].append(i)
    for d, members in units.items():
        meshes = sorted(robot.geoms[i].mesh for i in members)
        if meshes != sorted(SERVO_MESHES):
            raise ValueError(f"{robot.geoms[d].body} 的舵機網格組成不對：{meshes}")
    return [tuple(units[d]) for d in drives]


def assign_servos(robot: Robot, ids: dict[str, int]) -> list[ServoUnit]:
    """把舵機對到 `ids`（{關節名: 舵機 ID}）的每個關節。回傳依 ID 排序。"""
    groups = group_servo_geoms(robot)
    if len(groups) != len(ids):
        raise ValueError(f"CAD 有 {len(groups)} 顆 STS3215，上游 ID 表有 {len(ids)} 個")
    centers = [horn_center(robot.geoms[g[0]]) for g in groups]

    used: dict[int, str] = {}
    result: list[ServoUnit] = []
    for joint_name, servo_id in ids.items():
        if joint_name not in robot.joints:
            raise ValueError(f"上游 ID 表的關節 {joint_name!r} 不在 robot.xml")
        joint = robot.joints[joint_name]
        measures = []
        for k, c in enumerate(centers):
            d = c - joint.position
            along = float(np.dot(d, joint.axis))
            perp = float(np.linalg.norm(d - along * joint.axis))
            measures.append((float(np.linalg.norm(d)), perp, k))
        candidates = [m for m in measures if m[1] <= AXIS_TOLERANCE_M and m[0] <= JOINT_TOLERANCE_M]
        if len(candidates) != 1:
            raise ValueError(f"關節 {joint_name} 的舵機候選有 {len(candidates)} 個，應該剛好 1 個")
        dist, perp, k = candidates[0]
        if k in used:
            raise ValueError(f"同一顆舵機同時對到 {used[k]} 與 {joint_name}")
        used[k] = joint_name
        runner_up = min(m[0] for m in measures if m[2] != k)
        result.append(
            ServoUnit(
                servo_id=servo_id,
                joint=joint_name,
                body=robot.geoms[groups[k][0]].body,
                geom_indices=groups[k],
                horn_center=centers[k],
                axis_distance_m=perp,
                joint_distance_m=dist,
                runner_up_distance_m=runner_up,
            )
        )
    return sorted(result, key=lambda s: s.servo_id)
