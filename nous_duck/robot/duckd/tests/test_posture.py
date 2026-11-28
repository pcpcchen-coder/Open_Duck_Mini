"""原地蹲低／起立（ADR-0020 草案）：姿勢引擎、核心整合、本機指令、實機後端的腿部白名單。

全部用 mock（MockBody、舵機控制台的模擬匯流排），**不需要硬體，也不是實機驗證**。
MuJoCo 裡的交叉檢查在 `sim/tests/test_posture_sim.py`。
"""
import json
import math

import pytest
from conftest import make_harness

from duckd.body import EngageError, MockBody
from duckd.head_real import HEAD_IDS, HeadBody
from duckd.limits import LEG_JOINTS, LEG_SERVO_ID_BY_NAME, LEG_SERVO_IDS, ROBOT_XML_LEG_RANGE, ROBOT_XML_MARGIN_RAD, Limits
from duckd.localctl import handle
from duckd.posture import (
    MAX_STEP_S,
    MIN_DURATION_S,
    RECOVER_DURATION_S,
    TRACK_ERR_HOLD_S,
    PostureMotion,
    load_postures,
)

from servo_console.bus import MockBus

P = load_postures()
STAND, CROUCH = P["stand"], P["crouch"]


def run_motion(m: PostureMotion, seconds: float, dt: float = 0.02, actual_fn=None, t0: float = 0.0):
    out, t = [], t0
    for _ in range(round(seconds / dt)):
        target = m.step(dt, actual_fn(out[-1] if out else None) if actual_fn else None, t)
        out.append(target)
        t += dt
    return out


# ------------------------------------------------------------------ 姿勢檔
def test_postures_file_is_legs_only_and_inside_limits():
    for pose in (STAND, CROUCH):
        assert set(pose) == set(LEG_JOINTS)
        for j, v in pose.items():
            lo, hi = ROBOT_XML_LEG_RANGE[j]
            assert lo + ROBOT_XML_MARGIN_RAD <= v <= hi - ROBOT_XML_MARGIN_RAD
    # 右腿 hip_pitch 與左腿正負相反（上游關節軸），膝、踝同號
    assert CROUCH["right_hip_pitch"] == -CROUCH["left_hip_pitch"]
    assert CROUCH["left_knee"] == CROUCH["right_knee"]
    # 膝蓋在舵機控制台的上限（88°）以內
    assert CROUCH["left_knee"] < math.radians(88)


# ------------------------------------------------------------------ 引擎
def test_crouch_then_stand_follows_the_path():
    m = PostureMotion(P)
    assert m.attach(STAND) == "standing"
    assert m.start("crouch", STAND) is None
    assert m.state == "moving"
    seq = run_motion(m, MIN_DURATION_S + 0.1)
    assert m.state == "crouched"
    assert seq[-1] == pytest.approx(CROUCH)
    # 每一拍的目標都在路徑上，且單調地往蹲姿走
    s_prev = -1.0
    for target in seq:
        s, err = m.project(target)
        assert err < 1e-9
        assert s >= s_prev - 1e-12
        s_prev = s
    # 最大速度：smoothstep 的峰值是平均的 1.5 倍，任何關節都 < 30°/s（舵機控制台的限速）
    for a, b in zip(seq, seq[1:]):
        for j in LEG_JOINTS:
            assert abs(b[j] - a[j]) / 0.02 < math.radians(30)
    assert m.start("stand", CROUCH) is None
    run_motion(m, MIN_DURATION_S + 0.1)
    assert m.state == "standing"


def test_overrun_does_not_jump():
    """控制迴圈晚了 1 秒：時間軸只前進 MAX_STEP_S，目標不會一下跳很遠。"""
    m = PostureMotion(P)
    m.attach(STAND)
    m.start("crouch", STAND)
    run_motion(m, 1.0)
    s_before = m.s
    m.step(1.0, None, 10.0)
    elapsed_before = 1.0
    # 1.0 秒那一拍只算 MAX_STEP_S
    expected_a = (elapsed_before + MAX_STEP_S) / MIN_DURATION_S
    assert m.s == pytest.approx(3 * expected_a**2 - 2 * expected_a**3, abs=1e-6)
    assert m.s - s_before < 0.03


def test_duration_is_clamped_to_minimum():
    m = PostureMotion(P)
    m.attach(STAND)
    m.start("crouch", STAND, duration_s=0.5)
    run_motion(m, MIN_DURATION_S - 0.1)
    assert m.state == "moving"
    run_motion(m, 0.2)
    assert m.state == "crouched"


