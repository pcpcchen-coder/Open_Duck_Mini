"""隨時間產生每一幀的兩眼參數：表情切換的過場、自動眨眼、眼睛小幅飄動、動作型表情。

全部由 `t`（秒）與固定亂數種子決定，同樣的輸入一定得到同樣的畫面（測試與預覽可重現）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .expressions import EXPRESSIONS, Expression, Inputs
from .params import EyeParams, ease_in_out, lerp, with_

TRANSITION_S = 0.22
BLINK_S = 0.16


def blink_closure(dt: float) -> float:
    """眨眼曲線：0.06 s 閉上、停 0.02 s、0.08 s 張開。"""
    if dt < 0 or dt > BLINK_S:
        return 0.0
    if dt < 0.06:
        return ease_in_out(dt / 0.06)
    if dt < 0.08:
        return 1.0
    return 1.0 - ease_in_out((dt - 0.08) / 0.08)


@dataclass
class Frame:
    left: EyeParams
    right: EyeParams
    overlays: list = field(default_factory=list)  # [(eye_index, Overlay)]，0＝畫面左、1＝畫面右
    expression: str = "neutral"
    sound: str | None = None  # 這一幀剛觸發的音效代號（只在切換時出現一次）


class EyeAnimator:
    def __init__(self, expression: str = "neutral", seed: int = 0, t0: float = 0.0):
        self.rng = np.random.default_rng(seed)
        self._cur = EXPRESSIONS[expression]
        self._prev: Expression | None = None
        self._t_set = t0
        self._prev_t_set = t0
        self._action: Expression | None = None
        self._action_t = 0.0
        self._next_blink = t0 + self._blink_gap(self._cur)
        self._blink_t: float | None = None
        self._wander_from = (0.0, 0.0)
        self._wander_to = (0.0, 0.0)
        self._wander_t = t0
        self._next_wander = t0 + float(self.rng.uniform(1.2, 3.5))
        self._pending_sound: str | None = self._cur.sound

    # ---- 控制 ----
    @property
    def expression(self) -> str:
        return (self._action or self._cur).id

    def set_expression(self, name: str, t: float) -> None:
        exp = EXPRESSIONS[name]
        if exp.action_s is not None:
            self._action, self._action_t = exp, t
            self._pending_sound = exp.sound
            return
        if exp.id == self._cur.id:
            return
        self._prev, self._prev_t_set = self._cur, self._t_set
        self._cur, self._t_set = exp, t
        self._pending_sound = exp.sound
        self._next_blink = t + self._blink_gap(exp)

    # ---- 內部 ----
    def _blink_gap(self, exp: Expression) -> float:
        if exp.blink is None:
            return float("inf")
        return float(self.rng.uniform(*exp.blink))

    def _pose(self, exp: Expression, t_local: float, inp: Inputs, look: tuple[float, float]):
        L, R, ov = exp.left, exp.right, []
        if exp.follow_gaze and inp.gaze is not None:
            gx, gy = (max(-1.0, min(1.0, g)) for g in inp.gaze)
            L, R = with_(L, look_x=gx, look_y=gy), with_(R, look_x=gx, look_y=gy)
        elif exp.wander:
            L = with_(L, look_x=L.look_x + look[0], look_y=L.look_y + look[1])
            R = with_(R, look_x=R.look_x + look[0], look_y=R.look_y + look[1])
        if exp.animate is not None:
            L, R, ov = exp.animate(L, R, ov, t_local, inp)
        return L, R, ov

    def _update_wander(self, t: float) -> tuple[float, float]:
        if t >= self._next_wander:
            self._wander_from = self._wander_pos(t)
            self._wander_to = (float(self.rng.uniform(-0.18, 0.18)), float(self.rng.uniform(-0.12, 0.12)))
            self._wander_t = t
            self._next_wander = t + float(self.rng.uniform(1.2, 3.5))
        return self._wander_pos(t)

    def _wander_pos(self, t: float) -> tuple[float, float]:
        k = ease_in_out((t - self._wander_t) / 0.06)  # 跳視很快
        a, b = self._wander_from, self._wander_to
        return (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k)

    # ---- 每一幀 ----
    def frame(self, t: float, inputs: Inputs | None = None) -> Frame:
        inp = inputs or Inputs()
        look = self._update_wander(t)
        L, R, ov = self._pose(self._cur, t - self._t_set, inp, look)

        # 過場：形狀相同就插值；形狀不同就先暗下再亮起
        k = (t - self._t_set) / TRANSITION_S
        if self._prev is not None and k < 1.0:
            pL, pR, pov = self._pose(self._prev, t - self._prev_t_set, inp, look)
            same = pL.shape == L.shape and pR.shape == R.shape
            if same:
                e = ease_in_out(k)
                L, R = lerp(pL, L, e), lerp(pR, R, e)
                ov = ov if k >= 0.5 else pov
            elif k < 0.5:
                f = 1.0 - ease_in_out(k * 2)
                L, R, ov = with_(pL, brightness=pL.brightness * f), with_(pR, brightness=pR.brightness * f), pov
            else:
                f = ease_in_out((k - 0.5) * 2)
                L, R = with_(L, brightness=L.brightness * f), with_(R, brightness=R.brightness * f)

        # 動作型表情（眨單眼）
        if self._action is not None:
            dt = t - self._action_t
            if dt <= self._action.action_s:
                L, R = self._action.left, self._action.right
                ov = []
            else:
                self._action = None

        # 自動眨眼（動作進行中不眨）
        if self._action is None and self._cur.blink is not None:
            if self._blink_t is None and t >= self._next_blink:
                self._blink_t = t
            if self._blink_t is not None:
                c = blink_closure(t - self._blink_t)
                if t - self._blink_t > BLINK_S:
                    self._blink_t = None
                    self._next_blink = t + self._blink_gap(self._cur)
                elif L.shape not in ("arc_up", "arc_down"):
                    L = with_(L, upper=max(L.upper, c), lower=max(L.lower, c * 0.3))
                    R = with_(R, upper=max(R.upper, c), lower=max(R.lower, c * 0.3))

        sound, self._pending_sound = self._pending_sound, None
        return Frame(L, R, ov, self.expression, sound)
