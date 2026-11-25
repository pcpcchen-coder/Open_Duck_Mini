"""D3 視覺連動走路：頭轉到底就轉身、讓身體面向人、靠近到指定距離停下。

輸入：人的方位（相對鏡頭光軸）與距離（可能未知）＋頭部目前相對身體的角度。
輸出：身體速度**請求**（vx、yaw_rate）與頭部目標角度。

這是 ADR-0007「跟著我來」F1（原地轉身跟著看，`FollowMode.FACE`）的基礎；`FollowMode.APPROACH`
多了「走近到指定距離」。之後由 A 線的 `track`（`body: true`）與 C 線的導航呼叫。

安全相關的行為（都在這裡先收緊；身體端的 safety 仍是最後一關，會再夾限）：

- **遺失目標就停**：沒有觀測、觀測太舊、信心太低 → vx＝0、yaw_rate＝0（立刻，不慢慢減）。
- **距離未知不前進**：只轉身面向，不走。
- **不後退**（預設）：人太近只回報 `too_close`，不倒退走（後面沒有鏡頭）。
- 還沒大致面向人之前不前進；速度與加速度有上限；到位後有遲滯，不會在門檻附近抖動。
- 不管障礙、落差、禁區：那是導航與 safety 的事，這個控制器**不能**單獨拿來讓鴨子走路。

所有數值都是設計初值，**未校準**；vx 上限 0.10 m/s 低於上游手把上限 0.15 m/s（未實測）。
驗證層級：單元測試＋純運動學小模擬（差速模型，**不是步態模擬**）。未實機。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class FollowMode(str, Enum):
    FACE = "face"  # 只原地轉身面向人（F1）
    APPROACH = "approach"  # 面向並走近到 target_distance_m


class FollowState(str, Enum):
    IDLE = "idle"  # 停用
    LOST = "lost"  # 沒有可用的觀測：停
    TURNING = "turning"  # 原地轉身面向人
    APPROACHING = "approaching"  # 往人走
    HOLDING = "holding"  # 已面向（且到位或不需前進）：站著


@dataclass(frozen=True)
class FollowObservation:
    """一次目標觀測（就是 UDP `face` 訊息的內容）。"""

    t: float  # 拍攝時間（秒）
    bearing_yaw: float  # 相對光軸，往左為正
    bearing_pitch: float  # 相對光軸，往上為正
    distance_m: float | None
    confidence: float = 1.0


@dataclass
class FollowConfig:
    target_distance_m: float = 1.0
    #: 距離誤差小於 stop 就停；停下後要超過 resume 才再走（遲滯）。
    distance_stop_m: float = 0.10
    distance_resume_m: float = 0.25
    #: 超過這個距離的量測不可信（雙目 3 m 以外誤差很大），當成未知。
    max_trusted_distance_m: float = 3.0
    #: 人比 target − too_close 還近：回報 too_close。
    too_close_margin_m: float = 0.3
    allow_backward: bool = False
    max_vx: float = 0.10
    k_distance: float = 0.5  # 1/s
    max_accel_vx: float = 0.2  # m/s²
    #: 身體方位（頭角＋相對光軸方位）超過 start 開始轉身，回到 stop 以內停（遲滯）。
    turn_start: float = 0.35
    turn_stop: float = 0.08
    k_yaw: float = 1.5  # 1/s
    max_yaw_rate: float = 0.5  # rad/s
    max_accel_yaw: float = 1.5  # rad/s²
    #: 身體方位在這之內才允許前進；前進時用比例轉向（沒有遲滯，死區 walk_steer_deadband）。
    walk_align: float = 0.25
    walk_steer_deadband: float = 0.03
    #: 觀測超過這個時間沒更新、或信心低於門檻 → 停。
    lost_after_s: float = 0.5
    min_confidence: float = 0.3
    head_yaw_limit: tuple[float, float] = (-0.5, 0.5)
    head_pitch_limit: tuple[float, float] = (-0.4, 0.9)


@dataclass(frozen=True)
class FollowCommand:
    vx: float  # m/s，往前為正
    yaw_rate: float  # rad/s，往左為正
    head_yaw_target: float  # 相對身體
    head_pitch_target: float
    state: FollowState
    #: 為什麼沒有前進或停下：None、"lost"、"stale"、"low_confidence"、"distance_unknown"、
    #: "too_close"、"not_aligned"、"at_distance"、"face_mode"。
    reason: str | None = None


def _clip(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _slew(current: float, wanted: float, max_delta: float) -> float:
    """限制加速：速度大小往上最多 max_delta；往 0 的方向不限制（要停就停）。"""
    if abs(wanted) <= abs(current) and (wanted == 0.0 or wanted * current > 0):
        return wanted
    return current + _clip(wanted - current, -max_delta, max_delta)


class FollowController:
    def __init__(self, config: FollowConfig | None = None, mode: FollowMode = FollowMode.FACE) -> None:
        self.cfg = config or FollowConfig()
        self.mode = mode
        self._active = False
        self._vx = 0.0
        self._yaw_rate = 0.0
        self._turning = False
        self._walking = False
        self._last_t: float | None = None
        self._head_target = (0.0, 0.0)
        #: （t, 頭部偏航, 頭部俯仰, 累積的身體轉角）：觀測有延遲，要和拍攝當下的頭角相加
        self._history: list[tuple[float, float, float, float]] = []
        self._body_yaw = 0.0

    def _pose_at(self, t: float) -> tuple[float, float, float]:
        best = self._history[-1]
        for h in reversed(self._history):
            best = h
            if h[0] <= t:
                break
        return best[1], best[2], best[3]

    def activate(self, mode: FollowMode | None = None) -> None:
        if mode is not None:
            self.mode = mode
        self._active = True

    def deactivate(self) -> None:
        self._active = False
        self._stop()

    def _stop(self) -> None:
        self._vx = 0.0
        self._yaw_rate = 0.0
        self._turning = False
        self._walking = False

    def step(self, t: float, obs: FollowObservation | None, head_yaw: float, head_pitch: float = 0.0) -> FollowCommand:
        """推進一個控制週期。`head_yaw`／`head_pitch` 是頭部**目前**相對身體的角度（回讀或指令值）。"""
        cfg = self.cfg
        dt = 0.0 if self._last_t is None else max(0.0, t - self._last_t)
        self._last_t = t
        # 身體轉角用自己上一個週期的角速度指令積分（沒有 IMU 回授時的近似）
        self._body_yaw += self._yaw_rate * dt
        self._history.append((t, head_yaw, head_pitch, self._body_yaw))
        if len(self._history) > 200:
            del self._history[:100]
        if not self._active:
            self._stop()
            return FollowCommand(0.0, 0.0, 0.0, 0.0, FollowState.IDLE)

        reason = None
        if obs is None:
            reason = "lost"
        elif t - obs.t > cfg.lost_after_s:
            reason = "stale"
        elif obs.confidence < cfg.min_confidence:
            reason = "low_confidence"
        if reason is not None:
            self._stop()  # 遺失：立刻停；頭停在原處（找人由 look_at 負責）
            return FollowCommand(0.0, 0.0, self._head_target[0], self._head_target[1], FollowState.LOST, reason)
        assert obs is not None

        # 人相對身體的方位 ＝ **拍攝當下**的頭角 ＋ 相對光軸的方位（小角度相加；與 look_at 相同的近似），
        # 再扣掉拍攝之後身體已經轉過的角度。直接用「現在」的頭角會在頭轉動時算錯而來回擺盪。
        head_yaw_cap, head_pitch_cap, body_yaw_cap = self._pose_at(obs.t)
        body_bearing = head_yaw_cap + obs.bearing_yaw - (self._body_yaw - body_yaw_cap)
        pitch = head_pitch_cap + obs.bearing_pitch
        self._head_target = (_clip(body_bearing, *cfg.head_yaw_limit), _clip(pitch, *cfg.head_pitch_limit))

        # ---- 前進 ----
        dist = obs.distance_m
        if dist is not None and not (0.0 < dist <= cfg.max_trusted_distance_m):
            dist = None
        vx_wanted = 0.0
        if self.mode is FollowMode.FACE:
            self._walking = False
            reason = "face_mode"
        elif dist is None:
            self._walking = False
            reason = "distance_unknown"
        else:
            err = dist - cfg.target_distance_m
            if err > cfg.distance_resume_m:
                self._walking = True
            elif err < cfg.distance_stop_m:
                self._walking = False
            if err < -cfg.too_close_margin_m:
                reason = "too_close"
                if cfg.allow_backward:
                    vx_wanted = _clip(cfg.k_distance * err, -cfg.max_vx, 0.0)
            elif not self._walking:
                reason = "at_distance"
            elif abs(body_bearing) > cfg.walk_align:
                reason = "not_aligned"
            else:
                vx_wanted = _clip(cfg.k_distance * err, 0.0, cfg.max_vx)

        # ---- 轉身 ----
        if abs(body_bearing) > cfg.turn_start:
            self._turning = True
        elif abs(body_bearing) < cfg.turn_stop:
            self._turning = False
        yaw_wanted = 0.0
        if self._turning or (vx_wanted != 0.0 and abs(body_bearing) > cfg.walk_steer_deadband):
            yaw_wanted = _clip(cfg.k_yaw * body_bearing, -cfg.max_yaw_rate, cfg.max_yaw_rate)

        self._vx = _slew(self._vx, vx_wanted, cfg.max_accel_vx * dt)
        self._yaw_rate = _slew(self._yaw_rate, yaw_wanted, cfg.max_accel_yaw * dt)

        if self._vx != 0.0:
            state = FollowState.APPROACHING
        elif self._yaw_rate != 0.0 or self._turning:
            state = FollowState.TURNING
        else:
            state = FollowState.HOLDING
        return FollowCommand(self._vx, self._yaw_rate, self._head_target[0], self._head_target[1], state, reason)
