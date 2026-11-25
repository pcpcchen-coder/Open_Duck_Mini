"""對**真正的上游腳本**（Open_Duck_Mini_Runtime，鎖定 commit 376de65）做載入測試（ADR-0009 §5）。

要在裝了上游 runtime 的機器上跑（Pi：`DUCK_RUNTIME_DIR=~/duck/Open_Duck_Mini_Runtime`、
`DUCK_ONNX=~/duck/BEST_WALK_ONNX_2.onnx`），其他地方自動略過。

硬體介面全部是假的（`duckd.gait_fakes`，mock）：**不開序列埠、不開 I2C、不碰 GPIO、不需要手把**；
ONNX 策略是真的在 CPU 上推論。這只證明「不改上游就能把指令來源換成仲裁器」，不是走路的驗證。
"""
import os
import time
from pathlib import Path

import pytest

RUNTIME = os.environ.get("DUCK_RUNTIME_DIR")
ONNX = os.environ.get("DUCK_ONNX")
pytestmark = pytest.mark.skipif(not (RUNTIME and ONNX), reason="需要上游 runtime（設 DUCK_RUNTIME_DIR 與 DUCK_ONNX；在 Pi 上跑）")


def build(tmp_path, n_writes=None, on_poll=None):
    """建立 RLWalk（假硬體）。注意：建立時上游的 start() 會 sleep 2 s。"""
    import json

    from duckd.arbiter import SafetyArbiter
    from duckd.gait_fakes import FAKE_OVERRIDES
    from duckd.gait_host import build_rl_walk
    from duckd.limits import HEAD_JOINTS, Limits

    cfg = tmp_path / "duck_config.json"  # 測試自己的設定檔：不讀使用者的偏移
    cfg.write_text(json.dumps({"start_paused": False, "imu_upside_down": False, "phase_frequency_factor_offset": 0.0,
                               "expression_features": {k: False for k in ("eyes", "projector", "antennas", "speaker", "microphone", "camera")},
                               "joints_offsets": {}}))
    arb = SafetyArbiter(Limits(), walk_supported=True)  # 假硬體：這裡才把走路打開
    arb.enable_head({n: 0.0 for n in HEAD_JOINTS})
    rl, source, module = build_rl_walk(Path(RUNTIME), Path(ONNX), arb, overrides=dict(FAKE_OVERRIDES), duck_config=cfg, on_poll=on_poll)
    rl.hwi.max_writes = n_writes
    return arb, rl, source, module


def test_locked_commit():
    from duckd.gait_host import LOCKED_COMMIT, check_locked_commit

    assert check_locked_commit(Path(RUNTIME).expanduser()).startswith(LOCKED_COMMIT)


def test_upstream_main_loop_runs_on_arbiter_without_gamepad(tmp_path):
    box = {}

    def on_poll(polls):  # 測試扮演 Nous：每圈續租；另外設上限，迴圈不會卡死
        box["arb"].heartbeat(time.monotonic())
        if polls > 600:
            from duckd.gait_fakes import LoopFinished

            raise LoopFinished()

    arb, rl, source, module = build(tmp_path, n_writes=100, on_poll=on_poll)
    box["arb"] = arb
    assert rl.xbox_controller is source  # 上游的 __init__ 拿到的是仲裁器，不是手把
    assert type(rl.hwi).__name__ == "FakeHWI" and rl.hwi.turned_on
    now = time.monotonic()
    arb.heartbeat(now)
    arb.resume(now)
    assert arb.request_walk({"vx": 0.08, "duration_s": 3.0}, 60000, now).accepted
    arb.request_look({"head_yaw": 0.2}, 60000, now)
    cwd = os.getcwd()
    os.chdir(Path(RUNTIME).expanduser() / "scripts")
    t0 = time.monotonic()
    try:
        rl.run()  # 上游主迴圈，原封不動；假 HWI 在第 100 次寫入後結束它
    finally:
        os.chdir(cwd)
    elapsed = time.monotonic() - t0
    assert len(rl.hwi.targets) == 100 and source.polls >= 100
    assert rl.feet_contacts.stopped  # 上游的收尾有跑到
    assert set(rl.hwi.targets[-1]) == set(rl.hwi.joints) and len(rl.hwi.targets[-1]) == 14
    assert rl.last_commands[0] == pytest.approx(0.08)  # 仲裁器的速度進了上游的指令向量
    assert 0.0 < rl.last_commands[5] <= 0.2
    import math

    assert all(math.isfinite(v) for t in rl.hwi.targets for v in t.values())
    assert rl.imu.get_data_calls == 100  # 只有上游自己呼叫 get_data()，仲裁器沒有搶
    steps = sorted(rl.hwi.step_ms)
    print(f"\n[載入測試] 100 圈 {elapsed:.2f} s；每圈中位數 {steps[len(steps)//2]:.1f} ms、最大 {steps[-1]:.1f} ms（目標 20 ms）")
    assert 1.5 <= elapsed <= 4.0  # 50 Hz × 100 圈 ≈ 2 s


def test_upstream_loop_stays_paused_until_resume_and_stops_on_lease_loss(tmp_path):
    from duckd.gait_fakes import LoopFinished

    def stop_after(n):
        def on_poll(polls):
            if polls >= n:
                raise LoopFinished()
        return on_poll

    arb, rl, source, module = build(tmp_path, on_poll=stop_after(8))
    arb.heartbeat(time.monotonic())
    cwd = os.getcwd()
    os.chdir(Path(RUNTIME).expanduser() / "scripts")
    try:
        rl.run()  # 以暫停狀態啟動：上游每 0.1 s 問一次指令，不送任何馬達目標
        assert rl.paused is True and rl.hwi.targets == [] and source.polls == 8
        # resume＋walk，然後不再送 heartbeat：1.5 s 後速度歸零，兩腳著地 0.3 s 後暫停
        source.on_poll = stop_after(8 + 150)
        now = time.monotonic()
        arb.heartbeat(now)
        arb.resume(now)
        assert arb.request_walk({"vx": 0.1, "duration_s": 3.0}, 60000, now).accepted
        rl.run()
    finally:
        os.chdir(cwd)
    assert not arb.lease_ok and rl.paused is True
    assert rl.hwi.targets, "resume 之後主迴圈有送馬達目標"
    assert rl.last_commands[:3] == [0.0, 0.0, 0.0]
