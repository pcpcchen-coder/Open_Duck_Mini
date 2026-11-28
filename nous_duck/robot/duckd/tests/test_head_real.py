"""頭部實機後端（HeadBody）：用舵機控制台的**模擬匯流排**（mock）跑，不需要硬體。

重點是證明：不管上層怎麼用，都不會對腿部舵機（ID 10–14、20–24）寫入任何東西。
"""
import json
import math

import pytest
from conftest import make_harness

from duckd.body import EngageError
from duckd.head_real import HEAD_IDS, HeadBody, HeadOnlyBus, LegAccessBlocked
from duckd.limits import HEAD_JOINTS, LEG_SERVO_IDS, Limits

from servo_console.bus import MockBus  # 舵機控制台的模擬匯流排（mock）
from servo_console.controller import Controller

ALL_IDS = sorted(LEG_SERVO_IDS | HEAD_IDS)


class SpyBus(MockBus):
    """模擬匯流排＋記錄每一次寫入碰到的 ID。"""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.touched_write: set[int] = set()
        self.torque_calls: list[tuple[tuple[int, ...], bool]] = []
        self.kp_calls = 0

    def write_goals(self, goals):
        self.touched_write |= set(goals)
        super().write_goals(goals)

    def set_torque(self, ids, on):
        self.touched_write |= set(ids)
        self.torque_calls.append((tuple(ids), on))
        super().set_torque(ids, on)

    def set_kp(self, values):
        self.kp_calls += 1
        self.touched_write |= set(values)
        super().set_kp(values)


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def make_body(tmp_path, *, legs_on=True, head_on=False, port_users=lambda: [], limits=None, offsets=None):
    bus = SpyBus(ALL_IDS, start_deg={32: 3.0})
    for i in LEG_SERVO_IDS:
        bus.torque[i] = legs_on
    for i in HEAD_IDS:
        bus.torque[i] = head_on
    cfg = tmp_path / "duck_config.json"
    cfg.write_text(json.dumps({"joints_offsets": offsets or {"head_yaw": 0.0}}))
    clock = Clock()
    body = HeadBody(limits or Limits(), lambda: bus, cfg, port_users=port_users, clock=clock, mock=True)
    return body, bus, clock


def test_head_only_bus_blocks_every_leg_id():
    bus = HeadOnlyBus(SpyBus(ALL_IDS))
    bus.open()
    for leg in sorted(LEG_SERVO_IDS):
        for call in (
            lambda: bus.write_goals({leg: 0.0}),
            lambda: bus.write_goals({30: 0.0, leg: 0.0}),
            lambda: bus.set_torque([leg], True),
            lambda: bus.set_torque([leg], False),
            lambda: bus.read_positions([leg]),
            lambda: bus.read_status([30, leg]),
            lambda: bus.ping([leg]),
        ):
            with pytest.raises(LegAccessBlocked):
                call()
    with pytest.raises(LegAccessBlocked):
        bus.set_kp({30: 8})  # duckd 不寫 kp，頭也不寫
    assert bus._inner.touched_write == set() and bus._inner.kp_calls == 0
    bus.write_goals({30: 1.0, 33: -1.0})
    assert bus._inner.touched_write == {30, 33}


def test_controller_all_operations_only_reach_head(tmp_path):
    """舵機控制台的 Controller 只拿到 4 個頭部關節：它的「全部」（含緊急停止）就只有頭。"""
    body, bus, clock = make_body(tmp_path)
    body.engage()
    c: Controller = body.controller
    assert c.ids == [30, 31, 32, 33]
    c.set_targets({n: 0.1 for n in HEAD_JOINTS})
    for _ in range(50):
        clock.t += 0.02
        c.tick()
    c.estop("test")  # 「全部關扭力」
    assert bus.touched_write <= HEAD_IDS
    assert all(bus.torque[i] for i in LEG_SERVO_IDS)  # 腿的扭力沒變
    assert not any(bus.torque[i] for i in HEAD_IDS)
    with pytest.raises(Exception):
        c.set_targets({"left_knee": 0.5})  # Controller 根本不認得腿的關節


def test_full_session_never_writes_legs(tmp_path):
    """整段流程（接手、look、動作、presence、租約失效、緊急停止、釋放）之後，匯流排上只有頭被寫過。"""
    body, bus, clock = make_body(tmp_path)
    legs_before = {i: (bus.torque[i], bus.goal[i], bus.pos[i], bus.kp[i]) for i in LEG_SERVO_IDS}
    h = make_harness(body=body)

    def run(seconds):
        for _ in range(round(seconds / 0.02)):
            clock.t = h.t
            if h.heartbeats and h.t >= h._next_hb:
                h.heartbeat()
                h._next_hb = h.t + 0.5
            h.tick()
            h.t += 0.02

    run(0.2)
    assert h.cmd("look", {"head_yaw": 0.4, "head_pitch": -0.2, "duration_s": 1.0})["status"] == "accepted"
    run(1.5)
    assert h.cmd("look", {"head_yaw": 0.0, "head_pitch": 0.0})["status"] == "accepted"
    run(1.0)
    assert h.cmd("gesture", {"name": "nod"})["status"] == "accepted"
    run(3.5)
    assert h.events("gesture_done")[0]["data"]["completed"] is True
    h.cmd("presence", {"state": "thinking"})
    run(1.0)
    h.heartbeats = False
    run(2.0)
    h.heartbeats = True
    run(0.6)
    h.cmd("stop")
    h.cmd("walk", {"vx": 0.1, "duration_s": 1.0})
    h.core.local_estop("test", h.t)
    run(0.3)
    h.core.local_clear_estop()
    h.core.begin_release(h.t)
    run(1.0)
    assert not h.core.engaged and not bus.is_open
    assert bus.touched_write and bus.touched_write <= HEAD_IDS
    assert bus.kp_calls == 0
    assert legs_before == {i: (bus.torque[i], bus.goal[i], bus.pos[i], bus.kp[i]) for i in LEG_SERVO_IDS}
    assert body.bus.blocked == 0  # 沒有任何一次嘗試被擋：上層本來就沒去碰腿


