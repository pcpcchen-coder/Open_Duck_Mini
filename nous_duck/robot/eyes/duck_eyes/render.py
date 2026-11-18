"""把一顆眼睛的參數畫成 240×240 RGB 影像。

圖層由下而上：表情層（虹膜／形狀、眼皮、疊加圖示）→ 夜間調暗 → **狀態環（最上層）**。
表情層只畫在半徑 EXPR_R 以內，狀態環在它外面，兩者不重疊，所以任何表情都蓋不到狀態環。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import sdf
from .params import (
    ALERT_RED,
    GOLD,
    PUPIL,
    TEAR,
    WHITE_WARM,
    EyeParams,
)
from .status import NIGHT_SCALE, RingSpec

SIZE = 240
VISIBLE_R = 120.0  # 有效顯示區半徑（Ø32.4 mm）
RING_OUTER = 119.0
RING_INNER = 112.0
EXPR_R = 109.0  # 表情層的外緣（和狀態環之間留 3 px 黑邊）
LOOK_X_PX = 24.0
LOOK_Y_PX = 20.0
LID_OPEN_Y = 106.0  # 眼皮全開時邊緣離中心的距離
LID_MEET_Y = 6.0  # 眼皮全閉時上下眼皮的交會處（略低於中心）
LID = (0.085, 0.060, 0.045)  # 眼皮顏色：很深的暖褐，讓眼皮形狀在黑底上看得出來

_X, _Y = sdf.grid(SIZE)


@dataclass(frozen=True)
class Overlay:
    """疊加圖示（眼淚、汗、Zzz、問號…），畫在表情層裡。"""

    kind: str
    phase: float = 0.0  # 0～1 的動畫相位
    level: float = 1.0  # 電量、亮度等
    opts: dict = field(default_factory=dict)


def _paint(img: np.ndarray, cov: np.ndarray, color, alpha: float = 1.0) -> None:
    a = (cov * alpha)[..., None]
    img *= 1.0 - a
    img += a * np.asarray(color, dtype=np.float32)


def _iris(img: np.ndarray, p: EyeParams, cx: float, cy: float) -> None:
    r = p.iris_r
    ry = r * p.squash
    d = sdf.ellipse(_X, _Y, cx, cy, r, ry)
    cov = sdf.coverage(d)
    dx, dy = _X - cx, (_Y - cy) / max(p.squash, 1e-3)
    tn = np.clip(np.hypot(dx, dy) / r, 0.0, 1.0)
    g = tn**1.6
    cin = np.asarray(p.color_in, np.float32)
    crim = np.asarray(p.color_rim, np.float32)
    col = cin * (1 - g)[..., None] + crim * g[..., None]
    theta = np.arctan2(dy, dx)
    col *= (1.0 + 0.07 * np.sin(22 * theta) * tn)[..., None]  # 虹膜紋路
    col *= (1.0 - 0.55 * sdf.smoothstep(0.86, 1.0, tn))[..., None]  # 外圈較暗
    a = cov[..., None]
    img *= 1 - a
    img += a * np.clip(col, 0, 1)
    # 瞳孔（視差：比虹膜多移一點）
    pcx = cx + (cx * 0.08)
    pcy = cy + (cy * 0.08)
    _paint(img, sdf.coverage(sdf.ellipse(_X, _Y, pcx, pcy, p.pupil_r, p.pupil_r * p.squash)) * cov, PUPIL)
    # 高光（角膜反光）
    if p.highlight > 0:
        hx, hy = cx - 0.34 * r, cy - 0.40 * ry
        _paint(img, sdf.coverage(sdf.ellipse(_X, _Y, hx, hy, 0.18 * r, 0.14 * r)) * cov, (1, 1, 1), 0.92 * p.highlight)
        _paint(img, sdf.coverage(sdf.circle(_X, _Y, cx + 0.28 * r, cy + 0.30 * ry, 0.07 * r)) * cov, (1, 1, 1), 0.55 * p.highlight)


def _lid_cov(p: EyeParams, inner_sign: float) -> np.ndarray:
    follow = p.look_y * 12.0
    y_up = -LID_OPEN_Y + (LID_OPEN_Y + LID_MEET_Y) * p.upper + follow
    y_lo = LID_OPEN_Y - (LID_OPEN_Y - LID_MEET_Y) * p.lower + follow
    xn = (_X - p.off_x) / LID_OPEN_Y
    bow = 1.0 - xn**2
    e_up = y_up + p.off_y + p.upper_tilt * (_X - p.off_x) * inner_sign + p.upper_bow * bow
    e_lo = y_lo + p.off_y - p.lower_tilt * (_X - p.off_x) * inner_sign + p.lower_bow * bow
    s_up = np.sqrt(1 + p.upper_tilt**2)
    s_lo = np.sqrt(1 + p.lower_tilt**2)
    cov_up = sdf.coverage((_Y - e_up) / s_up)
    cov_lo = sdf.coverage((e_lo - _Y) / s_lo)
    return np.maximum(cov_up, cov_lo)


def _shape(img: np.ndarray, p: EyeParams, cx: float, cy: float) -> None:
    s = p.shape_scale
    if p.shape == "iris":
        _iris(img, p, cx, cy)
    elif p.shape == "arc_up":  # ^ 笑瞇瞇閉眼
        d = sdf.arc(_X, _Y, cx, cy + 34 * s, 60 * s, 10 * s, 25, 155)
        _paint(img, sdf.coverage(d), p.color_in)
    elif p.shape == "arc_down":  # ‿ 安穩閉眼
        d = sdf.arc(_X, _Y, cx, cy - 30 * s, 60 * s, 8 * s, 205, 335)
        _paint(img, sdf.coverage(d), p.color_in)
    elif p.shape == "heart":
        d = sdf.heart(_X, _Y, cx, cy + 4, 150 * s)
        _paint(img, sdf.coverage(d), p.color_in)
        _paint(img, sdf.coverage(sdf.ellipse(_X, _Y, cx - 30 * s, cy - 28 * s, 13 * s, 9 * s)), (1, 1, 1), 0.8)
    elif p.shape == "star":
        pts = sdf.star_points(cx, cy, 82 * s, 36 * s, 5, p.shape_rot)
        d = sdf.polygon(_X, _Y, pts)
        cov = sdf.coverage(d)
        _paint(img, cov, p.color_in)
        _paint(img, sdf.coverage(sdf.polygon(_X, _Y, sdf.star_points(cx, cy, 46 * s, 20 * s, 5, p.shape_rot))), p.color_rim, 0.55)
    elif p.shape == "spiral":
        d = sdf.spiral(_X, _Y, cx, cy, 20 * s, 4.5 * s, p.shape_rot, 86 * s)
        _paint(img, sdf.coverage(d), p.color_in)
        _paint(img, sdf.coverage(sdf.circle(_X, _Y, cx, cy, 7 * s)), p.color_in)
    else:
        raise ValueError(f"unknown shape {p.shape!r}")


def _z(img, cx, cy, h, alpha):
    w = h * 0.8
    t = max(h * 0.12, 1.6)
    d = np.minimum.reduce(
        [
            sdf.segment(_X, _Y, cx - w / 2, cy - h / 2, cx + w / 2, cy - h / 2, t),
            sdf.segment(_X, _Y, cx + w / 2, cy - h / 2, cx - w / 2, cy + h / 2, t),
            sdf.segment(_X, _Y, cx - w / 2, cy + h / 2, cx + w / 2, cy + h / 2, t),
        ]
    )
    _paint(img, sdf.coverage(d), WHITE_WARM, alpha)


def _overlay(img: np.ndarray, o: Overlay, side: float) -> None:
    """side：+1 表示外側在畫面右（畫面右眼），−1 表示外側在畫面左。"""
    ph = o.phase % 1.0
    if o.kind == "tear":  # 從眼睛下緣滑下
        x = side * 38.0
        y = 40.0 + 46.0 * ph
        a = 1.0 if ph < 0.75 else (1.0 - ph) / 0.25
        _paint(img, sdf.coverage(sdf.teardrop(_X, _Y, x, y, 9.0)), TEAR, a)
    elif o.kind == "sweat":  # 外側上方的汗滴
        x = side * 70.0
        y = -62.0 + 18.0 * ph
        a = 1.0 if ph < 0.8 else (1.0 - ph) / 0.2
        _paint(img, sdf.coverage(sdf.teardrop(_X, _Y, x, y, 10.0)), TEAR, a)
    elif o.kind == "zzz":
        for k, h in enumerate((22.0, 16.0, 11.0)):
            q = (ph + k / 3.0) % 1.0
            x = side * (30.0 + 22.0 * q)
            y = -10.0 - 70.0 * q
            a = math.sin(math.pi * q)
            _z(img, x, y, h * (0.7 + 0.5 * q), a)
    elif o.kind == "question":
        cx, cy = side * 52.0, -50.0
        bob = 3.0 * math.sin(2 * math.pi * ph)
        d = np.minimum.reduce(
            [
                sdf.arc(_X, _Y, cx, cy - 8 + bob, 13.0, 4.0, -55, 190),
                sdf.segment(_X, _Y, cx + 13 * math.cos(math.radians(-55)), cy - 8 + bob + 13 * math.sin(math.radians(55)), cx, cy + 12 + bob, 4.0),
                sdf.circle(_X, _Y, cx, cy + 24 + bob, 4.5),
            ]
        )
        _paint(img, sdf.coverage(d), GOLD)
    elif o.kind == "dots":  # 思考中的三個點
        for k in range(3):
            q = (ph * 3 - k) % 3
            a = 0.25 + 0.75 * max(0.0, 1.0 - abs(q - 0.5) * 1.4)
            _paint(img, sdf.coverage(sdf.circle(_X, _Y, -24.0 + 24.0 * k, 78.0, 7.0)), WHITE_WARM, a)
    elif o.kind == "battery":
        cx, cy = 0.0, 74.0
        outline = np.abs(sdf.box(_X, _Y, cx, cy, 26, 13, 4)) - 2.2
        nub = sdf.box(_X, _Y, cx + 30, cy, 3, 6, 1.5)
        _paint(img, sdf.coverage(np.minimum(outline, nub)), WHITE_WARM)
        lvl = min(max(o.level, 0.0), 1.0)
        fw = 21.0 * lvl
        if fw > 0.5:
            blink = 1.0 if (ph % 1.0) < 0.6 else 0.35
            _paint(img, sdf.coverage(sdf.box(_X, _Y, cx - 21 + fw, cy, fw, 8, 1.5)), ALERT_RED, blink)
    elif o.kind == "bolt":
        cx, cy = 0.0, 74.0
        pts = [(cx + 4, cy - 20), (cx - 12, cy + 3), (cx - 1, cy + 3), (cx - 5, cy + 20), (cx + 12, cy - 4), (cx + 1, cy - 4)]
        a = 0.55 + 0.45 * (0.5 - 0.5 * math.cos(2 * math.pi * ph))
        _paint(img, sdf.coverage(sdf.polygon(_X, _Y, pts)), GOLD, a)
    elif o.kind == "sparkle":
        for k, (sx, sy, sz) in enumerate(((side * 68, -60, 14), (side * 84, -20, 9), (side * 50, -86, 8))):
            q = (ph + k * 0.33) % 1.0
            a = math.sin(math.pi * q)
            if a > 0.02:
                pts = sdf.star_points(sx, sy, sz, sz * 0.28, 4, 45 * q)
                _paint(img, sdf.coverage(sdf.polygon(_X, _Y, pts)), WHITE_WARM, a)
    else:
        raise ValueError(f"unknown overlay {o.kind!r}")


def render_expression_layer(p: EyeParams, overlays=(), side: float = 1.0) -> np.ndarray:
    """只畫表情層（float32 0～1，還沒加狀態環與夜間調暗）。side：畫面左眼 −1、畫面右眼 +1。"""
    img = np.zeros((SIZE, SIZE, 3), np.float32)
    cx = p.look_x * LOOK_X_PX + p.off_x
    cy = p.look_y * LOOK_Y_PX + p.off_y
    _shape(img, p, cx, cy)
    if p.shape not in ("arc_up", "arc_down"):
        inner_sign = -side  # 畫面左眼的內側在 +x
        lid = _lid_cov(p, inner_sign)
        _paint(img, lid, LID)
    for o in overlays:
        _overlay(img, o, side)
    img *= p.brightness
    img *= sdf.coverage(np.hypot(_X, _Y) - EXPR_R)[..., None]
    return np.clip(img, 0.0, 1.0)


_RING_COV = sdf.coverage(np.maximum(np.hypot(_X, _Y) - RING_OUTER, RING_INNER - np.hypot(_X, _Y)))
_VISIBLE_COV = sdf.coverage(np.hypot(_X, _Y) - VISIBLE_R)


def compose(expr_layer: np.ndarray, ring: RingSpec, night: bool = False) -> np.ndarray:
    """表情層＋夜間調暗＋狀態環（最上層），回傳 uint8 240×240×3。"""
    img = expr_layer * (NIGHT_SCALE if night else 1.0)
    _paint(img, _RING_COV, ring.rgb)
    img *= _VISIBLE_COV[..., None]
    return (np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8)


def ring_mask() -> np.ndarray:
    """狀態環所在的像素（覆蓋率 > 0.99），測試用。"""
    return _RING_COV > 0.99


def expression_mask() -> np.ndarray:
    return np.hypot(_X, _Y) < EXPR_R + 1.0
