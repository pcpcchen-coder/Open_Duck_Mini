"""步態 host：importlib 載入＋換掉指令來源的機制，以及仲裁器 → 上游四元組的轉換。

這個檔案裡被載入的「上游腳本」是測試自己寫的**假腳本（mock）**，只模仿上游的名稱結構
（`XBoxController`、`RLWalk`、`paused`、`imu.last_imu_data`、`feet_contacts`）。
對真正的上游腳本（鎖定 commit 376de65）的載入測試在 `test_gait_host_upstream.py`，要在裝了上游 runtime 的 Pi 上跑。
"""
import textwrap

import pytest

from duckd.arbiter import SafetyArbiter
from duckd.gait_host import ArbiterCommandSource, GaitHostError, load_upstream_walk, tilt_from_accel
from duckd.limits import HEAD_JOINTS, Limits

FAKE_SCRIPT = textwrap.dedent(
    '''
    """假的上游腳本（mock）：只有測試需要的名稱結構。"""
    class XBoxController:
        def __init__(self, freq):
            raise RuntimeError("沒有手把")  # 真的上游在這裡會去開 pygame joystick

    class _Imu:
        last_imu_data = {"gyro": [0, 0, 0], "accelero": [0.0, 0.0, 9.81]}
        def get_data(self):
            raise AssertionError("仲裁器不可以呼叫 get_data()")

    class _Feet:
        def get(self):
            return [True, True]

    class RLWalk:
        def __init__(self):
            self.paused = False
            self.imu = _Imu()
            self.feet_contacts = _Feet()
            self.xbox_controller = XBoxController(20)
            self.sent = []

        def run(self, n):
            for _ in range(n):
                self.last_commands, self.buttons, lt, rt = self.xbox_controller.get_last_command()
                if self.paused:
                    continue
                self.sent.append(list(self.last_commands))

    if __name__ == "__main__":
        raise SystemExit("主程式區塊不應該被執行")
    '''
)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 0.02
        return self.t


@pytest.fixture
def script(tmp_path):
    path = tmp_path / "fake_rl_walk.py"
    path.write_text(FAKE_SCRIPT, encoding="utf-8")
    return path


def make(script):
    arb = SafetyArbiter(Limits(), walk_supported=True)  # 假腳本、沒有硬體：這裡才把走路打開
    arb.enable_head({n: 0.0 for n in HEAD_JOINTS})
    clock = Clock()
    source = ArbiterCommandSource(arb, buttons=object(), clock=clock)
    module = load_upstream_walk(script, {"XBoxController": lambda *a, **k: source})
    rl = module.RLWalk()  # 沒有換掉的話這裡會因為「沒有手把」失敗
    source.bind(rl)
    return arb, source, rl, clock


def test_swap_replaces_controller_without_touching_the_file(script):
    before = script.read_bytes()
    arb, source, rl, clock = make(script)
    assert rl.xbox_controller is source
    assert script.read_bytes() == before


def test_missing_name_or_file_is_an_error(tmp_path, script):
    with pytest.raises(GaitHostError, match="找不到"):
        load_upstream_walk(tmp_path / "nope.py", {})
    with pytest.raises(GaitHostError, match="HWI"):
        load_upstream_walk(script, {"HWI": object})
    bad = tmp_path / "renamed.py"
    bad.write_text("class RLWalk: pass\n")
    with pytest.raises(GaitHostError, match="XBoxController"):
        load_upstream_walk(bad, {})


def test_starts_paused_and_main_loop_sends_nothing_until_resume(script):
    arb, source, rl, clock = make(script)
    arb.heartbeat(clock.t)
    rl.run(10)
    assert source.polls == 10 and rl.paused is True and rl.sent == []
    assert arb.request_walk({"vx": 0.05, "duration_s": 1.0}, 3000, clock.t).reason == "paused"


def test_walk_intent_reaches_upstream_as_7_dim_command_with_limits(script):
    arb, source, rl, clock = make(script)
    arb.heartbeat(clock.t)
    arb.resume(clock.t)
    assert arb.request_walk({"vx": 0.5, "yaw_rate": -0.3, "duration_s": 1.0}, 60000, clock.t).clamped
    arb.request_look({"head_yaw": 0.2}, 60000, clock.t)
    for _ in range(20):
        arb.heartbeat(clock.t)
        rl.run(1)
    assert rl.paused is False and len(rl.sent) == 20
    assert all(len(c) == 7 for c in rl.sent)
    vx = [c[0] for c in rl.sent]
    assert vx[-1] == pytest.approx(0.10) and max(b - a for a, b in zip([0.0] + vx, vx)) <= 0.01 + 1e-9
    assert rl.sent[-1][2] == pytest.approx(-0.3)
    assert 0 < rl.sent[-1][5] <= 0.2 and rl.sent[-1][3] == 0.0
    assert rl.buttons is source.buttons


def test_lease_loss_zeroes_velocity_then_pauses_when_feet_are_down(script):
    arb, source, rl, clock = make(script)
    arb.heartbeat(clock.t)
    arb.resume(clock.t)
    arb.request_walk({"vx": 0.1, "duration_s": 3.0}, 60000, clock.t)
    rl.run(30)
    assert rl.sent[-1][0] == pytest.approx(0.1)
    rl.run(120)  # 不再送 heartbeat：1.5 s 後租約失效
    assert not arb.lease_ok
    assert rl.sent[-1][0] == 0.0  # 送出的最後一筆速度是 0（之後暫停，不再送）
    assert rl.paused is True  # 兩腳著地 0.3 s 後暫停


def test_fall_pauses_immediately(script):
    arb, source, rl, clock = make(script)
    arb.heartbeat(clock.t)
    arb.resume(clock.t)
    arb.request_walk({"vx": 0.1, "duration_s": 3.0}, 60000, clock.t)
    rl.run(10)
    rl.imu.last_imu_data = {"gyro": [0, 0, 0], "accelero": [9.0, 0.0, 3.0]}  # 傾斜約 72°
    for _ in range(15):
        arb.heartbeat(clock.t)
        rl.run(1)
    assert arb.fallen and rl.paused is True


def test_tilt_from_accel():
    assert tilt_from_accel([0, 0, 9.81]) == pytest.approx(0.0)
    assert tilt_from_accel([9.81, 0, 0]) == pytest.approx(90.0)
    assert tilt_from_accel([0, 0, 0]) is None and tilt_from_accel(None) is None
