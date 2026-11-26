"""C4：定位（AprilTag＋短程里程，不用步數）。驗證層級：單元測試（幾何合成的 mock 觀測）。"""

import inspect
import math

import numpy as np

from duck_nav.geometry import Pose2D, wrap
from duck_nav.localization import Localizer
from duck_nav.mock_sensors import MockCameraConfig, MockTagCamera
from duck_nav.testing import make_kinematic_loop
from duck_nav.types import SensorFrame, TagObservation


def test_no_step_count_anywhere():
    """定位的輸入只有速度、陀螺儀與標籤觀測；沒有步數。"""
    params = set(inspect.signature(Localizer.predict).parameters)
    assert params == {"self", "dt", "vx", "vy", "yaw_rate", "gyro"}
    assert not any("step_count" in f or "steps" in f for f in SensorFrame.__dataclass_fields__)


def test_uncertainty_grows_without_tags_and_reports_not_localized(home):
    loc = Localizer(home)
    loc.set_pose(Pose2D(1.0, 1.5, 0.0), 0.02, 0.03)
    assert loc.localized and loc.confident
    sig = []
    for i in range(50 * 60):  # 走 60 秒、沒有標籤
        loc.predict(0.02, 0.115, 0.01, 0.0, gyro=True)
        if i % 250 == 0:
            sig.append(loc.pos_sigma)
    assert all(b > a for a, b in zip(sig, sig[1:]))  # 一直變大
    assert not loc.confident
    assert not loc.localized  # 超過「未定位」門檻
    assert loc.since_tag_s > 59


def test_standing_still_does_not_blow_up(home):
    loc = Localizer(home)
    loc.set_pose(Pose2D(1.0, 1.5, 0.0), 0.02, 0.03)
    for _ in range(50 * 120):
        loc.predict(0.02, 0.0, 0.0, 0.0, gyro=True)
    assert loc.localized


def test_mock_camera_respects_fov_range_and_occlusion(home):
    cam = MockTagCamera(home, MockCameraConfig(dropout=0.0), seed=0)
    # 在客廳面向東牆：看得到標籤 1；面向西邊看不到。
    ids = {o.tag_id for o in cam.observe(Pose2D(2.0, 1.3, 0.0))}
    assert 1 in ids
    assert all(o.mock for o in cam.observe(Pose2D(2.0, 1.3, 0.0)))
    assert 1 not in {o.tag_id for o in cam.observe(Pose2D(2.0, 1.3, math.pi))}
    # 轉頭就看得到旁邊的標籤。
    assert 2 not in {o.tag_id for o in cam.observe(Pose2D(1.8, 1.0, 0.0))}
    assert 2 in {o.tag_id for o in cam.observe(Pose2D(1.8, 1.0, -math.pi / 2 + 0.5), head_yaw=-0.5)}
    # 隔著牆看不到別的房間的標籤（9 在哥哥房間北牆）。
    assert 9 not in {o.tag_id for o in cam.observe(Pose2D(2.8, 3.5, math.pi / 2))}
    # 太遠（標籤太小）看不到：從走廊西端看東邊 3.8 m 外的標籤 6。
    assert 6 not in {o.tag_id for o in cam.observe(Pose2D(0.8, 3.3, 0.0))}
    # 額外的遮擋物。
    cam.extra_boxes = [((2.9, 1.0, 3.0, 1.6), 1.0)]
    assert 1 not in {o.tag_id for o in cam.observe(Pose2D(2.0, 1.3, 0.0))}


def test_converges_to_truth_from_tag_observations(home):
    truth = Pose2D(2.0, 1.3, 0.1)
    cam = MockTagCamera(home, seed=3)
    loc = Localizer(home)
    assert not loc.initialized
    for _ in range(40):
        loc.predict(0.1, 0.0, 0.0, 0.0, gyro=True)
        loc.update(cam.observe(truth))
    assert loc.confident
    p = loc.pose
    assert math.hypot(p.x - truth.x, p.y - truth.y) < 0.05
    assert abs(wrap(p.yaw - truth.yaw)) < 0.04
    assert loc.pos_sigma < 0.05


def test_single_wrong_detection_is_rejected(home):
    loc = Localizer(home)
    loc.set_pose(Pose2D(2.0, 1.3, 0.0), 0.02, 0.03)
    before = loc.pose
    # 一筆離譜的觀測（把標籤 1 看成在 0.5 m 處、方向也錯）。
    assert loc.update([TagObservation(1, 0.5, 0.4, 1.0, 0.01, 0.02)]) == 0
    assert loc.pose == before
    assert loc.rejects == 1
    # 未知的標籤 ID 直接忽略。
    assert loc.update([TagObservation(400, 1.0, 0.0, 3.1, 0.01, 0.02)]) == 0


def test_kidnapped_relocalizes(home):
    """被抱到別的房間：舊的估計跟觀測對不上，連續幾次後重新定位。"""
    cam = MockTagCamera(home, MockCameraConfig(dropout=0.0), seed=1)
    loc = Localizer(home)
    loc.set_pose(Pose2D(2.0, 1.3, 0.0), 0.02, 0.03)
    truth = Pose2D(2.6, 5.0, math.pi / 2)  # 哥哥房間，面向北牆的標籤 9
    used = 0
    for _ in range(30):
        loc.predict(0.1, 0.0, 0.0, 0.0, gyro=True)
        obs = cam.observe(truth)
        assert obs, "這個位置應該看得到標籤"
        used += loc.update(obs)
    assert loc.reinit_count == 1
    p = loc.pose
    assert math.hypot(p.x - truth.x, p.y - truth.y) < 0.15
    assert home.room_at(p.x, p.y) == "brother_room"


def test_tracks_while_walking_in_closed_loop(home):
    """閉迴路（運動學 mock）：走一趟的過程中，估計位置跟真實位置的差距有上限。"""
    errs = []
    for seed in range(4):
        loop = make_kinematic_loop(home, seed=seed)
        loop.nav.go_to("study_room")
        r = loop.run_until_idle()
        assert r.last("mission_done") is not None, r.last("mission_failed")
        errs.append(r.max_est_err_m)
    assert max(errs) < 0.25, errs
    assert float(np.mean(errs)) < 0.18


def test_gyro_missing_still_works_but_less_certain(home):
    a, b = Localizer(home), Localizer(home)
    for loc, gyro in ((a, True), (b, False)):
        loc.set_pose(Pose2D(1.0, 1.5, 0.0), 0.02, 0.03)
        for _ in range(250):
            loc.predict(0.02, 0.0, 0.03, 0.85, gyro=gyro)
    assert b.yaw_sigma > a.yaw_sigma * 2
