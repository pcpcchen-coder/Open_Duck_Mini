"""鴨子眼睛（GC9A01 1.28 吋圓形螢幕 ×2）的渲染程式。

只負責「畫出每一幀」；螢幕的 SPI 驅動還沒寫（等 E1 實測）。設計見
`nous_duck/docs/eye_expressions.md` 與 `nous_duck/hardware/expression_mods/gc9a01_eyes.md`。
"""

from .animator import EyeAnimator, Frame
from .expressions import EXPRESSIONS, SOUND_CUES, Inputs
from .policy import NOUS_ALLOWED, nous_can_request, resting_expression
from .render import EyeRenderer, compose, render_expression_layer
from .status import DeviceState, ring_spec

__all__ = [
    "EXPRESSIONS",
    "SOUND_CUES",
    "DeviceState",
    "EyeAnimator",
    "Frame",
    "Inputs",
    "EyeRenderer",
    "compose",
    "render_expression_layer",
    "ring_spec",
    "render_frame",
    "NOUS_ALLOWED",
    "nous_can_request",
    "resting_expression",
]


_RENDERER = EyeRenderer(cache_size=8)
_POOL = None  # 第二隻眼睛用的執行緒（numpy 運算時會放開 GIL，兩眼可以同時畫）


def _pool():
    global _POOL
    if _POOL is None:
        from concurrent.futures import ThreadPoolExecutor

        _POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="duck-eyes")
    return _POOL


def render_frame(frame: Frame, device: DeviceState, t: float, renderer: EyeRenderer | None = None, parallel: bool = True):
    """把一幀畫成兩張 240×240 uint8 影像（畫面左眼、畫面右眼）。

    同樣的參數畫出同樣的畫面；`renderer` 記住最近畫過的表情層，參數沒變就直接沿用（不影響結果）。
    parallel=True 時右眼在另一個執行緒畫（結果相同，只是比較快）。
    """
    r = renderer or _RENDERER
    ring = ring_spec(device, t)
    ov_l = [o for i, o in frame.overlays if i == 0]
    ov_r = [o for i, o in frame.overlays if i == 1]
    if parallel:
        fut = _pool().submit(r.render, frame.right, ov_r, 1.0, ring, device.night)
        left = r.render(frame.left, ov_l, -1.0, ring, night=device.night)
        return left, fut.result()
    left = r.render(frame.left, ov_l, -1.0, ring, night=device.night)
    return left, r.render(frame.right, ov_r, 1.0, ring, night=device.night)
