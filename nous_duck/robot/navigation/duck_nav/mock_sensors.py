"""**mock 感測器**：由真實位姿用幾何算出來的標籤觀測與障礙點。只給模擬與測試用，不是真的偵測器。

實機上這兩樣資料會來自 perception（AprilTag 偵測、雙目深度）。這裡的模型：

- 標籤：在鏡頭視野內（AR0144 名目值：水平 65°、垂直 39.4°、1280×720，`docs/stereo_vision_plan.md`）、
  在最遠距離內、標籤沒有太斜、沒被地圖上的牆或額外的障礙擋住，才算看得到。
  雜訊：方位約 1 像素；距離誤差隨距離平方成長（由標籤邊長的像素誤差推得）；標籤朝向的誤差隨距離成長。
  有固定的漏偵測機率。
- 障礙：在水平視野內對牆與障礙物做 2D 光線投射，回傳近距離的命中點（機身座標）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .geometry import Pose2D, segment_hits_rect, to_body, wrap
from .mapfile import DuckMap
from .types import TagObservation

# AR0144 名目值（docs/stereo_vision_plan.md、tools/stereo_geometry.py）。
WIDTH_PX = 1280
HFOV = math.radians(65.0)
VFOV = math.radians(39.4)
FOCAL_PX = (WIDTH_PX / 2) / math.tan(HFOV / 2)  # ≈ 1005
CAM_HEIGHT_M = 0.37
#: 鏡頭在機身座標的前後位置（頭殼正面，假設值；頭殼還沒重新設計）。
CAM_FORWARD_M = 0.10


@dataclass
class MockCameraConfig:
    max_range_m: float = 3.5
    min_range_m: float = 0.15
    max_view_angle: float = math.radians(65)  # 標籤法線與視線的夾角上限
    min_tag_px: float = 30.0  # 標籤邊長小於這個像素數就當成偵測不到（假設值）
    px_sigma: float = 1.0  # 角點的像素雜訊
    yaw_sigma_base: float = math.radians(1.5)
    dropout: float = 0.1
    obstacle_range_m: float = 1.2
    obstacle_rays: int = 21
    obstacle_sigma_m: float = 0.01


class MockTagCamera:
    """幾何合成的 AprilTag 觀測（`TagObservation.mock = True`）。"""

    def __init__(self, duck_map: DuckMap, config: MockCameraConfig | None = None, seed: int = 0):
        self.map = duck_map
        self.cfg = config or MockCameraConfig()
        self.rng = np.random.default_rng(seed)
        #: 額外的遮擋物（例如關著的門、臨時放的箱子），軸對齊長方形與高度。
        self.extra_boxes: list[tuple[tuple[float, float, float, float], float]] = []

    def _occluded(self, cam, tag_xy, tag_z: float) -> bool:
        boxes = [(s.rect, s.height_m) for s in self.map.structures] + self.extra_boxes
        for rect, height in boxes:
            t = segment_hits_rect(cam, tag_xy, rect)
            if t is None or t > 0.995:
                continue
            # 視線在這個位置的高度；比障礙物高就看得過去。
            z = CAM_HEIGHT_M + (tag_z - CAM_HEIGHT_M) * t
            if z <= height:
                return True
        return False

    def observe(self, true_pose: Pose2D, head_yaw: float = 0.0, head_pitch: float = 0.0) -> list[TagObservation]:
        c = self.cfg
        cam_dir = wrap(true_pose.yaw + head_yaw)
        cam = (true_pose.x + CAM_FORWARD_M * math.cos(true_pose.yaw), true_pose.y + CAM_FORWARD_M * math.sin(true_pose.yaw))
        out = []
        for tag in self.map.tags.values():
            dx, dy = tag.x - cam[0], tag.y - cam[1]
            rng_m = math.hypot(dx, dy)
            if not c.min_range_m <= rng_m <= c.max_range_m:
                continue
            bearing = wrap(math.atan2(dy, dx) - cam_dir)
            # 標籤整個要在畫面內：留半個標籤的角度。
            half = math.atan2(tag.size_m / 2, rng_m)
            if abs(bearing) + half > HFOV / 2:
                continue
            elev = math.atan2(tag.z - CAM_HEIGHT_M, rng_m) - head_pitch
            if abs(elev) + half > VFOV / 2:
                continue
            view = abs(wrap(math.atan2(-dy, -dx) - tag.yaw))  # 標籤法線與「標籤→鏡頭」的夾角
            if view > c.max_view_angle:
                continue
            px = FOCAL_PX * tag.size_m / rng_m * math.cos(view)
            if px < c.min_tag_px:
                continue
            if self._occluded(cam, (tag.x, tag.y), tag.z):
                continue
            if self.rng.random() < c.dropout:
                continue
            # 雜訊模型。
            s_bearing = c.px_sigma / FOCAL_PX
            s_range = rng_m**2 * c.px_sigma / (FOCAL_PX * tag.size_m)
            s_yaw = c.yaw_sigma_base * (1.0 + (rng_m / 1.0) ** 2) / max(math.cos(view), 0.4)
            r_n = rng_m + self.rng.normal(0, s_range)
            b_n = bearing + self.rng.normal(0, s_bearing)
            # 換到機身座標（鏡頭在機身前方 CAM_FORWARD_M，朝向 head_yaw）。
            bx = CAM_FORWARD_M + r_n * math.cos(head_yaw + b_n)
            by = r_n * math.sin(head_yaw + b_n)
            byaw = wrap(tag.yaw - true_pose.yaw + self.rng.normal(0, s_yaw))
            out.append(TagObservation(tag.id, bx, by, byaw, sigma_xy=math.hypot(s_range, rng_m * s_bearing) + 0.005, sigma_yaw=s_yaw, mock=True))
        return out

    def obstacles(self, true_pose: Pose2D, head_yaw: float = 0.0) -> list[tuple[float, float]]:
        """水平視野內的近距離障礙點（機身座標）。牆與地圖上的家具也會回傳，由導航自己對照地圖。"""
        c = self.cfg
        cam = (true_pose.x + CAM_FORWARD_M * math.cos(true_pose.yaw), true_pose.y + CAM_FORWARD_M * math.sin(true_pose.yaw))
        rects = [s.rect for s in self.map.structures if s.height_m > 0.05] + [r for r, h in self.extra_boxes if h > 0.05]
        pts = []
        for i in range(c.obstacle_rays):
            a = wrap(true_pose.yaw + head_yaw - HFOV / 2 + HFOV * i / (c.obstacle_rays - 1))
            end = (cam[0] + c.obstacle_range_m * math.cos(a), cam[1] + c.obstacle_range_m * math.sin(a))
            best = None
            for rect in rects:
                t = segment_hits_rect(cam, end, rect)
                if t is not None and (best is None or t < best):
                    best = t
            if best is not None:
                d = best * c.obstacle_range_m + self.rng.normal(0, c.obstacle_sigma_m)
                hx, hy = cam[0] + d * math.cos(a), cam[1] + d * math.sin(a)
                pts.append(to_body(true_pose, hx, hy))
        return pts


class MockDockContact:
    """**mock 的充電訊號**：用真實位姿與充電座 CAD 的幾何容許量判斷「有沒有接上」。

    實機上「開始充電」只能來自電氣訊號（充電板或電流感測，ADR-0004 §3）。這裡沒有電，只能用幾何代替：

    1. 背後觸點面進到 V 形導引座開口（離停止面 `mouth_m`）的那一刻，記下左右偏差與偏航偏差。
       偏差在 CAD 算出的捕捉範圍內（±34 mm、±5°，`docs/validation/dock-cad-2026-11-13.md`）才算「被導引座接住」。
    2. 被接住之後，觸點面離停止面小於 `contact_m`（頂針開始接觸的 2.5 mm）就回報充電。

    **沒有模擬**：V 形座把鴨子推回中間的過程、頂針彈力、摩擦、鴨子被側推時的平衡。
    """

    def __init__(self, duck_map: DuckMap, base_to_contact_m: float, capture_lateral_m: float = 0.034, capture_yaw_rad: float = math.radians(5.0), mouth_m: float = 0.030, contact_m: float = 0.0025):
        self.dock = duck_map.dock
        self.k = base_to_contact_m
        self.capture_lateral_m = capture_lateral_m
        self.capture_yaw_rad = capture_yaw_rad
        self.mouth_m = mouth_m
        self.contact_m = contact_m
        self.reset()

    def reset(self) -> None:
        self.inside = False
        self.captured = False
        self.entries: list[dict] = []  # 每次進入開口時的偏差

    def gap_and_offsets(self, true_pose: Pose2D) -> tuple[float, float, float]:
        """（觸點面離停止面的距離, 左右偏差, 偏航偏差）。"""
        xd, yd = to_body(self.dock.pose, true_pose.x, true_pose.y)
        e = wrap(true_pose.yaw - self.dock.pose.yaw)
        # 觸點面中心在機身後方 k：考慮偏航後它在充電座座標的位置。
        cx = xd - self.k * math.cos(e)
        cy = yd - self.k * math.sin(e)
        return cx, cy, e

    def update(self, true_pose: Pose2D) -> bool:
        gap, lat, e = self.gap_and_offsets(true_pose)
        near_axis = abs(lat) < 0.15 and abs(e) < math.pi / 2
        if near_axis and gap <= self.mouth_m:
            if not self.inside:
                self.inside = True
                self.captured = abs(lat) <= self.capture_lateral_m and abs(e) <= self.capture_yaw_rad
                self.entries.append({"lateral_m": lat, "yaw_rad": e, "captured": self.captured})
        elif gap > self.mouth_m + 0.02:
            self.inside = False
            self.captured = False
        return bool(self.inside and self.captured and gap <= self.contact_m)
