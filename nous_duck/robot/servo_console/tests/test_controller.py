"""控制核心的單元測試（模擬匯流排，不需要硬體）。"""
import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from servo_console import controller as ctl  # noqa: E402
from servo_console.bus import MockBus, decode_load  # noqa: E402
from servo_console.controller import CommandError, Controller  # noqa: E402
from servo_console.joints import JOINT_TABLE, STANCE, load_joints  # noqa: E402

# robot.xml 的範圍（度），跟 console_joints.json 一致；測試只需要合理的值
RANGES_DEG = {
    "hip_yaw": (-30, 30),
    "hip_roll": (-25, 25),
    "knee": (-90, 90),
    "ankle": (-90, 90),
    "neck_pitch": (-20, 65),
    "head_pitch": (-45, 45),
    "head_yaw": (-160, 160),
    "head_roll": (-30, 30),
}


def _range(name):
    if name == "left_hip_pitch":
        return (-70, 30)
    if name == "right_hip_pitch":
        return (-30, 70)
    for key, r in RANGES_DEG.items():
        if name.endswith(key):
            return r
    raise KeyError(name)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def joints_file(tmp_path):
    data = {
        "schema": "nous-duck/console-joints@1",
        "joints": [
            {"name": n, "servo_id": i, "range_rad": [math.radians(v) for v in _range(n)]} for n, i, *_ in JOINT_TABLE
        ],
    }
    path = tmp_path / "console_joints.json"
    path.write_text(json.dumps(data))
    return path


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "duck_config.json"
    offsets = {n: 0.0 for n, *_ in JOINT_TABLE}
    offsets["right_hip_roll"] = -0.0081
    path.write_text(json.dumps({"start_paused": False, "imu_upside_down": False, "joints_offsets": offsets}, indent=4))
    return path


@pytest.fixture
def setup(joints_file, config_file, tmp_path):
    joints = load_joints(joints_file)
    bus = MockBus([j.servo_id for j in joints], start_deg={j.servo_id: 10.0 for j in joints})
    clock = Clock()
    c = Controller(joints, lambda: bus, config_file, tmp_path / "poses.json", clock=clock, mock=True)
    return c, bus, clock


def tick(c, clock, n=1, dt=0.02):
    for _ in range(n):
        clock.t += dt
        c.client_seen()
        c.tick()


def test_load_joints_checks(joints_file, tmp_path):
    joints = load_joints(joints_file)
    assert [j.servo_id for j in joints] == [10, 11, 12, 13, 14, 20, 21, 22, 23, 24, 30, 31, 32, 33]
    knee = next(j for j in joints if j.name == "left_knee")
    assert math.isclose(knee.hi, math.radians(88))  # 往內縮 2°
    bad = json.loads(joints_file.read_text())
    bad["joints"] = bad["joints"][:-1]
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(bad))
    with pytest.raises(ValueError):
        load_joints(p)


def test_decode_load():
    assert decode_load(24) == 2.4
    assert decode_load(1056) == -3.2


def test_connect_requires_all_servos(setup):
    c, bus, _ = setup
    bus.missing = {24}
    with pytest.raises(CommandError, match="24"):
        c.connect()
    assert not c.connected and not bus.is_open
    bus.missing = set()
    c.connect()
    assert c.connected


def test_connect_refused_when_port_in_use(joints_file, config_file, tmp_path):
    joints = load_joints(joints_file)
    bus = MockBus([j.servo_id for j in joints])
    c = Controller(joints, lambda: bus, config_file, tmp_path / "p.json", port_users=lambda: [(123, "python v2_rl_walk_mujoco.py")])
    with pytest.raises(CommandError, match="123"):
        c.connect()
    assert not bus.is_open


def test_offsets_loaded_and_applied(setup):
    c, bus, _ = setup
    c.connect()
    j = c.joints["right_hip_roll"]
    # 舵機 10° → 關節角度 = 10° − 偏移
    assert math.isclose(math.degrees(j.actual), 10 - math.degrees(-0.0081), abs_tol=0.1)


def test_targets_need_torque_and_torque_on_does_not_jump(setup):
    c, bus, clock = setup
    c.connect()
    notes = c.set_targets({"head_yaw": math.radians(20)})
    assert "沒有出力" in notes[0]
    present = dict(bus.pos)
    c.set_torque(["head_yaw"], True)
    # 開扭力前先寫一次目標 = 目前位置
    first = bus.writes[0]
    assert set(first) == {32}
    assert abs(first[32] - present[32]) < 0.2
    assert bus.torque[32]


