"""把一顆眼睛的參數畫成 240×240 RGB 影像。

圖層由下而上：表情層（虹膜／形狀、眼皮、疊加圖示）→ 夜間調暗 → **狀態環（最上層）**。
表情層只畫在半徑 EXPR_R 以內，狀態環在它外面，兩者不重疊，所以任何表情都蓋不到狀態環。

加速（2026-11-27，Pi 4 上兩眼一幀原本約 130 ms）：
- 每個形狀只在自己的外接矩形（加上反鋸齒的邊）裡算距離場與混色，不再每次算整個 240×240。
- 表情層外面本來就會被遮成黑色，所以所有視窗都先裁到表情層的外接正方形。
- 狀態環的像素位置與覆蓋率是固定的，預先算好，只對那幾千個像素上色。
- `render_eye()` 記住上一組輸入；參數完全相同（眼睛靜止、沒眨眼）時直接沿用上一幀。
畫出來的結果和逐像素算整張圖相同（量化後最多差 1，見 docs/validation/eyes-render-speed-2026-11-27.md）。
"""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
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

_C = (SIZE - 1) / 2.0  # 像素中心座標的原點（像素索引 i 的座標是 i − _C）
_X, _Y = sdf.grid(SIZE)
_XS = _X[0, :]  # 每一欄的 x（1D）
_YS = _Y[:, 0]

# 表情層的外接正方形：覆蓋率 > 0 只到半徑 EXPR_R + 0.5，往外再留 1 px
_E0 = max(0, int(math.floor(_C - EXPR_R - 1.5)))
_E1 = min(SIZE, int(math.ceil(_C + EXPR_R + 1.5)) + 1)
_EXPR_COV = sdf.coverage(np.hypot(_X, _Y) - EXPR_R)

Win = tuple  # (r0, r1, c0, c1)：列、欄的切片範圍，含頭不含尾


@dataclass(frozen=True)
class Overlay:
    """疊加圖示（眼淚、汗、Zzz、問號…），畫在表情層裡。"""

    kind: str
    phase: float = 0.0  # 0～1 的動畫相位
    level: float = 1.0  # 電量、亮度等
    opts: dict = field(default_factory=dict)

    def key(self) -> tuple:
        return (self.kind, self.phase, self.level, tuple(sorted(self.opts.items())))


def _win(x0: float, y0: float, x1: float, y1: float, m: float = 2.0) -> Win | None:
    """座標範圍（含反鋸齒邊 m px）→ 像素視窗，並裁到表情層的外接正方形；範圍是空的回傳 None。"""
    c0 = max(_E0, int(math.floor(x0 + _C - m)))
    c1 = min(_E1, int(math.ceil(x1 + _C + m)) + 1)
    r0 = max(_E0, int(math.floor(y0 + _C - m)))
    r1 = min(_E1, int(math.ceil(y1 + _C + m)) + 1)
    if c0 >= c1 or r0 >= r1:
        return None
    return (r0, r1, c0, c1)


def _ellipse_margin(rx: float, ry: float) -> float:
    """`sdf.ellipse` 是近似距離（乘上短軸），長軸方向的距離被低估，視窗要多留一點。"""
    lo = max(min(abs(rx), abs(ry)), 1e-3)
    return 2.0 + 0.5 * max(abs(rx), abs(ry)) / lo


def _pts_win(pts, m: float = 2.0) -> Win | None:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return _win(min(xs), min(ys), max(xs), max(ys), m)


def _union(*wins: Win | None) -> Win | None:
    ws = [w for w in wins if w is not None]
    if not ws:
        return None
    return (min(w[0] for w in ws), max(w[1] for w in ws), min(w[2] for w in ws), max(w[3] for w in ws))


