"""D4：合成雙目影像（已知真值）的估距。"""

import dataclasses
import math

import numpy as np
import pytest

from duck_perception.camera import StereoRig
from duck_perception.stereo_depth import depth_sigma_m, face_stereo_depth
from duck_perception.synthetic import SyntheticPerson, SyntheticStereoSource, TruthDetector


def measure(z, rig=None, yaw=0.05, pitch=0.03, noise=2.0, seed=0, **kw):
    rig = rig or StereoRig.ar0144_nominal(640, 360)
    src = SyntheticStereoSource(rig=rig, people=[SyntheticPerson(yaw, pitch, z, seed=seed)], noise_sigma=noise, seed=seed)
    f = src.read()
    det = TruthDetector(src).detect()[0]
    return face_stereo_depth(f.left, f.right, det, rig, **kw), f.truth[0]


@pytest.mark.parametrize("z", [0.5, 0.8, 1.0, 1.5, 2.0, 3.0])
def test_depth_matches_truth_within_one_pixel_step(z):
    rig = StereoRig.ar0144_nominal(640, 360)
    sd, ft = measure(z)
    assert sd.reason is None
    assert sd.disparity_px == pytest.approx(ft.disparity_px, abs=0.5)
    assert abs(sd.depth_m - ft.distance_m) < depth_sigma_m(ft.distance_m, rig, 0.5) + 1e-3
    assert sd.range_m == pytest.approx(ft.range_m, rel=0.08)


def test_error_grows_roughly_with_distance_squared():
    rig = StereoRig.ar0144_nominal(640, 360)
    assert depth_sigma_m(2.0, rig, 1.0) / depth_sigma_m(1.0, rig, 1.0) == pytest.approx(4.0)
    # 與 tools/stereo_geometry.py：640 寬、2 m、1 px ≈ 153 mm
    assert round(depth_sigma_m(2.0, rig, 1.0) * 1000) == 153


def test_returns_none_with_reason_when_cannot_match():
    rig = StereoRig.ar0144_nominal(640, 360)
    src = SyntheticStereoSource(rig=rig, people=[SyntheticPerson(0.05, 0.0, 1.0)])
    f = src.read()
    det = TruthDetector(src).detect()[0]
    assert face_stereo_depth(f.left, None, det, rig).reason == "no_stereo"
    assert face_stereo_depth(f.left, f.right, det, None).reason == "no_stereo"
    assert face_stereo_depth(f.left, f.right, det, dataclasses.replace(rig, rectified=False)).reason == "not_rectified"
    # 右眼被遮住（全黑＋雜訊）→ 配不到，回傳 None，不猜
    blocked = np.random.default_rng(0).integers(0, 12, f.right.shape).astype(np.uint8)
    sd = face_stereo_depth(f.left, blocked, det, rig)
    assert sd.depth_m is None and sd.range_m is None and sd.reason in ("no_match", "ambiguous")
    # 右眼畫面沒有這個人（只有背景）→ None
    bg = SyntheticStereoSource(rig=rig, people=[]).read()
    assert face_stereo_depth(f.left, bg.right, det, rig).depth_m is None
    # 臉太小
    small = dataclasses.replace(det, width_px=8, height_px=10)
    assert face_stereo_depth(f.left, f.right, small, rig).reason == "face_too_small"
    # 臉貼在畫面邊緣
    edge = dataclasses.replace(det, u=5.0)
    assert face_stereo_depth(f.left, f.right, edge, rig).reason == "face_at_edge"


def test_too_close_for_search_range_returns_none():
    # 0.4 m 的視差（640 寬）約 65 px；只搜尋 32 px 就配不到
    sd, ft = measure(0.4, yaw=0.0, pitch=0.0, max_disparity_px=32)
    assert ft.disparity_px > 32 and sd.depth_m is None


def test_noise_statistics_small_bias():
    errs = []
    for seed in range(12):
        sd, ft = measure(1.5, noise=4.0, seed=seed, yaw=0.02 * (seed - 6))
        assert sd.reason is None
        errs.append(sd.depth_m - ft.distance_m)
    assert abs(float(np.mean(errs))) < 0.03 and float(np.std(errs)) < 0.05
