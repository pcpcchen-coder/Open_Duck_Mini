"""平面幾何小工具。座標：地圖座標 x、y（m），yaw 逆時針為正（rad）；機身座標 x 朝前、y 朝左。"""

from __future__ import annotations

import math
from typing import NamedTuple


class Pose2D(NamedTuple):
    x: float
    y: float
    yaw: float


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def to_body(pose: Pose2D, x: float, y: float) -> tuple[float, float]:
    """地圖座標的點 → 機身座標。"""
    dx, dy = x - pose.x, y - pose.y
    c, s = math.cos(pose.yaw), math.sin(pose.yaw)
    return c * dx + s * dy, -s * dx + c * dy


def to_map(pose: Pose2D, bx: float, by: float) -> tuple[float, float]:
    """機身座標的點 → 地圖座標。"""
    c, s = math.cos(pose.yaw), math.sin(pose.yaw)
    return pose.x + c * bx - s * by, pose.y + s * bx + c * by


def compose(a: Pose2D, b: Pose2D) -> Pose2D:
    """a ∘ b：b 是在 a 的座標系裡的位姿。"""
    x, y = to_map(a, b.x, b.y)
    return Pose2D(x, y, wrap(a.yaw + b.yaw))


def inverse(a: Pose2D) -> Pose2D:
    c, s = math.cos(a.yaw), math.sin(a.yaw)
    return Pose2D(-(c * a.x + s * a.y), -(-s * a.x + c * a.y), wrap(-a.yaw))


def dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def point_in_rect(x: float, y: float, rect, margin: float = 0.0) -> bool:
    x0, y0, x1, y1 = rect
    return x0 - margin <= x <= x1 + margin and y0 - margin <= y <= y1 + margin


def rect_distance(x: float, y: float, rect) -> float:
    """點到長方形的距離（在裡面為 0）。"""
    x0, y0, x1, y1 = rect
    dx = max(x0 - x, 0.0, x - x1)
    dy = max(y0 - y, 0.0, y - y1)
    return math.hypot(dx, dy)


def segment_hits_rect(p0, p1, rect) -> float | None:
    """線段 p0→p1 與軸對齊長方形的第一個交點參數 t∈[0,1]；沒有交點回傳 None（slab 法）。"""
    x0, y0, x1, y1 = rect
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    t0, t1 = 0.0, 1.0
    for d, p, lo, hi in ((dx, p0[0], x0, x1), (dy, p0[1], y0, y1)):
        if abs(d) < 1e-12:
            if p < lo or p > hi:
                return None
        else:
            a, b = (lo - p) / d, (hi - p) / d
            if a > b:
                a, b = b, a
            t0, t1 = max(t0, a), min(t1, b)
            if t0 > t1:
                return None
    return t0