class _Canvas:
    """表情層的畫布：記住畫過的範圍，最後只處理那一塊。"""

    def __init__(self) -> None:
        self.img = np.zeros((SIZE, SIZE, 3), np.float32)
        self.box: Win | None = None

    def sub(self, w: Win):
        r0, r1, c0, c1 = w
        return self.img[r0:r1, c0:c1], _X[r0:r1, c0:c1], _Y[r0:r1, c0:c1]

    def touch(self, w: Win) -> None:
        self.box = _union(self.box, w)

    def paint(self, w: Win | None, dist, color, alpha: float = 1.0) -> None:
        """在視窗 w 裡用距離場 dist(X, Y) 上色。"""
        if w is None or alpha <= 0.0:
            return
        img, X, Y = self.sub(w)
        _paint(img, sdf.coverage(dist(X, Y)), color, alpha)
        self.touch(w)


def _paint(img: np.ndarray, cov: np.ndarray, color, alpha: float = 1.0) -> None:
    a = (cov * alpha)[..., None]
    img *= 1.0 - a
    img += a * np.asarray(color, dtype=np.float32)


def _iris(cv: _Canvas, p: EyeParams, cx: float, cy: float) -> None:
    r = p.iris_r
    ry = r * p.squash
    w = _win(cx - r, cy - abs(ry), cx + r, cy + abs(ry), _ellipse_margin(r, ry))
    if w is None:
        return
    img, X, Y = cv.sub(w)
    d = sdf.ellipse(X, Y, cx, cy, r, ry)
    cov = sdf.coverage(d)
    dx, dy = X - cx, (Y - cy) / max(p.squash, 1e-3)
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
    # 瞳孔（視差：比虹膜多移一點）。瞳孔與高光都乘上虹膜覆蓋率，所以只會落在虹膜視窗裡；
    # 各自只在自己的小視窗（和虹膜視窗的交集）裡算
    pcx = cx + (cx * 0.08)
    pcy = cy + (cy * 0.08)
    prx, pry = p.pupil_r, p.pupil_r * p.squash
    _paint_in(img, X, Y, cov, w, _win(pcx - prx, pcy - abs(pry), pcx + prx, pcy + abs(pry), _ellipse_margin(prx, pry)),
              lambda x, y: sdf.ellipse(x, y, pcx, pcy, prx, pry), PUPIL)
    # 高光（角膜反光）
    if p.highlight > 0:
        hx, hy, hrx, hry = cx - 0.34 * r, cy - 0.40 * ry, 0.18 * r, 0.14 * r
        _paint_in(img, X, Y, cov, w, _win(hx - hrx, hy - hry, hx + hrx, hy + hry, _ellipse_margin(hrx, hry)),
                  lambda x, y: sdf.ellipse(x, y, hx, hy, hrx, hry), (1, 1, 1), 0.92 * p.highlight)
        gx, gy, gr = cx + 0.28 * r, cy + 0.30 * ry, 0.07 * r
        _paint_in(img, X, Y, cov, w, _win(gx - gr, gy - gr, gx + gr, gy + gr),
                  lambda x, y: sdf.circle(x, y, gx, gy, gr), (1, 1, 1), 0.55 * p.highlight)
    cv.touch(w)


def _paint_in(img, X, Y, mask, w: Win, w2: Win | None, dist, color, alpha: float = 1.0) -> None:
    """在視窗 w 的子區域 w2 上色，覆蓋率再乘上 mask（同樣是 w 的大小）。"""
    if w2 is None or alpha <= 0.0:
        return
    r0, r1 = max(w[0], w2[0]) - w[0], min(w[1], w2[1]) - w[0]
    c0, c1 = max(w[2], w2[2]) - w[2], min(w[3], w2[3]) - w[2]
    if r0 >= r1 or c0 >= c1:
        return
    x, y = X[r0:r1, c0:c1], Y[r0:r1, c0:c1]
    _paint(img[r0:r1, c0:c1], sdf.coverage(dist(x, y)) * mask[r0:r1, c0:c1], color, alpha)


