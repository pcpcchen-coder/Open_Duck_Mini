"""D2 方位換算、選人、平滑與遺失處理。

輸入：人臉偵測（像素）＋鏡頭模型（＋選用的聲源方位、雙目距離）。
輸出：一個追蹤目標的觀測 `TargetObservation`（相對光軸的方位、距離或 None、信心），
也就是約定的 UDP `face` 訊息內容。**只有方位與距離，沒有影像或特徵。**

門檻與時間常數全部是設計初值，**未校準**。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from .camera import CameraModel
from .face_detect import FaceDetection

NOMINAL_FACE_WIDTH_M = 0.15  # 與 tools/stereo_geometry.py 相同的假設


class SelectPolicy(str, Enum):
    LARGEST = "largest"  # 臉最大（通常最近）
    CENTER = "center"  # 最靠近光軸
    SOUND = "sound"  # 與聲源方向最接近（沒有聲源方向時退回 LARGEST）


@dataclass(frozen=True)
class FaceBearing:
    """一張臉相對光軸的方位。distance_m 為 None 表示不知道（不猜）。"""

    yaw: float  # 往左為正
    pitch: float  # 往上為正
    width_px: float
    score: float
    distance_m: float | None = None
    #: 距離是怎麼來的："stereo"、"mono_face_width"（名目臉寬推算，誤差大）或 None。
    distance_source: str | None = None


@dataclass(frozen=True)
class TargetObservation:
    bearing_yaw_rad: float
    bearing_pitch_rad: float
    distance_m: float | None
    confidence: float  # 0～1
    t_capture: float
    #: True＝這次沒有新的偵測，是沿用上一次的方位（信心會下降）。
    coasting: bool = False


def to_bearing(det: FaceDetection, cam: CameraModel, distance_m: float | None = None, distance_source: str | None = None) -> FaceBearing:
    yaw, pitch = cam.ray_angles(det.u, det.v)
    return FaceBearing(yaw, pitch, det.width_px, det.score, distance_m, distance_source if distance_m is not None else None)


def mono_distance_m(width_px: float, cam: CameraModel, face_width_m: float = NOMINAL_FACE_WIDTH_M) -> float | None:
    """用名目臉寬估距離（單眼退路）。臉寬因人而異、偵測框也不等於臉寬，誤差可達 ±20% 以上，**未校準**。"""
    if width_px <= 1:
        return None
    return cam.fx * face_width_m / width_px


@dataclass
class TrackerConfig:
    policy: SelectPolicy = SelectPolicy.LARGEST
    min_score: float = 0.6
    #: 新偵測與目前目標的角度差在這之內算同一個人。
    match_gate_rad: float = math.radians(10.0)
    #: 目標這張沒偵測到時，沿用上一次方位最多這麼久；超過就算遺失（輸出 None）。
    lost_after_s: float = 0.6
    #: 方位的指數平滑時間常數（0＝不平滑）。
    smooth_tau_s: float = 0.15
    #: 距離的指數平滑時間常數。
    distance_tau_s: float = 0.4
    #: SOUND 政策：聲源方向與臉的偏航差在這之內才算對得上；聲源方向超過這個時間就不用。
    sound_gate_rad: float = math.radians(25.0)
    sound_max_age_s: float = 3.0
    #: 換人：只有目前目標遺失才換（黏著），避免兩個人之間跳。
    sticky: bool = True


class FaceTargetTracker:
    """從每張影像的偵測裡維持一個目標。鏡頭座標下工作，所以鏡頭轉動快時配對門檻要夠寬。

    `gaze_delta`（這張與上一張之間鏡頭轉了多少）可以由呼叫端提供來補償；沒有就不補償。
    """

    def __init__(self, config: TrackerConfig | None = None) -> None:
        self.cfg = config or TrackerConfig()
        self._yaw: float | None = None
        self._pitch = 0.0
        self._dist: float | None = None
        self._last_seen: float | None = None
        self._last_t: float | None = None
        self._score = 0.0
        self.lost_count = 0

    def reset(self) -> None:
        self._yaw = None
        self._dist = None
        self._last_seen = None
        self._last_t = None

    @property
    def has_target(self) -> bool:
        return self._yaw is not None

    def update(
        self,
        t: float,
        faces: list[FaceBearing],
        sound_yaw_cam: float | None = None,
        sound_t: float | None = None,
        gaze_delta: tuple[float, float] = (0.0, 0.0),
    ) -> TargetObservation | None:
        cfg = self.cfg
        faces = [f for f in faces if f.score >= cfg.min_score]
        dt = 0.0 if self._last_t is None else max(0.0, t - self._last_t)
        self._last_t = t
        if self._yaw is not None:
            # 鏡頭往左轉 → 目標在畫面裡往右（方位變小）
            self._yaw -= gaze_delta[0]
            self._pitch -= gaze_delta[1]
        sound = None
        if sound_yaw_cam is not None and (sound_t is None or t - sound_t <= cfg.sound_max_age_s):
            sound = sound_yaw_cam

        pick: FaceBearing | None = None
        if self._yaw is not None and faces:
            near = min(faces, key=lambda f: math.hypot(f.yaw - self._yaw, f.pitch - self._pitch))
            if math.hypot(near.yaw - self._yaw, near.pitch - self._pitch) <= cfg.match_gate_rad:
                pick = near
        if pick is None and faces and (self._yaw is None or not cfg.sticky):
            pick = self._select(faces, sound)
            if pick is not None:
                self._yaw = None  # 新目標：不和舊的平滑值混在一起

        if pick is not None:
            if self._yaw is None or cfg.smooth_tau_s <= 0 or dt <= 0:
                self._yaw, self._pitch = pick.yaw, pick.pitch
                self._dist = pick.distance_m
            else:
                a = 1.0 - math.exp(-dt / cfg.smooth_tau_s)
                self._yaw += a * (pick.yaw - self._yaw)
                self._pitch += a * (pick.pitch - self._pitch)
                if pick.distance_m is None:
                    pass  # 這張量不到距離：保留上一個值，遺失時一起清掉
                elif self._dist is None:
                    self._dist = pick.distance_m
                else:
                    b = 1.0 - math.exp(-dt / cfg.distance_tau_s)
                    self._dist += b * (pick.distance_m - self._dist)
            self._last_seen = t
            self._score = pick.score
            return TargetObservation(self._yaw, self._pitch, self._dist, min(1.0, pick.score), t)

        if self._yaw is None or self._last_seen is None:
            return None
        age = t - self._last_seen
        if age > cfg.lost_after_s:
            self.lost_count += 1
            self.reset()
            self._last_t = t
            return None
        conf = self._score * max(0.0, 1.0 - age / cfg.lost_after_s)
        return TargetObservation(self._yaw, self._pitch, self._dist, conf, t, coasting=True)

    def _select(self, faces: list[FaceBearing], sound: float | None) -> FaceBearing | None:
        cfg = self.cfg
        if cfg.policy is SelectPolicy.SOUND and sound is not None:
            near = min(faces, key=lambda f: abs(f.yaw - sound))
            # 聲源方向附近沒有臉：不選（讓上層轉向聲源去找），不隨便看別人
            return near if abs(near.yaw - sound) <= cfg.sound_gate_rad else None
        if cfg.policy is SelectPolicy.CENTER:
            return min(faces, key=lambda f: math.hypot(f.yaw, f.pitch))
        return max(faces, key=lambda f: f.width_px)
