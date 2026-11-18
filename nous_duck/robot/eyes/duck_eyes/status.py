"""狀態環：照**實際裝置狀態**決定顏色與閃法（ADR-0006 §4.2、§4.2.1）。

狀態環畫在最上層，表情改不到它；輸入只有裝置狀態，沒有任何「表情指令」參數。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .params import RGB

CYAN: RGB = (0.00, 0.90, 1.00)  # 鏡頭開著（保留色）
GREEN: RGB = (0.24, 1.00, 0.43)
WARM_WHITE: RGB = (1.00, 0.86, 0.66)
RED: RGB = (1.00, 0.12, 0.10)
YELLOW: RGB = (1.00, 0.84, 0.00)

NIGHT_SCALE = 0.4  # 夜間亮度倍率
CAMERA_NIGHT_FLOOR = 0.55  # 夜間「鏡頭開著」的最低亮度：要看得出來
PRIVACY_FLASH_S = 0.4


@dataclass(frozen=True)
class DeviceState:
    """全部來自鴨子本機的真實狀態（鏡頭串流事件、實體開關 GPIO、對話工作階段、安全事件）。"""

    camera_streaming: bool
    privacy_switch_off: bool = False
    privacy_switch_changed_at: float | None = None  # 開關被關掉的時間（秒，同一個時鐘）
    conversation_active: bool = False
    needs_help: bool = False  # 跌倒、迷路、卡住
    night: bool = False


@dataclass(frozen=True)
class RingSpec:
    name: str
    color: RGB
    level: float  # 0～1

    @property
    def rgb(self) -> RGB:
        return tuple(c * self.level for c in self.color)


def ring_spec(s: DeviceState, t: float) -> RingSpec:
    if s.camera_streaming:
        # 最高優先：只要鏡頭在串流就一定是青色；即使開關狀態讀值矛盾也照樣顯示（寧可多提示）
        if s.needs_help:
            spec = RingSpec("camera_on+help", CYAN if (t % 1.0) < 0.5 else YELLOW, 1.0)
        else:
            spec = RingSpec("camera_on", CYAN, 1.0)
    elif s.privacy_switch_off:
        flashing = s.privacy_switch_changed_at is not None and 0 <= t - s.privacy_switch_changed_at < PRIVACY_FLASH_S
        spec = RingSpec("privacy_off", RED, 1.0 if flashing else 0.3)
    elif s.needs_help:
        spec = RingSpec("help", YELLOW, 1.0 if (t % 1.0) < 0.5 else 0.15)
    elif s.conversation_active:
        spec = RingSpec("conversation", GREEN, 0.35 + 0.65 * (0.5 - 0.5 * math.cos(2 * math.pi * t / 3.0)))
    else:
        spec = RingSpec("standby", WARM_WHITE, 0.25)

    if s.night:
        level = spec.level * NIGHT_SCALE
        if spec.color == CYAN:
            level = max(level, CAMERA_NIGHT_FLOOR)
        spec = RingSpec(spec.name, spec.color, level)
    return spec