def _lid_edges(p: EyeParams, inner_sign: float, xs: np.ndarray):
    """上下眼皮的邊緣 y（只和 x 有關），以及斜率造成的距離修正。"""
    follow = p.look_y * 12.0
    y_up = -LID_OPEN_Y + (LID_OPEN_Y + LID_MEET_Y) * p.upper + follow
    y_lo = LID_OPEN_Y - (LID_OPEN_Y - LID_MEET_Y) * p.lower + follow
    xn = (xs - p.off_x) / LID_OPEN_Y
    bow = 1.0 - xn**2
    e_up = y_up + p.off_y + p.upper_tilt * (xs - p.off_x) * inner_sign + p.upper_bow * bow
    e_lo = y_lo + p.off_y - p.lower_tilt * (xs - p.off_x) * inner_sign + p.lower_bow * bow
    return e_up, e_lo, math.sqrt(1 + p.upper_tilt**2), math.sqrt(1 + p.lower_tilt**2)


def _lid_cov(p: EyeParams, inner_sign: float) -> np.ndarray:
    """整張畫面的眼皮覆蓋率（測試與除錯用；渲染走 `_lids` 的分段版本）。"""
    e_up, e_lo, s_up, s_lo = _lid_edges(p, inner_sign, _XS)
    cov_up = sdf.coverage((_Y - e_up[None, :]) / s_up)
    cov_lo = sdf.coverage((e_lo[None, :] - _Y) / s_lo)
    return np.maximum(cov_up, cov_lo)


def _lids(cv: _Canvas, p: EyeParams, inner_sign: float) -> None:
    cols = slice(_E0, _E1)
    xs = _XS[cols]
    e_up, e_lo, s_up, s_lo = _lid_edges(p, inner_sign, xs)
    # 上眼皮覆蓋率 > 0 的列：y < e_up + 0.5·s_up；下眼皮：y > e_lo − 0.5·s_lo
    r_up = min(_E1, max(_E0, int(math.ceil(float(e_up.max()) + 0.5 * s_up + _C)) + 2))
    r_lo = max(_E0, min(_E1, int(math.floor(float(e_lo.min()) - 0.5 * s_lo + _C)) - 2))
    if r_up <= r_lo:  # 上下兩條不相交：各畫各的，和取 max 的結果相同
        for r0, r1, cov_fn in (
            (_E0, r_up, lambda Y: sdf.coverage((Y - e_up[None, :]) / s_up)),
            (r_lo, _E1, lambda Y: sdf.coverage((e_lo[None, :] - Y) / s_lo)),
        ):
            if r0 < r1:
                w = (r0, r1, _E0, _E1)
                img, _, Y = cv.sub(w)
                _paint(img, cov_fn(Y), LID)
                cv.touch(w)
    else:  # 快閉上了：兩片眼皮重疊，照原本的方式取 max
        w = (_E0, _E1, _E0, _E1)
        img, _, Y = cv.sub(w)
        cov = np.maximum(sdf.coverage((Y - e_up[None, :]) / s_up), sdf.coverage((e_lo[None, :] - Y) / s_lo))
        _paint(img, cov, LID)
        cv.touch(w)


