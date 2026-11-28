"""蹲低／起立的開迴路關鍵影格模擬（ADR-0020 草案的 B 類動作）。

模型用 `walk_sim.model.build_model`（上游 `robot.xml` ＋ Playground 的舵機參數，不改原檔）。
控制方式模仿 duckd：**50 Hz** 送關節目標，目標依「牆上時間」做平滑內插（smoothstep），
所以控制迴圈晚一拍時，下一拍會直接跳到該時間的目標，不會累積延遲。

量的東西（都是模擬值）：

- `base_drop_cm`：蹲低後機身（base）比站姿低多少。
- `trunk_pitch_deg`：機身俯仰角，正值＝前傾（低頭）。
- `support_margin_cm`：重心投影到地面後，離鞋底前後緣最近的距離（負值＝重心已經在鞋底外面）。
  鞋底範圍取兩片鞋底碰撞網格頂點的 x 範圍（只看前後方向；左右方向雙腳對稱，這裡不檢查）。
- `foot_slip_cm`：腳在地上滑了多少（水平位移最大值）。
- `max_torque_nm`：所有關節力矩的最大絕對值（模擬的舵機上限是 3.23 N·m）。
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import mujoco
import numpy as np

from walk_sim.model import DECIMATION, HOME_BASE_Z, SIM_DT, ModelOptions, build_model

from .poses import CROUCH, CROUCH_HEAD_DOWN, JOINTS, STAND, as_array

CONTROL_HZ = 50


def smoothstep(a: float) -> float:
    a = min(max(a, 0.0), 1.0)
    return a * a * (3.0 - 2.0 * a)


@dataclass
class Segment:
    """從目前目標移到 `target`，花 `duration` 秒；`target=None` 代表原地保持。"""

    target: dict | None
    duration: float
    name: str = ""


@dataclass
class Metrics:
    name: str
    base_z: float
    trunk_pitch_deg: float
    support_margin_cm: float
    min_support_margin_cm: float
    pitch_range_deg: tuple[float, float]


@dataclass
class TrialResult:
    segments: list[Metrics]
    base_drop_cm: float
    foot_slip_cm: float
    max_torque_nm: float
    min_support_margin_cm: float
    fell: bool
    stand_base_z: float
    extras: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class PostureSim:
    def __init__(self, options: ModelOptions | None = None):
        self.m = build_model(options or ModelOptions())
        self.d = mujoco.MjData(self.m)
        m = self.m
        self._qadr = np.array([m.jnt_qposadr[m.joint(n).id] for n in JOINTS])
        self._act = np.array([m.actuator(n).id for n in JOINTS])
        self._feet_body = [m.body("foot_assembly").id, m.body("foot_assembly_2").id]
        self._soles = [m.geom("left_foot_bottom_tpu").id, m.geom("right_foot_bottom_tpu").id]
        self._head = m.body("head_assembly").id
        self.target = as_array(STAND)
        self._kp0 = m.actuator_gainprm[self._act, 0].copy()

    # ------------------------------------------------------------ 狀態
    def reset(self) -> None:
        m, d = self.m, self.d
        m.actuator_gainprm[self._act, 0] = self._kp0  # `limp_at` 會改 kp，這裡還原
        m.actuator_biasprm[self._act, 1] = -self._kp0
        mujoco.mj_resetData(m, d)
        d.qpos[2] = HOME_BASE_Z
        d.qpos[3] = 1.0
        d.qpos[self._qadr] = as_array(STAND)
        self.target = as_array(STAND)
        d.ctrl[self._act] = self.target
        mujoco.mj_forward(m, d)
        for _ in range(500):  # 1 秒：讓鴨子落地站穩
            mujoco.mj_step(m, d)

    def trunk_pitch_deg(self) -> float:
        R = self.d.xmat[1].reshape(3, 3)
        return math.degrees(math.atan2(-R[2, 0], R[2, 2]))

    def head_pitch_deg(self) -> float:
        R = self.d.xmat[self._head].reshape(3, 3)
        return math.degrees(math.atan2(-R[2, 0], R[2, 2]))

    def sole_x_range(self) -> tuple[float, float]:
        m, d = self.m, self.d
        xs = []
        for g in self._soles:
            mid = m.geom_dataid[g]
            V = m.mesh_vert[m.mesh_vertadr[mid] : m.mesh_vertadr[mid] + m.mesh_vertnum[mid]]
            W = V @ d.geom_xmat[g].reshape(3, 3).T + d.geom_xpos[g]
            xs.append(W[:, 0])
        xs = np.concatenate(xs)
        return float(xs.min()), float(xs.max())

    def support_margin(self) -> float:
        """重心離鞋底前後緣最近的距離（m）。需要先 mj_step（subtree_com 已更新）。"""
        lo, hi = self.sole_x_range()
        cx = float(self.d.subtree_com[1][0])
        return min(cx - lo, hi - cx)

    def feet_xy(self) -> np.ndarray:
        return self.d.xpos[self._feet_body][:, :2].copy()

    # ------------------------------------------------------------ 執行
    def run(
        self,
        segments: list[Segment],
        *,
        stall: tuple[float, float] | None = None,
        limp_at: float | None = None,
        limp_kp: float = 0.5,
        stall_mode: str = "jump",
    ) -> TrialResult:
        """依序執行各段。

        - `stall=(t, dur)`：從第 t 秒起，控制迴圈卡住 dur 秒（目標停在卡住前的值），
          模擬 duckd 控制迴圈 overrun。`stall_mode="jump"`：恢復後目標直接跳到牆上時間該到的位置；
          `"pause"`：時間軸跟著暫停，恢復後從卡住的地方接著走（動作總時間變長）。
        - `limp_at=t`：第 t 秒起把所有關節的 kp 降到 `limp_kp`（模擬「放鬆」收手）。
        """
        if stall_mode not in ("jump", "pause"):
            raise ValueError(f"unknown stall_mode {stall_mode!r}")
        m, d = self.m, self.d
        self.reset()
        feet0 = self.feet_xy()
        stand_z = float(d.qpos[2])
        out: list[Metrics] = []
        max_tau = 0.0
        min_margin_all = math.inf
        t = 0.0
        steps_per_ctrl = DECIMATION
        for seg in segments:
            start = self.target.copy()
            goal = start if seg.target is None else as_array(seg.target)
            n_ctrl = max(1, int(round(seg.duration * CONTROL_HZ)))
            pitches = []
            min_margin = math.inf
            k = 0  # 牆上時間（控制拍數）
            prog = 0  # 時間軸進度（拍數）；jump 模式下等於 k
            while prog < n_ctrl:
                t_ctrl = t + k / CONTROL_HZ
                stalled = stall is not None and stall[0] <= t_ctrl < stall[0] + stall[1]
                k += 1
                if stall_mode == "jump" or not stalled:
                    prog += 1
                if not stalled:
                    a = smoothstep(prog / n_ctrl)
                    self.target = start + (goal - start) * a
                    d.ctrl[self._act] = self.target
                if limp_at is not None and t_ctrl >= limp_at:
                    for aid in self._act:
                        m.actuator_gainprm[aid, 0] = limp_kp
                        m.actuator_biasprm[aid, 1] = -limp_kp
                for _ in range(steps_per_ctrl):
                    mujoco.mj_step(m, d)
                max_tau = max(max_tau, float(np.abs(d.actuator_force[self._act]).max()))
                margin = self.support_margin()
                min_margin = min(min_margin, margin)
                pitches.append(self.trunk_pitch_deg())
            t += k / CONTROL_HZ
            min_margin_all = min(min_margin_all, min_margin)
            out.append(
                Metrics(
                    name=seg.name,
                    base_z=round(float(d.qpos[2]), 4),
                    trunk_pitch_deg=round(pitches[-1], 1),
                    support_margin_cm=round(self.support_margin() * 100, 2),
                    min_support_margin_cm=round(min_margin * 100, 2),
                    pitch_range_deg=(round(min(pitches), 1), round(max(pitches), 1)),
                )
            )
        slip = float(np.abs(self.feet_xy() - feet0).max())
        lowest = min(s.base_z for s in out)
        fell = bool(d.qpos[2] < 0.08 or abs(self.trunk_pitch_deg()) > 60)
        return TrialResult(
            segments=out,
            base_drop_cm=round((stand_z - lowest) * 100, 2),
            foot_slip_cm=round(slip * 100, 2),
            max_torque_nm=round(max_tau, 3),
            min_support_margin_cm=round(min_margin_all * 100, 2),
            fell=fell,
            stand_base_z=round(stand_z, 4),
        )


def crouch_cycle(duration: float = 3.0, hold: float = 5.0, crouch: dict | None = None) -> list[Segment]:
    c = crouch or CROUCH
    return [
        Segment(c, duration, "down"),
        Segment(None, hold, "hold"),
        Segment(STAND, duration, "up"),
        Segment(None, 2.0, "settle"),
    ]


def partial(fraction: float, crouch: dict | None = None) -> dict:
    """站姿與蹲姿之間的中間姿勢（線性插值，fraction=0 站、1 蹲）。"""
    c = crouch or CROUCH
    return {n: STAND[n] + (c[n] - STAND[n]) * fraction for n in JOINTS}


def head_level_offset(crouch: dict | None = None) -> float:
    """蹲低時 head_pitch 要加多少（rad），頭的俯仰角才會跟站姿時一樣（模擬裡二分搜尋）。

    預設從「頭不抬」的蹲姿（`CROUCH_HEAD_DOWN`）算起。
    """
    c = dict(crouch or CROUCH_HEAD_DOWN)
    sim = PostureSim()
    sim.run([Segment(STAND, 0.1, "stand"), Segment(None, 1.0, "hold")])
    ref = sim.head_pitch_deg()

    def head_after(offset: float) -> float:
        p = dict(c)
        p["head_pitch"] = c["head_pitch"] + offset
        sim.run([Segment(p, 2.0, "down"), Segment(None, 1.0, "hold")])
        return sim.head_pitch_deg()

    lo, hi = -0.785, 0.785  # head_pitch 的 URDF 限位
    f_lo = head_after(lo) - ref
    for _ in range(14):
        mid = (lo + hi) / 2
        f_mid = head_after(mid) - ref
        if (f_mid > 0) == (f_lo > 0):
            lo, f_lo = mid, f_mid
        else:
            hi = mid
    return (lo + hi) / 2
