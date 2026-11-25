"""全身走路模擬器：上游步態策略（ONNX）＋ MuJoCo，50 Hz 控制，無頭執行。

觀測向量（101 維）與動作的組法對照下列檔案（唯讀查閱，自己重寫）：

- runtime `apirrone/Open_Duck_Mini_Runtime` v2 `376de65`：`scripts/v2_rl_walk_mujoco.py`
  的 `RLWalk.get_obs()` 與 `run()`。
- `apirrone/Open_Duck_Playground` main `b9be205`：`playground/open_duck_mini_v2/mujoco_infer.py`
  的 `MjInfer.get_obs()` 與 `run()`、`joystick.py` 的 `_get_obs()`。

| 索引 | 維度 | 內容 |
|---|---|---|
| 0–2 | 3 | 陀螺儀（IMU 座標，rad/s） |
| 3–5 | 3 | 加速度計（m/s²），x 加 1.3（Playground 訓練與推論都加；runtime 則在 IMU 端扣掉校正偏移） |
| 6–12 | 7 | 指令：vx、vy、yaw_rate、neck_pitch、head_pitch、head_yaw、head_roll |
| 13–26 | 14 | 關節角 − 起始姿勢 |
| 27–40 | 14 | 關節角速度 × 0.05 |
| 41–82 | 42 | 前三次的策略輸出（最近的在前） |
| 83–96 | 14 | 上一圈送出的馬達目標 |
| 97–98 | 2 | 左、右足底接觸（0／1） |
| 99–100 | 2 | 步態相位 (cos, sin)，一個週期 27 個控制步（0.54 s × 50 Hz，來自 `polynomial_coefficients.pkl`） |

動作：`馬達目標 = 起始姿勢 + 0.25 × 策略輸出`，再限制每圈變化不超過 5.24 rad/s × 0.02 s
（Playground 推論有開這個限制；runtime 把它註解掉了，這裡用 `motor_speed_limit` 選）。

頭部指令有兩種接法，用 `head_mode` 選：

- `"runtime"`（預設）：照 runtime，把指令的頭部角度**加在**策略輸出的頭部目標上。
- `"policy"`：照 Playground 推論，頭部指令只放進觀測，由策略自己輸出頭部目標。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import mujoco
import numpy as np
import onnxruntime

from .model import (
    CONTROL_DT,
    DECIMATION,
    HEAD_SLICE,
    HOME_BASE_Z,
    HOME_POSE,
    POLICY_JOINTS,
    POLICY_ONNX,
    ModelOptions,
    build_model,
)

OBS_DIM = 101
ACTION_SCALE = 0.25
DOF_VEL_SCALE = 0.05
ACCEL_X_OFFSET = 1.3
MAX_MOTOR_VELOCITY = 5.24  # rad/s
PHASE_PERIOD_STEPS = 27  # int(0.54 s × 50 fps)

#: 上游手把映射範圍（runtime `xbox_controller.py`、Playground `joystick.py` 的訓練範圍）。
CMD_RANGE = {
    "vx": (-0.15, 0.15),
    "vy": (-0.2, 0.2),
    "yaw_rate": (-1.0, 1.0),
    "neck_pitch": (-0.34, 1.1),
    "head_pitch": (-0.78, 0.78),
    "head_yaw": (-1.5, 1.5),
    "head_roll": (-0.5, 0.5),
}


@dataclass
class SimOptions:
    seed: int = 0
    head_mode: str = "runtime"  # "runtime" | "policy"
    motor_speed_limit: bool = True
    #: 相位頻率倍率。runtime 預設 1.0（按住 LB 是 1.3，另有 `get_phase_frequency_factor` 但主迴圈沒用）。
    phase_frequency_factor: float = 1.0
    #: 起始時的隨機擾動：機身水平速度（m/s）與偏航（rad）的均勻範圍；用來做多種子的跌倒率。
    init_vel_noise: float = 0.0
    init_yaw_noise: float = 0.0
    #: 觀測雜訊（均勻分佈的半寬）；預設 0。Playground 訓練時 gyro 0.1、accel 0.05 等。
    gyro_noise: float = 0.0
    accel_noise: float = 0.0
    #: 起始位姿（世界座標 x、y、偏航）。
    start_xy_yaw: tuple[float, float, float] = (0.0, 0.0, 0.0)
    #: 跌倒判定：機身 z 軸與鉛直的夾角超過這個角度，或機身高度低於門檻。
    fall_tilt_deg: float = 45.0
    fall_height_m: float = 0.08
    model: ModelOptions = field(default_factory=ModelOptions)


@dataclass
class StepInfo:
    t: float
    x: float
    y: float
    z: float
    yaw: float
    roll: float
    pitch: float
    tilt_deg: float
    vx_body: float
    vy_body: float
    yaw_rate: float
    contact_left: bool
    contact_right: bool
    fallen: bool


def clamp_command(cmd) -> np.ndarray:
    c = np.zeros(7)
    c[: len(cmd)] = cmd
    for i, k in enumerate(CMD_RANGE):
        lo, hi = CMD_RANGE[k]
        c[i] = min(max(c[i], lo), hi)
    return c


class WalkSim:
    """上游步態策略在 MuJoCo 裡走路。一次 `step(cmd)` 是一個 50 Hz 控制週期。"""

    def __init__(self, options: SimOptions | None = None, model: mujoco.MjModel | None = None):
        self.opt = options or SimOptions()
        self.m = model if model is not None else build_model(self.opt.model)
        self.d = mujoco.MjData(self.m)
        m = self.m
        self._qadr = np.array([m.jnt_qposadr[m.joint(n).id] for n in POLICY_JOINTS])
        self._vadr = np.array([m.jnt_dofadr[m.joint(n).id] for n in POLICY_JOINTS])
        self._act = np.array([m.actuator(n).id for n in POLICY_JOINTS])
        self._default = np.array([HOME_POSE[n] for n in POLICY_JOINTS])
        self._gyro_adr = m.sensor_adr[m.sensor("gyro").id]
        self._acc_adr = m.sensor_adr[m.sensor("accelerometer").id]
        self._floor = m.geom("floor").id
        self._lfoot = m.geom("left_foot_bottom_tpu").id
        self._rfoot = m.geom("right_foot_bottom_tpu").id
        self._base = m.body("base").id
        self._free_q = m.jnt_qposadr[m.joint("floating_base").id]
        self._free_v = m.jnt_dofadr[m.joint("floating_base").id]
        self.session = onnxruntime.InferenceSession(str(POLICY_ONNX), providers=["CPUExecutionProvider"])
        shape = self.session.get_inputs()[0].shape
        if shape[-1] != OBS_DIM:
            raise RuntimeError(f"策略輸入維度是 {shape}，預期 {OBS_DIM}")
        self._in = self.session.get_inputs()[0].name
        self.reset()

    # ------------------------------------------------------------------ 狀態
    def reset(self, seed: int | None = None) -> StepInfo:
        if seed is not None:
            self.opt.seed = seed
        self.rng = np.random.default_rng(self.opt.seed)
        m, d = self.m, self.d
        mujoco.mj_resetData(m, d)
        x, y, yaw = self.opt.start_xy_yaw
        yaw += self.rng.uniform(-1, 1) * self.opt.init_yaw_noise
        d.qpos[self._free_q : self._free_q + 3] = [x, y, HOME_BASE_Z]
        d.qpos[self._free_q + 3 : self._free_q + 7] = [math.cos(yaw / 2), 0, 0, math.sin(yaw / 2)]
        d.qpos[self._qadr] = self._default
        if self.opt.init_vel_noise > 0:
            d.qvel[self._free_v : self._free_v + 2] = self.rng.uniform(-1, 1, 2) * self.opt.init_vel_noise
        d.ctrl[:] = 0.0
        d.ctrl[self._act] = self._default
        mujoco.mj_forward(m, d)
        self.last_action = np.zeros(14)
        self.last_last_action = np.zeros(14)
        self.last_last_last_action = np.zeros(14)
        self.motor_targets = self._default.copy()
        self.prev_motor_targets = self._default.copy()
        self.imitation_i = 0.0
        self.phase = np.array([0.0, 0.0])
        self.steps = 0
        self.last_obs = np.zeros(OBS_DIM)
        return self.info()

    @property
    def t(self) -> float:
        return self.steps * CONTROL_DT

    def feet_contacts(self) -> tuple[bool, bool]:
        left = right = False
        d = self.d
        for i in range(d.ncon):
            c = d.contact[i]
            pair = {int(c.geom1), int(c.geom2)}
            if self._floor in pair:
                if self._lfoot in pair:
                    left = True
                if self._rfoot in pair:
                    right = True
        return left, right

    def base_pose(self) -> tuple[float, float, float]:
        """（x, y, yaw）：base 的世界座標與機身 x 軸在地面上的方向。"""
        d = self.d
        R = d.xmat[self._base].reshape(3, 3)
        return float(d.xpos[self._base][0]), float(d.xpos[self._base][1]), math.atan2(R[1, 0], R[0, 0])

    def info(self) -> StepInfo:
        d = self.d
        R = d.xmat[self._base].reshape(3, 3)
        x, y, z = (float(v) for v in d.xpos[self._base])
        yaw = math.atan2(R[1, 0], R[0, 0])
        pitch = math.asin(max(-1.0, min(1.0, -R[2, 0])))
        roll = math.atan2(R[2, 1], R[2, 2])
        tilt = math.degrees(math.acos(max(-1.0, min(1.0, R[2, 2]))))
        vw = d.qvel[self._free_v : self._free_v + 3]
        c, s = math.cos(yaw), math.sin(yaw)
        vxb = c * vw[0] + s * vw[1]
        vyb = -s * vw[0] + c * vw[1]
        # freejoint 的角速度在機身座標；用世界 z 分量當偏航角速度。
        wz = float((R @ d.qvel[self._free_v + 3 : self._free_v + 6])[2])
        cl, cr = self.feet_contacts()
        fallen = tilt > self.opt.fall_tilt_deg or z < self.opt.fall_height_m
        return StepInfo(self.t, x, y, z, yaw, roll, pitch, tilt, float(vxb), float(vyb), wz, cl, cr, fallen)

    def joint_positions(self) -> np.ndarray:
        return self.d.qpos[self._qadr].copy()

    def imu(self) -> tuple[np.ndarray, np.ndarray]:
        """（陀螺儀, 加速度計）原始感測值，未加偏移。"""
        s = self.d.sensordata
        return s[self._gyro_adr : self._gyro_adr + 3].copy(), s[self._acc_adr : self._acc_adr + 3].copy()

    # ------------------------------------------------------------------ 控制
    def observation(self, cmd: np.ndarray) -> np.ndarray:
        gyro, acc = self.imu()
        acc[0] += ACCEL_X_OFFSET
        if self.opt.gyro_noise:
            gyro += self.rng.uniform(-1, 1, 3) * self.opt.gyro_noise
        if self.opt.accel_noise:
            acc += self.rng.uniform(-1, 1, 3) * self.opt.accel_noise
        q = self.d.qpos[self._qadr]
        qd = self.d.qvel[self._vadr]
        contacts = np.array(self.feet_contacts(), dtype=np.float64)
        return np.concatenate(
            [
                gyro,
                acc,
                cmd,
                q - self._default,
                qd * DOF_VEL_SCALE,
                self.last_action,
                self.last_last_action,
                self.last_last_last_action,
                self.motor_targets,
                contacts,
                self.phase,
            ]
        )

    def step(self, cmd=(0, 0, 0, 0, 0, 0, 0)) -> StepInfo:
        """跑一個控制週期：組觀測 → 策略 → 馬達目標 → 10 個物理步。"""
        cmd = clamp_command(cmd)
        # 相位（runtime 與 Playground 推論都是先進相位再推論）。
        self.imitation_i = (self.imitation_i + self.opt.phase_frequency_factor) % PHASE_PERIOD_STEPS
        a = self.imitation_i / PHASE_PERIOD_STEPS * 2 * math.pi
        self.phase = np.array([math.cos(a), math.sin(a)])

        obs = self.observation(cmd).astype(np.float32)
        self.last_obs = obs
        action = self.session.run(None, {self._in: obs[None, :]})[0][0].astype(np.float64)
        self.last_last_last_action = self.last_last_action
        self.last_last_action = self.last_action
        self.last_action = action.copy()

        targets = self._default + ACTION_SCALE * action
        if self.opt.motor_speed_limit:
            lim = MAX_MOTOR_VELOCITY * CONTROL_DT
            targets = np.clip(targets, self.prev_motor_targets - lim, self.prev_motor_targets + lim)
        self.prev_motor_targets = targets.copy()
        self.motor_targets = targets.copy()
        if self.opt.head_mode == "runtime":
            # runtime：head_motor_targets = last_commands[3:] + motor_targets[5:9]，
            # 而且加完的值會留在 motor_targets 裡，下一圈進觀測。
            self.motor_targets[HEAD_SLICE] = cmd[3:] + self.motor_targets[HEAD_SLICE]
        elif self.opt.head_mode != "policy":
            raise ValueError(f"unknown head_mode {self.opt.head_mode!r}")

        self.d.ctrl[self._act] = self.motor_targets
        for _ in range(DECIMATION):
            mujoco.mj_step(self.m, self.d)
        self.steps += 1
        return self.info()

    def hold(self, n_steps: int = 1) -> StepInfo:
        """不跑策略，維持上一筆馬達目標（對應 runtime 的 `paused`）。"""
        for _ in range(n_steps):
            for _ in range(DECIMATION):
                mujoco.mj_step(self.m, self.d)
            self.steps += 1
        return self.info()

    def teleport(self, x: float, y: float, yaw: float) -> None:
        """把鴨子搬到別處（綁架測試用）。保留關節狀態，速度歸零。"""
        d = self.d
        d.qpos[self._free_q : self._free_q + 2] = [x, y]
        d.qpos[self._free_q + 3 : self._free_q + 7] = [math.cos(yaw / 2), 0, 0, math.sin(yaw / 2)]
        d.qpos[self._free_q + 2] = HOME_BASE_Z
        d.qvel[self._free_v : self._free_v + 6] = 0
        mujoco.mj_forward(self.m, d)
