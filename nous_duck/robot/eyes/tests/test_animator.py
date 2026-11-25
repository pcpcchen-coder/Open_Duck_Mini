"""動畫：眨眼、注視、過場、動作型表情、音效觸發、不假裝。"""

from duck_eyes import EXPRESSIONS, EyeAnimator, Inputs
from duck_eyes.animator import BLINK_S, blink_closure


def test_blink_curve():
    assert blink_closure(-0.01) == 0 and blink_closure(BLINK_S + 0.01) == 0
    assert blink_closure(0.07) == 1.0


def test_auto_blink_happens_within_interval():
    anim = EyeAnimator("neutral", seed=1)
    lo, hi = EXPRESSIONS["neutral"].blink
    closed = [t / 100 for t in range(0, int((hi + 1) * 100)) if anim.frame(t / 100).left.upper > 0.95]
    assert closed and closed[0] <= hi + BLINK_S


def test_no_blink_for_closed_eye_expressions():
    for eid in ("sleeping", "joy", "dizzy"):
        anim = EyeAnimator(eid, seed=2)
        assert all(anim.frame(t / 10).left.upper == EXPRESSIONS[eid].left.upper for t in range(0, 200))


def test_gaze_follows_real_target_only():
    anim = EyeAnimator("neutral", seed=3)
    fr = anim.frame(1.0, Inputs(gaze=(0.6, -0.3)))
    assert (fr.left.look_x, fr.left.look_y) == (0.6, -0.3)
    # 思考中不跟著看（眼睛往右上想事情）
    anim = EyeAnimator("thinking", seed=3)
    fr = anim.frame(1.0, Inputs(gaze=(-0.9, 0.9)))
    assert fr.left.look_x > 0.3 and fr.left.look_y < -0.3


def test_wander_is_small_without_target():
    anim = EyeAnimator("neutral", seed=4)
    for k in range(400):
        fr = anim.frame(k / 20)
        assert abs(fr.left.look_x) <= 0.18 + 1e-6 and abs(fr.left.look_y) <= 0.12 + 1e-6


def test_speaking_does_not_fake_lipsync():
    anim = EyeAnimator("speaking", seed=5)
    anim._next_blink = float("inf")
    vals = {(anim.frame(t / 10).left.brightness, anim.frame(t / 10).left.pupil_r) for t in range(5, 60)}
    assert vals == {(1.0, EXPRESSIONS["speaking"].left.pupil_r)}
    loud = anim.frame(7.0, Inputs(audio_level=1.0)).left
    assert loud.brightness > 1.0 and loud.pupil_r < EXPRESSIONS["speaking"].left.pupil_r


def test_low_battery_uses_real_level_when_given():
    anim = EyeAnimator("low_battery", seed=6)
    ov = [o for _, o in anim.frame(1.0, Inputs(battery=0.07)).overlays if o.kind == "battery"]
    assert ov and ov[0].level == 0.07


def test_wink_is_temporary():
    anim = EyeAnimator("happy", seed=7)
    anim.set_expression("wink", 1.0)
    assert anim.frame(1.2).right.shape == "arc_up"
    fr = anim.frame(1.0 + EXPRESSIONS["wink"].action_s + 0.05)
    assert fr.expression == "happy" and fr.right.shape == "iris"


def test_sound_fires_once_on_change():
    anim = EyeAnimator("neutral", seed=8)
    anim.frame(0.0)
    anim.set_expression("happy", 1.0)
    sounds = [anim.frame(1.0 + k / 30).sound for k in range(30)]
    assert sounds[0] == "quack_happy" and all(s is None for s in sounds[1:])


def test_shape_change_dips_brightness():
    anim = EyeAnimator("neutral", seed=9)
    anim._next_blink = float("inf")
    anim.set_expression("love", 2.0)
    mid = anim.frame(2.0 + 0.11)
    assert mid.left.brightness < 0.2
    assert anim.frame(2.5).left.shape == "heart"
