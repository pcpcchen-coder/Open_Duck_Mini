"""look_at 控制器的單元測試（不需要硬體，也不需要 MuJoCo）。"""

import math

import pytest

from behaviors.look_at import (
    CameraIntrinsics,
    Face,
    Gaze,
    HeadLimits,
    LookAtConfig,
    LookAtController,
    LookState,
    SpeakerDirection,
    VisionFrame,
    allocate_pitch,
)

INTR = CameraIntrinsics.ar0144_nominal()
DT = 0.02  # 上游 runtime 50 Hz


def face_at(yaw: float, pitch: float, gaze: Gaze = Gaze(0.0, 0.0), width: float = 80, **kw) -> Face:
    """在目前視線下，把身體座標方向換成像素位置（測試用的小角度近似，和控制器的換算一致）。"""
    u = INTR.cx - INTR.fx * math.tan(yaw - gaze.yaw)
    v = INTR.cy - INTR.fy * math.tan(pitch - gaze.pitch)
    return Face(u=u, v=v, width=width, **kw)


def run(ctrl: LookAtController, seconds: float, t0: float, people=(), speaker=None, frame_every=5, noise=None):
    """以 50 Hz 推進；每 frame_every 個週期給一張偵測（10 Hz）。people 是身體座標方向的清單。"""
    t = t0
    cmd = None
    n = int(round(seconds / DT))
    for i in range(n):
        frame = None
        if i % frame_every == 0:
            gaze = ctrl.commanded_gaze
            faces = []
            for k, p in enumerate(people):
                f = face_at(p.yaw, p.pitch, gaze)
                if noise:
                    f = Face(f.u + noise(), f.v + noise(), f.width)
                faces.append(f)
            frame = VisionFrame(t, tuple(faces), gaze)
        cmd = ctrl.step(t, frame, speaker)
        t += DT
    return cmd, t


def test_intrinsics_match_aios_nominal():
    assert INTR.fx == pytest.approx(1004.6, abs=0.1)
    yaw, pitch = INTR.ray_angles(INTR.cx + 100, INTR.cy - 50)
    assert yaw < 0  # 畫面右邊 → 往右（負）
    assert pitch > 0  # 畫面上方 → 往上（正）


def test_allocate_pitch_uses_head_first_then_neck():
    lim = HeadLimits()
    assert allocate_pitch(0.2, lim) == (pytest.approx(0.0), pytest.approx(0.2), False)
    neck, head, sat = allocate_pitch(0.7, lim)
    assert head == pytest.approx(0.3) and neck == pytest.approx(0.4) and not sat
    neck, head, sat = allocate_pitch(1.2, lim)
    assert head == pytest.approx(0.3) and neck == pytest.approx(0.6) and sat
    neck, head, sat = allocate_pitch(-0.5, lim)
    assert head == pytest.approx(-0.5) and neck == pytest.approx(0.0) and not sat


def test_tracks_face_and_converges():
    ctrl = LookAtController()
    ctrl.activate()
    person = Gaze(0.3, 0.45)
    cmd, _ = run(ctrl, 3.0, 0.0, [person])
    assert cmd.state == LookState.TRACKING
    assert cmd.head_yaw == pytest.approx(0.3, abs=math.radians(2.5))
    assert cmd.neck_pitch + cmd.head_pitch == pytest.approx(0.45, abs=math.radians(2.5))
    assert cmd.body_yaw_rate == 0.0  # 0.3 rad 在頭部範圍內，不轉身


def test_commands_respect_limits_and_rate():
    cfg = LookAtConfig()
    ctrl = LookAtController(cfg)
    ctrl.activate()
    prev = None
    t = 0.0
    for i in range(300):
        gaze = ctrl.commanded_gaze
        frame = VisionFrame(t, (face_at(1.2, 1.5, gaze),), gaze) if i % 5 == 0 else None
        cmd = ctrl.step(t, frame)
        lim = cfg.limits
        assert lim.head_yaw[0] <= cmd.head_yaw <= lim.head_yaw[1]
        assert lim.head_pitch[0] <= cmd.head_pitch <= lim.head_pitch[1]
        assert lim.neck_pitch[0] <= cmd.neck_pitch <= lim.neck_pitch[1]
        assert abs(cmd.body_yaw_rate) <= cfg.body_turn_max
        if prev is not None:
            assert abs(cmd.head_yaw - prev.head_yaw) <= cfg.max_rate_yaw * DT + 1e-9
        prev = cmd
        t += DT
    assert cmd.pitch_saturated and cmd.yaw_saturated
    assert cmd.body_yaw_rate > 0  # 人在左邊很遠 → 請身體往左轉


