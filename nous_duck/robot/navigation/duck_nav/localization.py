"""定位：AprilTag 觀測（絕對）＋短程里程（相對）的擴展卡爾曼濾波。**不用步數。**

- 狀態：地圖座標的 (x, y, yaw) 與 3×3 共變異數。
- 預測：機身速度來自「實際送出的速度指令 → 步態反應表」（`gait.py`），偏航角速度優先用陀螺儀。
  步態反應表只是短程的替身（之後換成視覺慣性里程），所以過程雜訊給得大：看不到標籤時不確定度會一直長。
- 更新：每個標籤觀測是「標籤在機身座標的位姿」，對照地圖上的標籤位姿。
- 不確定度：`pos_sigma`（位置共變異數最大特徵值的平方根）與 `yaw_sigma`。
  超過門檻就是「未定位」，上層要停下（ADR-0002 §5.3）。
- 綁架（被人抱到別處）：觀測連續被拒絕（馬氏距離太大），而且連續兩次由觀測反推的位姿互相一致，就重新初始化。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .geometry import Pose2D, compose, inverse, wrap
from .mapfile import DuckMap
from .types import TagObservation


@dataclass
class LocalizerConfig:
    #: 過程雜訊：速度的比例誤差與底噪（每秒的標準差）。
    vel_frac: float = 0.35
    vel_floor: float = 0.012  # m/s
    yaw_rate_frac_gyro: float = 0.03
    yaw_rate_floor_gyro: float = 0.01  # rad/s
    yaw_rate_frac_model: float = 0.35
    yaw_rate_floor_model: float = 0.05
    #: 站著不動時的漂移底噪（幾乎為 0，但不設成 0，避免濾波器過度自信）。
    idle_pos: float = 0.001
    idle_yaw: float = 0.002
    #: 觀測閘門（3 自由度卡方 99.9% ≈ 16.3）。
    gate_chi2: float = 16.3
    #: 連續幾次被拒絕就考慮重新定位。
    kidnap_rejects: int = 6
    #: 連續幾次被拒絕就先當成「不可信」（上層要停下來看清楚）。
    suspect_rejects: int = 2
    kidnap_agree_m: float = 0.35
    kidnap_agree_rad: float = 0.5
    #: 「已定位」的門檻與「未定位（要停下）」的門檻。
    ok_pos_sigma: float = 0.12
    lost_pos_sigma: float = 0.30
    ok_yaw_sigma: float = math.radians(10)
    lost_yaw_sigma: float = math.radians(20)
    #: 觀測雜訊的下限（感測端回報的 sigma 不會比這個更小）。
    min_sigma_xy: float = 0.01
    min_sigma_yaw: float = 0.02


class Localizer:
    def __init__(self, duck_map: DuckMap, config: LocalizerConfig | None = None):
        self.map = duck_map
        self.cfg = config or LocalizerConfig()
        self.x: np.ndarray | None = None
        self.P: np.ndarray | None = None
        self.since_tag_s = float("inf")
        self.rejects = 0
        self._candidate: Pose2D | None = None
        self.reinit_count = 0
        self.last_tag_ids: list[int] = []

    # ------------------------------------------------------------- 狀態
    @property
    def initialized(self) -> bool:
        return self.x is not None

    @property
    def pose(self) -> Pose2D | None:
        if self.x is None:
            return None
        return Pose2D(float(self.x[0]), float(self.x[1]), wrap(float(self.x[2])))

    @property
    def pos_sigma(self) -> float:
        if self.P is None:
            return float("inf")
        return float(math.sqrt(max(np.linalg.eigvalsh(self.P[:2, :2]).max(), 0.0)))

    @property
    def yaw_sigma(self) -> float:
        if self.P is None:
            return float("inf")
        return float(math.sqrt(max(self.P[2, 2], 0.0)))

    @property
    def localized(self) -> bool:
        """位姿可以拿來導航（未超過「未定位」門檻）。"""
        return self.initialized and not self.suspect and self.pos_sigma < self.cfg.lost_pos_sigma and self.yaw_sigma < self.cfg.lost_yaw_sigma

    @property
    def suspect(self) -> bool:
        """最近的標籤觀測連續跟估計對不上：可能被搬動過，估計不可信。"""
        return self.initialized and self.rejects >= self.cfg.suspect_rejects

    @property
    def confident(self) -> bool:
        return self.initialized and not self.suspect and self.pos_sigma < self.cfg.ok_pos_sigma and self.yaw_sigma < self.cfg.ok_yaw_sigma

    def set_pose(self, pose: Pose2D, sigma_xy: float = 0.02, sigma_yaw: float = 0.05) -> None:
        """由外部給定位姿（例如電氣訊號確認停在充電座上）。"""
        self.x = np.array([pose.x, pose.y, pose.yaw], dtype=float)
        self.P = np.diag([sigma_xy**2, sigma_xy**2, sigma_yaw**2])
        self.rejects = 0
        self._candidate = None

    def reset(self) -> None:
        self.x = None
        self.P = None
        self.rejects = 0
        self._candidate = None

    # ------------------------------------------------------------- 預測
    def predict(self, dt: float, vx: float, vy: float, yaw_rate: float, gyro: bool) -> None:
        """用機身速度（m/s、rad/s）往前推 dt 秒。`gyro` 表示 yaw_rate 來自陀螺儀。"""
        self.since_tag_s += dt
        if self.x is None or dt <= 0:
            return
        c = self.cfg
        th = self.x[2]
        cs, sn = math.cos(th), math.sin(th)
        dx = (cs * vx - sn * vy) * dt
        dy = (sn * vx + cs * vy) * dt
        self.x = self.x + np.array([dx, dy, yaw_rate * dt])
        F = np.array([[1, 0, -dy], [0, 1, dx], [0, 0, 1]], dtype=float)
        speed = math.hypot(vx, vy)
        moving = speed > 1e-4 or abs(yaw_rate) > 1e-3
        # 速度誤差在相鄰週期之間高度相關（比例誤差、打滑），所以用「隨時間線性成長的標準差」：
        # 每一步加的變異數 = (sigma_rate * dt)^2 * k，k 把相關時間（約 1 s）折算進去。
        k = max(1.0, 1.0 / max(dt, 1e-3)) * dt  # ≈ 1：等效成每秒 sigma_rate 的隨機漫步
        if moving:
            sv = c.vel_frac * speed + c.vel_floor
            if gyro:
                sw = c.yaw_rate_frac_gyro * abs(yaw_rate) + c.yaw_rate_floor_gyro
            else:
                sw = c.yaw_rate_frac_model * abs(yaw_rate) + c.yaw_rate_floor_model
        else:
            sv, sw = c.idle_pos, c.idle_yaw
        q_pos = (sv**2) * dt * k
        q_yaw = (sw**2) * dt * k
        self.P = F @ self.P @ F.T + np.diag([q_pos, q_pos, q_yaw])

    # ------------------------------------------------------------- 更新
    def _pose_from(self, obs: TagObservation) -> Pose2D | None:
        tag = self.map.tags.get(obs.tag_id)
        if tag is None:
            return None
        return compose(tag.pose, inverse(Pose2D(obs.x, obs.y, obs.yaw)))

    def update(self, observations: list[TagObservation]) -> int:
        """融合這個週期的標籤觀測；回傳被採用的數量。"""
        used = 0
        known = [o for o in observations if o.tag_id in self.map.tags]
        self.last_tag_ids = [o.tag_id for o in known]
        for obs in known:
            if self.x is None:
                if self._try_reinit(obs):
                    used += 1
                continue
            if self._ekf_update(obs):
                used += 1
                self.rejects = 0
                self._candidate = None
            else:
                self.rejects += 1
                if self.rejects >= self.cfg.kidnap_rejects and self._try_reinit(obs):
                    used += 1
        if used:
            self.since_tag_s = 0.0
        return used

    def _noise(self, obs: TagObservation) -> np.ndarray:
        sxy = max(obs.sigma_xy, self.cfg.min_sigma_xy)
        syaw = max(obs.sigma_yaw, self.cfg.min_sigma_yaw)
        return np.diag([sxy**2, sxy**2, syaw**2])

    def _ekf_update(self, obs: TagObservation) -> bool:
        tag = self.map.tags[obs.tag_id]
        x, y, th = self.x
        cs, sn = math.cos(th), math.sin(th)
        dx, dy = tag.x - x, tag.y - y
        h = np.array([cs * dx + sn * dy, -sn * dx + cs * dy, wrap(tag.yaw - th)])
        H = np.array([[-cs, -sn, -sn * dx + cs * dy], [sn, -cs, -cs * dx - sn * dy], [0, 0, -1]], dtype=float)
        z = np.array([obs.x, obs.y, obs.yaw])
        v = z - h
        v[2] = wrap(v[2])
        R = self._noise(obs)
        S = H @ self.P @ H.T + R
        Sinv = np.linalg.inv(S)
        if float(v @ Sinv @ v) > self.cfg.gate_chi2:
            return False
        K = self.P @ H.T @ Sinv
        self.x = self.x + K @ v
        self.x[2] = wrap(self.x[2])
        I_KH = np.eye(3) - K @ H
        self.P = I_KH @ self.P @ I_KH.T + K @ R @ K.T  # Joseph 形式，保持對稱正定
        return True

    def _try_reinit(self, obs: TagObservation) -> bool:
        """由單一觀測反推位姿；要連續兩次互相一致才採用（避免被一筆錯的偵測帶走）。"""
        cand = self._pose_from(obs)
        if cand is None:
            return False
        prev, self._candidate = self._candidate, cand
        if prev is None:
            return False
        if math.hypot(cand.x - prev.x, cand.y - prev.y) > self.cfg.kidnap_agree_m or abs(wrap(cand.yaw - prev.yaw)) > self.cfg.kidnap_agree_rad:
            return False
        r = math.hypot(obs.x, obs.y)
        syaw = max(obs.sigma_yaw, self.cfg.min_sigma_yaw)
        sxy = math.hypot(max(obs.sigma_xy, self.cfg.min_sigma_xy), r * syaw)
        self.x = np.array([cand.x, cand.y, cand.yaw], dtype=float)
        self.P = np.diag([sxy**2, sxy**2, syaw**2]) * 1.5
        self.rejects = 0
        self._candidate = None
        self.reinit_count += 1
        return True