def test_engage_enables_head_torque_without_jump_and_release_restores(tmp_path):
    body, bus, clock = make_body(tmp_path, head_on=False)
    actual = body.engage()
    assert actual["head_yaw"] == pytest.approx(math.radians(3.0), abs=0.002)
    assert all(bus.torque[i] for i in HEAD_IDS)
    assert bus.goal[32] == pytest.approx(3.0, abs=0.1)  # 開扭力前先寫目前位置
    assert bus.torque_calls == [((30, 31, 32, 33), True)]
    body.release()
    assert not any(bus.torque[i] for i in HEAD_IDS)  # 恢復成接手前（沒出力）
    assert not bus.is_open
    # 原本就在出力：接手不改、釋放也不改
    body, bus, clock = make_body(tmp_path, head_on=True)
    body.engage()
    body.release()
    assert bus.torque_calls == [] and all(bus.torque[i] for i in HEAD_IDS)


def test_engage_refuses_when_port_is_in_use(tmp_path):
    body, bus, _ = make_body(tmp_path, port_users=lambda: [(5872, "python -m servo_console")])
    with pytest.raises(EngageError, match="servo_console"):
        body.engage()
    assert not bus.is_open and bus.touched_write == set()
    h = make_harness(body=body, engage=False)
    with pytest.raises(EngageError):
        h.core.engage(h.t)
    assert h.cmd("look", {"head_yaw": 0.1})["reason"] == "unsupported"


def test_engage_refuses_when_a_head_servo_is_missing(tmp_path):
    body, bus, _ = make_body(tmp_path)
    bus.missing = {31}
    with pytest.raises(EngageError, match="31"):
        body.engage()
    assert not bus.is_open and bus.touched_write == set()


def test_offsets_from_duck_config_are_applied(tmp_path):
    body, bus, clock = make_body(tmp_path, offsets={"head_yaw": 0.072})
    actual = body.engage()
    assert actual["head_yaw"] == pytest.approx(math.radians(3.0) - 0.072, abs=0.002)  # 關節角度＝舵機角度−偏移


def test_real_head_through_core_tracks_target_and_reports_readback(tmp_path):
    body, bus, clock = make_body(tmp_path, limits=Limits(head_window=math.radians(15)))
    h = make_harness(body=body, limits=Limits(head_window=math.radians(15)))
    home = h.core._home["head_yaw"]
    ack = h.cmd("look", {"head_yaw": 1.0}, ttl_ms=60000)
    assert ack["clamped"] and ack["applied"]["head_yaw"] == pytest.approx(home + math.radians(15), abs=1e-4)
    for _ in range(100):
        clock.t = h.t
        h.heartbeat() if _ % 25 == 0 else None
        h.tick()
        h.t += 0.02
    st = h.last_state()
    assert st["mock"] is True  # 模擬匯流排：一定要標 mock
    assert st["head"]["head_yaw"] == pytest.approx(home + math.radians(15), abs=0.01)
    assert st["battery"]["source"] == "servo_bus" and st["battery"]["voltage_v"] == pytest.approx(8.1)
    assert st["temperature_c"]["servo_max"] == 30
    # 送到匯流排的目標每圈最多 0.6°（30°/s × 20 ms）
    yaw = [w[32] for w in bus.writes if 32 in w]
    assert max(abs(b - a) for a, b in zip(yaw, yaw[1:])) <= 0.6 + 1e-6


def test_overheat_and_low_voltage_refuse_new_motion(tmp_path):
    body, bus, clock = make_body(tmp_path)
    h = make_harness(body=body)

    def run(seconds):
        for i in range(round(seconds / 0.02)):
            clock.t = h.t
            if i % 25 == 0:
                h.heartbeat()
            h.tick()
            h.t += 0.02

    bus.temp[31] = 56
    run(0.7)  # 讀到 1～2 次還不算（舵機讀值有單拍雜訊，要連續 3 次）
    assert "reason" not in h.cmd("look", {"head_yaw": 0.0})
    run(1.2)
    ack = h.cmd("look", {"head_yaw": 0.1})
    assert ack["reason"] == "overheat" and "servo_overheat" in h.cmd("status")["data"]["faults"]
    bus.temp[31] = 30
    bus.voltage = 6.5
    run(1.7)
    assert h.cmd("look", {"head_yaw": 0.1})["reason"] == "low_battery"
    bus.voltage = 5.9  # 舵機控制台的規則：自動緊急停止（只關頭部扭力）
    run(1.7)
    assert h.last_state()["mode"] == "estop" and h.events("estop")
    assert all(bus.torque[i] for i in LEG_SERVO_IDS) and bus.touched_write <= HEAD_IDS


def test_bus_read_failures_block_motion(tmp_path):
    body, bus, clock = make_body(tmp_path)
    h = make_harness(body=body)
    bus.fail_reads = 50
    for i in range(20):
        clock.t = h.t
        if i % 25 == 0:
            h.heartbeat()
        h.tick()
        h.t += 0.02
    assert h.cmd("look", {"head_yaw": 0.1})["reason"] == "hardware_fault"
    assert h.cmd("status")["data"]["head"]["age_ms"] >= 300