def test_speed_limit_and_clamp(setup):
    c, bus, clock = setup
    c.connect()
    c.set_torque(["head_roll"], True)
    start = c.joints["head_roll"].cmd
    notes = c.set_targets({"head_roll": math.radians(80)})  # 範圍 ±30 → 夾到 28
    assert "夾到 28.0°" in notes[0]
    tick(c, clock, 1, dt=0.02)
    moved = math.degrees(c.joints["head_roll"].cmd - start)
    assert math.isclose(moved, 30 * 0.02, rel_tol=1e-6)  # 預設 30°/s
    tick(c, clock, 200, dt=0.02)
    assert math.isclose(math.degrees(c.joints["head_roll"].cmd), 28.0, abs_tol=1e-6)
    assert math.isclose(bus.goal[33], 28.0, abs_tol=1e-6)


def test_estop_latches(setup):
    c, bus, clock = setup
    c.connect()
    c.set_torque(list(c.joints), True)
    c.estop()
    assert not any(bus.torque.values())
    with pytest.raises(CommandError, match="緊急停止"):
        c.set_targets({"head_yaw": 0.1})
    with pytest.raises(CommandError, match="緊急停止"):
        c.set_torque(["head_yaw"], True)
    c.reset_estop()
    c.set_torque(["head_yaw"], True)
    assert bus.torque[32]


def test_estop_without_connection_still_disables_torque(setup):
    c, bus, _ = setup
    bus.open()
    bus.set_torque(bus.ids, True)  # 例如上游 turn_on.py 留下的出力
    bus.close()
    c.estop()
    assert not any(bus.torque.values())
    assert c.estop_reason


def test_overtemp_auto_estop(setup):
    c, bus, clock = setup
    c.connect()
    c.set_torque(list(c.joints), True)
    bus.temp[23] = ctl.TEMP_STOP_C
    tick(c, clock, ctl.CONFIRM_READS - 1, dt=ctl.STATUS_PERIOD_S + 0.01)
    assert not c.estop_reason  # 還沒連續 CONFIRM_READS 次
    tick(c, clock, 1, dt=ctl.STATUS_PERIOD_S + 0.01)
    assert c.estop_reason and "ID 23" in c.estop_reason
    assert not any(bus.torque.values())
    with pytest.raises(CommandError, match="警報"):
        c.reset_estop()
    bus.temp[23] = 40
    tick(c, clock, 1, dt=ctl.STATUS_PERIOD_S + 0.01)  # 一次正常的讀值就解除
    c.reset_estop()
    assert c.estop_reason is None


def test_low_voltage(setup):
    c, bus, clock = setup
    c.connect()
    bus.voltage = 6.5
    tick(c, clock, ctl.CONFIRM_READS, dt=ctl.STATUS_PERIOD_S + 0.01)
    assert c.alarms["volt"][0] == "warn" and not c.estop_reason
    bus.voltage = 5.9
    tick(c, clock, ctl.CONFIRM_READS, dt=ctl.STATUS_PERIOD_S + 0.01)
    assert c.estop_reason and "電壓" in c.estop_reason


class NoisyStatus:
    """包住 MockBus.read_status：照順序把某幾顆的電壓／溫度換成指定值（模擬 2026-11-28 實測的單拍雜訊）。"""

    def __init__(self, bus, script):
        self.bus, self.script, self.n = bus, list(script), 0
        self.orig = bus.read_status
        bus.read_status = self

    def __call__(self, ids):
        st = self.orig(ids)
        if self.n < len(self.script):
            for key, sid, value in self.script[self.n]:
                st[key][list(ids).index(sid)] = value
        self.n += 1
        return st


def test_single_servo_spikes_do_not_estop(setup):
    """實測：每輪最多 1 顆讀到 6.0 V 或 50°C，下一輪就正常。不能因此緊急停止或警告。"""
    c, bus, clock = setup
    c.connect()
    c.set_torque(list(c.joints), True)
    bus.voltage = 7.4
    script = []
    for k in range(30):
        sid = [14, 13, 12, 11, 10][k % 5]
        script.append([("voltage", sid, 5.5), ("temperature", 12, 70)] if k % 2 == 0 else [])
    NoisyStatus(bus, script)
    tick(c, clock, 30, dt=ctl.STATUS_PERIOD_S + 0.01)
    assert not c.estop_reason
    assert "volt" not in c.alarms and "temp" not in c.alarms and "volt_servo" not in c.alarms
    assert c.bus_voltage() == pytest.approx(7.4)


