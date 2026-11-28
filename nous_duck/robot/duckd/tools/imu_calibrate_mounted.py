"""用這隻鴨子的軸向修正（duckd.imu_mount）跑上游的校正流程：raw_imu.Imu(calibrate=True)，存 imu_calib_data.pkl。

上游的 scripts/calibrate_imu.py 會用上游的軸向校正，偏移量會跟著存錯座標；重校請用這個。
會寫 BNO055 的模式與偏移量，**不碰舵機**。四項都到 3 才存檔並結束（上游的行為）。

    cd ~/duck/Open_Duck_Mini_Runtime/scripts     # 存在這裡，上游走路程式才讀得到
    PYTHONPATH=<放 duckd 套件的資料夾> ~/duck/runtime-venv/bin/python imu_calibrate_mounted.py
"""
from mini_bdx_runtime.raw_imu import Imu
from duckd.imu_mount import mounted_imu_class
mounted_imu_class(Imu)(50, calibrate=True, upside_down=False)
