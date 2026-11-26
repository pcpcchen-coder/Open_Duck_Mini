"""舵機匯流排：真的（pypot FeetechSTS3215IO）與模擬（MockBus）。

角度單位：舵機角度（degree），2048 = 0°，跟 pypot 的換算一致；換成關節角度由 controller 處理。
pypot 讀取失敗時回傳空 tuple，不丟例外；這裡一律檢查長度，讀不到就丟 BusError。
"""
from __future__ import annotations

import random
import threading


class BusError(RuntimeError):
    pass


def decode_load(raw: int) -> float:
    """STS3215 present load：bit 10 是方向，0–1000 是千分比。回傳百分比（帶正負號）。"""
    value = (raw & 0x3FF) / 10.0
    return -value if raw & 0x400 else value


class FeetechBus:
    """真的匯流排。只在 Pi 上用（需要 runtime-venv 的 pypot）。"""

    mock = False

    def __init__(self, port: str = "/dev/ttyACM0"):
        self.port = port
        self.io = None
        self._lock = threading.Lock()

    def open(self) -> None:
        from pypot.feetech import FeetechSTS3215IO  # 只在 Pi 上有

        self.io = FeetechSTS3215IO(self.port, baudrate=1000000, timeout=0.02, use_sync_read=True)

    def close(self) -> None:
        if self.io is not None:
            try:
                self.io.close()
            finally:
                self.io = None

    def _get(self, fn, ids: list[int], what: str) -> list:
        if self.io is None:
            raise BusError("匯流排沒有開")
        with self._lock:
            values = list(fn(ids))
        if len(values) != len(ids):
            raise BusError(f"讀{what}失敗（回應 {len(values)}／{len(ids)}）")
        return values

    def ping(self, ids: list[int]) -> list[int]:
        with self._lock:
            return [i for i in ids if self.io.ping(i)]

    def read_positions(self, ids: list[int]) -> list[float]:
        return [float(v) for v in self._get(self.io.get_present_position, ids, "位置")]

    def read_status(self, ids: list[int]) -> dict[str, list]:
        return {
            "temperature": [int(v) for v in self._get(self.io.get_present_temperature, ids, "溫度")],
            "voltage": [v / 10.0 for v in self._get(self.io.get_present_voltage, ids, "電壓")],
            "load": [decode_load(int(v)) for v in self._get(self.io.get_present_load, ids, "負載")],
            "torque": [bool(v) for v in self._get(self.io.is_torque_enabled, ids, "扭力狀態")],
        }

    def read_kp(self, ids: list[int]) -> list[int]:
        return [int(v) for v in self._get(self.io.get_P_coefficient, ids, "kp")]

    def write_goals(self, goals: dict[int, float]) -> None:
        if not goals:
            return
        with self._lock:
            self.io.set_goal_position(goals)

    def set_torque(self, ids: list[int], on: bool) -> None:
        with self._lock:
            (self.io.enable_torque if on else self.io.disable_torque)(ids)

    def set_kp(self, values: dict[int, int]) -> None:
        with self._lock:
            self.io.set_P_coefficient(values)


class MockBus:
    """模擬匯流排（mock）：沒有硬體時測試介面與安全規則用。**不代表真實舵機的行為。**"""

    mock = True

    def __init__(self, ids: list[int], start_deg: dict[int, float] | None = None, seed: int = 1):
        self.ids = list(ids)
        self.pos = {i: (start_deg or {}).get(i, 0.0) for i in ids}
        self.goal = dict(self.pos)
        self.torque = {i: False for i in ids}
        self.kp = {i: 32 for i in ids}
        self.temp = {i: 30.0 for i in ids}
        self.voltage = 8.1
        self.fail_reads = 0  # 測試用：接下來幾次讀取失敗
        self.missing: set[int] = set()  # 測試用：不回應的 ID
        self.is_open = False
        self.writes: list[dict[int, float]] = []
        self._rng = random.Random(seed)

    def open(self) -> None:
        self.is_open = True

    def close(self) -> None:
        self.is_open = False

    def _check(self, ids: list[int]) -> None:
        if not self.is_open:
            raise BusError("匯流排沒有開")
        if self.fail_reads > 0:
            self.fail_reads -= 1
            raise BusError("模擬讀取失敗")
        if any(i in self.missing for i in ids):
            raise BusError("模擬舵機沒回應")

    def _settle(self) -> None:
        for i in self.ids:
            if self.torque[i]:
                # 每次讀取往目標走 40%（大約模擬舵機追目標）
                self.pos[i] += (self.goal[i] - self.pos[i]) * 0.4

    def ping(self, ids: list[int]) -> list[int]:
        return [i for i in ids if i not in self.missing]

    def read_positions(self, ids: list[int]) -> list[float]:
        self._check(ids)
        self._settle()
        return [self.pos[i] + self._rng.uniform(-0.05, 0.05) for i in ids]

    def read_status(self, ids: list[int]) -> dict[str, list]:
        self._check(ids)
        return {
            "temperature": [int(round(self.temp[i])) for i in ids],
            "voltage": [self.voltage for _ in ids],
            "load": [(self.goal[i] - self.pos[i]) * 2.0 if self.torque[i] else 0.0 for i in ids],
            "torque": [self.torque[i] for i in ids],
        }

    def read_kp(self, ids: list[int]) -> list[int]:
        self._check(ids)
        return [self.kp[i] for i in ids]

    def write_goals(self, goals: dict[int, float]) -> None:
        if not self.is_open:
            raise BusError("匯流排沒有開")
        self.writes.append(dict(goals))
        self.goal.update(goals)

    def set_torque(self, ids: list[int], on: bool) -> None:
        if not self.is_open:
            raise BusError("匯流排沒有開")
        for i in ids:
            self.torque[i] = on

    def set_kp(self, values: dict[int, int]) -> None:
        self.kp.update(values)