def test_off_path_start_is_refused():
    m = PostureMotion(P)
    odd = dict(STAND, left_knee=STAND["left_knee"] + math.radians(15))
    assert m.attach(odd) == "unknown"
    err = m.start("crouch", odd)
    assert err and "not on the stand-crouch path" in err
    assert m.step(0.02, odd, 0.0) is None  # unknown 時不送腿部目標


def test_hold_then_only_slow_stand():
    m = PostureMotion(P)
    m.attach(STAND)
    m.start("crouch", STAND)
    run_motion(m, 1.5)
    assert m.hold() == "holding_partial"
    frozen = m.pose_at(m.s)
    assert run_motion(m, 1.0)[-1] == pytest.approx(frozen)  # 停在原地，不放鬆
    assert "only 'stand'" in m.start("crouch", frozen)
    assert m.start("stand", frozen, duration_s=3.0) is None
    assert m.recovering
    # 從約一半回到站姿：全程 6 秒 × 一半路徑 ≈ 3 秒，比 3 秒×一半的 1.5 秒慢
    s0 = m.s
    run_motion(m, RECOVER_DURATION_S * s0 - 0.2)
    assert m.state == "moving"
    run_motion(m, 0.4)
    assert m.state == "standing"


def test_tracking_error_aborts():
    """腿被擋住（實際角度離目標 > 20° 持續 0.5 秒）：自動停住並回報。"""
    m = PostureMotion(P)
    m.attach(STAND)
    m.start("crouch", STAND)
    stuck = dict(STAND)  # 腿完全沒動
    run_motion(m, MIN_DURATION_S, actual_fn=lambda _: stuck)
    assert m.state == "holding_partial"
    assert m.last_fault is not None and m.last_fault.code == "tracking_error"


# ------------------------------------------------------------------ 核心整合（MockBody）
def legs_harness(**kw):
    body = MockBody(legs=True, legs_start=STAND)
    h = make_harness(body=body, **kw)
    return h, body


def test_engage_legs_required_and_not_on_duck_link():
    h, body = legs_harness()
    assert not h.core.posture_command("crouch", None, h.t)["ok"]
    r = h.core.engage_legs(h.t)
    assert r["posture"]["state"] == "standing"
    h.run(0.1)
    st = h.last_state()
    assert "posture" not in st  # duck-link 的 state 沒有新欄位（schema 沒動）


def test_core_crouch_and_stand_with_mock_body():
    h, body = legs_harness()
    h.core.engage_legs(h.t)
    h.run(0.1)
    assert h.core.posture_command("crouch", 3.0, h.t)["ok"]
    h.run(3.5)
    assert h.core.posture.state == "crouched"
    assert body.legs == pytest.approx(CROUCH, abs=1e-3)
    assert h.core.posture_command("stand", None, h.t)["ok"]
    h.run(3.5)
    assert h.core.posture.state == "standing"
    events = [e["event"] for e in h.core.posture_events]
    assert events == ["legs_engaged", "start", "done", "start", "done"]


def test_estop_holds_posture_target():
    h, body = legs_harness()
    h.core.engage_legs(h.t)
    h.run(0.1)
    h.core.posture_command("crouch", 3.0, h.t)
    h.run(1.5)
    h.core.local_estop("test", h.t)
    h.run(0.2)
    assert h.core.posture.state == "holding_partial"
    assert h.core.posture_events[-1]["event"] == "aborted"
    assert not h.core.posture_command("stand", None, h.t)["ok"]  # 緊急停止中不接受


def test_block_reason_aborts_motion():
    class BlockingBody(MockBody):
        block = None

        def read(self, now):
            r = super().read(now)
            r.block = self.block
            return r

    body = BlockingBody(legs=True, legs_start=STAND)
    h = make_harness(body=body)
    h.core.engage_legs(h.t)
    h.run(0.1)
    h.core.posture_command("crouch", 3.0, h.t)
    h.run(1.0)
    body.block = ("overheat", "leg servo 56 C")
    h.run(0.1)
    assert h.core.posture.state == "holding_partial"
    assert h.core.posture_events[-1]["reason"] == "overheat"
    r = h.core.posture_command("crouch", None, h.t)
    assert not r["ok"]  # 收手後只能回站姿
    # block 還在：允許慢慢回站姿（ADR-0020 §2.2），回站姿途中不再因 block 停住
    r = h.core.posture_command("stand", None, h.t)
    assert r["ok"] and r["posture"]["recovering"]
    h.run(6.5)
    assert h.core.posture.state == "standing"
    # 站好之後 block 還在：不接受新的蹲低
    r = h.core.posture_command("crouch", None, h.t)
    assert not r["ok"] and r["reason"] == "overheat"