def test_one_servo_persistently_low_warns_only(setup):
    """某一顆連續偏低、其他正常：只警告那一顆（可能是接線），不緊急停止。"""
    c, bus, clock = setup
    c.connect()
    bus.voltage = 7.4
    NoisyStatus(bus, [[("voltage", 14, 5.5)]] * 10)
    tick(c, clock, ctl.CONFIRM_READS + 1, dt=ctl.STATUS_PERIOD_S + 0.01)
    assert not c.estop_reason
    assert c.alarms["volt_servo"][0] == "warn" and "ID 14" in c.alarms["volt_servo"][1]
    assert "volt" not in c.alarms


def test_whole_bus_sag_still_stops(setup):
    """真的沒電（全部一起低）連續 CONFIRM_READS 次：照樣緊急停止。"""
    c, bus, clock = setup
    c.connect()
    c.set_torque(list(c.joints), True)
    bus.voltage = 5.8
    tick(c, clock, ctl.CONFIRM_READS, dt=ctl.STATUS_PERIOD_S + 0.01)
    assert c.estop_reason and "電源電壓" in c.estop_reason
    assert not any(bus.torque.values())


def test_read_failures_freeze_motion(setup):
    c, bus, clock = setup
    c.connect()
    c.set_torque(["head_yaw"], True)
    c.set_targets({"head_yaw": math.radians(25)})
    tick(c, clock, 2)
    bus.fail_reads = ctl.READ_FAIL_LIMIT
    tick(c, clock, ctl.READ_FAIL_LIMIT)
    j = c.joints["head_yaw"]
    assert "comm" in c.alarms and j.target == j.cmd
    with pytest.raises(CommandError):
        c.set_targets({"head_yaw": 0.0})
    tick(c, clock, 1)
    assert "comm" not in c.alarms


def test_heartbeat_stops_motion_but_keeps_torque(setup):
    c, bus, clock = setup
    c.connect()
    c.set_torque(["head_yaw"], True)
    c.set_targets({"head_yaw": math.radians(60)})
    clock.t += ctl.HEARTBEAT_S + 0.5
    c.tick()  # 沒有 client_seen
    j = c.joints["head_yaw"]
    assert j.target == j.cmd and bus.torque[32]


def test_offset_adjust_and_save(setup, config_file):
    c, bus, clock = setup
    c.connect()
    c.set_torque(["right_hip_roll"], True)
    before = bus.goal[11]
    c.adjust_offset("right_hip_roll", 1.0)
    assert math.isclose(bus.goal[11] - before, 1.0, abs_tol=0.11)
    with pytest.raises(CommandError):
        c.adjust_offset("right_hip_roll", 5)
    for _ in range(10):  # 到 20°
        c.adjust_offset("head_yaw", 2.0)
    with pytest.raises(CommandError, match="20"):
        c.adjust_offset("head_yaw", 2.0)
    assert c.snapshot()["offsets_dirty"]
    backup = c.save_offsets()
    assert (config_file.parent / backup).exists()
    saved = json.loads(config_file.read_text())
    assert saved["start_paused"] is False  # 其他欄位保留
    assert math.isclose(saved["joints_offsets"]["right_hip_roll"], round(-0.0081 + math.radians(1), 4))
    assert not c.snapshot()["offsets_dirty"]


def test_poses(setup):
    c, bus, clock = setup
    c.connect()
    c.set_torque(list(c.joints), True)
    notes = c.apply_pose("stance")
    assert not notes
    assert math.isclose(c.joints["left_knee"].target, STANCE["left_knee"])
    c.save_pose("坐下 1")
    assert any(p["key"] == "user:坐下 1" for p in c.poses())
    c.apply_pose("user:坐下 1")
    c.delete_pose("坐下 1")
    with pytest.raises(CommandError):
        c.save_pose("../bad")
    with pytest.raises(CommandError):
        c.apply_pose("nope")


