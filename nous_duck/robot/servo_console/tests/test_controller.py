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
    tick(c, clock, 1, dt=ctl.STATUS_PERIOD_S + 0.01)
    assert c.estop_reason and "ID 23" in c.estop_reason
    assert not any(bus.torque.values())
    with pytest.raises(CommandError, match="警報"):
        c.reset_estop()
    bus.temp[23] = 40
    tick(c, clock, 1, dt=ctl.STATUS_PERIOD_S + 0.01)
    c.reset_estop()
    assert c.estop_reason is None


def test_low_voltage(setup):
    c, bus, clock = setup
    c.connect()
    bus.voltage = 6.5
    tick(c, clock, 1, dt=ctl.STATUS_PERIOD_S + 0.01)
    assert c.alarms["volt"][0] == "warn" and not c.estop_reason
    bus.voltage = 5.9
    tick(c, clock, 1, dt=ctl.STATUS_PERIOD_S + 0.01)
    assert c.estop_reason and "電壓" in c.estop_reason


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