def _shape(cv: _Canvas, p: EyeParams, cx: float, cy: float) -> None:
    s = p.shape_scale
    if p.shape == "iris":
        _iris(cv, p, cx, cy)
    elif p.shape == "arc_up":  # ^ 笑瞇瞇閉眼
        ax, ay, ar, aw = cx, cy + 34 * s, 60 * s, 10 * s
        cv.paint(_win(ax - ar - aw, ay - ar - aw, ax + ar + aw, ay + ar + aw), lambda X, Y: sdf.arc(X, Y, ax, ay, ar, aw, 25, 155), p.color_in)
    elif p.shape == "arc_down":  # ‿ 安穩閉眼
        ax, ay, ar, aw = cx, cy - 30 * s, 60 * s, 8 * s
        cv.paint(_win(ax - ar - aw, ay - ar - aw, ax + ar + aw, ay + ar + aw), lambda X, Y: sdf.arc(X, Y, ax, ay, ar, aw, 205, 335), p.color_in)
    elif p.shape == "heart":
        hy, hs = cy + 4, 150 * s
        k = hs / 1.1  # sdf.heart 的範圍：x ±0.61k、y −0.56k～+0.55k
        cv.paint(_win(cx - 0.62 * k, hy - 0.57 * k, cx + 0.62 * k, hy + 0.56 * k, 3.0), lambda X, Y: sdf.heart(X, Y, cx, hy, hs), p.color_in)
        ex, ey, erx, ery = cx - 30 * s, cy - 28 * s, 13 * s, 9 * s
        cv.paint(_win(ex - erx, ey - ery, ex + erx, ey + ery, _ellipse_margin(erx, ery)), lambda X, Y: sdf.ellipse(X, Y, ex, ey, erx, ery), (1, 1, 1), 0.8)
    elif p.shape == "star":
        pts = sdf.star_points(cx, cy, 82 * s, 36 * s, 5, p.shape_rot)
        cv.paint(_pts_win(pts), lambda X, Y: sdf.polygon(X, Y, pts), p.color_in)
        pts2 = sdf.star_points(cx, cy, 46 * s, 20 * s, 5, p.shape_rot)
        cv.paint(_pts_win(pts2), lambda X, Y: sdf.polygon(X, Y, pts2), p.color_rim, 0.55)
    elif p.shape == "spiral":
        rm = 86 * s
        cv.paint(_win(cx - rm, cy - rm, cx + rm, cy + rm), lambda X, Y: sdf.spiral(X, Y, cx, cy, 20 * s, 4.5 * s, p.shape_rot, rm), p.color_in)
        cv.paint(_win(cx - 7 * s, cy - 7 * s, cx + 7 * s, cy + 7 * s), lambda X, Y: sdf.circle(X, Y, cx, cy, 7 * s), p.color_in)
    else:
        raise ValueError(f"unknown shape {p.shape!r}")


def _z(cv: _Canvas, cx, cy, h, alpha):
    w = h * 0.8
    t = max(h * 0.12, 1.6)

    def dist(X, Y):
        return np.minimum.reduce(
            [
                sdf.segment(X, Y, cx - w / 2, cy - h / 2, cx + w / 2, cy - h / 2, t),
                sdf.segment(X, Y, cx + w / 2, cy - h / 2, cx - w / 2, cy + h / 2, t),
                sdf.segment(X, Y, cx - w / 2, cy + h / 2, cx + w / 2, cy + h / 2, t),
            ]
        )

    cv.paint(_win(cx - w / 2 - t, cy - h / 2 - t, cx + w / 2 + t, cy + h / 2 + t), dist, WHITE_WARM, alpha)


def _teardrop_win(x: float, y: float, r: float) -> Win | None:
    return _win(x - r, y - 2.3 * r, x + r, y + r)


