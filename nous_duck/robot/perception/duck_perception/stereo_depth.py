"""D4 雙目估距：左眼偵測到的臉，在右眼同一列找對應位置，由視差算距離。

前提（不成立就不能用，函式會回傳 None 並說明原因）：

1. **影像已做立體校正**（`StereoRig.rectified`）：左右同一點在同一列，視差只在水平方向。
   真的 AR0144 要先做雙目校正（V1），之前量到的距離不可信。
2. 內參與基線正確。目前是**名目值（f≈1005 px @1280、B=52 mm），未校準**；焦距或基線差 1%，
   距離就差 1%。
3. 左右同時曝光（AR0144 是同步全域快門；合成來源本來就同時）。

距離：Z = f·B / d。視差誤差 σ_d 造成的深度誤差（一階）：σ_Z ≈ Z²·σ_d / (f·B)，
與 `tools/stereo_geometry.py` 的 `depth_step_m` 相同。

驗證層級：合成雙目影像（已知真值）。**沒有用真的鏡頭驗證。**
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .camera import StereoRig
from .face_detect import FaceDetection


@dataclass(frozen=True)
class StereoDepth:
    #: 沿光軸的深度 Z（公尺）；量不到為 None。
    depth_m: float | None
    #: 到鏡頭的直線距離（公尺）；量不到為 None。
    range_m: float | None
    disparity_px: float | None
    #: 比對分數（正規化互相關，-1～1）。
    ncc: float | None
    #: 量不到的原因；量到時為 None。
    reason: str | None = None


def _none(reason: str, ncc: float | None = None) -> StereoDepth:
    return StereoDepth(None, None, None, ncc, reason)


def depth_sigma_m(z_m: float, rig: StereoRig, disparity_sigma_px: float) -> float:
    """視差誤差 disparity_sigma_px 對應的深度誤差（一階近似）。"""
    return z_m**2 * disparity_sigma_px / (rig.left.fx * rig.baseline_m)


def face_stereo_depth(
    left_bgr: np.ndarray,
    right_bgr: np.ndarray | None,
    det: FaceDetection,
    rig: StereoRig | None,
    max_disparity_px: int | None = None,
    min_disparity_px: float = 1.0,
    min_ncc: float = 0.6,  # 未校準
    min_patch_px: int = 12,
    uniqueness: float = 0.03,
) -> StereoDepth:
    """用臉部區塊做一維樣板比對求視差。量不到回傳 depth_m=None（不猜、不退回單眼估計）。"""
    import cv2

    if rig is None or right_bgr is None:
        return _none("no_stereo")
    if not rig.rectified:
        return _none("not_rectified")
    H, W = left_bgr.shape[:2]
    if right_bgr.shape[:2] != (H, W):
        return _none("size_mismatch")
    # 取偵測框中間 70% 當樣板，少吃到背景
    pw, ph = int(det.width_px * 0.7), int(det.height_px * 0.7)
    if pw < min_patch_px or ph < min_patch_px:
        return _none("face_too_small")
    x0, y0 = int(round(det.u - pw / 2)), int(round(det.v - ph / 2))
    if x0 < 0 or y0 < 0 or x0 + pw > W or y0 + ph > H:
        return _none("face_at_edge")
    if max_disparity_px is None:
        max_disparity_px = W // 4
    xs = max(0, x0 - max_disparity_px)
    if x0 - xs < min_disparity_px:
        return _none("no_search_range")
    gl = cv2.cvtColor(left_bgr[y0 : y0 + ph, x0 : x0 + pw], cv2.COLOR_BGR2GRAY)
    gr = cv2.cvtColor(right_bgr[y0 : y0 + ph, xs : x0 + pw], cv2.COLOR_BGR2GRAY)
    if float(gl.std()) < 2.0:
        return _none("no_texture")
    res = cv2.matchTemplate(gr, gl, cv2.TM_CCOEFF_NORMED)[0]  # 長度 x0-xs+1；索引 i ↔ 右眼 x = xs+i
    i = int(np.argmax(res))
    peak = float(res[i])
    if not math.isfinite(peak) or peak < min_ncc:
        return _none("no_match", peak if math.isfinite(peak) else None)
    # 唯一性：樣板寬度以外的第二高峰不能太接近
    far = np.ones_like(res, dtype=bool)
    far[max(0, i - pw // 2) : i + pw // 2 + 1] = False
    if far.any() and float(res[far].max()) > peak - uniqueness:
        return _none("ambiguous", peak)
    sub = 0.0
    if 0 < i < len(res) - 1:
        a, b, c = float(res[i - 1]), peak, float(res[i + 1])
        den = a - 2 * b + c
        if den < -1e-9:
            sub = 0.5 * (a - c) / den
    disparity = x0 - (xs + i + sub)
    if disparity < min_disparity_px:
        return _none("too_far", peak)
    z = rig.left.fx * rig.baseline_m / disparity
    yaw, pitch = rig.left.ray_angles(det.u, det.v)
    rng = z * math.sqrt(1.0 + math.tan(yaw) ** 2 + math.tan(pitch) ** 2)
    return StereoDepth(z, rng, disparity, peak, None)
