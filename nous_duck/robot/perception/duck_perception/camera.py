"""D1 鏡頭抽象：影像來源介面、鏡頭模型（內參）、雙目外參、影格。

座標慣例：

- **鏡頭座標**（OpenCV）：X 往右、Y 往下、Z 往前（光軸）。
- **方位角**（給 look_at 與 UDP 介面用）：相對光軸，**往左為正（yaw）、往上為正（pitch）**，弧度。
- **身體座標**：x 往前、y 往左、z 往上。

影像只在記憶體裡傳遞（`Frame.left`／`Frame.right` 是 numpy 陣列）；這個模組沒有任何寫檔功能。

真的鏡頭來源（Waveshare AR0144 雙目 USB，UVC，2560×720 MJPG 左右併排）**沒有實作**：
鏡頭還沒到貨，沒有硬體可以對照，這裡不放假驅動。到貨後要做的事寫在 README「等硬體」一節。
目前唯一的來源是 `synthetic.SyntheticStereoSource`（合成畫面，`mock=True`）。

內參與基線目前都是**名目值、未校準**（`calibrated=False`）；數字與
`nous_duck/tools/stereo_geometry.py` 相同。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any, Protocol, runtime_checkable

import numpy as np

# ---- AR0144 名目規格（與 tools/stereo_geometry.py 相同；未校準） ----
AR0144_WIDTH_PX = 1280
AR0144_HEIGHT_PX = 720
AR0144_HFOV_DEG = 65.0
AR0144_BASELINE_M = 0.052


@dataclass(frozen=True)
class CameraModel:
    """針孔鏡頭內參（像素）。沒有畸變參數：校正後的影像才適用。"""

    fx: float
    fy: float
    cx: float
    cy: float
    width: int
    height: int
    #: False＝名目規格推算，不是量測。
    calibrated: bool = False

    @classmethod
    def from_hfov(cls, width: int, height: int, hfov_deg: float) -> "CameraModel":
        f = (width / 2) / math.tan(math.radians(hfov_deg) / 2)
        return cls(fx=f, fy=f, cx=width / 2, cy=height / 2, width=width, height=height)

    @classmethod
    def ar0144_nominal(cls, width: int = AR0144_WIDTH_PX, height: int = AR0144_HEIGHT_PX) -> "CameraModel":
        """AR0144 單眼的名目內參（未校準）。可以給縮小後的解析度（例如 640×360）。"""
        return cls.from_hfov(width, height, AR0144_HFOV_DEG)

    def scaled(self, width: int, height: int) -> "CameraModel":
        """影像縮放到 width×height 後的內參。"""
        sx, sy = width / self.width, height / self.height
        return replace(self, fx=self.fx * sx, fy=self.fy * sy, cx=self.cx * sx, cy=self.cy * sy, width=width, height=height)

    def ray_angles(self, u: float, v: float) -> tuple[float, float]:
        """像素相對光軸的（yaw, pitch）弧度；往左、往上為正。與 `look_at.CameraIntrinsics.ray_angles` 相同。"""
        return math.atan2(self.cx - u, self.fx), math.atan2(self.cy - v, self.fy)

    def project(self, p_cam: tuple[float, float, float]) -> tuple[float, float] | None:
        """鏡頭座標的點投影到像素；在鏡頭後方回傳 None。"""
        x, y, z = p_cam
        if z <= 1e-6:
            return None
        return self.cx + self.fx * x / z, self.cy + self.fy * y / z

    @property
    def hfov_rad(self) -> float:
        return 2 * math.atan((self.width / 2) / self.fx)

    @property
    def vfov_rad(self) -> float:
        return 2 * math.atan((self.height / 2) / self.fy)


@dataclass(frozen=True)
class StereoRig:
    """雙目外參（已校正成平行光軸、同一列對齊的理想情況）。

    `rectified=True` 表示影像已經做過立體校正：左右影像同一個點在同一列，視差只在水平方向。
    合成來源直接產生校正後的影像。真的鏡頭要先做雙目校正（V1），之前不能拿來量距離。
    """

    left: CameraModel
    right: CameraModel
    baseline_m: float
    rectified: bool
    calibrated: bool = False

    @classmethod
    def ar0144_nominal(cls, width: int = AR0144_WIDTH_PX, height: int = AR0144_HEIGHT_PX) -> "StereoRig":
        cam = CameraModel.ar0144_nominal(width, height)
        return cls(left=cam, right=cam, baseline_m=AR0144_BASELINE_M, rectified=True, calibrated=False)

    def disparity_px(self, z_m: float) -> float:
        return self.left.fx * self.baseline_m / z_m

    def depth_m(self, disparity_px: float) -> float | None:
        if disparity_px <= 0:
            return None
        return self.left.fx * self.baseline_m / disparity_px


@dataclass
class Frame:
    """一次擷取。影像是 BGR uint8（H×W×3），只存在記憶體裡。"""

    seq: int
    #: 拍攝時間（秒，來源自己的單調時鐘；合成來源用模擬時間）。
    t_capture: float
    left: np.ndarray
    #: 單眼來源為 None。
    right: np.ndarray | None
    #: True＝合成或模擬畫面，不是真的鏡頭。
    mock: bool
    #: 合成來源附的真值（測試用）；真的鏡頭沒有。
    truth: Any = None

    @property
    def is_stereo(self) -> bool:
        return self.right is not None


@runtime_checkable
class FrameSource(Protocol):
    """影像來源。單眼來源的 `rig` 為 None、`Frame.right` 為 None。"""

    #: 左眼（或單眼）的鏡頭模型。
    model: CameraModel
    rig: StereoRig | None
    #: True＝合成或模擬。
    mock: bool

    def read(self) -> Frame | None:
        """取下一張；暫時沒有新畫面回傳 None。來源壞掉（例如鏡頭被拔）要丟例外，不能回傳舊畫面。"""
        ...

    def close(self) -> None: ...
