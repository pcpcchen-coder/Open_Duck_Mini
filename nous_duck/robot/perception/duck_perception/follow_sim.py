"""D3 的小模擬（**純運動學，不是步態模擬**）：差速（unicycle）身體＋有角速度上限的頭＋有視角限制的鏡頭。

身體會「完美」照速度指令移動：沒有步態、打滑、慣性、舵機延遲。只能用來檢查控制邏輯
（正負號、遲滯、停止條件、上限），不能用來預測實機走路的表現。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .camera import AR0144_HFOV_DEG
from .follow import FollowCommand, FollowController, FollowObservation


@dataclass
class KinematicWorld:
    x: float = 0.0
    y: float = 0.0
    theta: float = 0.0  # 身體朝向（世界座標，往左為正）
    head_yaw: float = 0.0
    person: tuple[float, float] = (2.0, 0.0)
    person_visible: bool = True
    hfov_rad: float = math.radians(AR0144_HFOV_DEG)
    max_sense_m: float = 3.5
    head_max_rate: float = 2.0  # rad/s
    #: 距離量測是否可用（False＝模擬「只有單眼、不知道距離」）。
    distance_available: bool = True
    path: list[tuple[float, float, float]] = field(default_factory=list)

    def range_bearing(self) -> tuple[float, float]:
        dx, dy = self.person[0] - self.x, self.person[1] - self.y
        b = math.atan2(dy, dx) - self.theta
        return math.hypot(dx, dy), math.atan2(math.sin(b), math.cos(b))

    def observe(self, t: float) -> FollowObservation | None:
        """鏡頭看到的目標（相對光軸）；不在視角內或太遠就沒有。"""
        if not self.person_visible:
            return None
        d, b = self.range_bearing()
        cam = b - self.head_yaw
        cam = math.atan2(math.sin(cam), math.cos(cam))
        if abs(cam) > self.hfov_rad / 2 or d > self.max_sense_m:
            return None
        return FollowObservation(t, cam, 0.0, d if self.distance_available else None, 0.9)

    def advance(self, cmd: FollowCommand, dt: float) -> None:
        self.theta += cmd.yaw_rate * dt
        self.x += cmd.vx * math.cos(self.theta) * dt
        self.y += cmd.vx * math.sin(self.theta) * dt
        step = self.head_max_rate * dt
        self.head_yaw += max(-step, min(step, cmd.head_yaw_target - self.head_yaw))
        self.path.append((self.x, self.y, self.theta))


def run(world: KinematicWorld, ctrl: FollowController, seconds: float, dt: float = 0.02, frame_every: int = 5,
        latency_cycles: int = 4, on_step=None, t0: float = 0.0) -> list[tuple[float, FollowCommand]]:
    """50 Hz 控制、10 Hz 觀測、觀測延遲 latency_cycles 個週期。回傳每個週期的（t, 指令）。"""
    out: list[tuple[float, FollowCommand]] = []
    pending: list[tuple[int, FollowObservation | None]] = []
    latest: FollowObservation | None = None
    for i in range(int(round(seconds / dt))):
        t = t0 + i * dt
        if on_step is not None:
            on_step(t, world)
        if i % frame_every == 0:
            pending.append((i + latency_cycles, world.observe(t)))
        while pending and pending[0][0] <= i:
            latest = pending.pop(0)[1]
        cmd = ctrl.step(t, latest, world.head_yaw)
        world.advance(cmd, dt)
        out.append((t, cmd))
    return out
