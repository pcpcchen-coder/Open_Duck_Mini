"""身體後端的共同介面與 `MockBody`。

後端只做兩件事：把仲裁器輸出的設定值送給硬體、把硬體狀態讀回來。安全規則不在這裡。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .limits import HEAD_JOINTS, LEG_JOINTS


class EngageError(RuntimeError):
    """接手硬體失敗（例如匯流排被舵機控制台占用）。訊息給操作的人看。"""


@dataclass
class BodyReading:
    engaged: bool = False
    head: dict[str, float] | None = None  # 回讀的關節角度（rad）
    head_age_ms: int | None = None
    head_torque: bool = False  # 頭部 4 顆是不是都在出力（沒出力就送目標也不會動）
    voltage_v: float | None = None
    servo_temp_max_c: float | None = None
    estop: str | None = None  # 後端自己觸發的緊急停止（例如過熱）
    block: tuple[str, str] | None = None  # 拒絕新動作的原因（reason 列舉, 說明）
    faults: list[str] = field(default_factory=list)
    #: 腿（只有 `--legs` 模式才有）：duckd 有沒有接手腿、回讀角度、10 顆是不是都在出力
    legs_engaged: bool = False
    legs: dict[str, float] | None = None
    legs_torque: bool = False


class MockBody:
    """模擬身體（mock）：頭部以一階延遲追設定值。**不代表真實舵機的行為。**"""

    mock = True
    kind = "mock"

    def __init__(self, start: dict[str, float] | None = None, lag: float = 0.5, legs: bool = False,
                 legs_start: dict[str, float] | None = None):
        self.head = {n: float((start or {}).get(n, 0.0)) for n in HEAD_JOINTS}
        #: 腿（mock）：`legs=True` 才有。預設停在 0；測試會給站姿。
        self.legs_supported = legs
        self.legs = {n: float((legs_start or {}).get(n, 0.0)) for n in LEG_JOINTS}
        self.legs_engaged = False
        self.leg_setpoints: list[dict[str, float]] = []
        self.legs_stuck: set[str] = set()  # 測試用：這些關節不會動（模擬腿被擋住）
        self.lag = lag
        self.engaged = False
        self.voltage_v = 8.0
        self.temp_c = 30.0
        self.fault_estop: str | None = None  # 測試用：模擬後端觸發緊急停止
        self.setpoints: list[dict[str, float]] = []  # 測試用：收到的設定值
        self.velocities: list[tuple[float, float, float]] = []
        self._t_read = 0.0

    def engage(self) -> dict[str, float]:
        self.engaged = True
        return dict(self.head)

    def release(self) -> None:
        self.engaged = False
        self.legs_engaged = False  # 腿的扭力不關（實機也一樣），只是 duckd 不再送目標

    def engage_legs(self) -> dict[str, float]:
        if not self.legs_supported:
            raise EngageError("這個 duckd 沒有用 --legs 啟動，不能接手腿")
        if not self.engaged:
            raise EngageError("先 engage（接手頭部與匯流排）")
        self.legs_engaged = True
        return dict(self.legs)

    def estop(self, reason: str) -> None:
        self.fault_estop = reason

    def reset_estop(self) -> None:
        self.fault_estop = None

    def step(self, head: dict[str, float] | None, velocity: tuple[float, float, float], now: float,
             legs: dict[str, float] | None = None) -> None:
        if not self.engaged:
            return
        if legs is not None and self.legs_engaged and self.fault_estop is None:
            self.leg_setpoints.append(dict(legs))
            if len(self.leg_setpoints) > 5000:
                del self.leg_setpoints[:2500]
            for n in LEG_JOINTS:
                if n not in self.legs_stuck:
                    self.legs[n] += (legs[n] - self.legs[n]) * self.lag
        if head is not None:
            self.setpoints.append(dict(head))
            if len(self.setpoints) > 5000:
                del self.setpoints[:2500]
            for n in HEAD_JOINTS:
                self.head[n] += (head[n] - self.head[n]) * self.lag
        if any(velocity):
            self.velocities.append(velocity)
        self._t_read = now

    def read(self, now: float) -> BodyReading:
        if not self.engaged:
            return BodyReading(engaged=False, estop=self.fault_estop)
        return BodyReading(
            engaged=True,
            head=dict(self.head),
            head_torque=self.fault_estop is None,
            head_age_ms=max(0, int((now - self._t_read) * 1000)) if self._t_read else 0,
            voltage_v=self.voltage_v,
            servo_temp_max_c=self.temp_c,
            estop=self.fault_estop,
            legs_engaged=self.legs_engaged,
            legs=dict(self.legs) if self.legs_supported else None,
            legs_torque=self.legs_engaged and self.fault_estop is None,
        )
