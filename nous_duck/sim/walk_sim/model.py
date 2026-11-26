"""由上游 `robot.xml`（唯讀）組出可以走路的 MuJoCo 模型。

本 repo 的 `mini_bdx/robots/open_duck_mini_v2/robot.xml` 是固定機身、沒有 IMU 感測器、
舵機參數也跟訓練步態策略時用的不同。這裡**不改原檔**，用 `mujoco.MjSpec` 在記憶體裡補上：

| 補上的東西 | 數值 | 來源（唯讀查閱，只取數值，不複製檔案） |
|---|---|---|
| 浮動機身（freejoint） | — | Open_Duck_Playground `b9be205` `xmls/open_duck_mini_v2.xml` |
| IMU site | base 座標 (−0.08, 0, 0.05) | 同上 |
| 陀螺儀、加速度計感測器 | 掛在 IMU site | 同上（`<sensor>` 區塊） |
| 舵機：kp、力矩上限 | 13.37、±3.23 N·m | 同上（`sts3215` 類別） |
| 關節：阻尼、摩擦、轉子慣量 | 0.56、0.068、0.027 | 同上 |
| 碰撞：只有兩片鞋底（`foot_bottom_tpu` 網格） | — | 同上（只有鞋底是 collision 類別） |
| 地板摩擦 | 0.6，`priority=1`、`condim=3` | 同上 `xmls/scene_flat_terrain.xml` |
| 起始姿勢 | `HOME_POSE`，機身高 0.15 m | 同上 `home` keyframe；與 runtime `376de65` 的 `init_pos` 相同 |
| 時間步 | 0.002 s，每 10 步控制一次（50 Hz） | Playground `mujoco_infer_base.py` |

已知跟訓練用模型不同的地方（都寫進驗證紀錄）：

- 沒有背隙關節（訓練用 `open_duck_mini_v2_backlash.xml`，每個關節多一個 ±0.5° 的被動關節）。
- 本 repo 的模型多了兩個天線關節（各有質量），總質量 2.062 kg；Playground 的模型是 2.107 kg。
- 求解器用 MuJoCo 預設；Playground 的 XML 設 `iterations=1 ls_iterations=5`、關掉 `eulerdamp`
  （給 MJX 訓練加速用）。`solver="playground"` 可以改成那組設定做對照。
- 為了讓導航場景的牆擋得住鴨子，另外加了機身與頭的簡化碰撞外殼（只跟牆與地板碰撞），
  訓練時沒有。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import mujoco
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
ROBOT_XML = REPO_ROOT / "mini_bdx/robots/open_duck_mini_v2/robot.xml"
POLICY_ONNX = REPO_ROOT / "BEST_WALK_ONNX_2.onnx"

#: 策略輸出與觀測的關節順序（runtime `376de65` `rustypot_position_hwi.py` 的 `joints`；
#: 與 Playground 模型的 actuator 順序相同）。
POLICY_JOINTS = (
    "left_hip_yaw",
    "left_hip_roll",
    "left_hip_pitch",
    "left_knee",
    "left_ankle",
    "neck_pitch",
    "head_pitch",
    "head_yaw",
    "head_roll",
    "right_hip_yaw",
    "right_hip_roll",
    "right_hip_pitch",
    "right_knee",
    "right_ankle",
)
HEAD_SLICE = slice(5, 9)

#: 起始姿勢（rad）。runtime `init_pos` 與 Playground `home` keyframe 數值相同。
HOME_POSE = {
    "left_hip_yaw": 0.002,
    "left_hip_roll": 0.053,
    "left_hip_pitch": -0.63,
    "left_knee": 1.368,
    "left_ankle": -0.784,
    "neck_pitch": 0.0,
    "head_pitch": 0.0,
    "head_yaw": 0.0,
    "head_roll": 0.0,
    "right_hip_yaw": -0.003,
    "right_hip_roll": -0.065,
    "right_hip_pitch": 0.635,
    "right_knee": 1.379,
    "right_ankle": -0.796,
}
HOME_BASE_Z = 0.15

SIM_DT = 0.002
DECIMATION = 10
CONTROL_DT = SIM_DT * DECIMATION  # 0.02 s = 50 Hz

IMU_SITE_POS = (-0.08, 0.0, 0.05)

# 碰撞位元：1 = 地板，2 = 牆與障礙物。
_BIT_FLOOR = 1
_BIT_WALL = 2


@dataclass
class ModelOptions:
    #: 舵機位置增益（N·m/rad）。
    kp: float = 13.37
    force_limit: float = 3.23
    joint_damping: float = 0.56
    joint_frictionloss: float = 0.068
    joint_armature: float = 0.027
    floor_friction: float = 0.6
    #: "default"＝MuJoCo 預設求解器；"playground"＝Playground XML 的設定。
    solver: str = "default"
    #: 加在機身（trunk_assembly）質心附近的額外質量（kg）與位置（base 座標，m），
    #: 用來試「Pi 4、鏡頭、觸點板裝上去之後」的影響。預設不加。
    extra_mass_kg: float = 0.0
    extra_mass_pos: tuple[float, float, float] = (-0.05, 0.0, 0.04)
    #: 加裝件（`walk_sim.mass.MassItem`）：合進對應 body 的慣量，可加可減。見 `mass.py`。
    mass_items: tuple = ()
    #: 是否加機身與頭的簡化碰撞外殼（給有牆的場景）。
    body_hull: bool = True
    #: 加場景內容（牆、標籤、相機）的掛勾：收到 `MjSpec`，在編譯前修改。
    extend: Callable[[mujoco.MjSpec], None] | None = None
    #: 離螢幕算圖的畫布大小上限。
    offscreen: tuple[int, int] = (1280, 720)
    extras: dict = field(default_factory=dict)


def build_spec(options: ModelOptions | None = None) -> mujoco.MjSpec:
    """讀上游 `robot.xml`，回傳補好浮動機身、感測器、地板的 `MjSpec`（尚未編譯）。"""
    o = options or ModelOptions()
    spec = mujoco.MjSpec.from_file(str(ROBOT_XML))
    spec.option.timestep = SIM_DT
    if o.solver == "playground":
        spec.option.iterations = 1
        spec.option.ls_iterations = 5
        spec.option.disableflags |= int(mujoco.mjtDisableBit.mjDSBL_EULERDAMP)
    elif o.solver != "default":
        raise ValueError(f"unknown solver {o.solver!r}")

    base = spec.body("base")
    base.pos = [0.0, 0.0, HOME_BASE_Z]
    base.add_freejoint(name="floating_base")
    base.add_site(name="imu", pos=list(IMU_SITE_POS))

    # 關節與舵機參數。
    for j in spec.joints:
        if j.name == "floating_base":
            continue
        j.damping = [o.joint_damping, 0.0, 0.0]  # MuJoCo 4：阻尼是多項式係數，第一項是線性阻尼
        j.frictionloss = o.joint_frictionloss
        j.armature = o.joint_armature
    for a in spec.actuators:
        a.gainprm[0] = o.kp
        a.biasprm[1] = -o.kp
        a.forcerange = [-o.force_limit, o.force_limit]

    # 碰撞：全部關掉，只留兩片鞋底。
    foot_bodies = {"foot_assembly": "left", "foot_assembly_2": "right"}
    for b in spec.bodies:
        for g in b.geoms:
            g.contype = 0
            g.conaffinity = 0
            if b.name in foot_bodies and g.meshname == "foot_bottom_tpu":
                g.name = f"{foot_bodies[b.name]}_foot_bottom_tpu"
                g.contype = _BIT_FLOOR
                g.conaffinity = _BIT_FLOOR | _BIT_WALL
    # 上游的 exclude 是給全網格碰撞用的，留著無妨。

    if o.body_hull:
        # 簡化外殼：不跟自己或鞋底碰撞（contype=0），只被地板（位元 1）與牆（位元 2）碰到。
        trunk = spec.body("trunk_assembly")
        trunk.add_geom(
            name="hull_trunk",
            type=mujoco.mjtGeom.mjGEOM_BOX,
            # 後緣在 base x = −0.162：背後觸點凸台的外表面（hardware/dock 的外掛觸點板）。
            pos=[-0.0685, 0.0, 0.06],
            size=[0.0935, 0.065, 0.055],
            contype=0,
            conaffinity=_BIT_FLOOR | _BIT_WALL,
            rgba=[0.2, 0.6, 1.0, 0.0],
            mass=0.0,
            group=3,
        )
        head = spec.body("head_assembly")
        head.add_geom(
            name="hull_head",
            type=mujoco.mjtGeom.mjGEOM_SPHERE,
            pos=[0.03, 0.0, 0.03],
            size=[0.07, 0, 0],
            contype=0,
            conaffinity=_BIT_FLOOR | _BIT_WALL,
            rgba=[0.2, 0.6, 1.0, 0.0],
            mass=0.0,
            group=3,
        )

    if o.extra_mass_kg > 0:
        base.add_geom(
            name="extra_mass",
            type=mujoco.mjtGeom.mjGEOM_SPHERE,
            pos=list(o.extra_mass_pos),
            size=[0.015, 0, 0],
            contype=0,
            conaffinity=0,
            mass=o.extra_mass_kg,
            rgba=[1, 0, 0, 0.6],
        )

    if o.mass_items:
        from .mass import apply_mass_items  # 延遲匯入：mass.py 也匯入本模組

        o.extras["mass_log"] = apply_mass_items(spec, o.mass_items)

    # 感測器。
    spec.add_sensor(
        name="gyro",
        type=mujoco.mjtSensor.mjSENS_GYRO,
        objtype=mujoco.mjtObj.mjOBJ_SITE,
        objname="imu",
    )
    spec.add_sensor(
        name="accelerometer",
        type=mujoco.mjtSensor.mjSENS_ACCELEROMETER,
        objtype=mujoco.mjtObj.mjOBJ_SITE,
        objname="imu",
    )

    # 地板與光。
    world = spec.worldbody
    spec.add_texture(
        name="groundplane",
        type=mujoco.mjtTexture.mjTEXTURE_2D,
        builtin=mujoco.mjtBuiltin.mjBUILTIN_CHECKER,
        rgb1=[0.86, 0.84, 0.80],
        rgb2=[0.78, 0.76, 0.72],
        width=256,
        height=256,
    )
    mat = spec.add_material(name="groundplane", texrepeat=[2, 2], texuniform=True)
    mat.textures[mujoco.mjtTextureRole.mjTEXROLE_RGB] = "groundplane"
    world.add_geom(
        name="floor",
        type=mujoco.mjtGeom.mjGEOM_PLANE,
        size=[0, 0, 0.01],
        material="groundplane",
        contype=_BIT_FLOOR,
        conaffinity=0,
        priority=1,
        friction=[o.floor_friction, 0.005, 0.0001],
        condim=3,
    )
    world.add_light(pos=[0, 0, 3.0], dir=[0, 0, -1], type=mujoco.mjtLightType.mjLIGHT_DIRECTIONAL)
    spec.visual.global_.offwidth = o.offscreen[0]
    spec.visual.global_.offheight = o.offscreen[1]
    spec.visual.headlight.ambient = [0.45, 0.45, 0.45]
    spec.visual.headlight.diffuse = [0.5, 0.5, 0.5]

    if o.extend is not None:
        o.extend(spec)
    return spec


def add_wall_box(
    spec: mujoco.MjSpec,
    name: str,
    center: tuple[float, float, float],
    half: tuple[float, float, float],
    rgba: tuple[float, float, float, float] = (0.92, 0.9, 0.86, 1.0),
    yaw: float = 0.0,
) -> None:
    """加一個固定的長方體障礙（牆、門板、家具）。鴨子的鞋底與外殼會被它擋住。"""
    spec.worldbody.add_geom(
        name=name,
        type=mujoco.mjtGeom.mjGEOM_BOX,
        pos=list(center),
        size=list(half),
        quat=[float(np.cos(yaw / 2)), 0.0, 0.0, float(np.sin(yaw / 2))],
        contype=_BIT_WALL,
        conaffinity=0,
        rgba=list(rgba),
    )


def build_model(options: ModelOptions | None = None) -> mujoco.MjModel:
    return build_spec(options).compile()
