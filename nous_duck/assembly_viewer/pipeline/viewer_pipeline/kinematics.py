"""解析上游 MuJoCo `robot.xml`：body 樹、關節、每個網格 geom 的世界座標（零位姿態）。

只支援上游實際用到的寫法（`pos`、`quat`、`axis`，角度單位 radian）。遇到其他寫法
（`euler`、`axisangle`、`xyaxes`、`zaxis`、網格 `scale` 等）直接報錯，不默默算錯。
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .geometry import quat_wxyz_to_matrix

_UNSUPPORTED_ORIENTATION = ("euler", "axisangle", "xyaxes", "zaxis")


@dataclass(frozen=True)
class Joint:
    name: str
    body: str
    parent_body: str | None
    position: np.ndarray  # 世界座標（MuJoCo 座標，公尺）
    axis: np.ndarray  # 世界座標單位向量
    range: tuple[float, float] | None  # radian


@dataclass(frozen=True)
class Geom:
    body: str
    index_in_body: int
    mesh: str
    mesh_file: Path
    position: np.ndarray  # 網格原點的世界座標（MuJoCo 座標，公尺）
    rotation: np.ndarray  # 3×3，網格座標 → 世界座標
    rgba: tuple[float, float, float, float] | None


@dataclass
class Body:
    name: str
    parent: str | None
    position: np.ndarray
    rotation: np.ndarray
    joint: str | None = None
    children: list[str] = field(default_factory=list)


@dataclass
class Robot:
    bodies: dict[str, Body]
    joints: dict[str, Joint]
    geoms: list[Geom]
    mesh_files: dict[str, Path]


def _vec(node: ET.Element, attr: str, default: str) -> np.ndarray:
    text = node.get(attr, default)
    values = np.array([float(v) for v in text.split()])
    return values


def _orientation(node: ET.Element) -> np.ndarray:
    for attr in _UNSUPPORTED_ORIENTATION:
        if node.get(attr) is not None:
            raise ValueError(f"<{node.tag} name={node.get('name')!r}> 使用了未支援的 {attr}")
    return quat_wxyz_to_matrix(_vec(node, "quat", "1 0 0 0"))


def load_robot(robot_xml: Path) -> Robot:
    robot_xml = Path(robot_xml)
    root = ET.parse(robot_xml).getroot()

    compiler = root.find("compiler")
    if compiler is not None:
        if compiler.get("angle", "degree") != "radian":
            raise ValueError("只支援 <compiler angle=\"radian\">")
        meshdir = robot_xml.parent / compiler.get("meshdir", "")
    else:
        raise ValueError("缺少 <compiler>，無法確認角度單位")

    mesh_files: dict[str, Path] = {}
    for mesh in root.iterfind("asset/mesh"):
        if mesh.get("scale") is not None or mesh.get("refpos") is not None or mesh.get("refquat") is not None:
            raise ValueError(f"網格 {mesh.get('name')!r} 使用了未支援的 scale/refpos/refquat")
        name = mesh.get("name") or Path(mesh.get("file")).stem
        mesh_files[name] = meshdir / mesh.get("file")

    bodies: dict[str, Body] = {}
    joints: dict[str, Joint] = {}
    geoms: list[Geom] = []

    def walk(node: ET.Element, parent: str | None, p_parent: np.ndarray, r_parent: np.ndarray) -> None:
        name = node.get("name")
        if not name or name in bodies:
            raise ValueError(f"body 名稱缺少或重複：{name!r}")
        p = p_parent + r_parent @ _vec(node, "pos", "0 0 0")
        r = r_parent @ _orientation(node)
        body = Body(name=name, parent=parent, position=p, rotation=r)
        bodies[name] = body
        if parent is not None:
            bodies[parent].children.append(name)

        node_joints = node.findall("joint")
        if len(node_joints) > 1:
            raise ValueError(f"body {name!r} 有多個關節，未支援")
        for j in node_joints:
            if j.get("type", "hinge") != "hinge":
                raise ValueError(f"關節 {j.get('name')!r} 不是 hinge，未支援")
            axis = r @ _vec(j, "axis", "0 0 1")
            axis = axis / np.linalg.norm(axis)
            rng = j.get("range")
            joints[j.get("name")] = Joint(
                name=j.get("name"),
                body=name,
                parent_body=parent,
                position=p + r @ _vec(j, "pos", "0 0 0"),
                axis=axis,
                range=tuple(float(v) for v in rng.split()) if rng else None,
            )
            body.joint = j.get("name")

        index = 0
        for g in node.findall("geom"):
            if g.get("type") != "mesh":
                raise ValueError(f"body {name!r} 有非網格 geom（type={g.get('type')!r}），未支援")
            mesh = g.get("mesh")
            if mesh not in mesh_files:
                raise ValueError(f"geom 引用了不存在的網格 {mesh!r}")
            rgba = g.get("rgba")
            geoms.append(
                Geom(
                    body=name,
                    index_in_body=index,
                    mesh=mesh,
                    mesh_file=mesh_files[mesh],
                    position=p + r @ _vec(g, "pos", "0 0 0"),
                    rotation=r @ _orientation(g),
                    rgba=tuple(float(v) for v in rgba.split()) if rgba else None,
                )
            )
            index += 1

        for child in node.findall("body"):
            walk(child, name, p, r)

    top = root.findall("worldbody/body")
    if len(top) != 1:
        raise ValueError("worldbody 底下應該只有一個根 body")
    walk(top[0], None, np.zeros(3), np.eye(3))
    return Robot(bodies=bodies, joints=joints, geoms=geoms, mesh_files=mesh_files)
