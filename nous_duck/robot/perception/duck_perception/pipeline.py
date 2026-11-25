"""D2 每張影像的處理：偵測 → 方位（＋雙目距離）→ 選人與平滑 → 送 UDP `face`。

影像只在這個函式的區域變數裡，處理完就放掉：不寫檔、不放進 log、不送出。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .camera import Frame, FrameSource
from .face_detect import FaceDetection
from .link import UdpTargetSender
from .stereo_depth import face_stereo_depth
from .target import FaceBearing, FaceTargetTracker, TargetObservation, mono_distance_m, to_bearing


class Detector(Protocol):
    def detect(self, image_bgr) -> list[FaceDetection]: ...


@dataclass(frozen=True)
class FrameResult:
    seq: int
    t_capture: float
    detections: tuple[FaceDetection, ...]
    bearings: tuple[FaceBearing, ...]
    target: TargetObservation | None
    mock: bool


class FacePipeline:
    def __init__(
        self,
        source: FrameSource,
        detector: Detector,
        tracker: FaceTargetTracker | None = None,
        sender: UdpTargetSender | None = None,
        #: 沒有雙目距離時，要不要用名目臉寬估距離（誤差大；預設不要，寧可回報不知道）。
        allow_mono_distance: bool = False,
    ) -> None:
        self.source = source
        self.detector = detector
        self.tracker = tracker or FaceTargetTracker()
        self.sender = sender
        self.allow_mono_distance = allow_mono_distance

    def process(self, frame: Frame, sound_yaw_cam: float | None = None, gaze_delta: tuple[float, float] = (0.0, 0.0)) -> FrameResult:
        cam = self.source.model
        dets = self.detector.detect(frame.left)
        bearings = []
        for d in dets:
            dist, src = None, None
            if frame.right is not None and self.source.rig is not None:
                sd = face_stereo_depth(frame.left, frame.right, d, self.source.rig)
                if sd.range_m is not None:
                    dist, src = sd.range_m, "stereo"
            if dist is None and self.allow_mono_distance:
                dist = mono_distance_m(d.width_px, cam)
                src = "mono_face_width"
            bearings.append(to_bearing(d, cam, dist, src))
        target = self.tracker.update(frame.t_capture, bearings, sound_yaw_cam=sound_yaw_cam, gaze_delta=gaze_delta)
        if target is not None and self.sender is not None:
            self.sender.send(
                "face",
                target.bearing_yaw_rad,
                target.bearing_pitch_rad,
                target.distance_m,
                target.confidence,
                int(round(target.t_capture * 1000)),
                mock=bool(frame.mock),
            )
        return FrameResult(frame.seq, frame.t_capture, tuple(dets), tuple(bearings), target, bool(frame.mock))
