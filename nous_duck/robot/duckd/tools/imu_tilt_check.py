"""實機：用上游 `raw_imu.Imu`（走路程式用的）＋這隻鴨子的軸向修正（`duckd.imu_mount`），記錄重力與陀螺儀。

給「往前低頭、往右傾」的傾斜測試用：修正對的話，往前低頭時重力 x 變負、往右傾時重力 y 變正。
會寫 BNO055 的模式、軸向對應與校正偏移（和上游走路程式建構 IMU 時一樣），**不碰舵機**。

    cd ~/duck/Open_Duck_Mini_Runtime/scripts     # 上游從這裡讀 imu_calib_data.pkl
    PYTHONPATH=<放 duckd 套件的資料夾> ~/duck/runtime-venv/bin/python imu_tilt_check.py 75
"""
import sys
import time

import numpy as np
from mini_bdx_runtime.raw_imu import Imu  # 上游套件，不是本 repo

from duckd.imu_mount import mounted_imu_class

seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
imu = mounted_imu_class(Imu)(50, upside_down=False)
print("remap", imu.nous_duck_remap, "readback", imu.imu.axis_remap, flush=True)
time.sleep(1.0)
t0 = time.time()
print("START", time.strftime("%H:%M:%S"), flush=True)
while time.time() - t0 < seconds:
    d = imu.get_data()
    print(time.strftime("%H:%M:%S"), "grav", tuple(round(v, 2) for v in imu.imu.gravity),
          "gyro", np.round(np.asarray(d["gyro"]), 2).tolist(), flush=True)
    time.sleep(0.5)
