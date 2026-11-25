"""duckd 核心：duck-link 訊息處理與每圈的控制。

不做 I/O（WebSocket 在 `link.py`、硬體在身體後端），時間由呼叫端傳入，所以整個流程可以單元測試。
對外四個入口，全部回傳「要送給 Nous 的訊息」清單：

- `on_open(now)`：連上了 → `hello`，加上斷線期間累積的事件（例如 `link_lost`）。
- `on_text(text, now)`：收到一則訊息 → 心跳回聲、`ack`（每個 command 恰好一個）。
- `tick(now)`：50 Hz 控制迴圈的一圈 → 事件、每秒一次 `state`。
- `on_close(now)`：斷線。

duck-link 的指令處理裡**沒有**關扭力、解除緊急停止、接手／釋放硬體；那些只有本機入口
（`engage`、`begin_release`、`local_estop`、`local_clear_estop`）。
"""
from __future__ import annotations

import json
import logging
import math
import threading
from collections import OrderedDict, deque
from pathlib import Path

from . import SOFTWARE
from .arbiter import Decision, SafetyArbiter
from .body import BodyReading, EngageError
from .gestures import GestureLibrary, GesturePlayer
from .limits import HEAD_JOINTS
from .presence import EXPRESSION, PresenceState, head_target
from .protocol import PROTOCOL_VERSION, Protocol

log = logging.getLogger("duckd.core")

STATE_PERIOD_S = 1.0
DEDUPE_SIZE = 256
RELEASE_TIMEOUT_S = 8.0
TRACK_FRESH_S = 0.5  # 觀測超過這麼久就不拿來用
TRACK_LOST_S = 2.0  # 這麼久沒有觀測 → tracking_lost
TRACK_GAIN = 0.6
MISSION_ACTIONS = ("where", "places", "go_to", "find_person", "return_home", "follow_me", "wait_here")


