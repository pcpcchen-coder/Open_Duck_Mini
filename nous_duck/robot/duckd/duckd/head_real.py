"""頭部實機後端：只操作頭頸 4 顆舵機（ID 30–33），沿用舵機控制台的控制核心。

- 重用 `servo_console.controller.Controller`（限速、開扭力不跳、溫度電壓保護、讀取失敗處理）與
  `servo_console.bus.FeetechBus`，**不改它們**：Controller 只拿到 4 個頭部關節，所以它的
  「全部」（包含緊急停止關扭力）就只是這 4 顆。
- `HeadOnlyBus` 再包一層：任何讀寫只要帶到白名單以外的 ID（腿是 10–14、20–24）就丟例外，
  不會送到匯流排。就算上層程式寫錯，也不會對腿部舵機寫入任何東西（tests/test_head_real.py）。
- 接手前檢查序列埠有沒有被別的程式開著（舵機控制台、上游腳本）；有就不搶。
- 釋放時把頭部 4 顆的扭力恢復成接手前的狀態。腿的扭力從頭到尾不碰。
"""
from __future__ import annotations

import math
import tempfile
from pathlib import Path
from typing import Callable

from ._paths import ensure_sibling_packages
from .body import BodyReading, EngageError
from .limits import HEAD_JOINTS, HEAD_SERVO_IDS, LEG_SERVO_IDS, TEMP_REFUSE_C, VOLT_REFUSE_V, Limits

ensure_sibling_packages()
from servo_console.bus import BusError  # noqa: E402
from servo_console.controller import SPEED_CHOICES_DEG, CommandError, Controller, scan_port_users  # noqa: E402
from servo_console.joints import JointInfo  # noqa: E402

HEAD_IDS: frozenset[int] = frozenset(HEAD_SERVO_IDS.values())
assert not HEAD_IDS & LEG_SERVO_IDS

ZH = {"neck_pitch": "脖子・俯仰", "head_pitch": "頭・俯仰", "head_yaw": "頭・左右轉", "head_roll": "頭・側傾"}


class LegAccessBlocked(BusError):
    """有程式想透過頭部後端碰白名單以外的舵機。"""


class HeadOnlyBus:
    """匯流排的白名單包裝：只放行 ID 30–33。"""

    def __init__(self, inner):
        self._inner = inner
        self.mock = getattr(inner, "mock", False)
        self.blocked = 0

    def _check(self, ids) -> None:
        bad = sorted(set(int(i) for i in ids) - HEAD_IDS)
        if bad:
            self.blocked += 1
            raise LegAccessBlocked(f"頭部後端不能碰舵機 ID {bad}")

    def open(self) -> None:
        self._inner.open()

    def close(self) -> None:
        self._inner.close()

    def ping(self, ids):
        self._check(ids)
        return self._inner.ping(list(ids))

    def read_positions(self, ids):
        self._check(ids)
        return self._inner.read_positions(list(ids))

    def read_status(self, ids):
        self._check(ids)
        return self._inner.read_status(list(ids))

    def read_kp(self, ids):
        self._check(ids)
        return self._inner.read_kp(list(ids))

    def write_goals(self, goals):
        self._check(goals.keys())
        self._inner.write_goals(dict(goals))

    def set_torque(self, ids, on):
        self._check(ids)
        self._inner.set_torque(list(ids), on)

    def set_kp(self, values):
        # duckd 不改 kp（EEPROM 區的暫存器）
        raise LegAccessBlocked("頭部後端不寫 kp")


def head_joint_infos(limits: Limits) -> list[JointInfo]:
    return [JointInfo(n, HEAD_SERVO_IDS[n], ZH[n], "head", *limits.head_range[n]) for n in HEAD_JOINTS]


