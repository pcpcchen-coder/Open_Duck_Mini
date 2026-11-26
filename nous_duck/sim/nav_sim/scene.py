"""把地圖檔的 `structures` 蓋成 MuJoCo 場景（牆、家具、充電座），並提供身體轉接器。

- 牆與家具：地圖 `structures` 的長方體，鴨子的鞋底與簡化外殼會被擋住。
- 充電座：椅背與扶手照地圖；另外在機身高度加一塊「停止面」（V 形導引座的底面，
  `hardware/dock/cad/dock_cad/params.py` 的 `CRADLE_BASE_X = −1 mm`）。**V 形牆的導引沒有模擬**。
- AprilTag：貼在牆上的薄板，貼圖用 OpenCV 的 tag36h11 字典產生（`with_tag_textures=True` 時），
  給「相機算圖＋真的偵測器」的檢查用；平常的定位用幾何合成的觀測（mock）。
"""

from __future__ import annotations

import math
from collections import deque

import mujoco
import numpy as np

from duck_nav.gait import CONTROL_DT, ramp
from duck_nav.geometry import Pose2D
from duck_nav.mapfile import DuckMap
from duck_nav.navigator import BASE_TO_CONTACT_M
from duck_nav.types import NavOutput
from walk_sim.model import ModelOptions, add_wall_box
from walk_sim.sim import SimOptions, WalkSim

KIND_RGBA = {
    "wall": (0.93, 0.91, 0.87, 1.0),
    "furniture": (0.62, 0.48, 0.36, 1.0),
    "dock": (0.95, 0.75, 0.25, 1.0),
    "extra": (0.85, 0.35, 0.30, 1.0),
}


def mount_head_camera(sim: WalkSim) -> None:
    """把 `head_cam` 固定在頭上：站姿、頭回正時，鏡頭在機身前方 `CAM_FORWARD_M`、離地 `CAM_HEIGHT_M`、朝正前方。

    這兩個數字是 mock 感測器用的名目值（`duck_nav.mock_sensors`；頭殼還沒重新設計，鏡頭位置是假設）。
    相機座標：x 右、y 上、看 −z。之後頭轉動時相機跟著 head_assembly 動。
    """
    from duck_nav.mock_sensors import CAM_FORWARD_M, CAM_HEIGHT_M

    m, d = sim.m, sim.d
    cam = m.camera("head_cam").id
    head = m.body("head_assembly").id
    x, y, yaw = sim.base_pose()
    c, s_ = math.cos(yaw), math.sin(yaw)
    p_w = np.array([x + CAM_FORWARD_M * c, y + CAM_FORWARD_M * s_, CAM_HEIGHT_M])
    # 策略在站姿時會讓 head_yaw 停在一個小角度（不是 0）；相機要對齊「head_yaw = 0 時的正前方」。
    yaw += float(sim.joint_positions()[7])
    c, s_ = math.cos(yaw), math.sin(yaw)
    R_w = np.array([[s_, 0, -c], [-c, 0, -s_], [0, 1, 0]])  # 欄：相機 x（右）、y（上）、z（後）在世界座標
    Rh = d.xmat[head].reshape(3, 3)
    m.cam_pos[cam] = Rh.T @ (p_w - d.xpos[head])
    q = np.zeros(4)
    mujoco.mju_mat2Quat(q, (Rh.T @ R_w).flatten())
    m.cam_quat[cam] = q
    mujoco.mj_forward(m, d)


def tag_image(tag_id: int, px: int = 200) -> np.ndarray:
    """tag36h11 的影像（含一圈白邊），灰階 uint8。"""
    import cv2

    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    core = cv2.aruco.generateImageMarker(d, tag_id, px)
    border = px // 8  # 黑框邊長的 1/8：整張是黑框的 10/8 倍（與 hardware/dock 的紙本相同）
    img = np.full((px + 2 * border, px + 2 * border), 255, dtype=np.uint8)
    img[border:-border, border:-border] = core
    return img