class Duckd:
    def __init__(
        self,
        protocol: Protocol,
        body,
        arbiter: SafetyArbiter,
        library: GestureLibrary,
        *,
        eyes=None,
        percept=None,
        duck_id: str = "duck1",
        hardware_profile: str = "stock_head_direct_hold",
        allow_unverified_gestures: bool = False,
        head_reason: str = "direct head control; full range not verified on hardware",
    ):
        self.protocol = protocol
        self.body = body
        self.arbiter = arbiter
        self.library = library
        self.eyes = eyes
        self.percept = percept
        self.duck_id = duck_id
        self.hardware_profile = hardware_profile
        self.allow_unverified_gestures = allow_unverified_gestures
        self.head_reason = head_reason
        self.lock = threading.RLock()
        self.connected = False
        self.peer: dict | None = None
        self.player = GesturePlayer()
        self.presence = PresenceState()
        self.presence_motion = False
        self.tracking = "none"
        self._track_until = math.inf
        self._track_acquired = False
        self._track_seen = -math.inf
        self.reading = BodyReading()
        self._home: dict[str, float] | None = None
        self._releasing_until: float | None = None
        self._acks: OrderedDict[str, dict] = OrderedDict()
        self._backlog: deque = deque(maxlen=50)
        self._out: list[dict] = []
        self._event_n = 0
        self._last_state = -math.inf
        self._state_dirty = False
        self._last_tick: float | None = None
        self._hz_t0: float | None = None
        self._hz_n = 0
        self.loop_hz = 0.0
        self.overruns = 0
        self.invalid_messages = 0
        self.stats = {"commands": 0, "heartbeats": 0}
        # 量測用：動作指令被接受 → 仲裁器第一次送出不同的頭部設定值，中間隔多久（ms）
        self._latency_from: float | None = None
        self._prev_head_out: dict[str, float] | None = None
        self.motion_latency_ms: deque = deque(maxlen=50)

    # ================================================================ 輸出
    def _flush(self) -> list[dict]:
        out, self._out = self._out, []
        return out

    def _event(self, name: str, **fields) -> None:
        self._event_n += 1
        msg = self.protocol.make("event", event=name, event_id=f"e_{self._event_n:06d}", **fields)
        (self._out if self.connected else self._backlog).append(msg)

    # ================================================================ 能力
    def capabilities(self) -> dict:
        r = self.reading
        caps: dict[str, dict] = {}

        def put(name: str, status: str, reason: str | None = None) -> None:
            caps[name] = {"status": status, **({"reason": reason[:120]} if reason else {})}

        put("walk", "unsupported", self.arbiter.walk_unsupported_reason or "gait host not integrated")
        if not r.engaged:
            put("head", "unsupported", "servo bus not engaged (needs local engage)")
            put("battery", "unsupported", "servo bus not engaged")
        elif self.body.mock:
            put("head", "mock")
            put("battery", "mock")
        else:
            put("head", "degraded", self.head_reason)
            put("battery", "degraded", "voltage read from head servos only; no charge sensing")
        put("antennas", "unsupported", "antenna servos not installed")
        if self.eyes is None:
            put("eyes", "unsupported", "GC9A01 panels not installed; renderer not running")
        else:
            put("eyes", "mock", "virtual panel only (PNG preview); GC9A01 panels not installed")
        put("speaker", "unsupported", "audio is not wired into duckd yet")
        put("microphone", "unsupported", "no microphone")
        put("camera", "unsupported", "no camera")
        for kind in ("face", "sound"):
            obs = self.percept.get(kind, 5.0) if self.percept else None
            if obs is None:
                put(f"tracking_{kind}", "unsupported", "no perception source is feeding duckd")
            elif obs.mock:
                put(f"tracking_{kind}", "mock", "perception source is synthetic")
            else:
                put(f"tracking_{kind}", "degraded", "not verified on hardware")
        put("navigation", "unsupported", "navigation is not integrated into duckd yet")
        put("dock", "unsupported", "no dock")
        put("imu", "unsupported", "BNO055 not calibrated; not read by duckd")
        put("feet", "unsupported", "feet switches not wired")
        return caps

    def listed_gestures(self) -> list[str]:
        if not self.reading.engaged:
            return []
        return self.library.listed(self.hardware_profile, self.allow_unverified_gestures)

    def _hello(self) -> dict:
        return self.protocol.make(
            "hello",
            role="duck",
            software=SOFTWARE,
            duck_id=self.duck_id,
            mock=bool(self.body.mock),
            capabilities=self.capabilities(),
            gestures=self.listed_gestures(),
            expressions=self.eyes.expressions if self.eyes else [],
            sounds=[],
        )

    def _mode(self) -> str:
        if self.arbiter.estop_reason:
            return "estop"
        if self.arbiter.fallen:
            return "fallen"
        # limp＝duckd 沒有接手任何舵機（不代表舵機沒出力：可能有別的程式讓它出力中）
        return "holding" if self.reading.engaged else "limp"

    def state_fields(self) -> dict:
        r, a = self.reading, self.arbiter
        faults = list(r.faults)
        if a.estop_reason:
            faults.append("estop_latched")
        fields: dict = {
            "mock": bool(self.body.mock),
            "mode": self._mode(),
            "control_source": "duck_link" if (a.lease_ok and r.engaged) else "none",
            "capabilities": self.capabilities(),
            "faults": faults,
            "presence": self.presence.state,
            "tracking": self.tracking,
            "velocity_cmd": {"vx": a.vel_cmd[0], "vy": a.vel_cmd[1], "yaw_rate": a.vel_cmd[2], "remaining_s": 0.0},
            "battery": {"voltage_v": r.voltage_v, "source": "servo_bus", "charging": None} if r.voltage_v else {"source": "none", "charging": None},
            "tilt_deg": None,
            "mission": None,
            "location": None,
            "link": {"lease_ok": a.lease_ok, "rtt_ms": None},  # 往返時間由 Nous 端用心跳回聲量
            "loop": {"hz": round(self.loop_hz, 1), "overruns": self.overruns},
        }
        if self.eyes is not None:
            fields["expression"] = self.eyes.expression
        if r.head is not None:
            fields["head"] = {n: round(r.head[n], 4) for n in HEAD_JOINTS}
            fields["head"]["age_ms"] = int(r.head_age_ms or 0)
        temp: dict = {}
        if r.servo_temp_max_c is not None:
            temp["servo_max"] = r.servo_temp_max_c
        cpu = _cpu_temp()
        if cpu is not None:
            temp["cpu"] = cpu
        if temp:
            fields["temperature_c"] = temp
        return fields

    # ================================================================ 連線
    def on_open(self, now: float) -> list[dict]:
        with self.lock:
            self.connected = True
            self._out.append(self._hello())
            while self._backlog:
                self._out.append(self._backlog.popleft())
            self._state_dirty = True
            return self._flush()

    def on_close(self, now: float) -> None:
        with self.lock:
            self.connected = False
            self.peer = None
            self._out.clear()
            self.arbiter.link_down(now)

    # ================================================================ 收訊息
    def on_text(self, text: str, now: float, received_at: float | None = None) -> list[dict]:
        with self.lock:
            try:
                msg = json.loads(text)
            except (ValueError, TypeError):
                self.invalid_messages += 1
                return self._flush()
            errors = self.protocol.errors(msg)
            if errors:
                self.invalid_messages += 1
                if isinstance(msg, dict) and msg.get("type") == "command" and isinstance(msg.get("request_id"), str):
                    why = "protocol_version" if msg.get("protocol_version") != PROTOCOL_VERSION else errors[0]
                    self._ack(msg["request_id"], Decision(False, "invalid", why[:200]))
                return self._flush()
            kind = msg["type"]
            if kind == "heartbeat":
                if "echo_of" not in msg:
                    self.stats["heartbeats"] += 1
                    self.arbiter.heartbeat(now)
                    self._out.append(self.protocol.make("heartbeat", seq=msg["seq"], echo_of=msg["seq"]))
            elif kind == "hello":
                if msg.get("role") == "nous":
                    self.peer = {"software": msg.get("software"), "mock": msg.get("mock", False)}
            elif kind == "command":
                self._command(msg, now, now if received_at is None else received_at)
            # ack／state／event 是鴨子送的；Nous 送來就忽略
            return self._flush()

    def _ack(self, request_id: str, d: Decision, data: dict | None = None) -> None:
        ack = self.protocol.make(
            "ack",
            request_id=request_id,
            status="accepted" if d.accepted else "rejected",
            reason=None if d.accepted else (d.reason or "internal"),
            detail=d.detail,
            applied=d.applied,
            clamped=True if d.clamped else None,
            data=data,
        )
        self._acks[request_id] = ack
        while len(self._acks) > DEDUPE_SIZE:
            self._acks.popitem(last=False)
        self._out.append(ack)

    def _command(self, msg: dict, now: float, received_at: float) -> None:
        rid = msg["request_id"]
        if rid in self._acks:  # 重複的 request_id：回原本的 ack，不再執行
            self._out.append(self._acks[rid])
            return
        self.stats["commands"] += 1
        action, params, ttl_ms = msg["action"], msg.get("params") or {}, msg["ttl_ms"]
        if now - received_at > ttl_ms / 1000.0:
            self._ack(rid, Decision(False, "expired"))
            return
        try:
            handler = getattr(self, f"_do_{action}", None)
            if handler is None:
                d, data = Decision(False, "unsupported", f"{action}: not implemented in duckd"), None
            else:
                result = handler(params, ttl_ms, now, rid)
                d, data = result if isinstance(result, tuple) else (result, None)
        except Exception:  # noqa: BLE001 指令處理出錯也要回恰好一個 ack
            log.exception("處理 %s 失敗", action)
            d, data = Decision(False, "internal"), None
        self._ack(rid, d, data)
        if d.accepted:
            self._state_dirty = True
            if action in ("look", "gesture"):
                self._latency_from = now

    # ---------------------------------------------------------------- 各動作
    def _do_status(self, params, ttl_ms, now, rid):
        return Decision(True), self.state_fields()

    def _do_stop(self, params, ttl_ms, now, rid):
        d = self.arbiter.stop(now)
        self._cancel_gesture("stop")
        self.presence_motion = False
        self._end_tracking()
        return d

    def _do_resume(self, params, ttl_ms, now, rid):
        return self.arbiter.resume(now)

    def _do_walk(self, params, ttl_ms, now, rid):
        return self.arbiter.request_walk(params, ttl_ms, now)

    def _busy_head(self) -> Decision | None:
        if self._releasing_until is not None:
            return Decision(False, "unsupported", "head is being released")
        return None

    def _do_look(self, params, ttl_ms, now, rid):
        busy = self._busy_head()
        if busy:
            return busy
        d = self.arbiter.request_look(params, ttl_ms, now)
        if d.accepted:
            self._cancel_gesture("interrupted")
            self.presence_motion = False  # 明確的 look 蓋過 presence 的頭部編排，直到 presence 狀態改變
            self._end_tracking()
        return d

    def _do_gesture(self, params, ttl_ms, now, rid):
        name = params["name"]
        g = self.library.gestures.get(name)
        if g is None:
            return Decision(False, "unknown_name", f"gesture {name}")
        busy = self._busy_head()
        if busy:
            return busy
        if not self.arbiter.head_enabled:
            return Decision(False, "unsupported", "head is not engaged")
        if name not in self.listed_gestures():
            return Decision(False, "unsupported", f"gesture {name} is not verified on hardware profile {self.hardware_profile}")
        gate = self.arbiter.check_motion(now)
        if gate:
            return gate
        if self.player.active:
            # ADR-0011 §2.4：一次只做一個。協定的 reason 還沒有 busy，先用 invalid＋detail（見 protocol/proposals）
            return Decision(False, "invalid", f"busy: gesture {self.player.gesture.id} in progress")
        self.player.start(g, rid, now)
        self._end_tracking()
        return Decision(True, applied={"name": name, "duration_s": round(g.duration_s, 3)})

    def _do_express(self, params, ttl_ms, now, rid):
        if self.eyes is None:
            return Decision(False, "unsupported", "eyes: no panel or renderer")
        name = params["expression"]
        if not self.eyes.known(name):
            return Decision(False, "unknown_name", f"expression {name}")
        if not self.eyes.can_request(name):
            return Decision(False, "unsupported", f"expression {name} is local-only (reflects real duck state)")
        self.eyes.express(name, params.get("duration_s"))
        return Decision(True, applied=dict(params))

    def _do_antennas(self, params, ttl_ms, now, rid):
        return Decision(False, "unsupported", "antennas: servos not installed")

    def _do_sound(self, params, ttl_ms, now, rid):
        return Decision(False, "unsupported", "sound: audio is not wired into duckd yet")

    def _do_presence(self, params, ttl_ms, now, rid):
        if not self.arbiter.lease_ok:
            return Decision(False, "link_degraded", "no heartbeat lease")
        changed = params["state"] != self.presence.state
        self.presence.set(params["state"], params.get("speech_level"), now)
        if changed:
            self.presence_motion = True
            if self.eyes is not None:
                self.eyes.clear_express()
        self._sync_eyes(now)
        applied = {"state": self.presence.state}
        if "speech_level" in params:
            applied["speech_level"] = params["speech_level"]
        return Decision(True, applied=applied)

    def _do_track(self, params, ttl_ms, now, rid):
        target = params["target"]
        if target == "none":
            self._end_tracking()
            return Decision(True, applied={"target": "none"})
        busy = self._busy_head()
        if busy:
            return busy
        if not self.arbiter.head_enabled:
            return Decision(False, "unsupported", "head is not engaged")
        if self.percept is None or self.percept.get(target, 5.0) is None:
            return Decision(False, "unsupported", f"tracking_{target}: no perception source is feeding duckd")
        gate = self.arbiter.check_motion(now)
        if gate:
            return gate
        self._cancel_gesture("interrupted")
        self.tracking = target
        self._track_until = now + float(params.get("timeout_s", 600.0))
        self._track_acquired = False
        self._track_seen = now
        wants_body = bool(params.get("body", False))
        # 轉身需要走路；走路還不支援，所以只動頭並回報被改掉
        return Decision(True, applied={"target": target, "body": False}, clamped=wants_body)

    def _do_cancel_mission(self, params, ttl_ms, now, rid):
        return Decision(False, "no_mission")

    def _do_mission_status(self, params, ttl_ms, now, rid):
        return Decision(False, "no_mission")

    def _mission_unsupported(self, params, ttl_ms, now, rid):
        return Decision(False, "unsupported", "navigation is not integrated into duckd yet")

    _do_where = _do_places = _do_go_to = _do_find_person = _mission_unsupported
    _do_return_home = _do_follow_me = _do_wait_here = _mission_unsupported

    # ================================================================ 本機入口（不在 duck-link 上）
    def engage(self, now: float) -> dict[str, float]:
        """接手身體（開匯流排、頭部出力）。失敗丟 EngageError。"""
        with self.lock:
            if self.arbiter.estop_reason:
                raise EngageError(f"緊急停止鎖定中：{self.arbiter.estop_reason}")
            actual = self.body.engage()
            self.arbiter.enable_head(actual)
            self._home = dict(actual)
            self.reading = self.body.read(now)
            self._event("capability_changed", data={"capability": "head", "status": self.capabilities()["head"]["status"]})
            self._state_dirty = True
            return actual

    def begin_release(self, now: float) -> bool:
        """開始釋放：頭先以限速回到接手時的位置，到位（或逾時）後恢復扭力狀態、放開匯流排。"""
        with self.lock:
            if not self.reading.engaged and not getattr(self.body, "engaged", False):
                return False
            self._cancel_gesture("interrupted")
            self._end_tracking()
            self.presence_motion = False
            self._releasing_until = now + RELEASE_TIMEOUT_S
            if self._home:
                self.arbiter.local_head_goal(self._home)
            return True

    def _finish_release(self, now: float) -> None:
        self._releasing_until = None
        try:
            self.body.release()
        finally:
            self.arbiter.disable_head()
            self.reading = self.body.read(now)
            self._event("capability_changed", data={"capability": "head", "status": "unsupported"})
            self._state_dirty = True

    @property
    def engaged(self) -> bool:
        return self.reading.engaged

    def local_estop(self, reason: str, now: float) -> None:
        with self.lock:
            self.arbiter.estop(reason, now)
            self._cancel_gesture("estop")
            self._end_tracking()
            if hasattr(self.body, "estop"):
                self.body.estop(reason)

    def local_clear_estop(self) -> bool:
        with self.lock:
            if hasattr(self.body, "reset_estop"):
                self.body.reset_estop()
            return self.arbiter.clear_estop_local()

    # ================================================================ 每圈
    def _cancel_gesture(self, reason: str) -> None:
        if self.player.active:
            name, rid, clamped = self.player.finish()
            self._event("gesture_done", request_id=rid, reason=reason, data={"name": name, "completed": False, "clamped": clamped})

    def _end_tracking(self, lost: bool = False) -> None:
        if self.tracking != "none":
            if lost:
                self._event("tracking_lost", data={"target": self.tracking})
            self.tracking = "none"

    def _sync_eyes(self, now: float) -> None:
        if self.eyes is None:
            return
        self.eyes.set_base(EXPRESSION[self.presence.state], camera_streaming=False)
        self.eyes.set_device(
            camera_streaming=False,  # 沒有鏡頭：真實狀態就是沒在串流
            conversation_active=self.arbiter.lease_ok and self.presence.state in ("wake", "listening", "thinking", "speaking"),
            needs_help=bool(self.arbiter.estop_reason or self.arbiter.fallen),
        )
        level = self.presence.level(now)
        self.eyes.set_inputs(level if self.presence.state == "speaking" else None, None)

    def _track_step(self, now: float) -> dict[str, float] | None:
        if now >= self._track_until:
            self._end_tracking()
            return None
        obs = self.percept.get(self.tracking, TRACK_FRESH_S) if self.percept else None
        if obs is None:
            if now - self._track_seen > TRACK_LOST_S:
                self._end_tracking(lost=True)
            return None
        if obs.received <= self._track_seen and self._track_acquired:
            return None  # 同一筆觀測只用一次
        self._track_seen = obs.received
        if not self._track_acquired:
            self._track_acquired = True
            self._event("tracking_acquired", data={"target": self.tracking, "mock": obs.mock})
        head = self.reading.head or self.arbiter.head_cmd
        if self.tracking == "face":  # 方位相對鏡頭光軸：在目前頭部角度上修正
            return {
                "head_yaw": head["head_yaw"] + TRACK_GAIN * obs.yaw,
                "head_pitch": head["head_pitch"] + TRACK_GAIN * obs.pitch,
            }
        return {"head_yaw": obs.yaw}  # sound：方位相對身體正前方

    def tick(self, now: float) -> list[dict]:
        with self.lock:
            dt = 0.02 if self._last_tick is None else min(max(now - self._last_tick, 0.0), 0.1)
            self._last_tick = now
            a = self.arbiter
            self.reading = r = self.body.read(now)
            if r.estop and not a.estop_reason:
                a.estop(r.estop, now)
                self._cancel_gesture("estop")
                self._end_tracking()
            a.set_block(*(r.block or (None, "")))

            if r.engaged and a.head_enabled:
                if self._releasing_until is not None:
                    # 沒出力就回不去：不等了，直接釋放
                    done = not r.head_torque or (
                        a.head_settled()
                        and (r.head is None or self._home is None or all(abs(r.head[n] - self._home[n]) < 0.03 for n in HEAD_JOINTS))
                    )
                    if done or now >= self._releasing_until or a.estop_reason:
                        self._finish_release(now)
                elif self.player.active:
                    targets, finished = self.player.sample(now)
                    full = {n: targets.get(n, 0.0) for n in HEAD_JOINTS}
                    ok, clamped = a.stream_head(full, now)
                    self.player.clamped |= clamped
                    if not ok:
                        self._cancel_gesture("interrupted" if a.lease_ok else "link_lost")
                    elif finished and (a.head_settled() or now - self.player.t0 > self.player.gesture.duration_s + 2.0):
                        name, rid, was_clamped = self.player.finish()
                        self._event("gesture_done", request_id=rid, data={"name": name, "completed": True, "clamped": was_clamped})
                elif self.tracking != "none":
                    targets = self._track_step(now)
                    if targets:
                        a.stream_head(targets, now)
                elif self.presence_motion:  # look 會把它關掉；presence 狀態改變才再打開
                    a.stream_head(head_target(self.presence, now), now)

            out = a.update(now, dt)
            for name, fields in out.events:
                if name == "link_lost":
                    self._cancel_gesture("link_lost")
                    self._end_tracking()
                    self.presence.set("idle", None, now)
                    self.presence_motion = False
                self._event(name, **fields)
                self._state_dirty = True
            self.body.step(out.head, out.velocity, now)
            if self._latency_from is not None and out.head and self._prev_head_out and out.head != self._prev_head_out:
                self.motion_latency_ms.append(round((now - self._latency_from) * 1000.0, 1))
                self._latency_from = None
            self._prev_head_out = out.head
            self._sync_eyes(now)

            self._hz_n += 1
            if self._hz_t0 is None:
                self._hz_t0 = now
            elif now - self._hz_t0 >= 1.0:
                self.loop_hz = self._hz_n / (now - self._hz_t0)
                self._hz_t0, self._hz_n = now, 0

            if self.connected and (self._state_dirty or now - self._last_state >= STATE_PERIOD_S):
                self._last_state, self._state_dirty = now, False
                self._out.append(self.protocol.make("state", **self.state_fields()))
            return self._flush()


def _cpu_temp() -> float | None:
    try:
        return round(int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000.0, 1)
    except (OSError, ValueError):
        return None
