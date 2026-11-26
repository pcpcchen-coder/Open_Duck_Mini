"""D1：鏡頭模型、合成來源。"""

import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from duck_perception.camera import AR0144_BASELINE_M, CameraModel, Frame, FrameSource, StereoRig
from duck_perception.synthetic import SyntheticPerson, SyntheticStereoSource, body_dir, body_to_cam

REPO = Path(__file__).resolve().parents[4]


def test_nominal_matches_stereo_geometry_tool():
    """名目內參與 tools/stereo_geometry.py 一致（f≈1005 px、2 m 視差 26 px）。"""
    sys.path.insert(0, str(REPO / "nous_duck" / "tools"))
    import stereo_geometry as sg

    cam = CameraModel.ar0144_nominal()
    assert cam.fx == pytest.approx(sg.focal_px())
    assert not cam.calibrated
    rig = StereoRig.ar0144_nominal()
    assert rig.baseline_m == sg.BASELINE_M == AR0144_BASELINE_M
    assert round(rig.disparity_px(2.0)) == 26
    assert rig.depth_m(rig.disparity_px(1.3)) == pytest.approx(1.3)
    assert rig.depth_m(0.0) is None
    assert math.degrees(cam.vfov_rad) == pytest.approx(sg.vfov_deg(sg.focal_px()), abs=1e-6)


def test_scaled_intrinsics_keep_angles():
    cam = CameraModel.ar0144_nominal()
    half = cam.scaled(640, 360)
    assert half.fx == pytest.approx(cam.fx / 2)
    a = cam.ray_angles(900, 200)
    b = half.ray_angles(450, 100)
    assert a == pytest.approx(b)


def test_ray_angle_signs_and_look_at_consistency():
    cam = CameraModel.ar0144_nominal()
    yaw, pitch = cam.ray_angles(cam.cx + 100, cam.cy - 50)
    assert yaw < 0 and pitch > 0  # 畫面右邊＝往右（負），上方＝往上（正）
    from duck_perception.closed_loop import intrinsics_for

    assert intrinsics_for(cam).ray_angles(321.0, 123.0) == pytest.approx(cam.ray_angles(321.0, 123.0))


def test_body_to_cam_axes():
    assert body_to_cam(body_dir(0, 0), 0, 0) == pytest.approx([0, 0, 1])
    left = body_to_cam(body_dir(0.2, 0), 0, 0)
    assert left[0] < 0  # 在左邊 → 鏡頭 X（往右）為負
    up = body_to_cam(body_dir(0, 0.2), 0, 0)
    assert up[1] < 0  # 在上方 → 鏡頭 Y（往下）為負
    # 視線對準目標時，目標在光軸上
    assert body_to_cam(body_dir(0.3, 0.4), 0.3, 0.4) == pytest.approx([0, 0, 1], abs=1e-12)


def test_synthetic_source_is_marked_mock_and_matches_protocol():
    src = SyntheticStereoSource(people=[SyntheticPerson(0.1, 0.05, 1.5)])
    assert isinstance(src, FrameSource)
    f = src.read()
    assert isinstance(f, Frame) and f.mock is True and src.mock is True
    assert f.left.shape == (360, 640, 3) and f.right.shape == f.left.shape and f.left.dtype == np.uint8
    assert f.is_stereo and f.seq == 1 and src.read().seq == 2
    mono = SyntheticStereoSource(people=[SyntheticPerson(0, 0, 1.0)], stereo=False)
    assert mono.read().right is None


def test_truth_projection_and_disparity():
    rig = StereoRig.ar0144_nominal(640, 360)
    src = SyntheticStereoSource(rig=rig, people=[SyntheticPerson(0.2, 0.1, 2.0)])
    ft = src.truth()[0]
    assert ft.u < rig.left.cx and ft.v < rig.left.cy  # 左上
    assert ft.yaw_cam == pytest.approx(0.2, abs=0.01)
    assert ft.disparity_px == pytest.approx(rig.left.fx * 0.052 / ft.distance_m)
    assert ft.width_px == pytest.approx(rig.left.fx * 0.15 / ft.distance_m)
    # 鏡頭轉向目標 → 目標在畫面正中央
    src.set_pose(0.0, 0.2, 0.1)
    ft = src.truth()[0]
    assert (ft.u, ft.v) == pytest.approx((rig.left.cx, rig.left.cy))
    assert ft.distance_m == pytest.approx(2.0)


def test_face_pixels_are_where_truth_says():
    """臉真的畫在真值的位置：左眼在 u、右眼在 u−視差。"""
    src = SyntheticStereoSource(people=[SyntheticPerson(0.0, 0.0, 1.0)], noise_sigma=0.0)
    f = src.read()
    ft = f.truth[0]
    bg = SyntheticStereoSource(people=[], noise_sigma=0.0).read()
    for img, ref, u in ((f.left, bg.left, ft.u), (f.right, bg.right, ft.u - ft.disparity_px)):
        diff = np.abs(img.astype(int) - ref.astype(int)).sum(axis=2) > 30
        xs = np.nonzero(diff.any(axis=0))[0]
        assert (xs.min() + xs.max()) / 2 == pytest.approx(u, abs=1.5)
        assert 0.8 * ft.width_px < xs.max() - xs.min() <= ft.width_px + 2


def test_reproducible_and_closed_source_raises():
    a = SyntheticStereoSource(people=[SyntheticPerson(0.1, 0, 1)], seed=3).read().left
    b = SyntheticStereoSource(people=[SyntheticPerson(0.1, 0, 1)], seed=3).read().left
    assert np.array_equal(a, b)
    src = SyntheticStereoSource()
    src.close()
    with pytest.raises(RuntimeError):
        src.read()


def test_perception_code_never_writes_images():
    """感知模組的原始碼裡沒有寫影像檔的呼叫（影像只在記憶體）。"""
    pkg = Path(__file__).resolve().parents[1] / "duck_perception"
    banned = ("imwrite", "VideoWriter", "np.save", "tofile(", "imencode")
    for py in pkg.glob("*.py"):
        text = py.read_text(encoding="utf-8")
        for b in banned:
            assert b not in text, f"{py.name} 不應該有 {b}"