def test_deadband_ignores_small_noise():
    ctrl = LookAtController()
    ctrl.activate()
    run(ctrl, 2.0, 0.0, [Gaze(0.1, 0.2)])
    before = ctrl.commanded_gaze
    import random

    rng = random.Random(0)
    cmd, _ = run(ctrl, 3.0, 2.0, [Gaze(0.1, 0.2)], noise=lambda: rng.gauss(0, 2.0))
    # 2 px 雜訊約 0.1°，小於 resume（5°），頭不該跟著抖
    assert abs(cmd.head_yaw - before.yaw) < math.radians(0.5)


def test_hold_then_search_then_rest_when_face_lost():
    cfg = LookAtConfig()
    ctrl = LookAtController(cfg)
    ctrl.activate()
    _, t = run(ctrl, 2.0, 0.0, [Gaze(0.2, 0.3)])
    held = ctrl.commanded_gaze
    cmd, t = run(ctrl, 1.5, t, [])  # 不見 1.5 s：超過 lost_hold，但還沒到 return_after
    assert cmd.state == LookState.HOLD
    assert ctrl.commanded_gaze.yaw == pytest.approx(held.yaw, abs=1e-3)
    assert ctrl.commanded_gaze.pitch == pytest.approx(held.pitch, abs=1e-3)
    cmd, t = run(ctrl, 3.0, t, [])  # 超過 return_after：上下找
    assert cmd.state == LookState.SEARCH and cmd.target_id is None
    cmd, t = run(ctrl, 6.0, t, [])  # 超過 scan_timeout：停在休息視線
    assert cmd.state == LookState.IDLE
    assert abs(cmd.head_yaw) < math.radians(1)
    assert cmd.neck_pitch + cmd.head_pitch == pytest.approx(cfg.rest_pitch, abs=math.radians(1))


def test_speaker_direction_switches_after_confirmation():
    cfg = LookAtConfig()
    ctrl = LookAtController(cfg)
    ctrl.activate()
    a, b = Gaze(-0.25, 0.3), Gaze(0.25, 0.3)
    # A 的臉比較大 → 沒有說話者方向時先看 A
    t = 0.0
    for i in range(100):
        gaze = ctrl.commanded_gaze
        frame = None
        if i % 5 == 0:
            frame = VisionFrame(t, (face_at(a.yaw, a.pitch, gaze, width=100), face_at(b.yaw, b.pitch, gaze, width=60)), gaze)
        ctrl.step(t, frame)
        t += DT
    assert ctrl.commanded_gaze.yaw == pytest.approx(a.yaw, abs=0.05)
    assert ctrl.switch_count == 0
    # B 開始說話
    spk = SpeakerDirection(t, b.yaw)
    switched_at = None
    for i in range(150):
        gaze = ctrl.commanded_gaze
        frame = None
        if i % 5 == 0:
            frame = VisionFrame(t, (face_at(a.yaw, a.pitch, gaze, width=100), face_at(b.yaw, b.pitch, gaze, width=60)), gaze)
        ctrl.step(t, frame, spk)
        if switched_at is None and ctrl.switch_count == 1:
            switched_at = t - spk.t
        t += DT
    assert ctrl.switch_count == 1
    assert cfg.switch_confirm_s <= switched_at <= cfg.switch_confirm_s + 0.25
    assert ctrl.commanded_gaze.yaw == pytest.approx(b.yaw, abs=0.05)


def test_search_toward_speaker_without_face_requests_body_turn():
    ctrl = LookAtController()
    ctrl.activate()
    spk = SpeakerDirection(0.0, math.radians(90))
    cmd, _ = run(ctrl, 1.0, 0.0, [], speaker=spk)
    assert cmd.state == LookState.SEARCH
    assert cmd.body_yaw_rate > 0
    assert cmd.head_yaw == pytest.approx(0.5)  # 頭先轉到極限