def _overlay(cv: _Canvas, o: Overlay, side: float) -> None:
    """side：+1 表示外側在畫面右（畫面右眼），−1 表示外側在畫面左。"""
    ph = o.phase % 1.0
    if o.kind == "tear":  # 從眼睛下緣滑下
        x = side * 38.0
        y = 40.0 + 46.0 * ph
        a = 1.0 if ph < 0.75 else (1.0 - ph) / 0.25
        cv.paint(_teardrop_win(x, y, 9.0), lambda X, Y: sdf.teardrop(X, Y, x, y, 9.0), TEAR, a)
    elif o.kind == "sweat":  # 外側上方的汗滴
        x = side * 70.0
        y = -62.0 + 18.0 * ph
        a = 1.0 if ph < 0.8 else (1.0 - ph) / 0.2
        cv.paint(_teardrop_win(x, y, 10.0), lambda X, Y: sdf.teardrop(X, Y, x, y, 10.0), TEAR, a)
    elif o.kind == "zzz":
        for k, h in enumerate((22.0, 16.0, 11.0)):
            q = (ph + k / 3.0) % 1.0
            x = side * (30.0 + 22.0 * q)
            y = -10.0 - 70.0 * q
            a = math.sin(math.pi * q)
            _z(cv, x, y, h * (0.7 + 0.5 * q), a)
    elif o.kind == "question":
        cx, cy = side * 52.0, -50.0
        bob = 3.0 * math.sin(2 * math.pi * ph)

        def dist(X, Y):
            return np.minimum.reduce(
                [
                    sdf.arc(X, Y, cx, cy - 8 + bob, 13.0, 4.0, -55, 190),
                    sdf.segment(X, Y, cx + 13 * math.cos(math.radians(-55)), cy - 8 + bob + 13 * math.sin(math.radians(55)), cx, cy + 12 + bob, 4.0),
                    sdf.circle(X, Y, cx, cy + 24 + bob, 4.5),
                ]
            )

        cv.paint(_win(cx - 17.0, cy - 8 + bob - 17.0, cx + 17.0, cy + 24 + bob + 4.5), dist, GOLD)
    elif o.kind == "dots":  # 思考中的三個點
        for k in range(3):
            q = (ph * 3 - k) % 3
            a = 0.25 + 0.75 * max(0.0, 1.0 - abs(q - 0.5) * 1.4)
            dx = -24.0 + 24.0 * k
            cv.paint(_win(dx - 7.0, 71.0, dx + 7.0, 85.0), lambda X, Y, dx=dx: sdf.circle(X, Y, dx, 78.0, 7.0), WHITE_WARM, a)
    elif o.kind == "battery":
        cx, cy = 0.0, 74.0

        def frame(X, Y):
            outline = np.abs(sdf.box(X, Y, cx, cy, 26, 13, 4)) - 2.2
            nub = sdf.box(X, Y, cx + 30, cy, 3, 6, 1.5)
            return np.minimum(outline, nub)

        cv.paint(_win(cx - 28.2, cy - 15.2, cx + 33.0, cy + 15.2), frame, WHITE_WARM)
        lvl = min(max(o.level, 0.0), 1.0)
        fw = 21.0 * lvl
        if fw > 0.5:
            blink = 1.0 if (ph % 1.0) < 0.6 else 0.35
            bx = cx - 21 + fw
            cv.paint(_win(bx - fw, cy - 8, bx + fw, cy + 8), lambda X, Y: sdf.box(X, Y, bx, cy, fw, 8, 1.5), ALERT_RED, blink)
    elif o.kind == "bolt":
        cx, cy = 0.0, 74.0
        pts = [(cx + 4, cy - 20), (cx - 12, cy + 3), (cx - 1, cy + 3), (cx - 5, cy + 20), (cx + 12, cy - 4), (cx + 1, cy - 4)]
        a = 0.55 + 0.45 * (0.5 - 0.5 * math.cos(2 * math.pi * ph))
        cv.paint(_pts_win(pts), lambda X, Y: sdf.polygon(X, Y, pts), GOLD, a)
    elif o.kind == "sparkle":
        for k, (sx, sy, sz) in enumerate(((side * 68, -60, 14), (side * 84, -20, 9), (side * 50, -86, 8))):
            q = (ph + k * 0.33) % 1.0
            a = math.sin(math.pi * q)
            if a > 0.02:
                pts = sdf.star_points(sx, sy, sz, sz * 0.28, 4, 45 * q)
                cv.paint(_pts_win(pts), lambda X, Y, pts=pts: sdf.polygon(X, Y, pts), WHITE_WARM, a)
    else:
        raise ValueError(f"unknown overlay {o.kind!r}")


def _draw(p: EyeParams, overlays, side: float) -> _Canvas:
    cv = _Canvas()
    cx = p.look_x * LOOK_X_PX + p.off_x
    cy = p.look_y * LOOK_Y_PX + p.off_y
    _shape(cv, p, cx, cy)
    if p.shape not in ("arc_up", "arc_down"):
        inner_sign = -side  # 畫面左眼的內側在 +x
        _lids(cv, p, inner_sign)
    for o in overlays:
        _overlay(cv, o, side)
    return cv


