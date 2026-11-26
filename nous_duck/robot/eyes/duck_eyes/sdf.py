"""2D 有號距離場（SDF）基本形狀，全部用 numpy 向量化。

座標：畫面中心為原點、單位是像素、x 往右、**y 往下**（和影像一樣）。
距離 < 0 代表在形狀裡面。`coverage()` 把距離轉成 0～1 的覆蓋率（約 1 px 反鋸齒）。
部分公式改寫自 Inigo Quilez 公開的 2D SDF 推導（https://iquilezles.org/articles/distfunctions2d/）。
"""

from __future__ import annotations

import math

import numpy as np

Array = np.ndarray


def grid(size: int) -> tuple[Array, Array]:
    """回傳像素中心座標 (x, y)，原點在畫面正中央。"""
    c = (size - 1) / 2.0
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    return x - c, y - c


def coverage(d: Array, aa: float = 1.0) -> Array:
    return np.clip(0.5 - d / aa, 0.0, 1.0)


def smoothstep(e0: float, e1: float, v: Array) -> Array:
    t = np.clip((v - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def circle(x: Array, y: Array, cx: float, cy: float, r: float) -> Array:
    return np.hypot(x - cx, y - cy) - r


def ellipse(x: Array, y: Array, cx: float, cy: float, rx: float, ry: float) -> Array:
    """近似距離（接近圓形時誤差小，用在虹膜與高光已足夠）。"""
    k = np.hypot((x - cx) / rx, (y - cy) / ry)
    return (k - 1.0) * min(rx, ry)


def segment(x: Array, y: Array, ax: float, ay: float, bx: float, by: float, r: float) -> Array:
    """膠囊（線段加半徑）。"""
    px, py = x - ax, y - ay
    ex, ey = bx - ax, by - ay
    h = np.clip((px * ex + py * ey) / (ex * ex + ey * ey + 1e-9), 0.0, 1.0)
    return np.hypot(px - ex * h, py - ey * h) - r


def box(x: Array, y: Array, cx: float, cy: float, hw: float, hh: float, r: float = 0.0) -> Array:
    """圓角矩形；hw、hh 是半寬、半高。"""
    qx = np.abs(x - cx) - hw + r
    qy = np.abs(y - cy) - hh + r
    return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r


def polygon(x: Array, y: Array, pts) -> Array:
    """任意簡單多邊形（頂點順序不限）。"""
    v = np.asarray(pts, dtype=np.float32)
    d = (x - v[0, 0]) ** 2 + (y - v[0, 1]) ** 2
    s = np.ones_like(x)
    n = len(v)
    j = n - 1
    for i in range(n):
        ex, ey = v[j, 0] - v[i, 0], v[j, 1] - v[i, 1]
        wx, wy = x - v[i, 0], y - v[i, 1]
        h = np.clip((wx * ex + wy * ey) / (ex * ex + ey * ey + 1e-9), 0.0, 1.0)
        bx, by = wx - ex * h, wy - ey * h
        d = np.minimum(d, bx * bx + by * by)
        c1 = y >= v[i, 1]
        c2 = y < v[j, 1]
        c3 = ex * wy > ey * wx
        flip = (c1 & c2 & c3) | (~c1 & ~c2 & ~c3)
        s = np.where(flip, -s, s)
        j = i
    return s * np.sqrt(d)


def arc(x: Array, y: Array, cx: float, cy: float, radius: float, w: float, a0: float, a1: float) -> Array:
    """圓弧（粗 2w、兩端圓頭）。角度用數學慣例（度，0° 朝右、逆時針，畫面上「往上」為 90°）。"""
    px, py = x - cx, -(y - cy)
    ang = np.arctan2(py, px)
    r0, r1 = math.radians(a0), math.radians(a1)
    span = (r1 - r0) % (2 * math.pi)
    rel = (ang - r0) % (2 * math.pi)
    inside = rel <= span
    d_ring = np.abs(np.hypot(px, py) - radius) - w
    e0 = (radius * math.cos(r0), radius * math.sin(r0))
    e1 = (radius * math.cos(r1), radius * math.sin(r1))
    d_end = np.minimum(np.hypot(px - e0[0], py - e0[1]), np.hypot(px - e1[0], py - e1[1])) - w
    return np.where(inside, d_ring, d_end)


def heart(x: Array, y: Array, cx: float, cy: float, size: float) -> Array:
    """愛心，size 約等於整體高度。"""
    s = size / 1.1
    px = np.abs(x - cx) / s
    py = (cy - y) / s + 0.55
    d_top = np.hypot(px - 0.25, py - 0.75) - math.sqrt(2) / 4
    m = np.maximum(px + py, 0.0) * 0.5
    d_low = np.sqrt(np.minimum((px - 0.0) ** 2 + (py - 1.0) ** 2, (px - m) ** 2 + (py - m) ** 2)) * np.sign(px - py)
    return np.where(py + px > 1.0, d_top, d_low) * s


def star_points(cx: float, cy: float, r_out: float, r_in: float, n: int = 5, rot_deg: float = 0.0):
    pts = []
    for k in range(2 * n):
        r = r_out if k % 2 == 0 else r_in
        a = math.radians(rot_deg - 90 + k * 180 / n)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def spiral(x: Array, y: Array, cx: float, cy: float, pitch: float, half_w: float, phase: float, r_max: float) -> Array:
    """阿基米德螺線（線寬 2·half_w、圈距 pitch），phase 以圈為單位，用來旋轉。"""
    px, py = x - cx, y - cy
    r = np.hypot(px, py)
    th = np.arctan2(py, px) / (2 * math.pi)
    f = (r / pitch - th + phase) % 1.0
    d = np.minimum(f, 1.0 - f) * pitch - half_w
    return np.maximum(d, r - r_max)


def teardrop(x: Array, y: Array, cx: float, cy: float, r: float) -> Array:
    """水滴（圓在下、尖端朝上）。"""
    d_c = circle(x, y, cx, cy, r)
    tri = polygon(x, y, [(cx - r * 0.92, cy - r * 0.35), (cx + r * 0.92, cy - r * 0.35), (cx, cy - r * 2.3)])
    return np.minimum(d_c, tri)