def test_body_rotation_compensates_old_speaker_direction():
    ctrl = LookAtController()
    ctrl.activate()
    spk = SpeakerDirection(0.0, math.radians(60))
    t = 0.0
    rate = 0.5
    for _ in range(int(2.0 / DT)):  # 身體以 0.5 rad/s 轉了 1 rad（≈57°）
        ctrl.step(t, None, spk, measured_body_yaw_rate=rate)
        t += DT
    # 說話者現在只在身體左邊約 3°，不該再要求大幅轉身
    cmd = ctrl.step(t, None, spk, measured_body_yaw_rate=0.0)
    assert abs(cmd.body_yaw_rate) < 0.15


def test_deactivate_returns_to_neutral_and_never_turns_body():
    ctrl = LookAtController()
    ctrl.activate()
    _, t = run(ctrl, 2.0, 0.0, [Gaze(0.4, 0.4)])
    ctrl.deactivate()
    cmd, _ = run(ctrl, 3.0, t, [Gaze(0.4, 0.4)])
    assert cmd.state == LookState.IDLE
    assert cmd.body_yaw_rate == 0.0
    assert abs(cmd.head_yaw) < math.radians(1)


def test_low_score_faces_ignored():
    ctrl = LookAtController()
    ctrl.activate()
    t = 0.0
    for i in range(100):
        gaze = ctrl.commanded_gaze
        f = face_at(0.3, 0.3, gaze)
        frame = VisionFrame(t, (Face(f.u, f.v, f.width, score=0.2),), gaze) if i % 5 == 0 else None
        cmd = ctrl.step(t, frame)
        t += DT
    assert cmd.target_id is None and abs(cmd.head_yaw) < 1e-9


def test_scans_up_and_down_until_face_found():
    cfg = LookAtConfig()
    ctrl = LookAtController(cfg)
    ctrl.activate()
    pitches = []
    t = 0.0
    for _ in range(int(4 * cfg.scan_dwell_s / DT)):
        cmd = ctrl.step(t)
        pitches.append(cmd.neck_pitch + cmd.head_pitch)
        t += DT
    assert cmd.state == LookState.SEARCH
    assert max(pitches) == pytest.approx(cfg.high_pitch, abs=math.radians(2))
    assert min(pitches[len(pitches) // 2 :]) == pytest.approx(cfg.rest_pitch, abs=math.radians(2))


def test_compensates_servo_sag_with_readback():
    """舵機實際角度比指令低 0.1 rad（下垂）時，回讀讓控制器把指令加高，視線仍然對準。"""
    ctrl = LookAtController()
    ctrl.activate()
    person = Gaze(0.0, 0.5)
    sag = 0.1
    t = 0.0
    for i in range(300):
        cmd_gaze = ctrl.commanded_gaze
        actual = Gaze(cmd_gaze.yaw, cmd_gaze.pitch - sag)
        frame = VisionFrame(t, (face_at(person.yaw, person.pitch, actual),), actual) if i % 5 == 0 else None
        ctrl.step(t, frame)
        t += DT
    actual_pitch = ctrl.commanded_gaze.pitch - sag
    assert actual_pitch == pytest.approx(person.pitch, abs=math.radians(2.5))


def test_turns_to_speaker_outside_view_while_tracking_someone_else():
    """正在看 A；B 在視野外開口，鏡頭看不到 B 的臉 → 放下 A，轉向 B 的方向找。"""
    cfg = LookAtConfig()
    ctrl = LookAtController(cfg)
    ctrl.activate()
    a = Gaze(0.0, 0.3)
    _, t = run(ctrl, 2.0, 0.0, [a])
    spk = SpeakerDirection(t, math.radians(80))
    cmd, t = run(ctrl, cfg.speaker_search_after_s + 0.5, t, [a], speaker=spk)
    assert cmd.state == LookState.SEARCH
    assert cmd.body_yaw_rate > 0 and cmd.head_yaw > 0.3


def test_ignores_brief_speaker_outlier():
    """說話者方向偶爾一筆離群（短於 speaker_search_after_s），不放下目前的人。"""
    cfg = LookAtConfig()
    ctrl = LookAtController(cfg)
    ctrl.activate()
    a = Gaze(0.1, 0.3)
    _, t = run(ctrl, 2.0, 0.0, [a])
    outlier = SpeakerDirection(t, math.radians(70))
    _, t = run(ctrl, 0.4, t, [a], speaker=outlier)
    ok = SpeakerDirection(t, 0.1)
    cmd, t = run(ctrl, 1.5, t, [a], speaker=ok)
    assert cmd.state == LookState.TRACKING and ctrl.switch_count == 0
