"""步態 host 載入測試用的**假硬體介面（mock）**：假舵機介面、假 IMU、假足底開關。

只用來確認「上游主迴圈在不改原檔的情況下會呼叫仲裁器、不需要手把」。**不連任何硬體，
回傳的數值是固定的假資料，不代表真實鴨子的行為**，不能拿來當走路的驗證。
"""
from __future__ import annotations

import time

from ._paths import ensure_sibling_packages

ensure_sibling_packages()
from servo_console.joints import STANCE  # noqa: E402 上游 HWI.init_pos 的數值（已在本 repo，註明來源）

# 上游 HWI.joints 的順序（376de65 rustypot_position_hwi.py）：左腿、頭頸、右腿。主迴圈的 motor_targets[5:9] 是頭。
JOINT_ORDER = (
    "left_hip_yaw", "left_hip_roll", "left_hip_pitch", "left_knee", "left_ankle",
    "neck_pitch", "head_pitch", "head_yaw", "head_roll",
    "right_hip_yaw", "right_hip_roll", "right_hip_pitch", "right_knee", "right_ankle",
)


class LoopFinished(KeyboardInterrupt):
    """上游主迴圈是 `while True`，只接 KeyboardInterrupt；假介面用它在跑夠圈數後結束迴圈。"""


class FakeHWI:
    mock = True

    def __init__(self, *args, **kwargs):
        import numpy as np

        self._np = np
        self.joints = {name: i for i, name in enumerate(JOINT_ORDER)}
        self.init_pos = {name: STANCE[name] for name in JOINT_ORDER}
        self.targets: list[dict] = []
        self.turned_on = False
        self.max_writes: int | None = None
        self.step_ms: list[float] = []
        self._t: float | None = None

    def set_kps(self, kps):
        self.kps = list(kps)

    def set_kds(self, kds):
        self.kds = list(kds)

    def turn_on(self):
        self.turned_on = True

    def get_present_positions(self, ignore=()):
        return self._np.array([self.init_pos[n] for n in JOINT_ORDER], dtype=float)

    def get_present_velocities(self, ignore=()):
        return self._np.zeros(len(JOINT_ORDER))

    def set_position_all(self, action_dict):
        now = time.perf_counter()
        if self._t is not None:
            self.step_ms.append((now - self._t) * 1000.0)
        self._t = now
        self.targets.append({k: float(v) for k, v in action_dict.items()})
        if self.max_writes is not None and len(self.targets) >= self.max_writes:
            raise LoopFinished()


class FakeImu:
    mock = True

    def __init__(self, *args, **kwargs):
        import numpy as np

        self.last_imu_data = {"gyro": np.zeros(3), "accelero": np.array([0.0, 0.0, 9.81])}
        self.get_data_calls = 0

    def get_data(self):
        self.get_data_calls += 1
        return self.last_imu_data


class FakeFeetContacts:
    mock = True

    def __init__(self, *args, **kwargs):
        self.value = [True, True]
        self.stopped = False

    def get(self):
        return list(self.value)

    def stop(self):
        self.stopped = True


FAKE_OVERRIDES = {"HWI": FakeHWI, "Imu": FakeImu, "FeetContacts": FakeFeetContacts}
