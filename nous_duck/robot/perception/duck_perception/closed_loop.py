"""D2 閉迴路測試台（**模擬**）：合成畫面 → 偵測 → `look_at` 控制器 → 一階延遲的頭 → 新的合成畫面。

用途：確認「偵測結果的座標、正負號、延遲」和既有的 `LookAtController` 接得起來，頭會收斂到人臉。

模擬的部分（都不是實機）：

- 頭：視線以一階延遲＋角速度上限跟隨指令（不是舵機模型，沒有重力下垂與背隙）。
- 鏡頭：10 Hz、固定處理延遲；鏡頭繞光學中心轉。
- 身體不動（這裡不測轉身；轉身與走近見 `follow.py`）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import _robot_path  # noqa: F401
from behaviors.look_at import CameraIntrinsics, Face, Gaze, LookAtConfig, LookAtController, VisionFrame  # noqa: E402

from .camera import CameraModel
from .pipeline import FacePipeline
from .synthetic import SyntheticStereoSource, body_dir, body_to_cam


def intrinsics_for(cam: CameraModel) -> CameraIntrinsics:
    """本模組的鏡頭模型 → look_at 的內參型別（同一組數字）。"""
    return CameraIntrinsics(fx=cam.fx, fy=cam.fy, cx=cam.cx, cy=cam.cy, width=cam.width, height=cam.height)


@dataclass
class LoopLog:
    t: list[float] = field(default_factory=list)
    #: 視線與目標（people[target_index]）真實方向的夾角分量（弧度）。
    yaw_err: list[float] = field(default_factory=list)
    pitch_err: list[float] = field(default_factory=list)
    state: list[str] = field(default_factory=list)
    frames: int = 0
    frames_with_target: int = 0

    def settle_time(self, tol_rad: float) -> float | None:
        """誤差最後一次超出 tol 之後的時間（之後一直在 tol 內）；從未收斂回傳 None。"""
        last_bad = None
        for t, ey, ep in zip(self.t, self.yaw_err, self.pitch_err):
            if math.hypot(ey, ep) > tol_rad:
                last_bad = t
        if last_bad is None:
            return self.t[0] if self.t else None
        return None if last_bad >= self.t[-1] - 1e-9 else last_bad

    def final_error(self) -> float:
        return math.hypot(self.yaw_err[-1], self.pitch_err[-1])


def simulate_head_tracking(
    source: SyntheticStereoSource,
    pipeline: FacePipeline,
    controller: LookAtController | None = None,
    duration_s: float = 4.0,
    dt: float = 0.02,
    frame_every: int = 5,
    latency_cycles: int = 4,
    head_tau_s: float = 0.08,
    head_max_rate: float = 4.0,
    target_index: int = 0,
    on_step=None,
) -> LoopLog:
    if controller is None:
        cfg = LookAtConfig(intrinsics=intrinsics_for(source.model), allow_body_turn=False)
        controller = LookAtController(cfg)
    controller.activate()
    gaze = Gaze(0.0, 0.0)  # 模擬的實際視線
    pending: list[tuple[int, VisionFrame]] = []
    log = LoopLog()
    n = int(round(duration_s / dt))
    for i in range(n):
        t = i * dt
        if on_step is not None:
            on_step(t, source)
        vf = None
        if i % frame_every == 0:
            source.set_pose(t, gaze.yaw, gaze.pitch)
            frame = source.read()
            res = pipeline.process(frame)
            log.frames += 1
            log.frames_with_target += res.target is not None
            faces = tuple(Face(u=d.u, v=d.v, width=d.width_px, score=d.score) for d in res.detections)
            pending.append((i + latency_cycles, VisionFrame(t, faces, gaze_at_capture=gaze)))
        while pending and pending[0][0] <= i:
            vf = pending.pop(0)[1]
        cmd = controller.step(t, vf)
        want = Gaze(cmd.head_yaw, cmd.neck_pitch + cmd.head_pitch)
        a = 1.0 - math.exp(-dt / head_tau_s)
        lim = head_max_rate * dt
        gaze = Gaze(
            gaze.yaw + max(-lim, min(lim, (want.yaw - gaze.yaw) * a)),
            gaze.pitch + max(-lim, min(lim, (want.pitch - gaze.pitch) * a)),
        )
        p = source.people[target_index]
        pc = body_to_cam(body_dir(p.yaw, p.pitch), gaze.yaw, gaze.pitch)
        log.t.append(t)
        log.yaw_err.append(math.atan2(-pc[0], pc[2]))
        log.pitch_err.append(math.atan2(-pc[1], pc[2]))
        log.state.append(cmd.state.value)
    return log
