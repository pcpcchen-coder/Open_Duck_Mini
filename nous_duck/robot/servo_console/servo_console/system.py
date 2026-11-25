"""Pi 狀態、BNO055、足底開關、音效。都是「讀不到就回報讀不到」，不顯示假值。

- Pi 狀態：vcgencmd get_throttled、CPU 溫度、負載、記憶體。
- BNO055：照上游的接法（I2C、位址 0x28），用 adafruit_bno055 讀；I2C 只在「連線」時打開。
- 足底開關：上游 feet_contacts.py 的接法（GPIO 22 左、27 右，上拉，接 GND 算著地）。
  感測器沒接時腳位被上拉，**永遠讀成懸空**，畫面會註明。
- 音效：上游 runtime 附的 wav，用 aplay 播（ALSA default）。只能播清單裡的檔案。
"""
from __future__ import annotations

import math
import os
import random
import subprocess
import threading
import time
from pathlib import Path

THROTTLED_BITS = {
    0: "目前電壓不足",
    1: "目前 ARM 頻率受限",
    2: "目前降頻中",
    3: "目前達到溫度軟上限",
    16: "開機以來曾經電壓不足",
    17: "開機以來曾經頻率受限",
    18: "開機以來曾經降頻",
    19: "開機以來曾經達到溫度軟上限",
}


def decode_throttled(value: int) -> list[str]:
    return [text for bit, text in THROTTLED_BITS.items() if value & (1 << bit)]


def pi_status() -> dict:
    out: dict = {}
    try:
        raw = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=2).stdout
        value = int(raw.strip().split("=")[1], 16)
        out["throttled"] = f"0x{value:x}"
        out["throttled_flags"] = decode_throttled(value)
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        out["throttled"] = None
    try:
        out["cpu_temp_c"] = round(int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000, 1)
    except (OSError, ValueError):
        out["cpu_temp_c"] = None
    try:
        out["load"] = [round(x, 2) for x in os.getloadavg()]
    except OSError:
        out["load"] = None
    try:
        info = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines() if ":" in line)
        total = int(info["MemTotal"].split()[0])
        avail = int(info["MemAvailable"].split()[0])
        out["mem_used_mb"] = round((total - avail) / 1024)
        out["mem_total_mb"] = round(total / 1024)
    except (OSError, KeyError, ValueError):
        out["mem_used_mb"] = out["mem_total_mb"] = None
    try:
        out["uptime_s"] = int(float(Path("/proc/uptime").read_text().split()[0]))
    except (OSError, ValueError):
        out["uptime_s"] = None
    return out


class Sensors:
    """BNO055 與足底開關。open() 在背景執行緒以約 20 Hz 讀取；close() 釋放 I2C 與 GPIO。"""

    def __init__(self, mock: bool = False):
        self.mock = mock
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.imu: dict = {"ok": False, "error": "沒有連線"}
        self.feet: dict = {"ok": False, "error": "沒有連線"}
        self._bno = None
        self._i2c = None
        self._feet_pins = None

    def open(self) -> None:
        if self._thread:
            return
        self._stop.clear()
        if not self.mock:
            self._open_hw()
        self._thread = threading.Thread(target=self._run, name="sensors", daemon=True)
        self._thread.start()

    def _open_hw(self) -> None:
        try:
            import adafruit_bno055
            import board
            import busio

            self._i2c = busio.I2C(board.SCL, board.SDA)
            self._bno = adafruit_bno055.BNO055_I2C(self._i2c)  # 位址 0x28，跟上游一樣
        except Exception as exc:  # noqa: BLE001
            self._bno = None
            with self._lock:
                self.imu = {"ok": False, "error": f"BNO055 打不開：{exc}"}
        try:
            import board
            import digitalio

            pins = []
            for pin in (board.D22, board.D27):
                d = digitalio.DigitalInOut(pin)
                d.direction = digitalio.Direction.INPUT
                d.pull = digitalio.Pull.UP
                pins.append(d)
            self._feet_pins = pins
        except Exception as exc:  # noqa: BLE001
            self._feet_pins = None
            with self._lock:
                self.feet = {"ok": False, "error": f"GPIO 打不開：{exc}"}

    def _run(self) -> None:
        t0 = time.monotonic()
        while not self._stop.is_set():
            if self.mock:
                t = time.monotonic() - t0
                with self._lock:
                    self.imu = {
                        "ok": True,
                        "mock": True,
                        "euler_deg": [round(5 * math.sin(t / 3), 1), round(2 * math.sin(t / 2), 1), round(3 * math.cos(t / 4), 1)],
                        "accel": [round(random.uniform(-0.1, 0.1), 2), round(random.uniform(-0.1, 0.1), 2), 9.8],
                        "gyro": [0.0, 0.0, 0.0],
                        "calibration": [3, 3, 3, 3],
                        "temperature_c": None,
                    }
                    self.feet = {"ok": True, "mock": True, "left": False, "right": False}
            else:
                self._read_hw()
            self._stop.wait(0.05)

    def _read_hw(self) -> None:
        if self._bno is not None:
            try:
                euler = self._bno.euler
                imu = {
                    "ok": True,
                    "euler_deg": [None if v is None else round(v, 1) for v in euler],
                    "accel": [None if v is None else round(v, 2) for v in self._bno.acceleration],
                    "gyro": [None if v is None else round(v, 3) for v in self._bno.gyro],
                    "calibration": list(self._bno.calibration_status),
                    "temperature_c": self._bno.temperature,
                }
            except Exception as exc:  # noqa: BLE001
                imu = {"ok": False, "error": f"BNO055 讀取失敗：{exc}"}
            with self._lock:
                self.imu = imu
        if self._feet_pins is not None:
            try:
                left, right = (not p.value for p in self._feet_pins)
                feet = {"ok": True, "left": left, "right": right}
            except Exception as exc:  # noqa: BLE001
                feet = {"ok": False, "error": f"GPIO 讀取失敗：{exc}"}
            with self._lock:
                self.feet = feet

    def close(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        self._thread = None
        for p in self._feet_pins or []:
            try:
                p.deinit()
            except Exception:  # noqa: BLE001
                pass
        self._feet_pins = None
        if self._i2c is not None:
            try:
                self._i2c.deinit()
            except Exception:  # noqa: BLE001
                pass
        self._i2c = self._bno = None
        with self._lock:
            self.imu = {"ok": False, "error": "沒有連線"}
            self.feet = {"ok": False, "error": "沒有連線"}

    def snapshot(self) -> dict:
        with self._lock:
            return {"imu": dict(self.imu), "feet": dict(self.feet)}


class SoundPlayer:
    def __init__(self, assets_dir: Path | None, mock: bool = False):
        self.assets_dir = Path(assets_dir) if assets_dir else None
        self.mock = mock
        self._proc: subprocess.Popen | None = None

    def names(self) -> list[str]:
        if self.mock:
            return ["happy1", "beep1"]
        if not self.assets_dir or not self.assets_dir.is_dir():
            return []
        return sorted(p.stem for p in self.assets_dir.glob("*.wav"))

    def play(self, name: str) -> None:
        if name not in self.names():
            raise ValueError(f"沒有這個音效：{name}")
        if self.mock:
            return
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
        self._proc = subprocess.Popen(["aplay", "-q", str(self.assets_dir / f"{name}.wav")])