def _finish(cv: _Canvas, brightness: float, scale: float = 1.0, quantize: bool = False):
    """亮度 → 遮到表情層的圓 → clip；quantize=True 時再乘夜間倍率、轉 uint8（只處理畫過的範圍）。"""
    out = np.zeros((SIZE, SIZE, 3), np.uint8) if quantize else cv.img
    if cv.box is None:
        return out
    r0, r1, c0, c1 = cv.box
    img = cv.img[r0:r1, c0:c1]
    if brightness != 1.0:
        img *= brightness
    img *= _EXPR_COV[r0:r1, c0:c1, None]
    np.clip(img, 0.0, 1.0, out=img)
    if not quantize:
        return out
    img *= scale * 255.0
    img += 0.5
    out[r0:r1, c0:c1] = img.astype(np.uint8)
    return out


def render_expression_layer(p: EyeParams, overlays=(), side: float = 1.0) -> np.ndarray:
    """只畫表情層（float32 0～1，還沒加狀態環與夜間調暗）。side：畫面左眼 −1、畫面右眼 +1。"""
    return _finish(_draw(p, overlays, side), p.brightness)


# 狀態環：位置與覆蓋率固定，只存那幾千個像素
_RING_COV = sdf.coverage(np.maximum(np.hypot(_X, _Y) - RING_OUTER, RING_INNER - np.hypot(_X, _Y)))
_VISIBLE_COV = sdf.coverage(np.hypot(_X, _Y) - VISIBLE_R)
_RING_W_FULL = (_RING_COV * _VISIBLE_COV).astype(np.float32)
_RING_IDX = np.flatnonzero(_RING_W_FULL.ravel() > 0)
_RING_W = _RING_W_FULL.ravel()[_RING_IDX][:, None]
# 表情層（半徑 < EXPR_R + 0.5）和狀態環（半徑 > RING_INNER − 0.5）不重疊，合成時可以直接各自填入
assert not (_EXPR_COV.ravel()[_RING_IDX] > 0).any()


def _ring_values(ring: RingSpec) -> np.ndarray:
    v = _RING_W * np.asarray(ring.rgb, np.float32)
    return (np.clip(v, 0, 1) * 255 + 0.5).astype(np.uint8)


def _put_ring(out: np.ndarray, ring: RingSpec) -> np.ndarray:
    out.reshape(-1, 3)[_RING_IDX] = _ring_values(ring)
    return out


def compose(expr_layer: np.ndarray, ring: RingSpec, night: bool = False) -> np.ndarray:
    """表情層＋夜間調暗＋狀態環（最上層），回傳 uint8 240×240×3。

    `expr_layer` 要像 `render_expression_layer` 的輸出一樣，半徑 EXPR_R 以外是黑的（那裡會被當成黑色）。
    """
    out = np.zeros((SIZE, SIZE, 3), np.uint8)
    sub = expr_layer[_E0:_E1, _E0:_E1] * ((NIGHT_SCALE if night else 1.0) * 255.0)
    np.clip(sub, 0.0, 255.0, out=sub)
    sub += 0.5
    out[_E0:_E1, _E0:_E1] = sub.astype(np.uint8)
    return _put_ring(out, ring)


class EyeRenderer:
    """畫一顆眼睛，參數沒變就沿用上一幀的表情層（狀態環每次都重新上色，因為它會閃、會呼吸）。"""

    def __init__(self, cache_size: int = 4) -> None:
        self._cache: OrderedDict = OrderedDict()
        self._size = cache_size
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def render(self, p: EyeParams, overlays, side: float, ring: RingSpec, night: bool = False) -> np.ndarray:
        key = (p, tuple(o.key() for o in overlays), side, night)
        with self._lock:
            expr = self._cache.get(key)
            if expr is not None:
                self.hits += 1
                self._cache.move_to_end(key)
        if expr is None:
            expr = _finish(_draw(p, overlays, side), p.brightness, NIGHT_SCALE if night else 1.0, quantize=True)
            with self._lock:
                self.misses += 1
                self._cache[key] = expr
                if len(self._cache) > self._size:
                    self._cache.popitem(last=False)
        return _put_ring(expr.copy(), ring)


def ring_mask() -> np.ndarray:
    """狀態環所在的像素（覆蓋率 > 0.99），測試用。"""
    return _RING_COV > 0.99


def expression_mask() -> np.ndarray:
    return np.hypot(_X, _Y) < EXPR_R + 1.0
