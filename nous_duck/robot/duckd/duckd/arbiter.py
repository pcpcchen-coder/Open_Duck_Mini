"""安全仲裁器（ADR-0009 §2.5）：所有會讓身體動的指令都要經過這裡，它是最後一關。

純邏輯：不做 I/O、不讀時鐘（時間由呼叫端傳入單調時鐘的秒數），所以可以完整單元測試。
數值在 `limits.py`，都是**初始值、待實機修訂**。

規則摘要：

- 頭部目標夾在範圍內（可再加「接手位置 ± 視窗」），輸出的設定值每圈最多走 `head_max_speed × dt`。
- 速度指令先夾上游範圍、再夾室內上限，每圈變化量有上限；`duration_s` 上限 3 s。
- 期限：`duration_s` 到、`ttl_ms` 到、租約失效，任一成立就停。
- 租約失效：停下、送 `link_lost`；恢復後只送 `link_restored`，**不自動繼續**。
- `stop` 永遠接受。緊急停止會鎖住；這個類別裡解除的方法只給本機用，duck-link 沒有對應的指令。
- 跌倒（傾角連續超過門檻）鎖住，要本機復位。手把接管期間拒絕 duck-link 的移動意圖。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .limits import HEAD_JOINTS, Limits


@dataclass
class Decision:
    accepted: bool
    reason: str | None = None  # duck-link 的 reason 列舉
    detail: str | None = None
    applied: dict | None = None
    clamped: bool = False


@dataclass
class Output:
    head: dict[str, float] | None  # 這一圈要送給身體的頭部設定值；頭部沒有接手時是 None
    velocity: tuple[float, float, float]
    want_pause: bool  # 步態 host 用：可以設 paused 了
    events: list[tuple[str, dict]] = field(default_factory=list)  # (event 名稱, 其他欄位)


def _clip(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def clamp_velocity(vx: float, vy: float, yaw: float, limits: Limits) -> tuple[tuple[float, float, float], bool]:
    """先上游範圍、再室內上限。回傳（夾限後, 有沒有被夾）。"""
    req = (vx, vy, yaw)
    out = tuple(_clip(_clip(v, -u, u), -i, i) for v, u, i in zip(req, limits.vel_upstream, limits.vel_indoor))
    return out, any(abs(a - b) > 1e-12 for a, b in zip(req, out))


def step_toward(cur: float, goal: float, max_step: float) -> float:
    diff = goal - cur
    return goal if abs(diff) <= max_step else cur + math.copysign(max_step, diff)


class SafetyArbiter:
    def __init__(self, limits: Limits | None = None, walk_supported: bool = False, walk_unsupported_reason: str = ""):
        self.limits = limits or Limits()
        self.walk_supported = walk_supported
        self.walk_unsupported_reason = walk_unsupported_reason
        # 連線租約
        self.last_heartbeat: float | None = None
        self.lease_ok = False
        self._lost_reported = False  # 送過 link_lost、還沒送 link_restored
        # 鎖定狀態
        self.estop_reason: str | None = None
        self.fallen = False
        self.block: tuple[str, str] | None = None  # （reason 列舉, 說明）：過熱、低電壓、硬體故障時拒絕新動作
        self.controller_until = -math.inf
        # 頭
        self.head_enabled = False
        self.head_cmd: dict[str, float] = {}
        self.head_goal: dict[str, float] = {}
        self.head_speed: dict[str, float] = {}
        self.head_ref: dict[str, float] | None = None
        self.head_source = "none"  # none / look / stream
        self.head_deadline = math.inf
        # 走路
        self.paused = True  # 以暫停狀態啟動（ADR-0009 §2.5）
        self.vel_goal = (0.0, 0.0, 0.0)
        self.vel_cmd = (0.0, 0.0, 0.0)
        self.walk_deadline = math.inf
        self.walk_active = False
        self._stopping_since: float | None = None
        self._feet_since: float | None = None
        self._stop_reported = False
        self._tilt_since: float | None = None
        self._events: list[tuple[str, dict]] = []
        self._halt_pending = False
        self._idle = True  # 沒有在走也沒有在停：維持暫停，直到下一個被接受的 walk

    # ------------------------------------------------------------ 租約
    def heartbeat(self, now: float) -> None:
        self.last_heartbeat = now
        if not self.lease_ok:
            self.lease_ok = True
            if self._lost_reported:
                self._lost_reported = False
                self._events.append(("link_restored", {}))

    def link_down(self, now: float) -> None:
        """傳輸層確定斷了（socket 關閉）：不用等 1.5 s。"""
        self._lease_lost(now)

    def _lease_lost(self, now: float) -> None:
        if not self.lease_ok:
            return
        self.lease_ok = False
        self._halt(now)
        self._lost_reported = True
        self._events.append(("link_lost", {}))

    # ------------------------------------------------------------ 共用
    def _halt(self, now: float) -> None:
        """停止所有動作：頭停在目前的設定值，速度目標歸零（加速度限制下減速）。"""
        self.head_goal = dict(self.head_cmd)
        self.head_source = "none"
        self.head_deadline = math.inf
        if self.walk_active or any(self.vel_goal):
            self._begin_stop(now)
        self.vel_goal = (0.0, 0.0, 0.0)
        self.walk_deadline = math.inf

    def _begin_stop(self, now: float) -> None:
        self.walk_active = False
        self._stopping_since = now
        self._feet_since = None
        self._stop_reported = False

    def _gate(self, now: float, *, motion: bool = True) -> Decision | None:
        """動作指令的共同檢查。通過回傳 None。"""
        if self.estop_reason:
            return Decision(False, "estop_latched", self.estop_reason[:200])
        if self.fallen:
            return Decision(False, "fallen")
        if not self.lease_ok:
            return Decision(False, "link_degraded", "no heartbeat lease")
        if motion and now < self.controller_until:
            return Decision(False, "controller_active")
        if motion and self.block:
            return Decision(False, self.block[0], self.block[1][:200])
        return None

    # ------------------------------------------------------------ 頭
    def enable_head(self, actual: dict[str, float], window: bool = True) -> None:
        """接手頭部：設定值與目標都設成目前位置（不跳），視窗以這個位置為中心。"""
        self.head_cmd = {n: float(actual[n]) for n in HEAD_JOINTS}
        self.head_goal = dict(self.head_cmd)
        self.head_speed = {n: self.limits.head_max_speed for n in HEAD_JOINTS}
        self.head_ref = dict(self.head_cmd) if (window and self.limits.head_window is not None) else None
        self.head_enabled = True
        self.head_source = "none"

    def disable_head(self) -> None:
        self.head_enabled = False
        self.head_source = "none"

    def head_bounds(self, name: str) -> tuple[float, float]:
        lo, hi = self.limits.head_range[name]
        if self.head_ref is not None and self.limits.head_window is not None:
            lo = max(lo, self.head_ref[name] - self.limits.head_window)
            hi = min(hi, self.head_ref[name] + self.limits.head_window)
            if lo > hi:  # 接手時的位置已經在範圍外：只准往範圍內走，不准再往外
                c = _clip(self.head_ref[name], *self.limits.head_range[name])
                lo = hi = c
        return lo, hi

    def _clamp_head(self, targets: dict[str, float]) -> tuple[dict[str, float], bool]:
        out, clamped = {}, False
        for name, value in targets.items():
            if name not in HEAD_JOINTS:
                continue
            v = _clip(float(value), *self.head_bounds(name))
            clamped |= abs(v - float(value)) > 1e-9
            out[name] = v
        return out, clamped

    def request_look(self, params: dict, ttl_ms: int, now: float) -> Decision:
        if not self.head_enabled:
            return Decision(False, "unsupported", "head is not engaged")
        gate = self._gate(now)
        if gate:
            return gate
        targets = {k: v for k, v in params.items() if k in HEAD_JOINTS}
        if any(not math.isfinite(float(v)) for v in targets.values()):
            return Decision(False, "invalid", "non-finite angle")
        goal, clamped = self._clamp_head(targets)
        need = max((abs(goal[n] - self.head_cmd[n]) for n in goal), default=0.0) / self.limits.head_max_speed
        duration = params.get("duration_s")
        if duration is None:
            for n in goal:
                self.head_speed[n] = self.limits.head_max_speed
            applied_duration = need
        else:
            duration = min(float(duration), self.limits.look_duration_max_s)
            if duration < need - 1e-9:
                clamped = True  # 限速下做不到那麼快
            applied_duration = max(duration, need)
            for n in goal:
                dist = abs(goal[n] - self.head_cmd[n])
                self.head_speed[n] = min(self.limits.head_max_speed, dist / applied_duration) if dist > 0 else self.limits.head_max_speed
        self.head_goal.update(goal)
        self.head_source = "look"
        self.head_deadline = now + ttl_ms / 1000.0
        applied = {n: round(v, 5) for n, v in goal.items()}
        applied["duration_s"] = round(applied_duration, 3)
        return Decision(True, applied=applied, clamped=clamped)

    def stream_head(self, targets: dict[str, float], now: float) -> tuple[bool, bool]:
        """本機產生的連續目標（動作播放器、presence、track）。回傳（有沒有採用, 有沒有被夾）。

        一樣要過檢查、夾限、限速。誰可以蓋過誰（look、動作、presence）由 core 決定。
        """
        if not self.head_enabled or self._gate(now) is not None:
            return False, False
        goal, clamped = self._clamp_head(targets)
        for n in goal:
            self.head_speed[n] = self.limits.head_max_speed
        self.head_goal.update(goal)
        self.head_source = "stream"
        self.head_deadline = math.inf
        return True, clamped

    def local_head_goal(self, targets: dict[str, float]) -> bool:
        """本機操作（例如釋放前回到接手時的位置）：不需要租約，但緊急停止、跌倒時不動；一樣夾限、限速。"""
        if not self.head_enabled or self.estop_reason or self.fallen:
            return False
        goal, _ = self._clamp_head(targets)
        for n in goal:
            self.head_speed[n] = self.limits.head_max_speed
        self.head_goal.update(goal)
        self.head_source = "local"
        self.head_deadline = math.inf
        return True

    def check_motion(self, now: float) -> Decision | None:
        """動作指令的共同檢查（緊急停止、跌倒、租約、手把接管、健康）。通過回傳 None。"""
        return self._gate(now)

    def head_settled(self, tol: float = 1e-4) -> bool:
        return all(abs(self.head_goal[n] - self.head_cmd[n]) <= tol for n in self.head_cmd)

    # ------------------------------------------------------------ 走路
    def request_walk(self, params: dict, ttl_ms: int, now: float) -> Decision:
        if not self.walk_supported:
            return Decision(False, "unsupported", ("walk: " + self.walk_unsupported_reason)[:200])
        gate = self._gate(now)
        if gate:
            return gate
        if self.paused:
            return Decision(False, "paused", "resume required before walk")
        req = tuple(float(params.get(k, 0.0)) for k in ("vx", "vy", "yaw_rate"))
        if any(not math.isfinite(v) for v in req):
            return Decision(False, "invalid", "non-finite velocity")
        vel, clamped = clamp_velocity(*req, self.limits)
        duration = float(params["duration_s"])
        if duration > self.limits.walk_duration_max_s:
            duration, clamped = self.limits.walk_duration_max_s, True
        self.vel_goal = vel
        self.walk_deadline = now + min(duration, ttl_ms / 1000.0)
        self.walk_active = True
        self._idle = False
        self._stopping_since = None
        applied = {"vx": vel[0], "vy": vel[1], "yaw_rate": vel[2], "duration_s": duration}
        return Decision(True, applied=applied, clamped=clamped)

    def stop(self, now: float) -> Decision:
        """永遠接受，不受租約、鎖定或頻率限制。"""
        self._halt(now)
        self.paused = True
        return Decision(True)

    def resume(self, now: float) -> Decision:
        gate = self._gate(now, motion=False)
        if gate:
            return gate
        self.paused = False
        return Decision(True)

    # ------------------------------------------------------------ 鎖定（本機）
    def estop(self, reason: str, now: float) -> None:
        if self.estop_reason:
            return
        self.estop_reason = reason
        self._halt(now)
        self.vel_cmd = (0.0, 0.0, 0.0)  # 緊急停止不等減速
        self.paused = True
        self._events.append(("estop", {"reason": "local"}))

    def clear_estop_local(self) -> bool:
        """只給本機（操作的人）呼叫；duck-link 的指令處理不會呼叫這裡（tests/test_core.py 檢查）。"""
        if not self.estop_reason:
            return False
        self.estop_reason = None
        self._events.append(("estop_cleared", {"reason": "local"}))
        return True

    def reset_fallen_local(self) -> bool:
        if not self.fallen:
            return False
        self.fallen = False
        self._tilt_since = None
        return True

    def set_block(self, reason: str | None, message: str = "") -> None:
        new = (reason, message) if reason else None
        if new and not self.block:
            self._halt_pending = True
        self.block = new

    def controller_input(self, active: bool, now: float) -> None:
        """手把有輸入（搖桿超過死區或按鍵）：接管 3 s，duck-link 的動作意圖停下。"""
        if not active:
            return
        if now >= self.controller_until:
            self._halt(now)
            self._events.append(("controller_takeover", {}))
        self.controller_until = now + self.limits.controller_takeover_s

    def observe(self, now: float, tilt_deg: float | None = None, feet: tuple[bool, bool] | None = None) -> None:
        """餵感測值：傾角（由 accelero 推算）與足底接觸。沒有感測器就不要呼叫。"""
        if tilt_deg is not None and not self.fallen:
            if abs(tilt_deg) > self.limits.fall_tilt_deg:
                if self._tilt_since is None:
                    self._tilt_since = now
                elif now - self._tilt_since >= self.limits.fall_hold_s:
                    self.fallen = True
                    self._halt(now)
                    self.vel_cmd = (0.0, 0.0, 0.0)
                    self.paused = True
                    self._events.append(("fell", {}))
            else:
                self._tilt_since = None
        if feet is not None:
            if feet[0] and feet[1]:
                if self._feet_since is None:
                    self._feet_since = now
            else:
                self._feet_since = None

    # ------------------------------------------------------------ 每圈
    def update(self, now: float, dt: float) -> Output:
        lim = self.limits
        if self.lease_ok and self.last_heartbeat is not None and now - self.last_heartbeat > lim.lease_s:
            self._lease_lost(now)
        if self._halt_pending:
            self._halt_pending = False
            self._halt(now)
        if self.head_source == "look" and now >= self.head_deadline:
            # ttl 到期：頭停在目前的設定值
            self.head_goal = dict(self.head_cmd)
            self.head_source = "none"
            self.head_deadline = math.inf
        if self.walk_active and now >= self.walk_deadline:
            self.vel_goal = (0.0, 0.0, 0.0)
            self.walk_deadline = math.inf
            self._begin_stop(now)
            self._events.append(("walk_done", {"reason": "deadline"}))

        if self.head_enabled:
            for n in HEAD_JOINTS:
                self.head_cmd[n] = step_toward(self.head_cmd[n], self.head_goal[n], self.head_speed[n] * dt)
        # 加速度限制以 20 ms 一圈為準，dt 不同時按比例
        k = dt / 0.02 if dt > 0 else 0.0
        self.vel_cmd = tuple(step_toward(c, g, s * k) for c, g, s in zip(self.vel_cmd, self.vel_goal, lim.vel_step))

        # 步態 host 用：現在可不可以讓上游主迴圈暫停（暫停＝不再送馬達目標，扭力維持）
        if self.estop_reason or self.fallen:
            want_pause = True
        elif self.walk_active or any(self.vel_cmd):
            want_pause = False  # 還在走或還在減速
        elif self._stopping_since is not None:
            # 速度已經歸零：兩腳著地持續 0.3 s 才暫停；等不到就維持踏步並回報一次
            want_pause = False
            if self._feet_since is not None and now - self._feet_since >= lim.stop_settle_s:
                self._stopping_since = None
                self._idle = True
                want_pause = True
            elif now - self._stopping_since > lim.stop_timeout_s and not self._stop_reported:
                self._stop_reported = True
                self._events.append(("walk_done", {"reason": "stop_not_settled"}))
        else:
            want_pause = self.paused or self._idle

        events, self._events = self._events, []
        return Output(dict(self.head_cmd) if self.head_enabled else None, self.vel_cmd, want_pause, events)
