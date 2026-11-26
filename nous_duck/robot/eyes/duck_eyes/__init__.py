"""鴨子眼睛（GC9A01 1.28 吋圓形螢幕 ×2）的渲染程式。

只負責「畫出每一幀」；螢幕的 SPI 驅動還沒寫（等 E1 實測）。設計見
`nous_duck/docs/eye_expressions.md` 與 `nous_duck/hardware/expression_mods/gc9a01_eyes.md`。
"""

from .animator import EyeAnimator, Frame
from .expressions import EXPRESSIONS, SOUND_CUES, Inputs
from .policy import NOUS_ALLOWED, nous_can_request, resting_expression
from .render import compose, render_expression_layer
from .status import DeviceState, ring_spec

__all__ = [
    "EXPRESSIONS",
    "SOUND_CUES",
    "DeviceState",
    "EyeAnimator",
    "Frame",
    "Inputs",
    "compose",
    "render_expression_layer",
    "ring_spec",
    "render_frame",
    "NOUS_ALLOWED",
    "nous_can_request",
    "resting_expression",
]


def render_frame(frame: Frame, device: DeviceState, t: float):
    """把一幀畫成兩張 240×240 uint8 影像（畫面左眼、畫面右眼）。"""
    ring = ring_spec(device, t)
    out = []
    for idx, (p, side) in enumerate(((frame.left, -1.0), (frame.right, 1.0))):
        ov = [o for i, o in frame.overlays if i == idx]
        out.append(compose(render_expression_layer(p, ov, side), ring, night=device.night))
    return out[0], out[1]
