"""表情的使用規則（誠實規則寫成程式，見 `docs/eye_expressions.md` §6）。"""

from __future__ import annotations

from .expressions import EXPRESSIONS
from .status import DeviceState

# Nous（透過之後的 app.duck.express）可以叫的表情：社交回應，不代表鴨子的實際狀態
NOUS_ALLOWED: frozenset[str] = frozenset(
    {
        "neutral",
        "happy",
        "joy",
        "love",
        "sad",
        "sorry",
        "grumpy",
        "surprised",
        "curious",
        "confused",
        "thinking",
        "proud",
        "greeting",
        "wink",
        "sleepy",
    }
)

# 只能由鴨子本機依真實狀態觸發：代表電量、安全、收音、播音、導航、鏡頭等實際狀態，Nous 叫不出來
LOCAL_ONLY: frozenset[str] = frozenset(EXPRESSIONS) - NOUS_ALLOWED


def nous_can_request(expression: str) -> bool:
    return expression in NOUS_ALLOWED


def resting_expression(device: DeviceState, charging: bool) -> str:
    """休息時（待在充電座、夜間）的表情。

    鏡頭在串流時**不顯示閉眼睡著**：閉眼會讓人以為鴨子沒在看，但鏡頭其實開著（ADR-0007 §2.2）。
    """
    if device.camera_streaming:
        return "sleepy" if device.night else ("charging" if charging else "neutral")
    return "sleeping" if device.night else ("charging" if charging else "sleepy")