def test_release_stops_and_detaches():
    h, body = legs_harness()
    h.core.engage_legs(h.t)
    h.run(0.1)
    h.core.posture_command("crouch", 3.0, h.t)
    h.run(1.0)
    h.core.begin_release(h.t)
    h.run(2.0)
    assert not body.legs_engaged
    assert h.core.posture.state == "unknown"


def test_without_legs_flag_everything_is_refused():
    h = make_harness()
    with pytest.raises(EngageError):
        h.core.engage_legs(h.t)
    assert h.core.posture_command("crouch", None, h.t)["reason"] == "unsupported"
    assert h.core.posture_status() is None


def test_local_ctl_commands():
    h, body = legs_harness()
    assert handle(h.core, None, {"cmd": "engage-legs"})["ok"]
    h.run(0.1)
    r = handle(h.core, None, {"cmd": "posture", "target": "crouch", "duration_s": "x"})
    assert not r["ok"]
    assert handle(h.core, None, {"cmd": "posture", "target": "crouch"})["ok"]
    h.run(0.5)
    assert handle(h.core, None, {"cmd": "posture-stop"})["posture"]["state"] == "holding_partial"
    status = handle(h.core, None, {"cmd": "status"})
    assert status["posture"]["state"] == "holding_partial"


# ------------------------------------------------------------------ 實機後端（模擬匯流排）
def make_real(tmp_path, legs: bool, legs_torque: bool = False):
    ids = sorted(LEG_SERVO_IDS | HEAD_IDS)
    start = {LEG_SERVO_ID_BY_NAME[j]: math.degrees(STAND[j]) for j in LEG_JOINTS}
    bus = MockBus(ids, start_deg=start)
    for i in LEG_SERVO_IDS:
        bus.torque[i] = legs_torque
    writes: list[set] = []
    orig_write, orig_torque = bus.write_goals, bus.set_torque
    bus.write_goals = lambda goals: (writes.append(set(goals)), orig_write(goals))[1]
    bus.set_torque = lambda ids_, on: (writes.append(set(ids_)), orig_torque(ids_, on))[1]
    cfg = tmp_path / "duck_config.json"
    cfg.write_text(json.dumps({"joints_offsets": {}}))
    body = HeadBody(Limits(), lambda: bus, cfg, mock=True, legs=legs)
    return body, bus, writes


def test_real_backend_legs_untouched_until_engage_legs(tmp_path):
    body, bus, writes = make_real(tmp_path, legs=True)
    body.engage()
    for _ in range(20):
        body.step({"neck_pitch": 0.0, "head_pitch": 0.0, "head_yaw": 0.0, "head_roll": 0.0}, (0, 0, 0), 0.0,
                  legs=dict(CROUCH))  # 還沒 engage_legs：腿部目標被忽略
        body.controller.tick()
    assert not any(w & LEG_SERVO_IDS for w in writes)
    assert not any(bus.torque[i] for i in LEG_SERVO_IDS)
    actual = body.engage_legs()
    assert actual == pytest.approx(STAND, abs=0.01)
    assert all(bus.torque[i] for i in LEG_SERVO_IDS)
    r = body.read(0.0)
    assert r.legs_engaged and r.legs_torque


def test_real_backend_release_keeps_leg_torque(tmp_path):
    body, bus, _ = make_real(tmp_path, legs=True, legs_torque=True)
    body.engage()
    body.engage_legs()
    body.release()
    assert all(bus.torque[i] for i in LEG_SERVO_IDS)  # 站著時關掉會倒，所以不關
    assert not body.legs_engaged


def test_real_backend_without_legs_still_blocks_leg_ids(tmp_path):
    body, bus, writes = make_real(tmp_path, legs=False)
    body.engage()
    with pytest.raises(EngageError):
        body.engage_legs()
    body.step({"neck_pitch": 0.0, "head_pitch": 0.0, "head_yaw": 0.0, "head_roll": 0.0}, (0, 0, 0), 0.0, legs=dict(CROUCH))
    body.controller.tick()
    assert not any(w & LEG_SERVO_IDS for w in writes)


def test_real_backend_estop_relaxes_all_14(tmp_path):
    """--legs 時緊急停止讓 14 顆都放鬆（舵機控制台 Controller 的規則；ADR-0020 §2.2 寫明）。"""
    body, bus, _ = make_real(tmp_path, legs=True, legs_torque=True)
    body.engage()
    body.engage_legs()
    body.estop("test")
    assert not any(bus.torque.values())
