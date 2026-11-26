"""look_at 控制器的 MuJoCo 模擬（固定機身、合成人臉偵測、運動學轉身）。"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import mujoco
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
ROBOT_XML = REPO_ROOT / "mini_bdx/robots/open_duck_mini_v2/robot.xml"
sys.path.insert(0, str(REPO_ROOT / "nous_duck/robot"))

from behaviors.look_at import (  # noqa: E402
    CameraIntrinsics,
    Face,
    Gaze,
    LookAtConfig,
    LookAtController,
    SpeakerDirection,
    VisionFrame,
)

#: 上游 Open_Duck_Playground（main，2026-11-13 取得）scene_flat_terrain.xml 的 home keyframe，
#: 與 `hardware/dock/cad/dock_cad/duck.py` 相同。頭頸與天線為 0。
HOME_POSE = {
    "left_hip_yaw": 0.002,
    "left_hip_roll": 0.053,
    "left_hip_pitch": -0.63,
    "left_knee": 1.368,
    "left_ankle": -0.784,
    "right_hip_yaw": -0.003,
    "right_hip_roll": -0.065,
    "right_hip_pitch": 0.635,
    "right_knee": 1.379,
    "right_ankle": -0.796,
}
HEAD_JOINTS = ("neck_pitch", "head_pitch", "head_yaw", "head_roll")

#: 鏡頭在 `head` body 座標中的位置（m）：頭殼正面中間。頭殼還沒重新設計，這是假設值。
CAMERA_MOUNT = np.array([0.095, 0.0, -0.03])

FACE_WIDTH_M = 0.15
MIN_FACE_PX = 15.0  # 合成偵測器：臉寬小於這個像素就當成偵測不到（假設值）


@dataclass
class Person:
    name: str
    #: 時間 → 臉中心在房間座標的位置（m）。房間座標：原點在鴨子正下方，+x 是鴨子一開始的正前方，
    #: +y 是左邊，z 是離地高度。
    path: Callable[[float], tuple[float, float, float]]
    present: Callable[[float], bool] = lambda t: True


@dataclass
class Scenario:
    name: str
    description: str
    duration: float
    people: list[Person]
    #: 時間 → 這時應該看誰（量誤差用）；None 表示這時不該看任何人。
    expected: Callable[[float], str | None]
    #: （時間, 說話的人）：麥克風陣列在這些時間回報說話者方向。
    speaker_events: list[tuple[float, str]] = field(default_factory=list)


@dataclass
class SimOptions:
    seed: int = 0
    vision_fps: float = 10.0
    latency_s: float = 0.1  # 拍攝到控制器收到偵測結果的延遲
    px_noise: float = 2.0  # 人臉中心的像素雜訊（標準差）
    speaker_noise_deg: float = 10.0  # 說話者方向的雜訊（標準差）
    body_turn_tau_s: float = 0.3  # 轉身指令到實際轉速的一階延遲（近似步態）
    use_joint_readback: bool = True  # 偵測結果附拍攝當下的舵機回讀
    config: LookAtConfig = field(default_factory=LookAtConfig)


@dataclass
class Result:
    scenario: str
    t: np.ndarray
    error_deg: np.ndarray  # 鏡頭光軸與「應該看的人」的夾角；不該看人時為 nan
    in_view: np.ndarray  # 應該看的人是否在畫面內
    states: list[str]
    head_cmd: np.ndarray  # (N, 4) neck_pitch, head_pitch, head_yaw, head_roll 指令
    head_q: np.ndarray  # (N, 4) 實際關節角
    head_qvel_max: float  # 頭頸關節最大角速度（rad/s）
    body_yaw_final: float
    switch_count: int
    pitch_saturated_any: bool
    limits_ok: bool

    def settle_time(self, threshold_deg: float = 5.0, hold_s: float = 1.0, t_from: float = 0.0) -> float | None:
        """從 t_from 起，誤差第一次進入門檻並持續 hold_s 的時間（相對 t_from）。"""
        dt = self.t[1] - self.t[0]
        need = int(round(hold_s / dt))
        ok = (self.error_deg < threshold_deg) & (self.t >= t_from)
        run = 0
        for i, v in enumerate(ok):
            run = run + 1 if v else 0
            if run >= need:
                return float(self.t[i - need + 1] - t_from)
        return None

    def error_stats(self, t0: float, t1: float) -> tuple[float, float]:
        """區間內誤差的（中位數, 最大值），度。"""
        m = (self.t >= t0) & (self.t <= t1) & ~np.isnan(self.error_deg)
        if not m.any():
            return float("nan"), float("nan")
        e = self.error_deg[m]
        return float(np.median(e)), float(np.max(e))

    def in_view_ratio(self, t0: float, t1: float) -> float:
        m = (self.t >= t0) & (self.t <= t1)
        return float(self.in_view[m].mean())


def _rotz(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


class _Duck:
    def __init__(self) -> None:
        self.m = mujoco.MjModel.from_xml_path(str(ROBOT_XML))
        # 關掉碰撞：上游網格的凸包在頸部與軀幹之間互相穿透，會把頸部推開約 0.12 rad（模擬假象）。
        # 機身固定、沒有地板，這個模擬只看頭頸的運動，不需要碰撞。
        self.m.geom_contype[:] = 0
        self.m.geom_conaffinity[:] = 0
        self.d = mujoco.MjData(self.m)
        m, d = self.m, self.d
        self.act = {m.actuator(i).name: i for i in range(m.nu)}
        for name, q in HOME_POSE.items():
            d.qpos[m.jnt_qposadr[m.joint(name).id]] = q
            d.ctrl[self.act[name]] = q
        mujoco.mj_forward(m, d)
        self.head_body = m.body("head").id
        self.qadr = [m.jnt_qposadr[m.joint(j).id] for j in HEAD_JOINTS]
        self.vadr = [m.jnt_dofadr[m.joint(j).id] for j in HEAD_JOINTS]
        # 地板＝腳底網格最低點
        floor = math.inf
        for gi in range(m.ngeom):
            body = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, m.geom_bodyid[gi]) or ""
            if "foot" in body and m.geom_type[gi] == mujoco.mjtGeom.mjGEOM_MESH:
                mid = m.geom_dataid[gi]
                v = m.mesh_vert[m.mesh_vertadr[mid] : m.mesh_vertadr[mid] + m.mesh_vertnum[mid]]
                w = v @ d.geom_xmat[gi].reshape(3, 3).T + d.geom_xpos[gi]
                floor = min(floor, float(w[:, 2].min()))
        self.floor = floor
        self.origin_xy = d.xpos[m.body("trunk_assembly").id][:2].copy()

    def camera(self) -> tuple[np.ndarray, np.ndarray]:
        """鏡頭位置與旋轉（欄：前、左、上），世界座標。"""
        R = self.d.xmat[self.head_body].reshape(3, 3)
        return self.d.xpos[self.head_body] + R @ CAMERA_MOUNT, R

    def head_q(self) -> np.ndarray:
        return np.array([self.d.qpos[a] for a in self.qadr])

    def head_qvel(self) -> np.ndarray:
        return np.array([self.d.qvel[a] for a in self.vadr])

    def set_head(self, cmd: tuple[float, float, float, float]) -> None:
        for name, v in zip(HEAD_JOINTS, cmd):
            self.d.ctrl[self.act[name]] = v


def run_scenario(sc: Scenario, opt: SimOptions | None = None) -> Result:
    opt = opt or SimOptions()
    rng = np.random.default_rng(opt.seed)
    duck = _Duck()
    intr: CameraIntrinsics = opt.config.intrinsics
    ctrl = LookAtController(opt.config)
    ctrl.activate()
    lim = opt.config.limits

    dt_phys = duck.m.opt.timestep
    ctrl_every = int(round(0.02 / dt_phys))  # 50 Hz
    frame_period = 1.0 / opt.vision_fps

    body_yaw = 0.0
    body_rate = 0.0
    body_rate_cmd = 0.0
    pending: list[tuple[float, VisionFrame]] = []  # (送達時間, 偵測結果)
    next_capture = 0.0
    speaker: SpeakerDirection | None = None
    events = sorted(sc.speaker_events)
    ev_i = 0

    def world_point(p_room: tuple[float, float, float]) -> np.ndarray:
        x, y, z = p_room
        xy = _rotz(-body_yaw)[:2, :2] @ np.array([x, y])
        return np.array([duck.origin_xy[0] + xy[0], duck.origin_xy[1] + xy[1], duck.floor + z])

    def project(p_world: np.ndarray) -> tuple[float, float, float] | None:
        c, R = duck.camera()
        pc = R.T @ (p_world - c)  # 前、左、上
        if pc[0] <= 0.05:
            return None
        u = intr.cx - intr.fx * pc[1] / pc[0]
        v = intr.cy - intr.fy * pc[2] / pc[0]
        return u, v, intr.fx * FACE_WIDTH_M / pc[0]

    def body_azimuth(p_room) -> float:
        x, y, _ = p_room
        return math.atan2(y, x) - body_yaw

    ts, errs, inview, states, cmds, qs = [], [], [], [], [], []
    qvel_max = 0.0
    pitch_sat = False
    limits_ok = True
    cmd = None
    n_steps = int(round(sc.duration / dt_phys))
    for k in range(n_steps):
        t = k * dt_phys
        if k % ctrl_every == 0:
            # 拍攝（合成偵測）
            if t + 1e-9 >= next_capture:
                next_capture += frame_period
                faces = []
                for p in sc.people:
                    if not p.present(t):
                        continue
                    pr = project(world_point(p.path(t)))
                    if pr is None:
                        continue
                    u, v, w = pr
                    if 0 <= u < intr.width and 0 <= v < intr.height and w >= MIN_FACE_PX:
                        faces.append(Face(u + rng.normal(0, opt.px_noise), v + rng.normal(0, opt.px_noise), w))
                q = duck.head_q()
                gaze = Gaze(yaw=float(q[2]), pitch=float(q[0] + q[1])) if opt.use_joint_readback else None
                pending.append((t + opt.latency_s, VisionFrame(t, tuple(faces), gaze)))
            frame = None
            while pending and pending[0][0] <= t + 1e-9:
                frame = pending.pop(0)[1]  # 只用最新一張
            # 說話者方向
            while ev_i < len(events) and events[ev_i][0] <= t:
                who = next(p for p in sc.people if p.name == events[ev_i][1])
                az = body_azimuth(who.path(t)) + math.radians(rng.normal(0, opt.speaker_noise_deg))
                speaker = SpeakerDirection(t, az)
                ev_i += 1
            cmd = ctrl.step(t, frame, speaker, measured_body_yaw_rate=body_rate)
            duck.set_head((cmd.neck_pitch, cmd.head_pitch, cmd.head_yaw, cmd.head_roll))
            body_rate_cmd = cmd.body_yaw_rate
            pitch_sat = pitch_sat or cmd.pitch_saturated
            if not (
                lim.neck_pitch[0] - 1e-9 <= cmd.neck_pitch <= lim.neck_pitch[1] + 1e-9
                and lim.head_pitch[0] - 1e-9 <= cmd.head_pitch <= lim.head_pitch[1] + 1e-9
                and lim.head_yaw[0] - 1e-9 <= cmd.head_yaw <= lim.head_yaw[1] + 1e-9
            ):
                limits_ok = False

            # 紀錄
            who = sc.expected(t)
            err = math.nan
            vis = False
            if who is not None:
                person = next(p for p in sc.people if p.name == who)
                pw = world_point(person.path(t))
                c, R = duck.camera()
                d = pw - c
                err = math.degrees(math.acos(float(np.clip(R[:, 0] @ d / np.linalg.norm(d), -1, 1))))
                pr = project(pw)
                vis = pr is not None and 0 <= pr[0] < intr.width and 0 <= pr[1] < intr.height
            ts.append(t)
            errs.append(err)
            inview.append(vis)
            states.append(cmd.state.value)
            cmds.append((cmd.neck_pitch, cmd.head_pitch, cmd.head_yaw, cmd.head_roll))
            qs.append(duck.head_q())

        # 轉身（運動學近似）
        body_rate += (body_rate_cmd - body_rate) * (1 - math.exp(-dt_phys / opt.body_turn_tau_s))
        body_yaw += body_rate * dt_phys
        mujoco.mj_step(duck.m, duck.d)
        qvel_max = max(qvel_max, float(np.abs(duck.head_qvel()).max()))

    return Result(
        scenario=sc.name,
        t=np.array(ts),
        error_deg=np.array(errs),
        in_view=np.array(inview),
        states=states,
        head_cmd=np.array(cmds),
        head_q=np.array(qs),
        head_qvel_max=qvel_max,
        body_yaw_final=body_yaw,
        switch_count=ctrl.switch_count,
        pitch_saturated_any=pitch_sat,
        limits_ok=limits_ok,
    )


# ---------------------------------------------------------------- 情境


def _still(x: float, y: float, z: float):
    return lambda t: (x, y, z)


def _walk_across(t: float) -> tuple[float, float, float]:
    # 2 m 前方，從左 1.5 m 走到右 1.5 m，0.4 m/s，第 1 秒開始走
    y = 1.5 - 0.4 * min(max(t - 1.0, 0.0), 7.5)
    return (2.0, y, 1.6)


SCENARIOS: dict[str, Scenario] = {
    s.name: s
    for s in [
        Scenario(
            "adult_1p5m",
            "大人站在前方 1.5 m、偏左 0.3 m（臉 1.6 m）",
            6.0,
            [Person("adult", _still(1.5, 0.3, 1.6))],
            expected=lambda t: "adult",
        ),
        Scenario(
            "child_1m",
            "小孩站在前方 1.0 m、偏右 0.2 m（臉 1.0 m）",
            6.0,
            [Person("child", _still(1.0, -0.2, 1.0))],
            expected=lambda t: "child",
        ),
        Scenario(
            "adult_too_close_0p7m",
            "大人站在前方 0.7 m（臉 1.6 m）：需要的仰角超出頭部範圍",
            6.0,
            [Person("adult", _still(0.7, 0.0, 1.6))],
            expected=lambda t: "adult",
        ),
        Scenario(
            "walk_across_2m",
            "大人在前方 2 m 由左往右走過（0.4 m/s，左 1.5 m → 右 1.5 m）",
            11.0,
            [Person("adult", _walk_across)],
            expected=lambda t: "adult",
        ),
        Scenario(
            "called_from_side",
            "坐著的大人在左側 90°、1.5 m（臉 1.2 m），一開始不在畫面內；0.5 s 時開口（只有說話者方向）",
            10.0,
            [Person("adult", _still(0.0, 1.5, 1.2))],
            expected=lambda t: "adult",
            speaker_events=[(0.5, "adult"), (1.5, "adult")],
        ),
        Scenario(
            "two_people_switch",
            "A（右 0.6 m、臉 1.6 m）與 B（左 0.7 m、臉 1.2 m）都在 2 m 前方；A 先說話，5 s 起換 B 說話",
            12.0,
            [Person("A", _still(2.0, -0.6, 1.6)), Person("B", _still(2.0, 0.7, 1.2))],
            expected=lambda t: "A" if t < 5.0 else "B",
            speaker_events=[(0.5 + 0.5 * i, "A") for i in range(9)] + [(5.0 + 0.5 * i, "B") for i in range(12)],
        ),
        Scenario(
            "leaves_view",
            "大人在前方 1.5 m，3 s 時離開（不再出現）",
            14.0,
            [Person("adult", _still(1.5, 0.0, 1.6), present=lambda t: t < 3.0)],
            expected=lambda t: "adult" if t < 3.0 else None,
        ),
    ]
}
