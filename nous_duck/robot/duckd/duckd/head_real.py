"""頭部實機後端：預設只操作頭頸 4 顆舵機（ID 30–33），沿用舵機控制台的控制核心。

`legs=True`（duckd `--legs`，ADR-0020 草案）時白名單再加上腿部 10 顆，給原地蹲低／起立用：
接手頭部時**不碰腿的扭力**；要另外 `engage_legs()` 才會把沒出力的腿開扭力（先寫目前位置，不跳）、
開始送腿部目標。釋放時腿的扭力**不關**（站著時關掉會往前倒），只是不再送目標。
注意：`legs=True` 時 Controller 管 14 顆，緊急停止（包含過熱、低電壓的自動停止）會讓 14 顆都放鬆。

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
from .limits import (
    HEAD_JOINTS,
    HEAD_SERVO_IDS,
    LEG_JOINTS,
    LEG_SERVO_ID_BY_NAME,
    LEG_SERVO_IDS,
    ROBOT_XML_LEG_RANGE,
    ROBOT_XML_MARGIN_RAD,
    TEMP_REFUSE_C,
    VOLT_REFUSE_V,
    Limits,
)

ensure_sibling_packages()
from servo_console.bus import BusError  # noqa: E402
from servo_console.controller import SPEED_CHOICES_DEG, CommandError, Controller, scan_port_users  # noqa: E402
from servo_console.joints import JointInfo  # noqa: E402

HEAD_IDS: frozenset[int] = frozenset(HEAD_SERVO_IDS.values())
assert not HEAD_IDS & LEG_SERVO_IDS

ZH = {"neck_pitch": "脖子・俯仰", "head_pitch": "頭・俯仰", "head_yaw": "頭・左右轉", "head_roll": "頭・側傾"}
LEG_ZH = {
    "left_hip_yaw": "左髖・左右轉", "left_hip_roll": "左髖・側擺", "left_hip_pitch": "左髖・前後擺", "left_knee": "左膝",
    "left_ankle": "左踝", "right_hip_yaw": "右髖・左右轉", "right_hip_roll": "右髖・側擺", "right_hip_pitch": "右髖・前後擺",
    "right_knee": "右膝", "right_ankle": "右踝",
}


class LegAccessBlocked(BusError):
    """有程式想透過頭部後端碰白名單以外的舵機。"""


class HeadOnlyBus:
    """匯流排的白名單包裝：預設只放行 ID 30–33；`allowed` 可以加上腿（`--legs`）。"""

    def __init__(self, inner, allowed: frozenset[int] = HEAD_IDS):
        self._inner = inner
        self.allowed = frozenset(allowed)
        self.mock = getattr(inner, "mock", False)
        self.blocked = 0

    def _check(self, ids) -> None:
        bad = sorted(set(int(i) for i in ids) - self.allowed)
        if bad:
            self.blocked += 1
            raise LegAccessBlocked(f"這個後端不能碰舵機 ID {bad}")

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


def leg_joint_infos() -> list[JointInfo]:
    """腿部 10 顆：上游 robot.xml 的範圍往內縮 2°（跟舵機控制台一樣）。"""
    out = []
    for n in LEG_JOINTS:
        lo, hi = ROBOT_XML_LEG_RANGE[n]
        group = "left_leg" if n.startswith("left") else "right_leg"
        out.append(JointInfo(n, LEG_SERVO_ID_BY_NAME[n], LEG_ZH[n], group, lo + ROBOT_XML_MARGIN_RAD, hi - ROBOT_XML_MARGIN_RAD))
    return out


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
        legs: bool = False,
    ):
        self.limits = limits
        self.mock = mock
        self.legs_supported = legs
        self.kind = "head+legs" if legs else "head"
        allowed = HEAD_IDS | LEG_SERVO_IDS if legs else HEAD_IDS
        self.restore_torque = restore_torque
        self.bus: HeadOnlyBus | None = None

        def factory():
            self.bus = HeadOnlyBus(bus_factory(), allowed)
            return self.bus

        kwargs = {"clock": clock} if clock else {}
        self.controller = Controller(
            head_joint_infos(limits) + (leg_joint_infos() if legs else []),
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
        self.legs_engaged = False
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

    def engage_legs(self) -> dict[str, float]:
        """`--legs` 模式：把沒出力的腿開扭力（先寫目前位置，不跳），之後才接受腿部目標。回傳腿的角度。"""
        if not self.legs_supported:
            raise EngageError("這個 duckd 沒有用 --legs 啟動，不能接手腿")
        if not self.engaged:
            raise EngageError("先 engage（接手頭部與匯流排）")
        if self.controller.estop_reason:
            raise EngageError(f"緊急停止中：{self.controller.estop_reason}")
        off = [n for n in LEG_JOINTS if not self.controller.joints[n].torque]
        try:
            if off:
                self.controller.set_torque(off, True)
        except CommandError as exc:
            raise EngageError(str(exc)) from exc
        self.legs_engaged = True
        return self._legs_actual()

    def _legs_actual(self) -> dict[str, float]:
        return {n: float(self.controller.joints[n].actual) for n in LEG_JOINTS}

    def release(self) -> None:
        """恢復頭部 4 顆接手前的扭力狀態，釋放序列埠。腿的扭力不碰（`--legs` 也一樣：站著時關掉會倒）。"""
        self.legs_engaged = False
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
    def step(self, head: dict[str, float] | None, velocity, now: float, legs: dict[str, float] | None = None) -> None:
        if not self.engaged:
            return
        c = self.controller
        c.client_seen()  # duckd 的租約由仲裁器管；這裡只是讓 Controller 的 2 s 看門狗知道迴圈還活著
        targets = dict(head) if head is not None else {}
        if legs is not None and self.legs_engaged:
            targets.update({n: legs[n] for n in LEG_JOINTS})
        if targets and not c.estop_reason and "comm" not in c.alarms:
            try:
                c.set_targets(targets)
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
            legs_engaged=self.legs_engaged,
            legs=self._legs_actual() if self.legs_supported else None,
            legs_torque=self.legs_supported and all(bool(c.joints[n].torque) for n in LEG_JOINTS),
        )
