"""manifold3d 的小工具：方塊、圓柱、多邊形擠出、與 trimesh 互轉。"""

from __future__ import annotations

import numpy as np
import trimesh
from manifold3d import CrossSection, Manifold, Mesh

SEGMENTS = 64


def box(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float) -> Manifold:
    lo = np.array([min(x0, x1), min(y0, y1), min(z0, z1)])
    hi = np.array([max(x0, x1), max(y0, y1), max(z0, z1)])
    return Manifold.cube((hi - lo).tolist()).translate(lo.tolist())


def cyl(axis: str, center: tuple[float, float, float], r: float, a0: float, a1: float, seg: int = SEGMENTS) -> Manifold:
    """沿 axis（'x'、'y'、'z'）從 a0 到 a1 的圓柱，center 給另外兩軸的位置（該軸的值忽略）。"""
    h = a1 - a0
    c = Manifold.cylinder(h, r, r, seg)  # 沿 +Z，底在 0
    cx, cy, cz = center
    if axis == "z":
        return c.translate([cx, cy, a0])
    if axis == "x":
        # Z → X：繞 Y 轉 +90°
        return c.rotate([0, 90, 0]).translate([a0, cy, cz])
    if axis == "y":
        # Z → -Y：繞 X 轉 +90°，所以從 a1 往 a0
        return c.rotate([90, 0, 0]).translate([cx, a1, cz])
    raise ValueError(axis)


def slot(axis: str, p0: tuple[float, float, float], p1: tuple[float, float, float], r: float, a0: float, a1: float) -> Manifold:
    """兩個圓柱的凸包（長槽孔）。"""
    return Manifold.batch_hull([cyl(axis, p0, r, a0, a1), cyl(axis, p1, r, a0, a1)])


def extrude_xy(points_xy: list[tuple[float, float]], z0: float, z1: float, round_r: float = 0.0) -> Manifold:
    """在 XY 平面的多邊形，沿 Z 從 z0 擠出到 z1。點的順序不限（會自動修正方向）。

    round_r > 0 時把凸角修成圓角（先內縮再外擴）。
    """
    from manifold3d import JoinType

    pts = np.asarray(points_xy, dtype=float)
    area = 0.5 * np.sum(pts[:, 0] * np.roll(pts[:, 1], -1) - np.roll(pts[:, 0], -1) * pts[:, 1])
    if area < 0:
        pts = pts[::-1]
    cs = CrossSection([pts.tolist()])
    if round_r > 0:
        cs = cs.offset(-round_r, JoinType.Miter).offset(round_r, JoinType.Round, circular_segments=SEGMENTS)
    return cs.extrude(z1 - z0).translate([0, 0, z0])


def extrude_yz(points_yz: list[tuple[float, float]], x0: float, x1: float) -> Manifold:
    """在 YZ 平面的多邊形，沿 X 從 x0 擠出到 x1。"""
    # 先在 XY 平面以 (y, z) 擠出到 Z，再把 (X,Y,Z)=(y,z,x) 換回 (x,y,z)
    m = extrude_xy(points_yz, x0, x1)
    # 換軸：新 = (舊 Z, 舊 X, 舊 Y)
    t = np.array([[0, 0, 1, 0], [1, 0, 0, 0], [0, 1, 0, 0]], dtype=float)
    return m.transform(t)


def extrude_xz(points_xz: list[tuple[float, float]], y0: float, y1: float) -> Manifold:
    """在 XZ 平面的多邊形，沿 Y 從 y0 擠出到 y1。"""
    # 以 (z, x) 當平面座標、沿 Z' 擠出 y，再做正向（行列式 +1）的換軸
    m = extrude_xy([(z, x) for x, z in points_xz], y0, y1)
    # 新 = (舊 Y, 舊 Z, 舊 X)
    t = np.array([[0, 1, 0, 0], [0, 0, 1, 0], [1, 0, 0, 0]], dtype=float)
    return m.transform(t)


def from_trimesh(tm: trimesh.Trimesh) -> Manifold:
    mesh = Mesh(
        vert_properties=np.asarray(tm.vertices, dtype=np.float32),
        tri_verts=np.asarray(tm.faces, dtype=np.uint32),
    )
    m = Manifold(mesh)
    if m.status().name != "NoError":
        raise ValueError(f"網格不是封閉流形：{m.status()}")
    return m


def to_trimesh(m: Manifold) -> trimesh.Trimesh:
    mesh = m.to_mesh()
    verts = np.asarray(mesh.vert_properties)[:, :3]
    return trimesh.Trimesh(vertices=verts, faces=np.asarray(mesh.tri_verts), process=True)


def union_all(parts: list[Manifold]) -> Manifold:
    return Manifold.batch_boolean(parts, manifold3d_op("Add"))


def subtract_all(base: Manifold, cutters: list[Manifold]) -> Manifold:
    if not cutters:
        return base
    return base - Manifold.batch_boolean(cutters, manifold3d_op("Add"))


def manifold3d_op(name: str):
    from manifold3d import OpType

    return getattr(OpType, name)
