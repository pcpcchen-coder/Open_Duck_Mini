"""導航器：定位＋規劃＋路徑追蹤＋任務狀態機＋回充＋安全規則。

用法（每個控制週期呼叫一次 `step`）：

    nav = Navigator(load_map(path))
    ack = nav.go_to("brother_room")        # 或 nav.return_home()、nav.cancel()
    out = nav.step(frame)                  # SensorFrame → NavOutput（速度、頭部目標、事件）

同時只有一個任務。任務的進度、完成、失敗以 duck-link v0 的 `event` 訊息形狀放在 `NavOutput.events`。
失敗原因是固定代碼：`door_closed`、`lost`、`blocked`、`forbidden`、`timeout`、`fell`、`cancelled`、`dock_failed`。

速度指令只用步態反應表裡可靠的組合（`gait.py`）：前進固定 0.15、後退固定 −0.15、原地轉 ±1.0 或 ±0.6，
轉向連續可調；**不用側移**。走路時頭回正，停下才轉頭掃描（模擬量測：走路時轉頭會讓步態停住）。
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from .gait import GaitModel
from .geometry import Pose2D, rect_distance, to_body, to_map, wrap
from .localization import Localizer, LocalizerConfig
from .mapfile import DuckMap
from .planner import CostMap, Plan, PlanError, PlannerConfig, plan_path
from .types import HeadTarget, NavOutput, SensorFrame

PROTOCOL_VERSION = "0.1"
FAIL_REASONS = ("door_closed", "lost", "blocked", "forbidden", "timeout", "fell", "cancelled", "dock_failed")

#: 機身原點到背後觸點凸台外表面的距離（m）：`robot.xml` 的 body_back 幾何在 base 的 x = −0.019，
#: 凸台外表面在列印座標 x = −0.143（`hardware/dock/cad/dock_cad/params.py` 的 `BOSS_FACE_X`）。
BASE_TO_CONTACT_M = 0.162


@dataclass
class NavConfig:
    arrive_tol_m: float = 0.12
    final_yaw_tol: float = 0.20
    lookahead_m: float = 0.35
    turn_enter: float = 0.70
    turn_exit: float = 0.22
    k_heading: float = 2.2
    #: 不確定度的「先停下來看一看」門檻（比「未定位」門檻低）。
    soft_pos_sigma: float = 0.16
    soft_since_tag_s: float = 4.0
    scan_hold_s: float = 1.4
    scan_head_yaw: float = 0.5
    scan_rotate_rad: float = 1.6
    lost_timeout_s: float = 45.0
    mission_timeout_s: float = 600.0
    max_replans: int = 3
    max_replans_same_spot: int = 10
    #: 門關著時停在門前多遠（m，離門中心）。
    door_standoff_m: float = 0.5
    #: 估計位置離禁區的距離小於「這個值＋不確定度」就立刻停下、任務失敗。
    zone_guard_m: float = 0.20
    zone_guard_sigma_gain: float = 1.0
    #: 正前方的緊急停止區（機身座標）：x 在這個範圍、|y| 小於半寬內有障礙點就不往前走。
    stop_zone_x: tuple[float, float] = (0.05, 0.30)
    stop_zone_half_w: float = 0.13
    stop_zone_wait_s: float = 4.0
    progress_interval_s: float = 5.0
    #: 送出移動指令後多久還沒踏步就算沒起步。
    stall_s: float = 3.0
    max_stalls: int = 3
    # 回充。
    dock_far_m: float = 1.25  # 對位起點：機身原點離觸點平面的距離
    dock_turn_extra_m: float = 0.0
    dock_k_y: float = 3.0
    dock_k_h: float = 2.5
    dock_max_heading: float = 0.35
    dock_align_tol_m: float = 0.02
    dock_overrun_m: float = 0.05
    dock_back_heading: float = 0.07
    #: 放掉轉身指令後還會多轉多久（s × 目前角速度）。模擬裡步態停得很快。
    dock_turn_coast_s: float = 0.10
    #: 回充的橫向校正量（m，充電座座標的 +y）：加在轉身前的對位線上，用來補掉步態反應表沒涵蓋的系統偏差。
    #: 由實際量到的「進導引座時的平均橫向偏差」決定；模擬的值在 data/dock_trim.sim.json。
    dock_lateral_trim_m: float = 0.0
    dock_back_hold_m: float = 0.10
    dock_back_k_y: float = 2.5
    dock_back_k_h: float = 1.5
    dock_max_attempts: int = 3
    dock_max_align_retries: int = 4
    undock_m: float = 0.55
    localizer: LocalizerConfig = field(default_factory=LocalizerConfig)
    planner: PlannerConfig = field(default_factory=PlannerConfig)


@dataclass
class Mission:
    mission_id: str
    kind: str  # go_to | return_home
    place: str
    goal: Pose2D
    goal_yaw: float | None
    started_t: float
    phase: str = "starting"
    plan: Plan | None = None
    seg: int = 0
    replans: int = 0
    dock_attempts: int = 0
    align_retries: int = 0
    strikes: int = 0
    replans_here: int = 0
    replan_at: tuple[float, float] | None = None
    door_fail: str | None = None
    stalls: int = 0
    last_progress_t: float = -1e9
    request_id: str | None = None
    status: str = "active"  # active | done | failed
    reason: str | None = None
    progress: float = 0.0
    total_m: float = 0.0


class Navigator:
    def __init__(
        self,
        duck_map: DuckMap,
        config: NavConfig | None = None,
        gait: GaitModel | None = None,
        clock_ms=None,
        mock: bool = False,
    ):
        self.map = duck_map
        self.cfg = config or NavConfig()
        self.gait = gait or GaitModel.load()
        self.loc = Localizer(duck_map, self.cfg.localizer)
        self.cm = CostMap(duck_map, self.cfg.planner)
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        #: 這個導航器接的是 mock／模擬的感測與身體；事件的 data 會帶 `mock: true`。
        self.mock = mock
        self.mission: Mission | None = None
        self.last_mission: Mission | None = None
        self.closed_doors: set[str] = set()
        self.on_dock: bool | None = None
        self.t = 0.0
        self._n_mission = 0
        self._n_event = 0
        self._last_cmd = (0.0, 0.0, 0.0)
        self._v_est = [0.0, 0.0, 0.0]
        self._turning = False
        self._scan: dict | None = None
        self._moving_since: float | None = None
        self._stopzone_since: float | None = None
        self._phase_t0 = 0.0
        self._events: list[dict] = []
        self._soft_skip_sigma = 0.0
        self._replan_wait_until = 0.0
        self._path_dirty = False
        self._reinit_seen = 0

    # ================================================================ 指令（對應 duck-link 的 action）
    def go_to(self, place: str, request_id: str | None = None) -> dict:
        if self.mission is not None:
            return {"status": "rejected", "reason": "busy_mission", "mission_id": self.mission.mission_id}
        p = self.map.places.get(place)
        if p is None:
            return {"status": "rejected", "reason": "unknown_name"}
        if self.map.dock is not None and place == self.map.dock.place:
            return self.return_home(request_id)
        goal = Pose2D(p.x, p.y, p.yaw if p.yaw is not None else 0.0)
        return self._start("go_to", place, goal, p.yaw, request_id)

    def return_home(self, request_id: str | None = None) -> dict:
        if self.mission is not None:
            return {"status": "rejected", "reason": "busy_mission", "mission_id": self.mission.mission_id}
        if self.map.dock is None:
            return {"status": "rejected", "reason": "unsupported"}
        d = self.map.dock.pose
        gx, gy = to_map(d, self.cfg.dock_far_m, self._dock_pre_turn_offset())
        goal = Pose2D(gx, gy, wrap(d.yaw + math.pi))
        return self._start("return_home", self.map.dock.place, goal, goal.yaw, request_id)

    def cancel(self, mission_id: str | None = None) -> dict:
        m = self.mission
        if m is None or (mission_id is not None and mission_id != m.mission_id):
            return {"status": "rejected", "reason": "no_mission"}
        self._fail("cancelled")
        return {"status": "accepted", "mission_id": m.mission_id}

    def where(self) -> dict:
        """`where` 指令與 `state.location` 的資料：只有地點 ID 與不確定度，不含座標。"""
        pose = self.loc.pose
        localized = self.loc.localized
        place = self.map.nearest_place(pose.x, pose.y) if (pose and localized) else None
        room = self.map.room_at(pose.x, pose.y) if (pose and localized) else None
        sig = self.loc.pos_sigma
        return {
            "place": place,
            "room": room,
            "localized": bool(localized),
            "uncertainty_m": round(sig, 3) if math.isfinite(sig) else None,
            "on_dock": self.on_dock,
            "map_version": self.map.map_version,
            "mock": self.mock,
        }

    def location_state(self) -> dict:
        w = self.where()
        return {k: w[k] for k in ("place", "localized", "uncertainty_m", "on_dock")}

    def places(self) -> dict:
        return {"map_version": self.map.map_version, "synthetic_map": self.map.synthetic, "places": self.map.places_summary()}

    def mission_status(self, mission_id: str | None = None) -> dict:
        m = self.mission or self.last_mission
        if m is None or (mission_id is not None and m.mission_id != mission_id):
            return {"status": "rejected", "reason": "no_mission"}
        return {
            "status": "accepted",
            "data": {
                "mission_id": m.mission_id,
                "kind": m.kind,
                "place": m.place,
                "phase": m.phase,
                "progress": round(m.progress, 3),
                "state": m.status,
                "reason": m.reason,
                "mock": self.mock,
            },
        }

    def mission_state(self) -> dict | None:
        """`state.mission` 的形狀；沒有進行中的任務回傳 None。"""
        m = self.mission
        if m is None:
            return None
        return {"mission_id": m.mission_id, "kind": m.kind, "phase": m.phase, "progress": round(m.progress, 3)}

    def set_docked(self, sigma_xy: float = 0.01, sigma_yaw: float = 0.04) -> None:
        """告訴導航「現在停在充電座上」（電氣訊號或人工確認）。位姿由充電座的機械位置決定。"""
        self.loc.set_pose(self.map.dock_base_pose(BASE_TO_CONTACT_M), sigma_xy, sigma_yaw)
        self.on_dock = True

    # ================================================================ 內部：任務與事件
    def _start(self, kind: str, place: str, goal: Pose2D, goal_yaw, request_id) -> dict:
        self._n_mission += 1
        m = Mission(f"m_{self._n_mission:04d}", kind, place, goal, goal_yaw, self.t, request_id=request_id)
        self.mission = m
        self.closed_doors.clear()  # 門可能已經開了：每個任務重新判斷
        self._reinit_seen = self.loc.reinit_count
        self._replan_wait_until = 0.0
        self._path_dirty = False
        self._turning = False
        self._scan = None
        self._moving_since = None
        self._stopzone_since = None
        self._set_phase("undocking" if self.on_dock else "planning")
        return {"status": "accepted", "mission_id": m.mission_id}

    def _set_phase(self, phase: str) -> None:
        if self.mission is not None:
            self.mission.phase = phase
        self._phase_t0 = self.t
        self._turning = False
        self._moving_since = None

    def _emit(self, event: str, reason: str | None = None, data: dict | None = None) -> None:
        self._n_event += 1
        msg = {
            "protocol_version": PROTOCOL_VERSION,
            "type": "event",
            "sent_at_ms": int(self.clock_ms()),
            "event": event,
            "event_id": f"nav_{self._n_event:06d}",
        }
        m = self.mission
        if m is not None:
            msg["mission_id"] = m.mission_id
            if m.request_id:
                msg["request_id"] = m.request_id
        if reason is not None:
            msg["reason"] = reason
        d = dict(data or {})
        if self.mock:
            d["mock"] = True
        if d:
            msg["data"] = d
        self._events.append(msg)

    def _fail(self, reason: str, detail: dict | None = None) -> None:
        assert reason in FAIL_REASONS, reason
        m = self.mission
        if m is None:
            return
        m.status, m.reason = "failed", reason
        w = self.where()
        self._emit("mission_failed", reason, {"kind": m.kind, "place": m.place, "phase": m.phase, "near": w["place"], **(detail or {})})
        self.last_mission, self.mission = m, None
        self._scan = None

    def _done(self, data: dict | None = None) -> None:
        m = self.mission
        m.status, m.progress = "done", 1.0
        self._emit("mission_done", None, {"kind": m.kind, "place": m.place, **(data or {})})
        self.last_mission, self.mission = m, None

    # ================================================================ 主迴圈
    def step(self, frame: SensorFrame) -> NavOutput:
        self.t = frame.t
        cfg = self.cfg
        # ---- 1. 定位：預測＋更新 ----
        cmd = frame.applied_cmd if frame.applied_cmd is not None else self._last_cmd
        tgt = self.gait.response(cmd[0], cmd[2])
        if frame.stepping is False and abs(cmd[0]) < 1e-6 and abs(cmd[2]) < 1e-6:
            tgt = (0.0, 0.0, 0.0)
        a = min(1.0, frame.dt / self.gait.tau_s) if frame.dt > 0 else 0.0
        self._v_est = [v + (t_ - v) * a for v, t_ in zip(self._v_est, tgt)]
        if frame.stepping is False and all(abs(c) < 1e-6 for c in cmd):
            self._v_est = [0.0, 0.0, 0.0]
        if frame.lifted:
            # 被抱起來：位置不可信。丟掉定位與用舊位置記下的障礙，之後重新找標籤。
            self.loc.reset()
            self.cm.dynamic.clear()
            self.cm._rebuild()
            self.closed_doors.clear()
            self.on_dock = False
            self._v_est = [0.0, 0.0, 0.0]
            if self.mission is not None and self.mission.phase not in ("localizing",):
                self._scan = None
                self._set_phase("planning")
        gyro = frame.gyro_z is not None
        wz = frame.gyro_z if gyro else self._v_est[2]
        self.loc.predict(frame.dt, self._v_est[0], self._v_est[1], wz, gyro)
        self.loc.update(frame.tags)
        if frame.charging is True and self.map.dock is not None:
            self.set_docked()
        elif frame.charging is False:
            self.on_dock = False

        out = NavOutput()
        m = self.mission
        if m is None:
            self._last_cmd = (0.0, 0.0, 0.0)
            return self._finish(out)
        out.active = True

        # ---- 2. 不分階段的安全規則 ----
        if frame.fallen:
            self._fail("fell")
            return self._finish(out)
        if self.t - m.started_t > cfg.mission_timeout_s:
            self._fail("timeout")
            return self._finish(out)
        pose = self.loc.pose
        if pose is not None and self.loc.initialized:
            guard = cfg.zone_guard_m + cfg.zone_guard_sigma_gain * min(self.loc.pos_sigma, 0.3)
            for z in self.map.zones.values():
                if rect_distance(pose.x, pose.y, z.rect) < guard:
                    self._fail("forbidden", {"zone": z.id, "zone_kind": z.kind})
                    return self._finish(out)

        # ---- 3. 依階段決定指令 ----
        cmd_out, head = self._phase_step(frame)
        if self.mission is None:  # 這一步結束了任務
            return self._finish(out)
        # 沒起步的偵測（有足底訊號才做）。
        moving_cmd = abs(cmd_out[0]) > 1e-6 or abs(cmd_out[2]) > 1e-6
        if moving_cmd and frame.stepping is not None:
            if frame.stepping:
                self._moving_since = self.t
            elif self._moving_since is None:
                self._moving_since = self.t
            elif self.t - self._moving_since > cfg.stall_s:
                m.stalls += 1
                self._moving_since = self.t
                if m.stalls > cfg.max_stalls:
                    self._fail("blocked", {"detail": "gait_did_not_start"})
                    return self._finish(out)
        else:
            self._moving_since = None
        out.vx, out.vy, out.yaw_rate = cmd_out
        out.head = head
        # 進度事件。
        if self.t - m.last_progress_t >= cfg.progress_interval_s:
            m.last_progress_t = self.t
            w = self.where()
            self._emit("mission_progress", None, {"kind": m.kind, "phase": m.phase, "progress": round(m.progress, 3), "near": w["place"], "uncertainty_m": w["uncertainty_m"]})
        self._last_cmd = cmd_out
        return self._finish(out)

    def _finish(self, out: NavOutput) -> NavOutput:
        if self.mission is None:
            out.vx = out.vy = out.yaw_rate = 0.0
            out.head = HeadTarget()
            self._last_cmd = (0.0, 0.0, 0.0)
            out.active = False
        out.events, self._events = self._events, []
        return out

    # ================================================================ 階段
    def _phase_step(self, frame: SensorFrame):
        m = self.mission
        stop = (0.0, 0.0, 0.0)
        head0 = HeadTarget()
        ph = m.phase

        # 掃描（未定位或不確定度偏高）可以打斷大部分階段。
        if ph in ("planning", "navigating", "final_turn", "dock_approach", "localizing"):
            need = not self.loc.localized
            soft = (
                ph == "navigating"
                and self.loc.pos_sigma > max(self.cfg.soft_pos_sigma, self._soft_skip_sigma)
                and self.loc.since_tag_s > self.cfg.soft_since_tag_s
            )
            if self.loc.since_tag_s < 1.0:
                self._soft_skip_sigma = 0.0
            if self._scan is None and (need or soft):
                self._scan = {"stage": "settle", "t0": self.t, "start": self.t, "rot": 0.0, "rot_total": 0.0, "hard": need, "resume": "planning"}
                if ph != "localizing":
                    m.phase = "localizing"
            if self._scan is not None:
                return self._scan_step(frame)

        if ph == "undocking":
            return self._undock_step(frame)
        if ph == "localizing":  # 掃描結束
            self._set_phase("planning")
            ph = "planning"
        if ph == "planning":
            return self._plan_step(), head0
        if ph == "navigating":
            return self._navigate_step(frame), head0
        if ph == "final_turn":
            return self._final_turn_step(), head0
        if ph == "dock_approach":
            return self._dock_approach_step(frame), head0
        if ph == "dock_settle":
            if self.t - self._phase_t0 > 1.5:
                _, yd = self._dock_xy()
                err = yd - self._dock_pre_turn_offset()
                if abs(err) <= self.cfg.dock_align_tol_m:
                    self._set_phase("dock_turn")
                else:
                    m.align_retries += 1
                    if m.align_retries > self.cfg.dock_max_align_retries:
                        self._fail("dock_failed", {"detail": "align", "attempts": m.dock_attempts})
                    else:
                        self._set_phase("dock_retreat")
            return stop, head0
        if ph == "dock_turn":
            return self._dock_turn_step(), head0
        if ph == "dock_settle2":
            if self.t - self._phase_t0 > 1.0:
                e = wrap(self.map.dock.pose.yaw - self.loc.pose.yaw)
                self._turn_fixes = getattr(self, "_turn_fixes", 0)
                if abs(e) > 0.09 and self._turn_fixes < 4:
                    self._turn_fixes += 1
                    self._set_phase("dock_turn")
                else:
                    self._turn_fixes = 0
                    m.dock_attempts += 1
                    self._set_phase("dock_back")
            return stop, head0
        if ph == "dock_back":
            return self._dock_back_step(frame), head0
        if ph == "dock_retreat":
            return self._dock_retreat_step(), head0
        return stop, head0

    # ---------------------------------------------------------------- 掃描找標籤
    def _scan_step(self, frame: SensorFrame):
        cfg, s = self.cfg, self._scan
        stop = (0.0, 0.0, 0.0)
        good = self.loc.confident and self.loc.since_tag_s < 1.0
        if good and s["stage"] != "rotate_stop":
            self._scan = None
            self.mission.phase = "localizing"
            return stop, HeadTarget()
        if self.t - s["start"] > cfg.lost_timeout_s:
            self._fail("lost")
            return stop, HeadTarget()
        st, el = s["stage"], self.t - s["t0"]

        def go(stage):
            s["stage"], s["t0"] = stage, self.t

        if st == "settle":
            if (frame.stepping is False and el > 0.4) or el > 1.2:
                go("left")
            return stop, HeadTarget()
        if st == "left":
            if el > cfg.scan_hold_s:
                go("right")
            return stop, HeadTarget(head_yaw=cfg.scan_head_yaw)
        if st == "right":
            if el > cfg.scan_hold_s * 1.3:
                go("center")
            return stop, HeadTarget(head_yaw=-cfg.scan_head_yaw)
        if st == "center":
            if el > 0.6:
                if not s["hard"] and self.loc.localized:
                    # 只是不確定度偏高：轉頭沒看到標籤也先繼續走，等真的超過「未定位」門檻再原地轉。
                    # 不確定度再長一截之前不重複做同樣的掃描。
                    self._soft_skip_sigma = self.loc.pos_sigma + 0.07
                    self._scan = None
                    self.mission.phase = "localizing"
                    return stop, HeadTarget()
                if s["rot_total"] >= 2 * math.pi + 0.5:
                    self._fail("lost")
                    return stop, HeadTarget()
                s["rot"] = 0.0
                go("rotate")
            return stop, HeadTarget()
        if st == "rotate":
            wz = frame.gyro_z if frame.gyro_z is not None else self._v_est[2]
            s["rot"] += abs(wz) * frame.dt
            s["rot_total"] += abs(wz) * frame.dt
            if s["rot"] >= cfg.scan_rotate_rad or el > 8.0:
                go("rotate_stop")
                return stop, HeadTarget()
            return (0.0, 0.0, self.gait.TURN_CMD), HeadTarget()
        if st == "rotate_stop":
            if (frame.stepping is False and el > 0.4) or el > 1.2:
                go("left")
            return stop, HeadTarget()
        return stop, HeadTarget()

    # ---------------------------------------------------------------- 離開充電座
    def _undock_step(self, frame: SensorFrame):
        xd, yd = self._dock_xy()
        if xd >= BASE_TO_CONTACT_M + self.cfg.undock_m or self.t - self._phase_t0 > 15.0:
            self.on_dock = False
            self._emit("undocked", None, {"place": self.map.dock.place})
            self._set_phase("planning")
            return (0.0, 0.0, 0.0), HeadTarget()
        e = wrap(self.loc.pose.yaw - self.map.dock.pose.yaw)
        w = max(-0.6, min(0.6, self.cfg.dock_k_h * (-self.cfg.dock_k_y * yd * 0.3 - e)))
        return (self.gait.FWD_CMD, 0.0, w), HeadTarget()

    # ---------------------------------------------------------------- 規劃
    def _plan_step(self):
        m = self.mission
        pose = self.loc.pose
        stop = (0.0, 0.0, 0.0)
        if self.t < self._replan_wait_until:
            return stop
        try:
            m.plan = plan_path(self.cm, (pose.x, pose.y), (m.goal.x, m.goal.y), self.closed_doors)
        except PlanError as e:
            if e.reason == "forbidden":
                self._fail("forbidden")
                return stop
            door = self._door_blocked_on_route()
            if e.reason == "door_closed" or door is not None:
                self._door_closed(door or next(iter(sorted(self.closed_doors)), None))
                return stop
            # 柵格上找不到路：可能是暫時的障礙。等一下再試，次數有上限。
            m.strikes += 1
            if m.strikes > self.cfg.max_replans:
                self._fail("blocked", {"replans": m.replans})
                return stop
            self._replan_wait_until = self.t + 2.0
            return stop
        m.seg = 0
        if m.total_m <= 0:
            m.total_m = max(m.plan.length_m, 1e-6)
        self._set_phase("navigating")
        return stop

    def _door_closed(self, door_id: str | None) -> None:
        """門關著：走到門前停下再回報（ADR-0002 §5.3）。已經在門前就直接回報。"""
        m = self.mission
        if door_id is None or door_id not in self.map.doors:
            self._fail("blocked", {"replans": m.replans})
            return
        self.closed_doors.add(door_id)
        if m.door_fail is not None:  # 連走到門前都做不到
            self._fail("door_closed", {"door": m.door_fail})
            return
        from .planner import topo_route

        door = self.map.doors[door_id]
        pose = self.loc.pose
        here = self.map.room_at(pose.x, pose.y)
        side = None
        for room in door.between:
            if here is not None and topo_route(self.map, here, room, self.closed_doors) is not None:
                side = room
                break
        if side is None:
            self._fail("door_closed", {"door": door_id})
            return
        rc = self.map.rooms[side].center
        d = self.cfg.door_standoff_m
        if door.axis == "x":
            sgn = 1.0 if rc[1] > door.center[1] else -1.0
            stand = (door.center[0], door.center[1] + sgn * d)
            yaw = -sgn * math.pi / 2
        else:
            sgn = 1.0 if rc[0] > door.center[0] else -1.0
            stand = (door.center[0] + sgn * d, door.center[1])
            yaw = math.pi if sgn > 0 else 0.0
        m.door_fail = door_id
        if math.hypot(stand[0] - pose.x, stand[1] - pose.y) < 0.25:
            self._fail("door_closed", {"door": door_id})
            return
        m.goal = Pose2D(stand[0], stand[1], yaw)
        m.goal_yaw = yaw
        m.strikes = 0
        self._set_phase("planning")

    def _door_blocked_on_route(self) -> str | None:
        """目前路線（拓撲層）會經過的門裡，有沒有哪一扇的門口整個被擋住、穿不過去。"""
        m = self.mission
        pose = self.loc.pose
        ra, rb = self.map.room_at(pose.x, pose.y), self.map.room_at(m.goal.x, m.goal.y)
        if not ra or not rb:
            return None
        from .planner import topo_route

        route = topo_route(self.map, ra, rb, self.closed_doors) or []
        for d in route:
            if not self.cm.door_passable(d):
                return d.id
        return None

    # ---------------------------------------------------------------- 路徑追蹤
    def _ingest_obstacles(self, frame: SensorFrame) -> tuple[bool, bool]:
        """把障礙點放進動態圖層。回傳（有沒有新的動態障礙, 正前方緊急停止區有沒有東西）。

        緊急停止區直接用機身座標的點判斷，不靠定位。放進地圖的動態圖層則要定位夠準才做：
        位置估錯時，牆會被當成「地圖上沒有的障礙」，進而誤判成門關著或被擋住。
        """
        cfg = self.cfg
        pose = self.loc.pose
        new = False
        in_zone = False
        self.cm.expire(self.t)
        trust = self.loc.confident
        for bx, by in frame.obstacles:
            if cfg.stop_zone_x[0] <= bx <= cfg.stop_zone_x[1] and abs(by) <= cfg.stop_zone_half_w:
                in_zone = True
            if trust:
                x, y = to_map(pose, bx, by)
                if self.cm.add_obstacle(x, y, self.t):
                    new = True
        return new, in_zone

    def _path_blocked(self) -> bool:
        m = self.mission
        pts = m.plan.points
        pose = self.loc.pose
        prev = (pose.x, pose.y)
        for p in pts[m.seg + 1 :] if m.seg + 1 < len(pts) else pts[-1:]:
            # 只看動態障礙：靜態地圖在規劃時已經考慮過。
            n = max(2, int(math.hypot(p[0] - prev[0], p[1] - prev[1]) / 0.03))
            for i in range(n + 1):
                t = i / n
                if self.cm.dynamic_xy(prev[0] + (p[0] - prev[0]) * t, prev[1] + (p[1] - prev[1]) * t):
                    return True
            prev = p
        return False

    def _carrot(self, pose: Pose2D):
        """沿路徑往前的目標點（離鴨子約 lookahead）。同時推進目前所在的線段。回傳（目標點, 到終點的路徑長）。"""
        m = self.mission
        pts = m.plan.points
        L = self.cfg.lookahead_m

        def project(i):
            a, b = pts[i], pts[i + 1]
            ab = (b[0] - a[0], b[1] - a[1])
            l2 = ab[0] ** 2 + ab[1] ** 2
            t = 0.0 if l2 < 1e-12 else max(0.0, min(1.0, ((pose.x - a[0]) * ab[0] + (pose.y - a[1]) * ab[1]) / l2))
            p = (a[0] + ab[0] * t, a[1] + ab[1] * t)
            return p, t, math.hypot(pose.x - p[0], pose.y - p[1])

        if len(pts) < 2:
            return pts[-1], 0.0
        # 推進線段：往前看幾段，取投影最近的那一段（不往回退）。
        best_i, best_d = m.seg, None
        for i in range(m.seg, min(m.seg + 4, len(pts) - 1)):
            _, t, d = project(i)
            if best_d is None or d < best_d - 1e-6:
                best_i, best_d = i, d
        m.seg = min(best_i, len(pts) - 2)
        proj, t, _ = project(m.seg)
        if t >= 1.0 and m.seg < len(pts) - 2:
            m.seg += 1
            proj, t, _ = project(m.seg)
        remaining = math.hypot(pts[m.seg + 1][0] - proj[0], pts[m.seg + 1][1] - proj[1]) + sum(
            math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(pts[m.seg + 1 :], pts[m.seg + 2 :])
        )
        # 從投影點沿路徑往前找第一個離鴨子至少 L 的點。
        cur, i = proj, m.seg + 1
        target = pts[-1]
        while i < len(pts):
            nxt = pts[i]
            if math.hypot(nxt[0] - pose.x, nxt[1] - pose.y) >= L:
                # 在 cur→nxt 上二分找離鴨子剛好 L 的點。
                lo, hi = 0.0, 1.0
                for _ in range(20):
                    mid = (lo + hi) / 2
                    q = (cur[0] + (nxt[0] - cur[0]) * mid, cur[1] + (nxt[1] - cur[1]) * mid)
                    if math.hypot(q[0] - pose.x, q[1] - pose.y) >= L:
                        hi = mid
                    else:
                        lo = mid
                target = (cur[0] + (nxt[0] - cur[0]) * hi, cur[1] + (nxt[1] - cur[1]) * hi)
                break
            cur = nxt
            i += 1
        return target, remaining

    def _steer(self, pose: Pose2D, target, allow_forward: bool = True):
        """朝目標點走：角度差大就原地轉，否則前進並用轉向修正。"""
        cfg, g = self.cfg, self.gait
        e = wrap(math.atan2(target[1] - pose.y, target[0] - pose.x) - pose.yaw)
        if self._turning:
            if abs(e) < cfg.turn_exit:
                self._turning = False
        elif abs(e) > cfg.turn_enter:
            self._turning = True
        if self._turning:
            mag = g.TURN_CMD if abs(e) > 0.6 else g.TURN_CMD_FINE
            return (0.0, 0.0, math.copysign(mag, e))
        if not allow_forward:
            return (0.0, 0.0, 0.0)
        return (g.FWD_CMD, 0.0, max(-1.0, min(1.0, cfg.k_heading * e)))

    def _replan(self, why: str) -> None:
        """路被新看到的障礙擋住：重新規劃。

        規劃得出新路就不算失敗（障礙通常是一點一點被看到的）；真的沒路時由 `_plan_step` 累計次數。
        同一個地方重新規劃太多次（一直繞不過去）也當成被擋住。
        """
        m, cfg = self.mission, self.cfg
        pose = self.loc.pose
        m.replans += 1
        if m.replan_at is not None and math.hypot(pose.x - m.replan_at[0], pose.y - m.replan_at[1]) < 0.4:
            m.replans_here += 1
        else:
            m.replans_here = 1
            m.replan_at = (pose.x, pose.y)
        if why == "stop_zone":
            m.strikes += 1
        if m.replans_here > cfg.max_replans_same_spot or m.strikes > cfg.max_replans:
            door = self._door_blocked_on_route()
            if door is not None:
                self._door_closed(door)
            else:
                self._fail("blocked", {"replans": m.replans, "detail": why})
            return
        self._replan_wait_until = self.t + 0.6
        self._set_phase("planning")

    def _navigate_step(self, frame: SensorFrame):
        cfg, m = self.cfg, self.mission
        pose = self.loc.pose
        stop = (0.0, 0.0, 0.0)
        if self.loc.reinit_count != self._reinit_seen:
            # 剛重新定位（被搬動過）：之前用錯的位置記下的障礙與關門判斷都不可信。
            self._reinit_seen = self.loc.reinit_count
            self.cm.dynamic.clear()
            self.cm._rebuild()
            self.closed_doors.clear()
            m.strikes, m.replan_at, m.door_fail = 0, None, m.door_fail
            self._set_phase("planning")
            return stop
        new_obs, in_zone = self._ingest_obstacles(frame)
        if new_obs:
            self._path_dirty = True
        if self._path_dirty and self.t >= self._replan_wait_until:
            self._path_dirty = False
            if self._path_blocked():
                self._replan("path_blocked")
                return stop
        target, remaining = self._carrot(pose)
        total = max(m.total_m, 1e-6)
        frac = 1.0 - remaining / total
        m.progress = max(m.progress, min(0.99, frac)) if m.kind == "go_to" else max(m.progress, min(0.7, 0.7 * frac))
        d_goal = math.hypot(m.goal.x - pose.x, m.goal.y - pose.y)
        if m.seg >= len(m.plan.points) - 2 and d_goal < cfg.arrive_tol_m:
            self._set_phase("final_turn")
            return stop
        cmd = self._steer(pose, target, allow_forward=not in_zone)
        # 緊急停止區有東西：不前進（可以原地轉）；等太久就重新規劃。
        if in_zone and cmd[0] == 0.0 and cmd[2] == 0.0:
            if self._stopzone_since is None:
                self._stopzone_since = self.t
            elif self.t - self._stopzone_since > cfg.stop_zone_wait_s:
                self._stopzone_since = None
                self._replan("stop_zone")
                return stop
        else:
            self._stopzone_since = None
        return cmd

    def _final_turn_step(self):
        m = self.mission
        pose = self.loc.pose
        stop = (0.0, 0.0, 0.0)
        if m.goal_yaw is None:
            self._arrived()
            return stop
        e = wrap(m.goal_yaw - pose.yaw)
        if abs(e) < self.cfg.final_yaw_tol or self.t - self._phase_t0 > 25.0:
            self._arrived()
            return stop
        mag = self.gait.TURN_CMD if abs(e) > 0.6 else self.gait.TURN_CMD_FINE
        return (0.0, 0.0, math.copysign(mag, e))

    def _arrived(self) -> None:
        m = self.mission
        if m.door_fail is not None:
            self._fail("door_closed", {"door": m.door_fail})
        elif m.kind == "go_to":
            self._done({"uncertainty_m": round(self.loc.pos_sigma, 3)})
        else:
            self._set_phase("dock_approach")

    # ---------------------------------------------------------------- 回充
    def _dock_xy(self) -> tuple[float, float]:
        """機身原點在充電座座標的位置（x：離觸點平面的距離，往房間為正；y：往充電座的左邊為正）。"""
        return to_body(self.map.dock.pose, self.loc.pose.x, self.loc.pose.y)

    def _turn_shift(self) -> tuple[float, float]:
        """原地轉 180°（順時針、TURN_CMD）時機身原點的位移，以轉身前的機身座標表示（前, 左）。

        由步態反應表推算：原地轉其實是繞著機身原點以外的一點在轉。回充時把這段位移預先補掉。
        """
        vx, vy, w = self.gait.response(0.0, -self.gait.TURN_CMD)
        if abs(w) < 1e-6:
            return (0.0, 0.0)
        cx, cy = -vy / w, vx / w  # 轉動中心（機身座標）
        return (2 * cx, 2 * cy)

    def _back_drift_ratio(self) -> float:
        """倒退時每退 1 m 往機身左邊滑多少 m（步態反應表；負值是往右）。"""
        vx, vy, _ = self.gait.response(self.gait.BACK_CMD, self._back_trim_w())
        return vy / abs(vx) if abs(vx) > 1e-6 else 0.0

    def _back_trim_w(self) -> float:
        """倒退時讓實際偏航角速度為 0 的轉向指令（步態反應表在轉向指令 0 時不一定走直線）。"""
        if getattr(self, "_trim_w", None) is None:
            lo, hi = -0.3, 0.3
            f = lambda w: self.gait.response(self.gait.BACK_CMD, w)[2]  # noqa: E731
            if f(lo) * f(hi) > 0:
                self._trim_w = 0.0
            else:
                for _ in range(30):
                    mid = (lo + hi) / 2
                    if f(lo) * f(mid) <= 0:
                        hi = mid
                    else:
                        lo = mid
                self._trim_w = (lo + hi) / 2
        return self._trim_w

    def _dock_pre_turn_offset(self) -> float:
        """轉身前要站在充電座中線的哪一側（充電座座標的 y，m）。

        面向充電座時自己的左邊是 −Y_dock：轉身會往左移 `shift_left`；轉身後面朝外，左邊是 +Y_dock，
        倒退 `staging_distance_m` 會再滑 `drift_ratio × 距離`。兩段都預先補掉，倒退到底時剛好在中線。
        """
        _, shift_left = self._turn_shift()
        return shift_left - self._back_drift_ratio() * self.map.dock.staging_distance_m + self.cfg.dock_lateral_trim_m

    def _dock_approach_step(self, frame: SensorFrame):
        """面向充電座、看著標籤，沿充電座中線往前走到預備點，把左右誤差收斂掉。

        追的線不是正中線，而是預先偏掉「轉身 180° 會造成的橫向位移」，轉完剛好落在中線上。
        """
        cfg, dock = self.cfg, self.map.dock
        xd, yd = self._dock_xy()
        e = wrap(self.loc.pose.yaw - wrap(dock.pose.yaw + math.pi))
        self.mission.progress = max(self.mission.progress, 0.75)
        shift_fwd, _ = self._turn_shift()
        y_ref = self._dock_pre_turn_offset()
        err = yd - y_ref
        # 前進時步態也有固定的側滑：用「蟹行角」前饋抵銷，否則橫向誤差收不到 0。
        vx_f, vy_f, _ = self.gait.response(self.gait.FWD_CMD, 0.0)
        crab = -math.atan2(vy_f, vx_f) if abs(vx_f) > 1e-6 else 0.0
        if xd <= BASE_TO_CONTACT_M + dock.staging_distance_m + shift_fwd:
            self._set_phase("dock_settle")  # 先停下站穩，讓標籤觀測把位置收斂，再檢查對位
            return (0.0, 0.0, 0.0)
        des = crab + max(-cfg.dock_max_heading, min(cfg.dock_max_heading, cfg.dock_k_y * err))
        w = max(-1.0, min(1.0, cfg.dock_k_h * (des - e)))
        return (self.gait.FWD_CMD, 0.0, w)

    def _dock_turn_step(self):
        """原地轉 180°，背對充電座。角度靠陀螺儀（定位的偏航）；快到時提早放掉指令，讓它自己滑到位。"""
        cfg = self.cfg
        e = wrap(self.map.dock.pose.yaw - self.loc.pose.yaw)
        self.mission.progress = max(self.mission.progress, 0.85)
        coast = abs(self._v_est[2]) * cfg.dock_turn_coast_s + 0.03
        if abs(e) <= coast or self.t - self._phase_t0 > 30.0:
            self._set_phase("dock_settle2")
            return (0.0, 0.0, 0.0)
        mag = self.gait.TURN_CMD if abs(e) > 0.9 else self.gait.TURN_CMD_FINE
        # 一開始固定往順時針轉（位移用步態反應表預先補過），接近目標後依誤差方向修正。
        sign = -1.0 if abs(e) > 2.0 else math.copysign(1.0, e)
        return (0.0, 0.0, sign * mag)

    def _dock_back_step(self, frame: SensorFrame):
        """倒退進座。鏡頭看不到充電座，位置靠陀螺儀航向＋步態反應表推算（ADR-0004 §2.2）。

        倒退時的轉向很弱，而且一轉向機身會先往同一側滑（模擬量測），所以只做小幅修正：
        航向目標限制在 ±dock_back_heading 內，靠近導引座開口就只維持航向。
        """
        cfg = self.cfg
        xd, yd = self._dock_xy()
        e = wrap(self.loc.pose.yaw - self.map.dock.pose.yaw)
        self.mission.progress = max(self.mission.progress, 0.9)
        if frame.charging is True:
            self._emit("docked", None, {"place": self.map.dock.place})
            self._emit("charging_started", None, {"signal": "mock" if frame.charging_mock else "electrical"})
            self._done({"charging": True, "charging_signal_mock": bool(frame.charging_mock), "attempts": self.mission.dock_attempts})
            return (0.0, 0.0, 0.0)
        if xd < BASE_TO_CONTACT_M - cfg.dock_overrun_m or self.t - self._phase_t0 > 40.0:
            # 推算的位置已經超過觸點平面，卻沒有充電訊號：沒對準，或訊號沒來。
            self._retreat_or_fail("no_charging_signal")
            return (0.0, 0.0, 0.0)
        gap = xd - BASE_TO_CONTACT_M
        # 倒退時，車頭往左偏（e > 0）會讓機身往 −Y 走；yd > 0 時要 e > 0。
        lim = cfg.dock_back_heading if gap > cfg.dock_back_hold_m else 0.0
        # 控制的是「照目前的側滑退到底時會停在哪裡」，不是現在的橫向位置。
        y_final = yd + self._back_drift_ratio() * max(gap, 0.0)
        des = max(-lim, min(lim, cfg.dock_back_k_y * y_final))
        w = max(-0.3, min(0.3, self._back_trim_w() + cfg.dock_back_k_h * (des - e)))
        return (self.gait.BACK_CMD, 0.0, w)

    def _retreat_or_fail(self, why: str) -> None:
        m = self.mission
        if m.dock_attempts >= self.cfg.dock_max_attempts:
            self._fail("dock_failed", {"detail": why, "attempts": m.dock_attempts})
            return
        self._emit("mission_progress", None, {"kind": m.kind, "phase": "dock_retry", "detail": why, "attempt": m.dock_attempts, "progress": round(m.progress, 3)})
        self._set_phase("dock_retreat")

    def _dock_retreat_step(self):
        """往前走出充電座、回到對位起點重來。"""
        xd, yd = self._dock_xy()
        facing_out = abs(wrap(self.loc.pose.yaw - self.map.dock.pose.yaw)) < math.pi / 2
        if xd >= self.cfg.dock_far_m - 0.1 or self.t - self._phase_t0 > 30.0:
            self._set_phase("planning")
            return (0.0, 0.0, 0.0)
        if facing_out:
            e = wrap(self.loc.pose.yaw - self.map.dock.pose.yaw)
            return (self.gait.FWD_CMD, 0.0, max(-0.6, min(0.6, -self.cfg.dock_k_h * e)))
        e = wrap(self.loc.pose.yaw - wrap(self.map.dock.pose.yaw + math.pi))
        return (self.gait.BACK_CMD, 0.0, max(-0.6, min(0.6, -self.cfg.dock_k_h * e)))
