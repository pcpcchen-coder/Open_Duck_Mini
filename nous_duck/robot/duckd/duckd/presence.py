"""`presence` 編排：Nous 語音工作階段的狀態 → 眼睛表情＋頭部目標。

對應 `docs/companion/README.md` §4 的表。天線、聲音兩欄沒有硬體／不歸 duckd，這裡不做也不假裝。
只由**真實事件**驅動：`speech_level` 沒有更新就當作沒在出聲，不會自己演。
角度都很小（最大 0.25 rad），時間函式的角速度都低於 30°/s；仲裁器仍會夾限與限速。
數值是初始值，使用者看過實機後再調。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

PRESENCE_STATES = ("idle", "wake", "listening", "thinking", "speaking", "working", "error", "sleeping")

#: presence → 眼睛表情（duck_eyes 的代號；這是鴨子本機依真實工作階段狀態選的，不是 Nous 指定的）
EXPRESSION = {
    "idle": "neutral",
    "wake": "surprised",
    "listening": "listening",
    "thinking": "thinking",
    "speaking": "speaking",
    "working": "focused",
    "error": "confused",
    "sleeping": "sleeping",  # 鏡頭開著時改成不閉眼（duck_eyes.policy.resting_expression）
}

SPEECH_LEVEL_STALE_S = 0.6  # 這麼久沒有新的 speech_level 就當 0
SPEECH_BOB_HZ = 1.5
SPEECH_BOB_RAD = 0.05
ERROR_SHAKE_S = 1.6
ERROR_SHAKE_RAD = 0.12
THINK_SWAY_S = 4.0
THINK_SWAY_RAD = 0.10

ZERO = {"neck_pitch": 0.0, "head_pitch": 0.0, "head_yaw": 0.0, "head_roll": 0.0}


@dataclass
class PresenceState:
    state: str = "idle"
    since: float = 0.0
    speech_level: float = 0.0
    speech_at: float = -math.inf

    def set(self, state: str, speech_level: float | None, now: float) -> None:
        if state != self.state:
            self.state, self.since = state, now
        if speech_level is not None:
            self.speech_level, self.speech_at = float(speech_level), now
        elif state != "speaking":
            self.speech_level = 0.0

    def level(self, now: float) -> float:
        if self.state != "speaking" or now - self.speech_at > SPEECH_LEVEL_STALE_S:
            return 0.0
        return self.speech_level


def head_target(p: PresenceState, now: float, *, amplitude: float = 1.0, motion: bool = True, speaking_bob: bool = True) -> dict[str, float]:
    """這個 presence 狀態在此刻的頭部目標（rad；head_pitch 正值＝抬頭、head_yaw 正值＝往左）。

    `amplitude`（0～1，只能調小）、`motion`、`speaking_bob` 來自鴨子設定（ADR-0019）；關掉的部分頭回正。
    """
    t = max(0.0, now - p.since)
    out = dict(ZERO)
    if p.state == "speaking":
        if not speaking_bob:
            return out
    elif not motion:
        return out
    s = p.state
    if s == "wake":
        out["head_pitch"] = 0.10  # 抬頭（沒有聲源方向可轉：麥克風陣列還沒裝）
    elif s == "listening":
        out["head_roll"] = 0.12  # 微微歪頭
    elif s == "thinking":
        out["head_yaw"] = THINK_SWAY_RAD * math.sin(2 * math.pi * t / THINK_SWAY_S)
    elif s == "speaking":
        level = p.level(now)
        out["head_pitch"] = -SPEECH_BOB_RAD * level * (0.5 - 0.5 * math.cos(2 * math.pi * SPEECH_BOB_HZ * t))
    elif s == "error":
        if t < ERROR_SHAKE_S:  # 小幅搖頭一次
            out["head_yaw"] = ERROR_SHAKE_RAD * math.sin(2 * math.pi * t / ERROR_SHAKE_S)
    elif s == "sleeping":
        out["head_pitch"] = -0.25  # 低頭
    scale = min(1.0, max(0.0, amplitude))
    return {n: v * scale for n, v in out.items()}
