"""聽聲辨位轉頭（`track sound`）的目標決定：死區、平滑、舵機自噪音迴避、逾時回正。

純邏輯，時間由呼叫端傳入。輸入是感知來源送來的聲音方位（相對**身體正前方**，左為正，rad），
輸出是頭部 yaw 的目標；夾限與限速仍由仲裁器負責。數值都是初始值，待實機修訂。

- **死區**：新方位和目前目標差不到 `deadzone` 就不動，避免說話的人稍微晃動頭就跟著抖。
- **平滑**：要在 `window_s` 內有 `min_count` 筆方位、彼此分散不超過 `max_spread` 才採用，取環狀平均。
- **自噪音**：頭在動、或剛停下不到 `settle_s`，這段時間收到的方位全部丟掉（舵機的聲音會被麥克風當成聲源）。
- **回正**：`recenter_s` 沒有聽到任何（被採用的）聲音，目標回到 0。
- **超出範圍**：聲源在頭轉得到的範圍外，就轉到極限，並記下 `at_limit`。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SoundTrackConfig:
    deadzone: float = math.radians(8.0)
    window_s: float = 0.8
    min_count: int = 2
    max_spread: float = math.radians(25.0)
    min_confidence: float = 0.3
    #: 2026-11-26 實機：頭一動，舵機聲就被 XVF3800 當成語音；DOA 服務的 0.5 s 視窗在頭停下後還會送出轉動中的方位，所以要等超過它。
    settle_s: float = 1.0
    recenter_s: float = 8.0
    yaw_limit: float = 0.5  # 頭部 yaw 可用範圍（±rad）；core 會填仲裁器的實際範圍


def circular_mean(angles: list[float]) -> float:
    return math.atan2(sum(math.sin(a) for a in angles), sum(math.cos(a) for a in angles))


def angular_distance(a: float, b: float) -> float:
    return abs((a - b + math.pi) % (2 * math.pi) - math.pi)


@dataclass
class SoundTracker:
    cfg: SoundTrackConfig = field(default_factory=SoundTrackConfig)
    target: float = 0.0
    bearing: float | None = None  # 最後採用的聲源方位（夾限前）
    at_limit: bool = False
    heard_at: float = -math.inf
    ignored_self_noise: int = 0
    _recent: list[tuple[float, float]] = field(default_factory=list)  # (收到時間, 方位)
    _last_obs_time: float = -math.inf
    _moving_until: float = -math.inf

    def reset(self, now: float, yaw: float = 0.0) -> None:
        self.target, self.bearing, self.at_limit = yaw, None, False
        self.heard_at = now
        self._recent.clear()

    def update(self, obs, now: float, head_moving: bool) -> tuple[float, str | None]:
        """餵最新的觀測（沒有就 None）。回傳（頭部 yaw 目標, 這一圈發生的事）。

        事件：`"turn"`（採用新方位）、`"recenter"`（太久沒聲音，回正）、None。
        """
        cfg = self.cfg
        if head_moving:
            self._moving_until = now + cfg.settle_s
        fresh = obs is not None and obs.received > self._last_obs_time
        if fresh:
            self._last_obs_time = obs.received
            if now < self._moving_until:
                self.ignored_self_noise += 1  # 頭在動或剛停：可能是舵機的聲音
                self._recent.clear()
            elif obs.confidence >= cfg.min_confidence:
                self._recent.append((obs.received, obs.yaw))
        self._recent = [(t, a) for t, a in self._recent if now - t <= cfg.window_s]

        if len(self._recent) >= cfg.min_count:
            angles = [a for _, a in self._recent]
            mean = circular_mean(angles)
            if max(angular_distance(a, mean) for a in angles) <= cfg.max_spread:
                self.heard_at = now
                wanted = max(-cfg.yaw_limit, min(cfg.yaw_limit, mean))
                if abs(wanted - self.target) > cfg.deadzone:
                    self.target, self.bearing = wanted, mean
                    self.at_limit = abs(mean) > cfg.yaw_limit + 1e-9
                    self._recent.clear()
                    return self.target, "turn"
        if now - self.heard_at > cfg.recenter_s and (self.target != 0.0 or self.bearing is not None):
            self.target, self.bearing, self.at_limit = 0.0, None, False
            return self.target, "recenter"
        return self.target, None
