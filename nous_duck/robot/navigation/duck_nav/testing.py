"""測試與示範用的**運動學假鴨**（mock）與共用的閉迴路。不是物理模擬，更不是實機。

`KinematicDuck` 用步態反應表（模擬量測）把速度指令變成位移：有加速度限制、一階延遲、
比例誤差與隨機擾動，撞到牆就停住。用途是讓導航的單元測試不需要 MuJoCo、幾秒內跑完。
物理層級的驗證在 `nous_duck/sim/nav_sim`（MuJoCo＋上游步態策略）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .gait import CONTROL_DT, GaitModel, ramp
from .geometry import Pose2D, rect_distance, wrap
from .mapfile import DuckMap
from .mock_sensors import MockDockContact, MockTagCamera
from .navigator import BASE_TO_CONTACT_M, Navigator
from .types import HeadTarget, NavOutput, SensorFrame


@dataclass
class KinematicConfig:
    seed: int = 0
    #: 實際速度相對反應表的比例誤差（每次建立時抽一次）與每步的隨機擾動。
    scale_sigma: float = 0.08
    jitter: float = 0.15
    yaw_bias_sigma: float = 0.02  # rad/s，走路時的固定偏航漂移
    gyro_sigma: float = 0.01
    gyro_bias: float = 0.002
    body_radius_m: float = 0.11
    use_gyro: bool = True


class KinematicDuck:
    """mock 身體：位姿、步態反應、撞牆。"""

    mock = True

    def __init__(self, duck_map: DuckMap, pose: Pose2D, config: KinematicConfig | None = None, gait: GaitModel | None = None):
        self.map = duck_map
        self.cfg = config or KinematicConfig()
        self.gait = gait or GaitModel.load()
        self.rng = np.random.default_rng(self.cfg.seed)
        self.pose = pose
        self.cmd = (0.0, 0.0, 0.0)
        self.v = np.zeros(3)
        self.scale = 1.0 + self.rng.normal(0, self.cfg.scale_sigma, 3)
        self.yaw_bias = self.rng.normal(0, self.cfg.yaw_bias_sigma)
        self.head = HeadTarget()
        self.head_yaw = 0.0
        self.t = 0.0
        self.fallen = False
        self.extra_boxes: list[tuple[float, float, float, float]] = []
        self.collisions = 0
        self.lifted = False
        self.gyro_z = 0.0
        self.trace: list[tuple[float, float, float, float]] = []

    @property
    def true_pose(self) -> Pose2D:
        return self.pose

    @property
    def stepping(self) -> bool:
        return bool(np.abs(self.v).max() > 0.01)

    def _hits(self, x: float, y: float) -> bool:
        r = self.cfg.body_radius_m
        for s in self.map.structures:
            if s.kind == "dock":
                continue  # 充電座由 MockDockContact 與下面的停止面處理
            if rect_distance(x, y, s.rect) < r:
                return True
        return any(rect_distance(x, y, b) < r for b in self.extra_boxes)

    def apply(self, out: NavOutput) -> None:
        """執行一個控制週期（20 ms）。"""
        dt = CONTROL_DT
        self.cmd = ramp(self.cmd, out.velocity)
        tgt = np.array(self.gait.response(self.cmd[0], self.cmd[2])) * self.scale
        walking = abs(tgt).max() > 1e-6
        self.v += (tgt - self.v) * min(1.0, dt / self.gait.tau_s)
        v = self.v * (1.0 + self.rng.normal(0, self.cfg.jitter, 3)) if walking else self.v
        w = v[2] + (self.yaw_bias if walking else 0.0)
        c, s = math.cos(self.pose.yaw), math.sin(self.pose.yaw)
        nx = self.pose.x + (c * v[0] - s * v[1]) * dt
        ny = self.pose.y + (s * v[0] + c * v[1]) * dt
        # 充電座的停止面：背後觸點面不能退過去。
        if self.map.dock is not None:
            gap, lat, e = MockDockContact(self.map, BASE_TO_CONTACT_M).gap_and_offsets(Pose2D(nx, ny, self.pose.yaw))
            if abs(lat) < 0.10 and abs(e) < 1.0 and gap < -0.001:
                nx, ny = self.pose.x, self.pose.y
        if self._hits(nx, ny):
            self.collisions += 1
            nx, ny = self.pose.x, self.pose.y
        self.pose = Pose2D(nx, ny, wrap(self.pose.yaw + w * dt))
        self.gyro_z = w + self.cfg.gyro_bias + self.rng.normal(0, self.cfg.gyro_sigma)
        self.head = out.head
        self.head_yaw += max(-0.06, min(0.06, out.head.head_yaw - self.head_yaw))  # 3 rad/s
        self.t += dt
        self.trace.append((self.t, self.pose.x, self.pose.y, self.pose.yaw))

    def teleport(self, pose: Pose2D) -> None:
        """被抱到別處放下。"""
        self.pose = pose
        self.lifted = True
        self.v[:] = 0
        self.cmd = (0.0, 0.0, 0.0)


@dataclass
class LoopResult:
    events: list[dict] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)
    min_zone_dist_m: float = float("inf")
    max_est_err_m: float = 0.0
    steps: int = 0

    def last(self, name: str) -> dict | None:
        for e in reversed(self.events):
            if e["event"] == name:
                return e
        return None

    def names(self) -> list[str]:
        return [e["event"] for e in self.events]


class ClosedLoop:
    """導航器 ＋ 身體（`KinematicDuck` 或 MuJoCo 轉接器）＋ mock 感測器的閉迴路。

    身體要提供：`true_pose`、`stepping`、`fallen`、`gyro_z`、`head_yaw`、`cmd`（實際送給步態的指令）、
    `apply(NavOutput)`、`t`。
    """

    def __init__(self, nav: Navigator, body, camera: MockTagCamera, dock: MockDockContact | None = None, use_gyro: bool = True, camera_hz: float = 10.0, obstacle_sensor: bool = True):
        self.nav, self.body, self.camera, self.dock = nav, body, camera, dock
        self.use_gyro = use_gyro
        self.camera_every = max(1, int(round(1.0 / (camera_hz * CONTROL_DT))))
        self.obstacle_sensor = obstacle_sensor
        self.result = LoopResult()
        self.n = 0
        self.record_every = 5
        #: 身體端會不會回報「被抱起來」（關掉可以測只靠標籤對不上來發現被搬動的情況）。
        self.report_lift = True

    def frame(self) -> SensorFrame:
        b = self.body
        tags, obstacles, valid = [], [], False
        if self.n % self.camera_every == 0:
            tags = self.camera.observe(b.true_pose, getattr(b, "head_yaw", 0.0))
            if self.obstacle_sensor:
                obstacles = self.camera.obstacles(b.true_pose, getattr(b, "head_yaw", 0.0))
                valid = True
        charging = None
        if self.dock is not None:
            charging = self.dock.update(b.true_pose)
        return SensorFrame(
            t=b.t,
            dt=CONTROL_DT,
            tags=tags,
            gyro_z=b.gyro_z if self.use_gyro else None,
            applied_cmd=tuple(b.cmd),
            obstacles=obstacles,
            obstacles_valid=valid,
            fallen=bool(b.fallen),
            lifted=bool(self._take_lifted()),
            stepping=bool(b.stepping),
            charging=charging,
            charging_mock=True,
            head_yaw=getattr(b, "head_yaw", None),
        )

    def _take_lifted(self) -> bool:
        if self.report_lift and getattr(self.body, "lifted", False):
            self.body.lifted = False
            return True
        return False

    def step(self) -> NavOutput:
        out = self.nav.step(self.frame())
        self.body.apply(out)
        self.n += 1
        r = self.result
        r.steps = self.n
        r.events += out.events
        tp = self.body.true_pose
        for z in self.nav.map.zones.values():
            r.min_zone_dist_m = min(r.min_zone_dist_m, rect_distance(tp.x, tp.y, z.rect))
        est = self.nav.loc.pose
        if est is not None and self.nav.loc.localized:
            r.max_est_err_m = max(r.max_est_err_m, math.hypot(est.x - tp.x, est.y - tp.y))
        if self.n % self.record_every == 0:
            r.trace.append(
                {
                    "t": round(self.body.t, 2),
                    "x": tp.x,
                    "y": tp.y,
                    "yaw": tp.yaw,
                    "ex": est.x if est else None,
                    "ey": est.y if est else None,
                    "sigma": self.nav.loc.pos_sigma if est else None,
                    "phase": self.nav.mission.phase if self.nav.mission else "idle",
                }
            )
        return out

    def run_until_idle(self, max_seconds: float = 400.0) -> LoopResult:
        """跑到目前的任務結束（或逾時）。"""
        n_max = int(max_seconds / CONTROL_DT)
        for _ in range(n_max):
            self.step()
            if self.nav.mission is None:
                break
        return self.result

    def run_for(self, seconds: float) -> LoopResult:
        for _ in range(int(seconds / CONTROL_DT)):
            self.step()
        return self.result


def make_kinematic_loop(duck_map: DuckMap, start: Pose2D | None = None, seed: int = 0, docked: bool = True, extra_boxes=(), **kw) -> ClosedLoop:
    """建立「運動學假鴨＋mock 感測器＋導航器」的閉迴路。`docked=True` 表示從充電座上開始。

    `extra_boxes`：[(id, rect, height)]，地圖上沒有的障礙（關著的門、箱子）。
    """
    if start is None:
        start = duck_map.dock_base_pose(BASE_TO_CONTACT_M)
    body = KinematicDuck(duck_map, start, KinematicConfig(seed=seed))
    nav = Navigator(duck_map, mock=True, clock_ms=lambda: int(1_795_600_000_000 + body.t * 1000), config=kw.pop("config", None))
    cam = MockTagCamera(duck_map, seed=seed + 1)
    body.extra_boxes = [rect for _, rect, _ in extra_boxes]
    cam.extra_boxes = [(rect, h) for _, rect, h in extra_boxes]
    dock = MockDockContact(duck_map, BASE_TO_CONTACT_M) if duck_map.dock else None
    loop = ClosedLoop(nav, body, cam, dock, **kw)
    if docked:
        nav.set_docked()
    return loop
