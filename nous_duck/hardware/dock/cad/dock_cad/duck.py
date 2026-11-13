"""從上游 MJCF 算出鴨子站姿（home）時的幾何，換到充電座座標。

只唯讀上游檔案：
- `mini_bdx/robots/open_duck_mini_v2/robot.xml` 與同目錄的 STL（運動樹與網格）
- `print/body_back.stl`（背殼列印檔，與 robot.xml 的 body_back 網格座標相同，單位 mm）

站姿用上游 Open_Duck_Playground `playground/open_duck_mini_v2/xmls/scene_flat_terrain.xml`
的 `home` keyframe（步態策略的起始姿態）。頭頸與天線維持 0。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import params as P

#: 上游 Open_Duck_Playground（main，2026-11-13 取得）scene_flat_terrain.xml 的 home keyframe。
HOME_POSE = {
    "left_hip_yaw": 0.002,
    "left_hip_roll": 0.053,
    "left_hip_pitch": -0.63,
    "left_knee": 1.368,
    "left_ankle": -0.784,
    "neck_pitch": 0.0,
    "head_pitch": 0.0,
    "head_yaw": 0.0,
    "head_roll": 0.0,
    "right_hip_yaw": -0.003,
    "right_hip_roll": -0.065,
    "right_hip_pitch": 0.635,
    "right_knee": 1.379,
    "right_ankle": -0.796,
}

ROBOT_DIR = Path("mini_bdx/robots/open_duck_mini_v2")


def default_repo_root() -> Path:
    # .../nous_duck/hardware/dock/cad/dock_cad/duck.py → repo 根目錄往上 5 層
    return Path(__file__).resolve().parents[5]


@dataclass
class DuckPart:
    name: str
    vertices: np.ndarray  # (N, 3) mm，充電座座標
    faces: np.ndarray  # (M, 3)


@dataclass
class DuckGeometry:
    parts: list[DuckPart]
    #: print frame → 充電座座標的平移（站姿下軀幹沒有旋轉）。
    print_to_dock_offset: np.ndarray
    #: 地板在 MuJoCo 世界座標的高度（mm）。
    floor_world_z: float
    notes: list[str] = field(default_factory=list)

    def print_to_dock(self, pts: np.ndarray) -> np.ndarray:
        return np.asarray(pts, dtype=float) + self.print_to_dock_offset

    def dock_to_print(self, pts: np.ndarray) -> np.ndarray:
        return np.asarray(pts, dtype=float) - self.print_to_dock_offset

    def all_vertices(self, exclude: tuple[str, ...] = ()) -> np.ndarray:
        return np.vstack([p.vertices for p in self.parts if p.name not in exclude])


def _body_back_geom_pos_mm(robot_xml: Path) -> np.ndarray:
    root = ET.parse(robot_xml).getroot()
    for geom in root.iter("geom"):
        if geom.get("mesh") == "body_back":
            return np.array([float(v) for v in geom.get("pos", "0 0 0").split()]) * 1000.0
    raise ValueError("robot.xml 找不到 body_back 網格")


@lru_cache(maxsize=2)
def load_duck(repo_root: Path | None = None) -> DuckGeometry:
    import mujoco  # 只有需要鴨子幾何時才載入

    repo_root = Path(repo_root or default_repo_root())
    robot_xml = repo_root / ROBOT_DIR / "robot.xml"
    m = mujoco.MjModel.from_xml_path(str(robot_xml))
    d = mujoco.MjData(m)
    for name, value in HOME_POSE.items():
        d.qpos[m.jnt_qposadr[m.joint(name).id]] = value
    mujoco.mj_kinematics(m, d)

    raw: list[tuple[str, np.ndarray, np.ndarray]] = []
    for gi in range(m.ngeom):
        if m.geom_type[gi] != mujoco.mjtGeom.mjGEOM_MESH:
            continue
        mid = m.geom_dataid[gi]
        vadr, vnum = m.mesh_vertadr[mid], m.mesh_vertnum[mid]
        fadr, fnum = m.mesh_faceadr[mid], m.mesh_facenum[mid]
        verts = m.mesh_vert[vadr : vadr + vnum] @ d.geom_xmat[gi].reshape(3, 3).T + d.geom_xpos[gi]
        raw.append((m.mesh(mid).name, verts * 1000.0, m.mesh_face[fadr : fadr + fnum].copy()))

    floor = min(v[:, 2].min() for _, v, _ in raw)

    trunk = m.body("trunk_assembly").id
    rot = d.xmat[trunk].reshape(3, 3)
    if not np.allclose(rot, np.eye(3), atol=1e-9):
        raise ValueError("站姿下軀幹應該沒有旋轉；上游模型可能改了，請重新檢查座標換算")
    geom_pos = _body_back_geom_pos_mm(robot_xml)
    trunk_pos = d.xpos[trunk] * 1000.0
    # print frame (mm) → 世界 (mm)：p + geom_pos + trunk_pos
    boss_face_world_x = P.BOSS_FACE_X + geom_pos[0] + trunk_pos[0]
    offset = geom_pos + trunk_pos - np.array([boss_face_world_x, 0.0, floor])

    world_to_dock = np.array([boss_face_world_x, 0.0, floor])
    parts = [DuckPart(n, v - world_to_dock, f) for n, v, f in raw]
    return DuckGeometry(parts=parts, print_to_dock_offset=offset, floor_world_z=float(floor))

