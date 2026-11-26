"""表情庫：每個表情的兩眼參數、動畫、眨眼節奏與搭配的音效代號。

表情的用途、使用情境與音效規格寫在 `nous_duck/docs/eye_expressions.md`；測試會檢查兩邊一致。
音效只是**代號**，聲音檔還沒做（規劃中，見文件 §5）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from .params import (
    EMBER_IN,
    EMBER_RIM,
    GOLD,
    LAVENDER_IN,
    LAVENDER_RIM,
    PALE_IN,
    PALE_RIM,
    ROSE_IN,
    ROSE_RIM,
    SUN_IN,
    SUN_RIM,
    AMBER_IN,
    AMBER_RIM,
    EyeParams,
    with_,
)
from .render import Overlay


@dataclass(frozen=True)
class Inputs:
    """來自真實感測的輸入；沒有就是 None，表情不會假裝有。"""

    gaze: tuple[float, float] | None = None  # 看向的目標（人臉偵測、聲源方向換算），−1～1
    audio_level: float | None = None  # 鴨子正在播放的語音音量 0～1（說話時虹膜跟著亮）
    battery: float | None = None  # 電量 0～1


Animate = Callable[[EyeParams, EyeParams, list, float, Inputs], tuple[EyeParams, EyeParams, list]]


@dataclass(frozen=True)
class Expression:
    id: str
    name_zh: str
    left: EyeParams  # 畫面左
    right: EyeParams  # 畫面右
    blink: tuple[float, float] | None = (2.5, 6.0)  # 自動眨眼間隔（秒）；None＝不眨
    wander: bool = True  # 沒有注視目標時，眼睛自己小幅飄動
    follow_gaze: bool = True  # 有真實注視目標時看過去
    animate: Animate | None = None
    sound: str | None = None  # 進入這個表情時播的音效代號
    action_s: float | None = None  # 動作型（例如眨單眼）：播完自動回到前一個表情
    preview_t: float = 1.0  # 預覽圖取樣時間


SOUND_CUES: dict[str, str] = {
    "boot_chirp": "開機啾啾",
    "quack_hello": "打招呼鴨叫",
    "quack_happy": "開心兩聲鴨叫",
    "giggle_trill": "咯咯笑顫音",
    "coo_love": "撒嬌咕嚕",
    "sad_slide": "下滑嗚",
    "sorry_hum": "低聲嗯…",
    "grumble": "嘟囔",
    "surprise_up": "上揚「喔！」",
    "scared_wobble": "顫抖嗚",
    "yawn": "打哈欠",
    "curious_chirp": "好奇「啾？」",
    "confused_hm": "疑問「嗯？」",
    "listen_on": "開始聽",
    "listen_off": "聽完了",
    "dizzy_wobble": "暈眩搖擺音",
    "proud_fanfare": "小號角",
    "help_call": "求救三聲",
    "battery_low": "沒電下降兩音",
    "charge_start": "充電上升琶音",
    "wink_click": "眨眼「叮」",
}


def _sin(t: float, period: float) -> float:
    return math.sin(2 * math.pi * t / period)


# ---------------------------------------------------------------- 動畫


def _anim_love(L, R, ov, t, inp):
    s = 1.0 + 0.08 * max(0.0, _sin(t, 0.62))
    return with_(L, shape_scale=s), with_(R, shape_scale=s), ov


def _anim_sad(L, R, ov, t, inp):
    return L, R, ov + [(1, Overlay("tear", phase=t / 2.4))]


def _anim_scared(L, R, ov, t, inp):
    jx = 2.2 * math.sin(t * 61.0)
    jy = 1.6 * math.sin(t * 47.0 + 1.0)
    return with_(L, off_x=jx, off_y=jy), with_(R, off_x=jx, off_y=jy), ov


def _anim_sleepy(L, R, ov, t, inp):
    u = 0.55 + 0.13 * (0.5 - 0.5 * math.cos(2 * math.pi * t / 3.4))
    return with_(L, upper=u), with_(R, upper=u + 0.03), ov


def _anim_sleeping(L, R, ov, t, inp):
    b = 0.42 + 0.08 * _sin(t, 4.0)
    return with_(L, brightness=b), with_(R, brightness=b), ov + [(1, Overlay("zzz", phase=t / 3.0))]


def _anim_confused(L, R, ov, t, inp):
    return L, R, ov + [(1, Overlay("question", phase=t / 1.6))]


def _anim_thinking(L, R, ov, t, inp):
    dx = 0.08 * _sin(t, 2.7)
    return (
        with_(L, look_x=L.look_x + dx),
        with_(R, look_x=R.look_x + dx),
        ov + [(1, Overlay("dots", phase=t / 1.2))],
    )


def _anim_listening(L, R, ov, t, inp):
    b = 0.94 + 0.06 * _sin(t, 2.2)
    return with_(L, brightness=b), with_(R, brightness=b), ov


def _anim_speaking(L, R, ov, t, inp):
    if inp.audio_level is None:  # 沒有真的音量就不動，不假裝對嘴
        return L, R, ov
    lv = min(max(inp.audio_level, 0.0), 1.0)
    b = 0.85 + 0.25 * lv
    pr = L.pupil_r * (1.0 - 0.12 * lv)
    return with_(L, brightness=b, pupil_r=pr), with_(R, brightness=b, pupil_r=pr), ov


def _anim_dizzy(L, R, ov, t, inp):
    return with_(L, shape_rot=t * 0.8), with_(R, shape_rot=-t * 0.8), ov


def _anim_proud(L, R, ov, t, inp):
    rot = 6 * _sin(t, 1.8)
    s = 1.0 + 0.04 * _sin(t, 0.9)
    return with_(L, shape_rot=rot, shape_scale=s), with_(R, shape_rot=-rot, shape_scale=s), ov + [(1, Overlay("sparkle", phase=t / 1.5))]


def _anim_worried(L, R, ov, t, inp):
    return L, R, ov + [(0, Overlay("sweat", phase=t / 2.0))]


def _anim_low_battery(L, R, ov, t, inp):
    lvl = 0.12 if inp.battery is None else inp.battery
    return L, R, ov + [(1, Overlay("battery", phase=t / 1.0, level=lvl))]


def _anim_charging(L, R, ov, t, inp):
    return L, R, ov + [(1, Overlay("bolt", phase=t / 1.6))]


def _anim_happy(L, R, ov, t, inp):
    by = -2.5 * abs(_sin(t, 1.4))
    return with_(L, off_y=by), with_(R, off_y=by), ov


def _anim_joy(L, R, ov, t, inp):
    by = -5.0 * abs(_sin(t, 0.5))
    return with_(L, off_y=by), with_(R, off_y=by), ov + [(1, Overlay("sparkle", phase=t / 1.2))]


def _anim_waking(L, R, ov, t, inp):
    k = min(t / 1.4, 1.0)
    u = 1.0 - 0.72 * k
    b = 0.35 + 0.65 * k
    return with_(L, upper=u, brightness=b), with_(R, upper=u, brightness=b), ov


def _anim_curious(L, R, ov, t, inp):
    dx = 0.12 * _sin(t, 3.1)
    return with_(L, look_x=L.look_x + dx), with_(R, look_x=R.look_x + dx), ov


# ---------------------------------------------------------------- 表情庫

N = EyeParams()


def _pair(p: EyeParams, **right_overrides) -> tuple[EyeParams, EyeParams]:
    return p, (with_(p, **right_overrides) if right_overrides else p)


def _build() -> dict[str, Expression]:
    E: list[Expression] = []
    add = E.append

    add(Expression("neutral", "平常", *_pair(N)))
    add(Expression("waking", "剛醒", *_pair(with_(N, upper=0.28)), blink=(3.0, 5.0), animate=_anim_waking, sound="boot_chirp", preview_t=0.8))
    happy = with_(N, color_in=SUN_IN, color_rim=SUN_RIM, upper=0.06, lower=0.36, lower_bow=-44, pupil_r=32)
    add(Expression("happy", "開心", *_pair(happy), animate=_anim_happy, sound="quack_happy"))
    joy = with_(N, shape="arc_up", color_in=SUN_IN, color_rim=SUN_RIM)
    add(Expression("joy", "大笑", *_pair(joy), blink=None, wander=False, follow_gaze=False, animate=_anim_joy, sound="giggle_trill", preview_t=0.3))
    love = with_(N, shape="heart", color_in=ROSE_IN, color_rim=ROSE_RIM)
    add(Expression("love", "喜歡", *_pair(love), blink=(3.5, 7.0), follow_gaze=False, animate=_anim_love, sound="coo_love", preview_t=0.15))
    sad = with_(N, color_in=LAVENDER_IN, color_rim=LAVENDER_RIM, look_y=0.30, upper=0.42, upper_tilt=-0.50, upper_bow=-2, lower=0.08)
    add(Expression("sad", "難過", *_pair(sad), blink=(3.0, 6.0), wander=False, animate=_anim_sad, sound="sad_slide", preview_t=1.0))
    sorry = with_(N, look_y=0.55, look_x=-0.2, upper=0.46, upper_tilt=-0.32, upper_bow=-2, lower=0.10, brightness=0.85)
    add(Expression("sorry", "抱歉", *_pair(sorry), blink=(2.5, 5.0), wander=False, follow_gaze=False, sound="sorry_hum"))
    grumpy = with_(N, color_in=EMBER_IN, color_rim=EMBER_RIM, upper=0.42, upper_tilt=0.40, upper_bow=0, lower=0.20, lower_bow=-6, pupil_r=26, look_y=0.08)
    add(Expression("grumpy", "不高興", *_pair(grumpy), blink=(3.0, 6.0), sound="grumble"))
    surprised = with_(N, upper=0.0, lower=0.0, iris_r=80, pupil_r=19, upper_bow=-20)
    add(Expression("surprised", "驚訝", *_pair(surprised), blink=(4.0, 8.0), wander=False, sound="surprise_up"))
    scared = with_(N, color_in=PALE_IN, color_rim=PALE_RIM, iris_r=66, pupil_r=14, upper=0.06, upper_tilt=-0.22, lower=0.10, look_y=-0.1)
    add(Expression("scared", "害怕", *_pair(scared), blink=(1.2, 2.5), wander=False, animate=_anim_scared, sound="scared_wobble"))
    sleepy = with_(N, upper=0.55, upper_bow=4, lower=0.14, brightness=0.75, look_y=0.2)
    add(Expression("sleepy", "想睡", *_pair(sleepy), blink=(1.5, 3.0), wander=False, animate=_anim_sleepy, sound="yawn", preview_t=0.2))
    sleeping = with_(N, shape="arc_down", brightness=0.45)
    add(Expression("sleeping", "睡著", *_pair(sleeping), blink=None, wander=False, follow_gaze=False, animate=_anim_sleeping, sound=None, preview_t=0.5))
    cl = with_(N, iris_r=80, pupil_r=35, upper=0.0, look_x=0.25, upper_bow=-20)
    cr = with_(N, iris_r=70, pupil_r=32, upper=0.26, upper_tilt=0.12, look_x=0.25)
    add(Expression("curious", "好奇", cl, cr, animate=_anim_curious, sound="curious_chirp"))
    fl = with_(N, upper=0.30, upper_tilt=0.22, look_x=-0.35, look_y=0.35)
    fr = with_(N, upper=0.04, upper_tilt=-0.28, look_x=-0.35, look_y=0.35, upper_bow=-20)
    add(Expression("confused", "困惑", fl, fr, wander=False, follow_gaze=False, animate=_anim_confused, sound="confused_hm", preview_t=0.4))
    think = with_(N, look_x=0.45, look_y=-0.50, upper=0.16)
    add(Expression("thinking", "思考中", *_pair(think), blink=(3.0, 6.0), wander=False, follow_gaze=False, animate=_anim_thinking, sound=None, preview_t=0.4))
    listen = with_(N, upper=0.04, lower=0.03, pupil_r=34, upper_bow=-18)
    add(Expression("listening", "聆聽", *_pair(listen), blink=(3.0, 6.0), wander=False, animate=_anim_listening, sound="listen_on"))
    add(Expression("speaking", "說話", *_pair(with_(N, upper=0.10)), blink=(2.5, 5.0), animate=_anim_speaking, sound=None))
    focused = with_(N, upper=0.38, upper_bow=6, lower=0.22, lower_bow=-4, pupil_r=26, look_y=0.15)
    add(Expression("focused", "專心", *_pair(focused), blink=(3.0, 7.0), wander=False, sound=None))
    dizzy = with_(N, shape="spiral", color_in=AMBER_IN, color_rim=AMBER_RIM)
    add(Expression("dizzy", "頭暈", *_pair(dizzy), blink=None, wander=False, follow_gaze=False, animate=_anim_dizzy, sound="dizzy_wobble", preview_t=0.3))
    proud = with_(N, shape="star", color_in=GOLD, color_rim=SUN_RIM)
    add(Expression("proud", "得意", *_pair(proud), blink=None, wander=False, follow_gaze=False, animate=_anim_proud, sound="proud_fanfare", preview_t=0.4))
    worried = with_(N, upper=0.32, upper_tilt=-0.48, upper_bow=-6, lower=0.10, look_y=-0.20, pupil_r=35)
    add(Expression("worried", "需要幫忙", *_pair(worried), blink=(2.0, 4.0), wander=False, animate=_anim_worried, sound="help_call", preview_t=0.6))
    lowb = with_(N, upper=0.50, upper_bow=0, lower=0.42, lower_bow=0, brightness=0.6, look_y=-0.1)
    add(Expression("low_battery", "沒電了", *_pair(lowb), blink=(2.0, 4.0), wander=False, animate=_anim_low_battery, sound="battery_low", preview_t=0.3))
    charging = with_(N, upper=0.30, lower=0.36, lower_bow=-34, look_y=-0.15, brightness=0.85)
    add(Expression("charging", "充電中", *_pair(charging), blink=(3.0, 7.0), animate=_anim_charging, sound="charge_start", preview_t=0.8))
    add(Expression("greeting", "打招呼", *_pair(with_(happy, lower=0.30)), animate=_anim_happy, sound="quack_hello"))
    add(Expression("wink", "眨單眼", happy, with_(joy, shape_scale=0.85), blink=None, wander=False, follow_gaze=False, sound="wink_click", action_s=0.7))
    return {e.id: e for e in E}


EXPRESSIONS: dict[str, Expression] = _build()
