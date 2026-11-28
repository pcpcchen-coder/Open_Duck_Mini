"""原地蹲低／起立（ADR-0020 草案）：腿部 10 顆的開迴路關鍵影格。

這個模組只算「這一拍腿要到哪裡」，不碰硬體、不做安全判斷以外的事；硬體由身體後端執行。

- 姿勢只有兩個：`stand`（上游 `init_pos`）與 `crouch`，數字在 `postures/postures.json`，
  由 `sim/posture_sim/poses.py` 產生（`sim/tests/test_posture_sim.py` 檢查兩邊一致）。
- 腿只會沿著「站姿 ↔ 蹲姿」這一條路徑走：路徑上的位置用 `s`（0＝站、1＝蹲）表示，
  目標＝站姿＋(蹲姿−站姿)×smoothstep。模擬裡這條路徑上**任何一點停住都站得住**。
- 起點必須在路徑上（每個關節離路徑 ≤ `ON_PATH_TOL_RAD`）；不在路徑上就拒絕，請人用舵機控制台擺好。
- **時間軸用「每拍最多前進 `MAX_STEP_S`」**：控制迴圈晚了，動作就跟著慢，不會一拍跳很遠
  （模擬：卡 1 秒後直接跳，力矩打到上限；時間軸暫停則沒事）。
- 收手＝`hold()`：停在目前的目標，狀態變成 `holding_partial`（或兩端的 standing／crouched）。
  之後只接受回到站姿，而且用 `RECOVER_DURATION_S` 慢慢回去。**不放鬆**：模擬裡放鬆會往前倒。
- 跟隨誤差：任何一個關節的實際角度離目標超過 `TRACK_ERR_RAD` 持續 `TRACK_ERR_HOLD_S`，
  就自動 `hold()` 並回報 `tracking_error`（腿被擋住、被抱起來、或倒了）。沒有 IMU 時這是唯一的自動判斷。

驗證層級：單元測試＋MuJoCo（`sim/tests/test_posture_sim.py` 把這個模組的輸出餵進模擬）。**沒有實機驗證。**
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from .limits import LEG_JOINTS, ROBOT_XML_LEG_RANGE, ROBOT_XML_MARGIN_RAD

POSTURES_PATH = Path(__file__).resolve().parent / "postures" / "postures.json"
SCHEMA = "nous-duck/postures@1"

CONTROL_DT = 0.02
MAX_STEP_S = 0.03  # 每拍時間軸最多前進 1.5 拍
DEFAULT_DURATION_S = 3.0
MIN_DURATION_S = 3.0  # ADR-0020 §2.4：不能比 3 秒快
MAX_DURATION_S = 10.0
RECOVER_DURATION_S = 6.0  # 收手後回站姿用的時間（全程）
ON_PATH_TOL_RAD = math.radians(6.0)
END_TOL = 0.03  # s 離兩端這麼近就算到了
TRACK_ERR_RAD = math.radians(20.0)
TRACK_ERR_HOLD_S = 0.5

STATES = ("unknown", "standing", "crouched", "moving", "holding_partial")


def smoothstep(a: float) -> float:
    a = min(max(a, 0.0), 1.0)
    return a * a * (3.0 - 2.0 * a)


def load_postures(path: Path = POSTURES_PATH) -> dict[str, dict[str, float]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise ValueError(f"{path} 不是 {SCHEMA}")
    out = {}
    for name in ("stand", "crouch"):
        pose = data["postures"][name]["legs"]
        if set(pose) != set(LEG_JOINTS):
            raise ValueError(f"{name} 的關節不是腿部 10 顆")
        for j, v in pose.items():
            lo, hi = ROBOT_XML_LEG_RANGE[j]
            if not lo + ROBOT_XML_MARGIN_RAD <= float(v) <= hi - ROBOT_XML_MARGIN_RAD:
                raise ValueError(f"{name}.{j}={v} 超出 robot.xml 範圍（內縮 2°）")
        out[name] = {j: float(pose[j]) for j in LEG_JOINTS}
    return out


@dataclass
class Fault:
    code: str  # tracking_error、off_path
    detail: str


class PostureMotion:
    def __init__(self, postures: dict[str, dict[str, float]] | None = None):
        p = postures or load_postures()
        self.stand = p["stand"]
        self.crouch = p["crouch"]
        self._delta = {j: self.crouch[j] - self.stand[j] for j in LEG_JOINTS}
        self._norm2 = sum(d * d for d in self._delta.values())
        self.state = "unknown"
        self.s = 0.0  # 目前目標在路徑上的位置（0＝站、1＝蹲）
        self._from = self._to = 0.0
        self._duration = DEFAULT_DURATION_S
        self._elapsed = 0.0
        self.target_name: str | None = None
        self.recovering = False
        self._err_since: float | None = None
        self.last_fault: Fault | None = None

    # ------------------------------------------------------------ 路徑
    def pose_at(self, s: float) -> dict[str, float]:
        return {j: self.stand[j] + self._delta[j] * s for j in LEG_JOINTS}

    def project(self, actual: dict[str, float]) -> tuple[float, float]:
        """實際腿部角度投影到路徑上：回傳 (s, 離路徑最遠的關節誤差 rad)。s 夾在 0～1。"""
        s = sum((actual[j] - self.stand[j]) * self._delta[j] for j in LEG_JOINTS) / self._norm2
        s = min(max(s, 0.0), 1.0)
        on = self.pose_at(s)
        return s, max(abs(actual[j] - on[j]) for j in LEG_JOINTS)

    def _end_state(self, s: float) -> str:
        if s <= END_TOL:
            return "standing"
        if s >= 1.0 - END_TOL:
            return "crouched"
        return "holding_partial"

    # ------------------------------------------------------------ 指令
    def attach(self, actual: dict[str, float]) -> str:
        """腿剛接手時呼叫：從實際角度判斷目前在哪。回傳狀態。"""
        s, err = self.project(actual)
        self._err_since = None
        if err > ON_PATH_TOL_RAD:
            self.state = "unknown"
            self.s = 0.0
        else:
            self.s = s
            self.state = self._end_state(s)
        self.recovering = False
        return self.state

    def detach(self) -> None:
        self.state = "unknown"
        self.target_name = None
        self.recovering = False

    def start(self, target: str, actual: dict[str, float], duration_s: float | None = None) -> str | None:
        """開始移動。成功回傳 None，拒絕回傳原因（給人看的字串）。`duration_s` 是走完整條路徑的時間。"""
        if target not in ("stand", "crouch"):
            return f"unknown posture {target!r}"
        if self.state == "moving":
            return "busy: posture motion in progress"
        s_actual, err = self.project(actual)
        if err > ON_PATH_TOL_RAD:
            self.state = "unknown"
            return f"legs are not on the stand-crouch path (max error {math.degrees(err):.1f} deg); pose the legs with the servo console first"
        if self.state == "holding_partial" and target != "stand":
            return "after an abort only 'stand' is allowed"
        goal = 0.0 if target == "stand" else 1.0
        # 從目前目標出發（剛接手時目標＝實際角度的投影）
        start = self.s if self.state in ("standing", "crouched", "holding_partial") else s_actual
        if abs(goal - start) <= END_TOL:
            self.s = goal
            self.state = self._end_state(goal)
            return f"already {self.state}"
        full = DEFAULT_DURATION_S if duration_s is None else float(duration_s)
        if not math.isfinite(full):
            return "duration_s is not a number"
        full = min(max(full, MIN_DURATION_S), MAX_DURATION_S)
        self.recovering = self.state == "holding_partial"
        if self.recovering:
            full = max(full, RECOVER_DURATION_S)
        self._from, self._to = start, goal
        self._duration = full * abs(goal - start)
        self._elapsed = 0.0
        self.target_name = target
        self.state = "moving"
        self.last_fault = None
        return None

    def hold(self) -> str:
        """收手：停在目前目標。回傳新狀態。"""
        if self.state == "moving":
            self.state = self._end_state(self.s)
            self.target_name = None
        return self.state

    # ------------------------------------------------------------ 每拍
    def step(self, dt: float, actual: dict[str, float] | None, now: float) -> dict[str, float] | None:
        """回傳這一拍的腿部目標；`state` 是 unknown 時回傳 None（不送腿部目標）。

        `dt` 是牆上時間；時間軸最多前進 `MAX_STEP_S`。`actual` 是回讀角度（None＝這拍沒讀到）。
        """
        if self.state == "unknown":
            return None
        finished = False
        if self.state == "moving":
            self._elapsed += min(max(dt, 0.0), MAX_STEP_S)
            a = 1.0 if self._duration <= 0 else self._elapsed / self._duration
            self.s = self._from + (self._to - self._from) * smoothstep(a)
            finished = a >= 1.0
        target = self.pose_at(self.s)
        if actual is not None:
            err = max(abs(actual[j] - target[j]) for j in LEG_JOINTS)
            if err > TRACK_ERR_RAD:
                if self._err_since is None:
                    self._err_since = now
                elif now - self._err_since >= TRACK_ERR_HOLD_S and self.state == "moving":
                    worst = max(LEG_JOINTS, key=lambda j: abs(actual[j] - target[j]))
                    self.last_fault = Fault("tracking_error", f"{worst} is {math.degrees(abs(actual[worst] - target[worst])):.0f} deg from target")
                    self.hold()
                    return target
            else:
                self._err_since = None
        if finished:
            self.s = self._to
            self.state = self._end_state(self.s)
            self.target_name = None
            self.recovering = False
            target = self.pose_at(self.s)
        return target

    def snapshot(self) -> dict:
        return {
            "state": self.state,
            "s": round(self.s, 3),
            "target": self.target_name,
            "recovering": self.recovering,
            "fault": None if self.last_fault is None else {"code": self.last_fault.code, "detail": self.last_fault.detail},
        }
