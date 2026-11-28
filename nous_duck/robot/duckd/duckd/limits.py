"""安全上限與時間常數。

**全部是初始值，待模擬與實機量測後修訂**（ADR-0009 §2.5；定案要有 `docs/validation/` 的紀錄）。
這個檔案取代原本規劃的 `robot/config/` safety 上限（見 `duckd/README.md` 的目錄對應）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

HEAD_JOINTS: tuple[str, ...] = ("neck_pitch", "head_pitch", "head_yaw", "head_roll")
# 上游 Open_Duck_Mini_Runtime（376de65）rustypot_position_hwi.py 的 ID
HEAD_SERVO_IDS: dict[str, int] = {"neck_pitch": 30, "head_pitch": 31, "head_yaw": 32, "head_roll": 33}
LEG_SERVO_IDS: frozenset[int] = frozenset({10, 11, 12, 13, 14, 20, 21, 22, 23, 24})
LEG_JOINTS: tuple[str, ...] = (
    "left_hip_yaw", "left_hip_roll", "left_hip_pitch", "left_knee", "left_ankle",
    "right_hip_yaw", "right_hip_roll", "right_hip_pitch", "right_knee", "right_ankle",
)
LEG_SERVO_ID_BY_NAME: dict[str, int] = {
    "right_hip_yaw": 10, "right_hip_roll": 11, "right_hip_pitch": 12, "right_knee": 13, "right_ankle": 14,
    "left_hip_yaw": 20, "left_hip_roll": 21, "left_hip_pitch": 22, "left_knee": 23, "left_ankle": 24,
}
# 上游 robot.xml 的腿部關節範圍（rad）。tests/test_limits.py 會對照上游檔案（唯讀）。
ROBOT_XML_LEG_RANGE: dict[str, tuple[float, float]] = {
    "left_hip_yaw": (-0.523599, 0.523599),
    "left_hip_roll": (-0.436332, 0.436332),
    "left_hip_pitch": (-1.22173, 0.523599),
    "left_knee": (-1.5708, 1.5708),
    "left_ankle": (-1.5708, 1.5708),
    "right_hip_yaw": (-0.523599, 0.523599),
    "right_hip_roll": (-0.436332, 0.436332),
    "right_hip_pitch": (-0.523599, 1.22173),
    "right_knee": (-1.5708, 1.5708),
    "right_ankle": (-1.5708, 1.5708),
}

# 上游 robot.xml 的頭頸關節範圍（rad）。tests/test_limits.py 會對照上游檔案（唯讀）。
ROBOT_XML_HEAD_RANGE: dict[str, tuple[float, float]] = {
    "neck_pitch": (-0.349066, 1.13446),
    "head_pitch": (-0.785398, 0.785398),
    "head_yaw": (-2.79253, 2.79253),
    "head_roll": (-0.523599, 0.523599),
}
# ADR-0009 §2.5 的頭部範圍（上游手把範圍）
ADR_HEAD_RANGE: dict[str, tuple[float, float]] = {
    "neck_pitch": (-0.34, 1.1),
    "head_pitch": (-0.78, 0.3),
    "head_yaw": (-0.5, 0.5),
    "head_roll": (-0.5, 0.5),
}
ROBOT_XML_MARGIN_RAD = math.radians(2.0)  # 跟舵機控制台一樣往內縮 2°


def default_head_range() -> dict[str, tuple[float, float]]:
    """ADR-0009 §2.5 與（robot.xml 內縮 2°）的交集。"""
    out = {}
    for name in HEAD_JOINTS:
        a_lo, a_hi = ADR_HEAD_RANGE[name]
        x_lo, x_hi = ROBOT_XML_HEAD_RANGE[name]
        out[name] = (max(a_lo, x_lo + ROBOT_XML_MARGIN_RAD), min(a_hi, x_hi - ROBOT_XML_MARGIN_RAD))
    return out


@dataclass(frozen=True)
class Limits:
    """仲裁器用的上限。初始值、待實機修訂。"""

    head_range: dict[str, tuple[float, float]] = field(default_factory=default_head_range)
    #: 頭部角速度上限（rad/s）。30°/s 是 2026-11-25 夜間無人看顧的規定；ADR-0015 §2.3 要求的模擬量測還沒做。
    head_max_speed: float = math.radians(30.0)
    #: 頭部角速度的硬上限：設定檔或命令列不能超過（舵機控制台的最高檔）。
    head_speed_hard_cap: float = math.radians(90.0)
    #: 可選：每軸只能在「接手時的位置」± 這個角度內（rad）。None＝不限制。
    head_window: float | None = None
    #: look 的 duration_s 上限（協定也是 10）
    look_duration_max_s: float = 10.0

    # 速度：先上游範圍，再室內上限（vx, vy, yaw_rate）
    vel_upstream: tuple[float, float, float] = (0.15, 0.2, 1.0)
    vel_indoor: tuple[float, float, float] = (0.10, 0.10, 0.6)
    #: 每圈（20 ms）最多變化
    vel_step: tuple[float, float, float] = (0.01, 0.01, 0.05)
    walk_duration_max_s: float = 3.0

    lease_s: float = 1.5  # 連續這麼久沒有 heartbeat 就視為斷線
    stop_settle_s: float = 0.3  # 兩腳著地持續這麼久才暫停
    stop_timeout_s: float = 2.0  # 等不到兩腳著地就維持踏步並回報
    fall_tilt_deg: float = 45.0
    fall_hold_s: float = 0.2
    controller_takeover_s: float = 3.0

    def __post_init__(self) -> None:
        if not 0 < self.head_max_speed <= self.head_speed_hard_cap:
            raise ValueError("head_max_speed 超出硬上限")
        for name in HEAD_JOINTS:
            lo, hi = self.head_range[name]
            if not lo < hi:
                raise ValueError(f"{name} 的範圍不對")


# 身體健康門檻：沿用舵機控制台的暫定值（servo_console.controller），這裡是「拒絕新動作」的門檻。
TEMP_REFUSE_C = 55
VOLT_REFUSE_V = 6.6