class HeadBody:
    kind = "head"

    def __init__(
        self,
        limits: Limits,
        bus_factory: Callable[[], object],
        config_path: Path,
        port_users: Callable[[], list[tuple[int, str]]] = lambda: [],
        clock: Callable[[], float] | None = None,
        restore_torque: bool = True,
        mock: bool = False,
    ):
        self.limits = limits
        self.mock = mock
        self.restore_torque = restore_torque
        self.bus: HeadOnlyBus | None = None

        def factory():
            self.bus = HeadOnlyBus(bus_factory())
            return self.bus

        kwargs = {"clock": clock} if clock else {}
        self.controller = Controller(
            head_joint_infos(limits),
            factory,
            Path(config_path),
            Path(tempfile.gettempdir()) / "duckd-unused-poses.json",  # 姿勢功能不用
            port_users=port_users,
            mock=mock,
            **kwargs,
        )
        # Controller 的限速是第二道：取不低於仲裁器上限的最小檔
        want = math.degrees(limits.head_max_speed)
        self.controller.set_speed(next((c for c in SPEED_CHOICES_DEG if c >= want - 1e-6), SPEED_CHOICES_DEG[-1]))
        self.torque_before: dict[str, bool] | None = None
        self.engaged = False
        self._clock = self.controller.clock
        self._last_read = 0.0
        self.step_errors = 0

    @classmethod
    def real(cls, limits: Limits, serial: str, config_path: Path, **kw) -> "HeadBody":
        from servo_console.bus import FeetechBus

        return cls(limits, lambda: FeetechBus(serial), config_path, port_users=lambda: scan_port_users([serial]), **kw)

    # ------------------------------------------------------------ 接手／釋放
    def engage(self) -> dict[str, float]:
        """開匯流排、讀目前位置、把沒出力的頭部舵機開扭力（先寫目前位置，不跳）。回傳目前角度。"""
        if self.engaged:
            return self._actual()
        try:
            self.controller.connect()
        except CommandError as exc:
            raise EngageError(str(exc)) from exc
        if self.controller.estop_reason:
            self.controller.release()
            raise EngageError(f"頭部後端在緊急停止狀態：{self.controller.estop_reason}")
        self.torque_before = {n: bool(self.controller.joints[n].torque) for n in HEAD_JOINTS}
        off = [n for n, on in self.torque_before.items() if not on]
        try:
            if off:
                self.controller.set_torque(off, True)
        except CommandError as exc:
            self.controller.release()
            raise EngageError(str(exc)) from exc
        self.engaged = True
        self._last_read = self._clock()
        return self._actual()

    def release(self) -> None:
        """恢復頭部 4 顆接手前的扭力狀態，釋放序列埠。腿的扭力不碰。"""
        if not self.engaged:
            return
        try:
            if self.restore_torque and self.torque_before and not self.controller.estop_reason:
                off = [n for n, on in self.torque_before.items() if not on]
                if off:
                    self.controller.set_torque(off, False)
        except CommandError:
            pass
        finally:
            self.controller.release()
            self.engaged = False

    def _actual(self) -> dict[str, float]:
        return {n: float(self.controller.joints[n].actual) for n in HEAD_JOINTS}

    # ------------------------------------------------------------ 每圈
    def step(self, head: dict[str, float] | None, velocity, now: float) -> None:
        if not self.engaged:
            return
        c = self.controller
        c.client_seen()  # duckd 的租約由仲裁器管；這裡只是讓 Controller 的 2 s 看門狗知道迴圈還活著
        if head is not None and not c.estop_reason and "comm" not in c.alarms:
            try:
                c.set_targets(head)
            except CommandError:
                self.step_errors += 1
        c.tick()
        if c.fail_count == 0:  # 這一圈位置讀成功
            self._last_read = now

    def estop(self, reason: str) -> None:
        """本機緊急停止：頭部 4 顆關扭力並鎖住（Controller 的規則）。腿不碰。"""
        self.controller.estop(reason)

    def reset_estop(self) -> None:
        try:
            self.controller.reset_estop()
        except CommandError as exc:
            raise EngageError(str(exc)) from exc

    def read(self, now: float) -> BodyReading:
        c = self.controller
        if not self.engaged:
            return BodyReading(engaged=False)
        temps = [j.temperature for j in c.joints.values() if j.temperature is not None]
        volts = [j.voltage for j in c.joints.values() if j.voltage]
        block = None
        faults = []
        if "comm" in c.alarms:
            block = ("hardware_fault", "servo bus read failures")
            faults.append("servo_comm")
        if temps and max(temps) >= TEMP_REFUSE_C:
            block = block or ("overheat", f"head servo {max(temps)} C")
            faults.append("servo_overheat")
        if volts and min(volts) < VOLT_REFUSE_V:
            block = block or ("low_battery", f"servo bus {min(volts):.1f} V")
            faults.append("low_voltage")
        return BodyReading(
            engaged=True,
            head=self._actual(),
            head_torque=all(bool(c.joints[n].torque) for n in HEAD_JOINTS),
            head_age_ms=max(0, int((now - self._last_read) * 1000)),
            voltage_v=min(volts) if volts else None,
            servo_temp_max_c=float(max(temps)) if temps else None,
            estop=c.estop_reason,
            block=block,
            faults=faults,
        )
