"""BNO055 軸向修正（imu_mount）：不需要硬體，用假的 adafruit 模組。實機驗證見 tools/imu_tilt_check.py。"""
import types

import numpy as np
import pytest

from duckd.imu_mount import BODY_FROM_CHIP, adafruit_remap, mounted_imu_class

# adafruit_bno055 的常數（AXIS_REMAP_X=0x00、Y=0x01、Z=0x02、POSITIVE=0x00、NEGATIVE=0x01）
FAKE = types.SimpleNamespace(AXIS_REMAP_X=0, AXIS_REMAP_Y=1, AXIS_REMAP_Z=2, AXIS_REMAP_POSITIVE=0, AXIS_REMAP_NEGATIVE=1)


def remap_matrix(remap):
    """六元組 → 3×3 矩陣（輸出＝M @ 晶片）。"""
    m = np.zeros((3, 3))
    for out_axis in range(3):
        m[out_axis, remap[out_axis]] = -1.0 if remap[3 + out_axis] == FAKE.AXIS_REMAP_NEGATIVE else 1.0
    return m


UPSTREAM_NOT_UPSIDE_DOWN = (1, 0, 2, 1, 0, 0)  # 上游 raw_imu：(Y, X, Z, −, +, +)


def test_remap_is_a_proper_rotation():
    m = remap_matrix(adafruit_remap(FAKE))
    assert np.allclose(m @ m.T, np.eye(3))
    assert np.linalg.det(m) == pytest.approx(1.0)  # 右手座標，不是鏡像
    assert BODY_FROM_CHIP == ("X", "Y", "Z", -1, -1, +1)


def test_remap_explains_the_tilt_test():
    """2026-11-28 傾斜測試：用上游設定時，往前低頭 21.8° 讀到重力 y +3.63、往右傾 31.4° 讀到重力 x +5.10。

    用上游設定的矩陣把讀值換回晶片座標，再套我們的設定，應該得到機身座標下的預期值
    （往前低頭：重力 x ＝ −9.8·sin θ；往右傾：重力 y ＝ +9.8·sin φ）。
    """
    up = remap_matrix(UPSTREAM_NOT_UPSIDE_DOWN)
    ours = remap_matrix(adafruit_remap(FAKE))
    forward = ours @ up.T @ np.array([0.19, 3.63, 9.10])
    right = ours @ up.T @ np.array([5.10, -0.83, 8.33])
    assert forward[0] == pytest.approx(-9.8 * np.sin(np.radians(21.8)), abs=0.3)
    assert abs(forward[1]) < 0.4
    assert right[1] == pytest.approx(9.8 * np.sin(np.radians(31.4)), abs=0.3)
    assert abs(right[0]) < 1.0  # 那次往右傾時也帶到一點前後（讀值 0.83 m/s²，約 5°）


def make_fake_module():
    mod = types.SimpleNamespace(**vars(FAKE))

    class BNO055_I2C:  # noqa: N801 跟 adafruit 同名
        writes: list = []

        def __init__(self, i2c):
            self._remap = None

        @property
        def axis_remap(self):
            return self._remap

        @axis_remap.setter
        def axis_remap(self, value):
            BNO055_I2C.writes.append(value)
            self._remap = value

    mod.BNO055_I2C = BNO055_I2C
    return mod


def test_mounted_class_writes_our_remap_during_upstream_init():
    mod = make_fake_module()
    original = mod.BNO055_I2C

    class UpstreamImu:  # 跟上游 raw_imu.Imu 一樣：建立感測器、寫自己的軸向設定
        def __init__(self, freq, upside_down=True):
            self.imu = mod.BNO055_I2C(None)
            self.imu.axis_remap = UPSTREAM_NOT_UPSIDE_DOWN
            self.freq = freq

    imu = mounted_imu_class(UpstreamImu, mod)(50, upside_down=False)
    assert imu.freq == 50
    assert imu.imu.axis_remap == adafruit_remap(FAKE) == (0, 1, 2, 1, 1, 0)
    assert original.writes == [(0, 1, 2, 1, 1, 0)]  # 上游的值從來沒有寫進感測器
    assert mod.BNO055_I2C is original  # 建構完換回原本的類別
    assert isinstance(imu, UpstreamImu)


def test_module_restored_even_if_upstream_init_fails():
    mod = make_fake_module()
    original = mod.BNO055_I2C

    class Broken:
        def __init__(self, *a, **k):
            raise OSError("no IMU")

    with pytest.raises(OSError):
        mounted_imu_class(Broken, mod)(50)
    assert mod.BNO055_I2C is original
