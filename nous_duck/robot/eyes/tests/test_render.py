"""渲染：狀態環在最上層、青色保留、表情畫不出界。"""

import colorsys

import numpy as np
import pytest

from duck_eyes import EXPRESSIONS, DeviceState, EyeAnimator, Inputs, render_expression_layer, render_frame
from duck_eyes import params as P
from duck_eyes.render import SIZE, expression_mask, ring_mask
from duck_eyes.sdf import grid

TIMES = (0.05, 0.4, 0.9, 1.7, 2.6)


def _frames(eid):
    anim = EyeAnimator(eid, seed=5)
    if EXPRESSIONS[eid].action_s is not None:
        anim = EyeAnimator("neutral", seed=5)
        anim.set_expression(eid, 0.0)
    for t in TIMES:
        yield t, anim.frame(t, Inputs(audio_level=0.7, battery=0.1, gaze=(0.3, -0.2)))


def test_output_shape_and_outside_black():
    a, b = render_frame(EyeAnimator().frame(0.5), DeviceState(True), 0.5)
    for img in (a, b):
        assert img.shape == (SIZE, SIZE, 3) and img.dtype == np.uint8
    x, y = grid(SIZE)
    outside = np.hypot(x, y) > 121
    assert a[outside].max() == 0 and b[outside].max() == 0


@pytest.mark.parametrize("dev", [DeviceState(True), DeviceState(False, conversation_active=True), DeviceState(True, night=True)])
def test_ring_identical_for_every_expression(dev):
    """任何表情都改不到狀態環的像素。"""
    m = ring_mask()
    ref = None
    for eid in EXPRESSIONS:
        for t, fr in _frames(eid):
            left, right = render_frame(fr, dev, 0.4)  # 狀態環用同一個時間
            for img in (left, right):
                if ref is None:
                    ref = img[m].copy()
                assert np.array_equal(img[m], ref), eid


def test_expression_layer_stays_inside():
    inside = expression_mask()
    for eid in EXPRESSIONS:
        for t, fr in _frames(eid):
            for p, side in ((fr.left, -1.0), (fr.right, 1.0)):
                ov = [o for i, o in fr.overlays if i == (0 if side < 0 else 1)]
                layer = render_expression_layer(p, ov, side)
                assert layer[~inside].max() == 0, eid


def _reserved_pixels(layer):
    flat = layer.reshape(-1, 3)
    hsv = np.array([colorsys.rgb_to_hsv(*px) for px in flat[flat.max(axis=1) > 0.2]])
    if len(hsv) == 0:
        return 0
    vivid = hsv[(hsv[:, 1] > 0.35) & (hsv[:, 2] > 0.2)]
    lo, hi = P.RESERVED_HUE_DEG
    h = vivid[:, 0] * 360
    return int(((h >= lo) & (h <= hi)).sum())


def test_palette_avoids_reserved_cyan():
    lo, hi = P.RESERVED_HUE_DEG
    for name in dir(P):
        v = getattr(P, name)
        if isinstance(v, tuple) and len(v) == 3 and all(isinstance(c, float) for c in v):
            s = colorsys.rgb_to_hsv(*v)[1]
            if s > 0.2:
                assert not (lo <= P.hue_deg(v) <= hi), name


@pytest.mark.parametrize("eid", list(EXPRESSIONS))
def test_rendered_expression_never_uses_cyan(eid):
    for t, fr in _frames(eid):
        for p, idx, side in ((fr.left, 0, -1.0), (fr.right, 1, 1.0)):
            ov = [o for i, o in fr.overlays if i == idx]
            assert _reserved_pixels(render_expression_layer(p, ov, side)[::3, ::3]) == 0, (eid, t)


def test_deterministic():
    a = [render_frame(EyeAnimator("happy", seed=9).frame(t), DeviceState(True), t) for t in (0.2, 3.3)]
    b = [render_frame(EyeAnimator("happy", seed=9).frame(t), DeviceState(True), t) for t in (0.2, 3.3)]
    for (a0, a1), (b0, b1) in zip(a, b):
        assert np.array_equal(a0, b0) and np.array_equal(a1, b1)
