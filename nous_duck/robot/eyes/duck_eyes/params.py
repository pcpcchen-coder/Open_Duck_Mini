"""單眼的外觀參數、調色盤與插值。

兩眼的順序固定為 **(畫面左, 畫面右)**，也就是站在鴨子面前看到的左邊與右邊
（畫面左＝鴨子的右眼）。`inner` 是靠近臉中央的那一側。
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass, fields, replace

RGB = tuple[float, float, float]

# ---- 調色盤（0～1）。青色系保留給「鏡頭開著」的狀態環（ADR-0006 §4.2.2），表情不能用 ----
AMBER_IN: RGB = (1.00, 0.78, 0.36)
AMBER_RIM: RGB = (0.86, 0.42, 0.10)
SUN_IN: RGB = (1.00, 0.88, 0.40)  # 開心
SUN_RIM: RGB = (0.95, 0.55, 0.12)
ROSE_IN: RGB = (1.00, 0.55, 0.72)  # 喜歡
ROSE_RIM: RGB = (0.85, 0.22, 0.45)
LAVENDER_IN: RGB = (0.72, 0.66, 1.00)  # 難過（刻意不用藍綠，避開青色）
LAVENDER_RIM: RGB = (0.42, 0.33, 0.85)
EMBER_IN: RGB = (1.00, 0.52, 0.30)  # 不高興
EMBER_RIM: RGB = (0.80, 0.20, 0.10)
PALE_IN: RGB = (1.00, 0.90, 0.66)  # 害怕
PALE_RIM: RGB = (0.85, 0.62, 0.30)
GOLD: RGB = (1.00, 0.82, 0.22)
WHITE_WARM: RGB = (1.00, 0.96, 0.88)
TEAR: RGB = (0.84, 0.82, 1.00)  # 眼淚、汗：淡紫白，不用水藍
ALERT_RED: RGB = (1.00, 0.25, 0.20)
PUPIL: RGB = (0.03, 0.03, 0.05)

# 保留給狀態環的色相範圍（度）。表情層任何夠鮮豔的像素都不能落在這裡
RESERVED_HUE_DEG = (160.0, 205.0)


def hue_deg(c: RGB) -> float:
    return colorsys.rgb_to_hsv(*c)[0] * 360.0


@dataclass(frozen=True)
class EyeParams:
    look_x: float = 0.0  # −1（畫面左）～ 1（畫面右）
    look_y: float = 0.0  # −1（上）～ 1（下）
    iris_r: float = 74.0
    pupil_r: float = 30.0
    squash: float = 1.0  # 虹膜垂直縮放
    color_in: RGB = AMBER_IN
    color_rim: RGB = AMBER_RIM
    brightness: float = 1.0
    upper: float = 0.12  # 上眼皮閉合 0（全開）～ 1（全閉）
    lower: float = 0.04
    upper_tilt: float = 0.0  # 正＝內側較低（生氣）；負＝內側較高（難過、擔心）
    lower_tilt: float = 0.0
    upper_bow: float = -14.0  # 眼皮邊緣中間的彎曲（px）；負＝中間往上拱
    lower_bow: float = 8.0
    highlight: float = 1.0
    shape: str = "iris"  # iris | arc_up | arc_down | heart | star | spiral
    shape_scale: float = 1.0
    shape_rot: float = 0.0  # 度（星星）或圈數（螺旋）
    off_x: float = 0.0  # 整顆眼睛的額外位移（px），給顫抖、彈跳用
    off_y: float = 0.0


_NUMERIC = [f.name for f in fields(EyeParams) if f.name not in ("shape", "color_in", "color_rim")]


def lerp(a: EyeParams, b: EyeParams, k: float) -> EyeParams:
    """數值欄位線性插值；形狀不能插值，k < 0.5 用 a 的、否則用 b 的。"""
    k = min(max(k, 0.0), 1.0)
    vals = {n: getattr(a, n) + (getattr(b, n) - getattr(a, n)) * k for n in _NUMERIC}
    vals["color_in"] = tuple(x + (y - x) * k for x, y in zip(a.color_in, b.color_in))
    vals["color_rim"] = tuple(x + (y - x) * k for x, y in zip(a.color_rim, b.color_rim))
    vals["shape"] = a.shape if k < 0.5 else b.shape
    return EyeParams(**vals)


def ease_in_out(k: float) -> float:
    k = min(max(k, 0.0), 1.0)
    return k * k * (3 - 2 * k)


def with_(p: EyeParams, **kw) -> EyeParams:
    return replace(p, **kw)
