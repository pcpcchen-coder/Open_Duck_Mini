"""這隻鴨子的 BNO055 裝法：比上游的設計轉了 90°，用 BNO055 的軸向對應（axis remap）在軟體修正。

背景（`docs/validation/bno055-i2c-2026-11-28.md` §6，2026-11-28 傾斜測試）：用上游的軸向設定
（`imu_upside_down: false` → 輸出 x＝−晶片 Y、y＝晶片 X、z＝晶片 Z）讀到的座標，比機身座標
（x 往前、y 往左、z 往上，上游 MuJoCo 模型與步態策略用的）繞 z 軸轉了 90°：往前低頭被讀成左右傾。
使用者確認小板裝轉了 90°，已經裝好不好拆，所以改軟體。

修正後的對應：機身 x＝−晶片 X、機身 y＝−晶片 Y、機身 z＝晶片 Z（繞 z 轉 180°，右手座標）。
這是從一次傾斜測試推出來的；`tools/imu_tilt_check.py` 在實機上重測。

**不改上游**：上游 `raw_imu.Imu`／`imu.Imu` 在建構時用 `adafruit_bno055.BNO055_I2C(i2c)` 建立感測器、
接著寫自己的軸向設定，最後開一條執行緒不停讀 I2C（一直占著 I2C 鎖，建構完之後再寫會搶不到鎖，
2026-11-28 實機卡住）。所以這裡在上游建構的期間，暫時把 `adafruit_bno055.BNO055_I2C` 換成子類別：
它的 `axis_remap` setter 不管上游給什麼，都寫我們的設定。建構完就換回原本的類別。
步態 host 用 `mounted_imu_class()` 取代上游腳本裡的 `Imu` 名稱。
"""
from __future__ import annotations

#: 晶片軸 → 機身軸：(機身 x 取哪一軸, 機身 y, 機身 z, x 正負, y 正負, z 正負)
BODY_FROM_CHIP: tuple[str, str, str, int, int, int] = ("X", "Y", "Z", -1, -1, +1)


def adafruit_remap(bno055_module) -> tuple:
    """換成 `adafruit_bno055` 的 `axis_remap` 六元組。"""
    m = bno055_module
    axis = {"X": m.AXIS_REMAP_X, "Y": m.AXIS_REMAP_Y, "Z": m.AXIS_REMAP_Z}
    sign = {+1: m.AXIS_REMAP_POSITIVE, -1: m.AXIS_REMAP_NEGATIVE}
    x, y, z, sx, sy, sz = BODY_FROM_CHIP
    return (axis[x], axis[y], axis[z], sign[sx], sign[sy], sign[sz])


def mounted_imu_class(upstream_imu_cls, bno055_module=None):
    """包住上游的 `Imu` 類別：上游寫軸向設定的那一刻改寫成這隻鴨子的。`bno055_module` 給測試用。"""
    if bno055_module is None:
        import adafruit_bno055 as bno055_module  # 只在鴨子上有
    remap = adafruit_remap(bno055_module)

    class MountedImu(upstream_imu_cls):
        nous_duck_mount = BODY_FROM_CHIP

        def __init__(self, *args, **kwargs):
            orig = bno055_module.BNO055_I2C
            prop = orig.axis_remap

            class _MountedBNO055(orig):
                axis_remap = property(prop.fget, lambda dev, _upstream_value: prop.fset(dev, remap))

            bno055_module.BNO055_I2C = _MountedBNO055
            try:
                super().__init__(*args, **kwargs)
            finally:
                bno055_module.BNO055_I2C = orig
            self.nous_duck_remap = remap

    MountedImu.__name__ = f"Mounted{upstream_imu_cls.__name__}"
    return MountedImu