def test_release_keeps_torque_state(setup):
    c, bus, clock = setup
    c.connect()
    c.set_torque(["head_yaw"], True)
    c.release()
    assert not c.connected and bus.torque[32]
    with pytest.raises(CommandError, match="連線"):
        c.set_targets({"head_yaw": 0.0})


# ---------------------------------------------------------------- 電力與匯流排錯誤
from servo_console.bus import BusError, FeetechBus, decode_current_ma, decode_status  # noqa: E402


def test_decode_current_and_status():
    assert decode_current_ma(2) == 13.0
    assert decode_current_ma(0x8002) == 13.0  # 位元 15 是方向
    assert decode_status(0) == []
    assert decode_status(1 | 4 | 32) == ["電壓", "溫度", "過載"]


class _FakeIO:
    """模擬 pypot：丟出通訊例外或回傳空值。"""

    def __init__(self):
        self.flushed = 0

    def get_present_position(self, ids):
        raise RuntimeError("could not parse received data")

    def get_present_voltage(self, ids):
        return ()

    def flush(self):
        self.flushed += 1


def test_feetech_bus_turns_pypot_errors_into_bus_error():
    bus = FeetechBus("/dev/null")
    bus.io = _FakeIO()
    with pytest.raises(BusError, match="RuntimeError"):
        bus.read_positions([10, 11])
    assert bus.io.flushed == 1  # 出錯後清掉緩衝區
    with pytest.raises(BusError, match="回應 0／2"):
        bus._get(bus.io.get_present_voltage, [10, 11], "電壓")


def test_power_summary(setup):
    c, bus, clock = setup
    assert c.power_summary() == {"available": False}
    c.connect()
    c.set_torque(list(c.joints), True)
    bus.voltage = 7.7
    tick(c, clock, 1, dt=ctl.STATUS_PERIOD_S + 0.01)
    p = c.power_summary()
    assert p["available"] and p["battery_v"] == 7.7 and p["cell_v"] == 3.85
    assert p["torque_on"] == 14
    assert p["current_a"] == pytest.approx(sum(j.current_ma for j in c.joints.values()) / 1000, abs=1e-3)
    assert p["power_w"] == pytest.approx(7.7 * p["current_a"], abs=0.01)  # 各自四捨五入


def test_servo_status_flags_raise_warning(setup, monkeypatch):
    c, bus, clock = setup
    c.connect()
    orig = bus.read_status

    def flagged(ids):
        s = orig(ids)
        s["status"][3] = ["過載"]
        return s

    monkeypatch.setattr(bus, "read_status", flagged)
    tick(c, clock, 1, dt=ctl.STATUS_PERIOD_S + 0.01)
    assert c.alarms["servo_status"][0] == "warn" and "ID 13" in c.alarms["servo_status"][1]
    assert c.snapshot()["joints"][3]["status"] == ["過載"]
    assert not c.estop_reason  # 只警告，不自動停止


def test_recorded_noise_from_real_duck_does_not_alarm(setup):
    """用 2026-11-28 實機量到的 1500 輪讀值（fixture）重播：舊規則（看最低電壓、最高溫度）會反覆發出低電壓警告（最低 6.0 V，再低 0.1 V 就緊急停止），新規則不會。"""
    import json
    from pathlib import Path

    data = json.loads((Path(__file__).parent / "fixtures" / "status_noise_2026-11-28.json").read_text(encoding="utf-8"))
    c, bus, clock = setup
    c.connect()
    c.set_torque(list(c.joints), True)
    order = {sid: k for k, sid in enumerate(data["ids"])}
    rows = iter(zip(data["voltage_dv"], data["temperature_c"]))
    orig = bus.read_status

    def replay(ids):
        st = orig(ids)
        v, t = next(rows)
        st["voltage"] = [v[order[i]] / 10.0 for i in ids]
        st["temperature"] = [t[order[i]] for i in ids]
        return st

    bus.read_status = replay
    raw_min_v = min(min(v) for v in data["voltage_dv"]) / 10.0
    raw_max_t = max(max(t) for t in data["temperature_c"])
    assert raw_min_v <= 6.0 and raw_max_t >= 50  # fixture 裡真的有這些單拍怪值
    tick(c, clock, len(data["voltage_dv"]) - 1, dt=ctl.STATUS_PERIOD_S + 0.01)
    assert not c.estop_reason
    assert not {"volt", "temp", "volt_servo"} & set(c.alarms)
