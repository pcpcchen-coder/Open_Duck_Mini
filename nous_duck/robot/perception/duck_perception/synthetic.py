"""D1 合成影像來源（**mock**）：程式畫出的「人臉」貼在已知方位與距離，產生校正後的雙目畫面與真值。

這不是真的鏡頭，也不是真人影像：臉是用橢圓與色塊畫的示意圖，只用來

- 驗證控制鏈（方位換算、選人、平滑、look_at 閉迴路、雙目估距）對得上已知真值；
- 量偵測器在 Pi 4 上的運算時間（畫面大小與內容接近即可）。

**不能**用來宣稱偵測器對真人的偵測率或估距精度。

簡化（都會讓合成畫面比真實情況容易）：

- 鏡頭繞自己的光學中心轉（忽略頭頸機構造成的鏡頭平移）。
- 臉永遠正對鏡頭、是平面貼圖；沒有遮蔽、沒有動態模糊；光照均勻。
- 背景是一面固定距離的雜訊紋理牆，只做水平視差位移，不隨鏡頭轉動變形。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from .camera import CameraModel, Frame, StereoRig

FACE_WIDTH_M = 0.15  # 與 tools/stereo_geometry.py 相同的臉寬假設


@dataclass
class SyntheticPerson:
    """一個合成的人：臉中心在**身體座標**的方位（yaw 往左為正、pitch 往上為正）與離鏡頭的距離。"""

    yaw: float
    pitch: float
    distance_m: float
    face_width_m: float = FACE_WIDTH_M
    #: 畫臉用的色調種子（讓不同人看起來不一樣）。
    seed: int = 0
    visible: bool = True


@dataclass(frozen=True)
class FaceTruth:
    """合成臉在左眼影像的真值。"""

    person_index: int
    u: float
    v: float
    width_px: float
    distance_m: float  # 沿光軸的深度 Z
    range_m: float  # 到鏡頭的直線距離
    disparity_px: float
    yaw_cam: float  # 相對光軸的方位（往左為正）
    pitch_cam: float
    in_view: bool


def body_dir(yaw: float, pitch: float) -> np.ndarray:
    """身體座標（x 前、y 左、z 上）的單位方向。"""
    return np.array([math.cos(pitch) * math.cos(yaw), math.cos(pitch) * math.sin(yaw), math.sin(pitch)])


def body_to_cam(p_body: np.ndarray, gaze_yaw: float, gaze_pitch: float) -> np.ndarray:
    """身體座標的點 → 鏡頭座標（X 右、Y 下、Z 前），鏡頭視線為（gaze_yaw, gaze_pitch）、無側傾。"""
    f = body_dir(gaze_yaw, gaze_pitch)
    left = np.array([-math.sin(gaze_yaw), math.cos(gaze_yaw), 0.0])
    up = np.cross(f, left)
    return np.array([-float(p_body @ left), -float(p_body @ up), float(p_body @ f)])


def draw_face(size_px: int, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """畫一張示意臉（BGR）與遮罩（0～1）。寬度 size_px；高度約 1.35 倍。**不是真人影像。**"""
    rng = np.random.default_rng(seed)
    w = max(8, int(size_px))
    h = int(w * 1.35)
    s = 4  # 超取樣
    W, H = w * s, h * s
    img = np.zeros((H, W, 3), np.uint8)
    mask = np.zeros((H, W), np.uint8)
    skin = np.array([150, 175, 215]) + rng.integers(-18, 18, 3)
    cx, cy = W // 2, H // 2
    cv2.ellipse(mask, (cx, cy), (int(W * 0.48), int(H * 0.48)), 0, 0, 360, 255, -1)
    img[:] = skin
    # 由上往下、由中間往兩側稍微變暗，模擬立體感
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    shade = 1.0 - 0.25 * ((xx - cx) / (W / 2)) ** 2 - 0.15 * ((yy - cy * 0.8) / (H / 2)) ** 2
    img = np.clip(img * shade[..., None], 0, 255).astype(np.uint8)
    hair = tuple(int(c) for c in rng.integers(15, 60, 3))
    cv2.ellipse(img, (cx, int(H * 0.16)), (int(W * 0.50), int(H * 0.24)), 0, 180, 360, hair, -1)
    ey, ex = int(H * 0.42), int(W * 0.21)
    for sx in (-1, 1):
        c = (cx + sx * ex, ey)
        cv2.ellipse(img, c, (int(W * 0.11), int(H * 0.035)), 0, 0, 360, (245, 245, 245), -1)
        cv2.circle(img, c, int(W * 0.035), (40, 30, 20), -1)
        cv2.ellipse(img, (c[0], ey - int(H * 0.07)), (int(W * 0.13), int(H * 0.02)), 0, 0, 360, hair, -1)
        cv2.ellipse(img, (c[0], ey + int(H * 0.035)), (int(W * 0.12), int(H * 0.03)), 0, 0, 180, tuple(int(v * 0.8) for v in skin), -1)
    nose_dark = tuple(int(v * 0.72) for v in skin)
    cv2.line(img, (cx, int(H * 0.44)), (cx - int(W * 0.03), int(H * 0.62)), nose_dark, max(1, s))
    cv2.ellipse(img, (cx, int(H * 0.63)), (int(W * 0.07), int(H * 0.02)), 0, 0, 180, nose_dark, -1)
    cv2.ellipse(img, (cx, int(H * 0.76)), (int(W * 0.17), int(H * 0.03)), 0, 0, 360, (70, 70, 150), -1)
    cv2.line(img, (cx - int(W * 0.17), int(H * 0.76)), (cx + int(W * 0.17), int(H * 0.76)), (40, 40, 90), max(1, s))
    img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    m = cv2.resize(mask, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    return img, m


def _paste(canvas: np.ndarray, patch: np.ndarray, mask: np.ndarray, cu: float, cv_: float) -> None:
    """把 patch 以（cu, cv_）為中心貼上（次像素位移用仿射內插）。"""
    h, w = patch.shape[:2]
    x0f, y0f = cu - w / 2, cv_ - h / 2
    x0, y0 = math.floor(x0f), math.floor(y0f)
    M = np.float32([[1, 0, x0f - x0], [0, 1, y0f - y0]])
    patch_s = cv2.warpAffine(patch, M, (w + 1, h + 1), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    mask_s = cv2.warpAffine(mask, M, (w + 1, h + 1), flags=cv2.INTER_LINEAR)
    H, W = canvas.shape[:2]
    xa, ya = max(x0, 0), max(y0, 0)
    xb, yb = min(x0 + w + 1, W), min(y0 + h + 1, H)
    if xa >= xb or ya >= yb:
        return
    sub = canvas[ya:yb, xa:xb].astype(np.float32)
    p = patch_s[ya - y0 : yb - y0, xa - x0 : xb - x0].astype(np.float32)
    m = mask_s[ya - y0 : yb - y0, xa - x0 : xb - x0, None]
    canvas[ya:yb, xa:xb] = (sub * (1 - m) + p * m).astype(np.uint8)


@dataclass
class SyntheticStereoSource:
    """合成雙目來源（`mock=True`）。呼叫端設定視線與時間，再 `read()` 取得畫面與真值。"""

    rig: StereoRig = field(default_factory=lambda: StereoRig.ar0144_nominal(640, 360))
    people: list[SyntheticPerson] = field(default_factory=list)
    stereo: bool = True
    background_m: float = 4.0
    #: 每個像素加的高斯雜訊標準差（0～255 的灰階單位）。
    noise_sigma: float = 2.0
    seed: int = 0
    mock: bool = True

    def __post_init__(self) -> None:
        self.model: CameraModel = self.rig.left
        self._rng = np.random.default_rng(self.seed)
        self._seq = 0
        self.gaze_yaw = 0.0
        self.gaze_pitch = 0.0
        self.t = 0.0
        w, h = self.model.width, self.model.height
        pad = int(self.rig.disparity_px(self.background_m)) + 4
        base = self._rng.integers(60, 140, (h // 8 + 2, (w + pad) // 8 + 2, 3)).astype(np.uint8)
        self._bg = cv2.resize(base, (w + pad, h), interpolation=cv2.INTER_CUBIC)
        self._closed = False

    def set_pose(self, t: float, gaze_yaw: float, gaze_pitch: float) -> None:
        """設定下一張的拍攝時間與鏡頭視線（身體座標）。"""
        self.t, self.gaze_yaw, self.gaze_pitch = t, gaze_yaw, gaze_pitch

    def truth(self) -> list[FaceTruth]:
        out = []
        cam = self.model
        for i, p in enumerate(self.people):
            if not p.visible:
                continue
            pc = body_to_cam(body_dir(p.yaw, p.pitch) * p.distance_m, self.gaze_yaw, self.gaze_pitch)
            uv = cam.project(tuple(pc))
            if uv is None:
                continue
            z = float(pc[2])
            wpx = cam.fx * p.face_width_m / z
            yaw_c, pitch_c = cam.ray_angles(*uv)
            half_w, half_h = wpx / 2, wpx * 1.35 / 2
            in_view = half_w <= uv[0] <= cam.width - half_w and half_h <= uv[1] <= cam.height - half_h
            out.append(FaceTruth(i, uv[0], uv[1], wpx, z, p.distance_m, self.rig.disparity_px(z), yaw_c, pitch_c, in_view))
        return out

    def read(self) -> Frame:
        if self._closed:
            raise RuntimeError("來源已關閉")
        cam = self.model
        w, h = cam.width, cam.height
        d_bg = self.rig.disparity_px(self.background_m)
        truth = self.truth()
        # 遠的先畫
        order = sorted(truth, key=lambda t: -t.distance_m)

        def render(shift_scale: float) -> np.ndarray:
            off = d_bg * shift_scale
            M = np.float32([[1, 0, -off], [0, 1, 0]])
            img = cv2.warpAffine(self._bg, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            for ft in order:
                patch, mask = draw_face(int(round(ft.width_px)), self.people[ft.person_index].seed)
                _paste(img, patch, mask, ft.u - ft.disparity_px * shift_scale, ft.v)
            if self.noise_sigma > 0:
                n = self._rng.normal(0, self.noise_sigma, img.shape)
                img = np.clip(img.astype(np.float32) + n, 0, 255).astype(np.uint8)
            return img

        left = render(0.0)
        right = render(1.0) if self.stereo else None
        self._seq += 1
        return Frame(seq=self._seq, t_capture=self.t, left=left, right=right, mock=True, truth=truth)

    def close(self) -> None:
        self._closed = True


class TruthDetector:
    """**合成偵測（mock）**：不看影像，直接把來源的真值加上雜訊當成偵測結果。

    用來測控制鏈（不需要模型檔、跑得快、可重現）。不代表任何偵測器的表現。
    """

    def __init__(self, source: SyntheticStereoSource, noise_px: float = 0.0, dropout: float = 0.0, seed: int = 0, width_scale: float = 0.92) -> None:
        from .face_detect import FaceDetection

        self._FaceDetection = FaceDetection
        self.source = source
        self.noise_px = noise_px
        self.dropout = dropout
        self.width_scale = width_scale  # YuNet 的框比合成臉寬略小（實測約 0.92）
        self._rng = np.random.default_rng(seed)

    def detect(self, image_bgr=None):
        out = []
        for ft in self.source.truth():
            if not ft.in_view or self._rng.random() < self.dropout:
                continue
            du, dv = (self._rng.normal(0, self.noise_px, 2) if self.noise_px > 0 else (0.0, 0.0))
            w = ft.width_px * self.width_scale
            out.append(self._FaceDetection(u=ft.u + du, v=ft.v + dv, width_px=w, height_px=w * 1.3, score=0.9))
        return out