def make_extender(duck_map: DuckMap, extra_boxes=(), with_tag_textures: bool = False):
    """回傳給 `ModelOptions.extend` 用的函式。`extra_boxes`：[(id, rect, height)]，地圖上沒有的障礙。"""

    def extend(spec: mujoco.MjSpec) -> None:
        for s in duck_map.structures:
            x0, y0, x1, y1 = s.rect
            add_wall_box(
                spec,
                f"map_{s.id}",
                ((x0 + x1) / 2, (y0 + y1) / 2, s.height_m / 2),
                ((x1 - x0) / 2, (y1 - y0) / 2, s.height_m / 2),
                KIND_RGBA.get(s.kind, KIND_RGBA["wall"]),
            )
        for bid, rect, h in extra_boxes:
            x0, y0, x1, y1 = rect
            add_wall_box(spec, f"extra_{bid}", ((x0 + x1) / 2, (y0 + y1) / 2, h / 2), ((x1 - x0) / 2, (y1 - y0) / 2, h / 2), KIND_RGBA["extra"])
        if duck_map.dock is not None:
            d = duck_map.dock.pose
            # 停止面：充電座座標 X 從椅背到 −1 mm、|Y| ≤ 78 mm、高度涵蓋機身外殼。
            depth = 0.06
            cx = d.x + math.cos(d.yaw) * (-0.001 - depth / 2)
            cy = d.y + math.sin(d.yaw) * (-0.001 - depth / 2)
            add_wall_box(spec, "dock_stop", (cx, cy, 0.20), (depth / 2, 0.078, 0.07), KIND_RGBA["dock"], yaw=d.yaw)
        # 禁區在地板上畫出來（只有外觀）。
        for z in duck_map.zones.values():
            x0, y0, x1, y1 = z.rect
            spec.worldbody.add_geom(
                name=f"zone_{z.id}",
                type=mujoco.mjtGeom.mjGEOM_BOX,
                pos=[(x0 + x1) / 2, (y0 + y1) / 2, 0.001],
                size=[(x1 - x0) / 2, (y1 - y0) / 2, 0.001],
                contype=0,
                conaffinity=0,
                rgba=[0.9, 0.15, 0.15, 0.55] if z.kind == "stairs" else [0.95, 0.6, 0.1, 0.45],
            )
        # 標籤。
        for t in duck_map.tags.values():
            half = t.size_m * 10 / 8 / 2
            kw = {}
            if with_tag_textures:
                img = tag_image(t.id)
                rgb = np.repeat(img[:, :, None], 3, axis=2)
                tex = spec.add_texture(name=f"tag{t.id}", type=mujoco.mjtTexture.mjTEXTURE_2D, width=img.shape[1], height=img.shape[0], nchannel=3)
                tex.data = rgb.tobytes()  # 這個方向算出來的圖不是鏡像（鏡像的標籤偵測器讀不到）
                mat = spec.add_material(name=f"tag{t.id}")
                mat.textures[mujoco.mjtTextureRole.mjTEXROLE_RGB] = f"tag{t.id}"
                kw["material"] = f"tag{t.id}"
            else:
                kw["rgba"] = [0.1, 0.1, 0.1, 1.0]
            # 薄板的局部 z 軸朝標籤面的方向；局部 x 軸水平、局部 y 軸朝上。
            cyaw, syaw = math.cos(t.yaw), math.sin(t.yaw)
            R = np.array([[-syaw, 0, cyaw], [cyaw, 0, syaw], [0, 1, 0]])
            q = np.zeros(4)
            mujoco.mju_mat2Quat(q, R.flatten())
            spec.worldbody.add_geom(
                name=f"tag_{t.id}",
                type=mujoco.mjtGeom.mjGEOM_BOX,
                pos=[t.x + 0.002 * cyaw, t.y + 0.002 * syaw, t.z],
                size=[half, half, 0.001],
                quat=q.tolist(),
                contype=0,
                conaffinity=0,
                **kw,
            )
        # 頭上的鏡頭（AR0144 名目值：垂直視角 39.4°）。位置與朝向在站穩後由 `mount_head_camera` 設定。
        spec.body("head_assembly").add_camera(name="head_cam", pos=[0, 0, 0], fovy=39.4)
        spec.worldbody.add_camera(name="top", pos=[3.5, 3.5, 11.0], quat=[1, 0, 0, 0], fovy=40)

    return extend


class MujocoBody:
    """`duck_nav.testing.ClosedLoop` 要的身體介面，後面是 MuJoCo＋上游步態策略。

    這裡同時扮演「身體端」：照 ADR-0009 §2.5 對速度指令做加速度限制、頭部以限速轉到目標。
    """

    mock = True  # 模擬，不是實機

    def __init__(self, duck_map: DuckMap, start: Pose2D | None = None, seed: int = 0, extra_boxes=(), with_tag_textures: bool = False, gyro_sigma: float = 0.01, gyro_bias: float = 0.002, model_kw: dict | None = None, obs_noise: bool = True):
        self.map = duck_map
        if start is None:
            start = duck_map.dock_base_pose(BASE_TO_CONTACT_M)
        opts = SimOptions(
            seed=seed,
            start_xy_yaw=(start.x, start.y, start.yaw),
            gyro_noise=0.1 if obs_noise else 0.0,
            accel_noise=0.05 if obs_noise else 0.0,
            model=ModelOptions(extend=make_extender(duck_map, extra_boxes, with_tag_textures), **(model_kw or {})),
        )
        self.sim = WalkSim(opts)
        self.rng = np.random.default_rng(seed + 77)
        self.gyro_sigma, self.gyro_bias = gyro_sigma, gyro_bias
        self.cmd = (0.0, 0.0, 0.0)
        self._head_cmd = 0.0
        self._air = deque(maxlen=int(0.5 / CONTROL_DT))
        self.info = self.sim.info()
        self.gyro_z = 0.0
        self.lifted = False
        self.max_tilt_deg = 0.0
        # 先站穩。
        for _ in range(25):
            self.info = self.sim.step()
        mount_head_camera(self.sim)

    @property
    def t(self) -> float:
        return self.sim.t

    @property
    def true_pose(self) -> Pose2D:
        return Pose2D(self.info.x, self.info.y, self.info.yaw)

    @property
    def stepping(self) -> bool:
        return sum(self._air) >= 3

    @property
    def fallen(self) -> bool:
        return self.info.fallen

    @property
    def head_yaw(self) -> float:
        return float(self.sim.joint_positions()[7])

    def apply(self, out: NavOutput) -> None:
        self.cmd = ramp(self.cmd, out.velocity)
        d = out.head.head_yaw - self._head_cmd
        self._head_cmd += max(-0.02, min(0.02, d))  # 1 rad/s
        self.info = self.sim.step([self.cmd[0], self.cmd[1], self.cmd[2], 0.0, 0.0, self._head_cmd, 0.0])
        self._air.append(not (self.info.contact_left and self.info.contact_right))
        gyro, _ = self.sim.imu()
        self.gyro_z = float(gyro[2]) + self.gyro_bias + self.rng.normal(0, self.gyro_sigma)
        self.max_tilt_deg = max(self.max_tilt_deg, self.info.tilt_deg)

    def teleport(self, pose: Pose2D) -> None:
        self.sim.teleport(pose.x, pose.y, pose.yaw)
        self.lifted = True
        self.info = self.sim.info()
