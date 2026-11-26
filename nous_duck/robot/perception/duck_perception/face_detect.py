"""D2 人臉偵測：YuNet（OpenCV `FaceDetectorYN`）的薄包裝。

模型：`face_detection_yunet_2023mar.onnx`（OpenCV Zoo，MIT），與 AIOS 相同；用
`tools/fetch_models.py` 下載並核對 SHA-256，不進版控。

輸出只有位置、大小與分數：**不輸出影像、不算特徵、不做身分辨識**。
驗證層級：只在合成示意臉上做過煙霧測試；對真人的偵測率、最小像素、暗處表現都**沒有量過**。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

DEFAULT_MODEL = Path(__file__).resolve().parents[1] / "models" / "face_detection_yunet_2023mar.onnx"


@dataclass(frozen=True)
class FaceDetection:
    """一個人臉偵測結果（像素；只有位置與大小）。"""

    u: float  # 框中心
    v: float
    width_px: float
    height_px: float
    score: float


class ModelMissing(RuntimeError):
    """模型檔不存在：照實報錯，不退回假偵測。"""


class YuNetDetector:
    def __init__(
        self,
        input_size: tuple[int, int],
        model_path: Path | str = DEFAULT_MODEL,
        score_threshold: float = 0.6,  # 未校準：沿用 OpenCV 範例附近的值
        nms_threshold: float = 0.3,
        top_k: int = 50,
    ) -> None:
        import cv2  # 延後匯入：控制鏈的其他部分不需要 OpenCV

        path = Path(model_path)
        if not path.exists():
            raise ModelMissing(f"找不到 {path}；先執行 tools/fetch_models.py")
        self.input_size = input_size
        self._det = cv2.FaceDetectorYN.create(str(path), "", input_size, score_threshold, nms_threshold, top_k)

    def detect(self, image_bgr: np.ndarray) -> list[FaceDetection]:
        h, w = image_bgr.shape[:2]
        if (w, h) != self.input_size:
            raise ValueError(f"影像大小 {(w, h)} 與偵測器輸入 {self.input_size} 不同；先縮放影像並用 CameraModel.scaled()")
        _, faces = self._det.detect(image_bgr)
        if faces is None:
            return []
        out = []
        for r in faces:
            x, y, bw, bh = (float(v) for v in r[:4])
            out.append(FaceDetection(u=x + bw / 2, v=y + bh / 2, width_px=bw, height_px=bh, score=float(r[14])))
        return out
