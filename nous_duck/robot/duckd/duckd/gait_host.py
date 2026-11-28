"""步態 host（ADR-0009 §2.4）：不改上游，載入鎖定 commit 的 `scripts/v2_rl_walk_mujoco.py`，
把它的指令來源 `XBoxController` 換成仲裁器。

狀態：**只做到載入測試**（假的硬體介面，見 `gait_fakes.py`）。沒有連過真的舵機、沒有讓真的鴨子走路；
duckd 主程式也還沒有把 duck-link 的 `walk` 接到這裡（`capabilities.walk` 是 `unsupported`）。
實機走路要等足底開關、IMU 校準，而且要有人在場（ADR-0009 §5）。

做法：

1. 上游 runtime 以 git clone 放在鴨子上並 checkout 鎖定的 commit（`376de65`）；這裡用 importlib 從那個路徑
   載入腳本。**本 repo 不含上游 runtime 的任何程式碼**（上游沒有授權檔）。
2. 腳本載入後、建立 `RLWalk` 之前，把模組裡的 `XBoxController` 名稱換成 `ArbiterCommandSource` 的工廠。
   主迴圈完全照上游執行；工作目錄設成 `scripts/`，上游才讀得到 `./polynomial_coefficients.pkl`。
3. `ArbiterCommandSource.get_last_command()` 回傳和上游一樣的四元組（7 維指令、Buttons、左右扳機）。
   暫停直接設 `RLWalk.paused`，不模擬按 A 鍵；IMU 只讀 `imu.last_imu_data`，不呼叫 `get_data()`。

風險：依賴上游模組的內部名稱（`XBoxController`、`RLWalk`、`paused`、`imu.last_imu_data`、`feet_contacts`），
只對鎖定的 commit 成立；換 commit 要重跑載入測試。
"""
from __future__ import annotations

import importlib.util
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from .arbiter import SafetyArbiter

LOCKED_COMMIT = "376de65"
SCRIPT = Path("scripts") / "v2_rl_walk_mujoco.py"
REQUIRED_NAMES = ("RLWalk", "XBoxController")


class GaitHostError(RuntimeError):
    pass


def runtime_commit(runtime_dir: Path) -> str:
    try:
        out = subprocess.run(["git", "-C", str(runtime_dir), "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise GaitHostError(f"讀不到 {runtime_dir} 的 commit：{exc}") from exc
    return out.stdout.strip()


def check_locked_commit(runtime_dir: Path, locked: str = LOCKED_COMMIT) -> str:
    head = runtime_commit(runtime_dir)
    if not head.startswith(locked):
        raise GaitHostError(f"上游 runtime 是 {head[:7]}，不是鎖定的 {locked}；換 commit 要先重跑載入測試再改鎖定值")
    return head


def load_upstream_walk(script_path: Path, replacements: dict[str, object], module_name: str = "duckd_upstream_rl_walk"):
    """以 importlib 載入上游腳本（不執行它的 `__main__` 區塊），再換掉指定的模組層級名稱。"""
    script_path = Path(script_path)
    if not script_path.is_file():
        raise GaitHostError(f"找不到上游腳本：{script_path}")
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in (*REQUIRED_NAMES, *replacements):
        if not hasattr(module, name):
            raise GaitHostError(f"上游腳本裡沒有 {name}（commit 換了嗎？）")
    for name, obj in replacements.items():
        setattr(module, name, obj)
    return module


def tilt_from_accel(accel) -> float | None:
    """由加速度推算機身和重力方向的夾角（度）。**軸向與正負號還沒在實機確認。**"""
    try:
        ax, ay, az = (float(v) for v in accel)
    except (TypeError, ValueError):
        return None
    norm = math.sqrt(ax * ax + ay * ay + az * az)
    if norm < 1e-6:
        return None
    return math.degrees(math.acos(max(-1.0, min(1.0, az / norm))))


class ArbiterCommandSource:
    """取代上游的 `XBoxController`：每圈被主迴圈呼叫一次，只做便宜的運算。"""

    def __init__(self, arbiter: SafetyArbiter, buttons, clock: Callable[[], float] = time.monotonic, on_poll: Callable[[int], None] | None = None):
        self.arbiter = arbiter
        self.buttons = buttons  # 上游的 mini_bdx_runtime.buttons.Buttons 物件；沒有人按，永遠不觸發
        self.clock = clock
        self.on_poll = on_poll
        self.rl_walk = None
        self.polls = 0
        self._last: float | None = None
        self.last_output = None

    def bind(self, rl_walk) -> None:
        self.rl_walk = rl_walk

    def get_last_command(self):
        now = self.clock()
        dt = 0.02 if self._last is None else min(max(now - self._last, 0.0), 0.1)
        self._last = now
        self.polls += 1
        rl = self.rl_walk
        tilt = feet = None
        if rl is not None:
            imu = getattr(rl, "imu", None)
            data = getattr(imu, "last_imu_data", None)  # 只讀最新值，不呼叫 get_data()
            if isinstance(data, dict) and "accelero" in data:
                tilt = tilt_from_accel(data["accelero"])
            contacts = getattr(rl, "feet_contacts", None)
            if contacts is not None:
                left, right = contacts.get()
                feet = (bool(left), bool(right))
        self.arbiter.observe(now, tilt_deg=tilt, feet=feet)
        out = self.arbiter.update(now, dt)
        self.last_output = out
        if rl is not None:
            rl.paused = out.want_pause  # 直接設，不模擬按 A 鍵
        head = out.head or {}
        command = [
            out.velocity[0], out.velocity[1], out.velocity[2],
            head.get("neck_pitch", 0.0), head.get("head_pitch", 0.0), head.get("head_yaw", 0.0), head.get("head_roll", 0.0),
        ]
        if self.on_poll:
            self.on_poll(self.polls)
        return command, self.buttons, 0.0, 0.0


def build_rl_walk(runtime_dir: Path, onnx_model: Path, arbiter: SafetyArbiter, *, overrides: dict[str, object] | None = None,
                  duck_config: Path | None = None, clock: Callable[[], float] = time.monotonic, on_poll=None, check_commit: bool = True,
                  imu_mount: bool = True):
    """載入上游腳本並建立 `RLWalk`（指令來源已換成仲裁器）。回傳（rl_walk, source, module）。

    `overrides` 可以再換掉其他模組層級名稱——載入測試用它把 `HWI`、`Imu`、`FeetContacts` 換成假的。
    不給 `overrides` 就會用上游真的硬體介面：**建立 `RLWalk` 時上游就會開扭力並移到預備姿勢**。
    `imu_mount`（預設開）：用 `imu_mount.mounted_imu_class` 包住上游的 `Imu`，改寫成這隻鴨子的軸向對應
    （BNO055 裝轉了 90°；`overrides` 已經換掉 `Imu` 時不包）。
    """
    runtime_dir = Path(runtime_dir).expanduser()
    if check_commit:
        check_locked_commit(runtime_dir)
    from mini_bdx_runtime.buttons import Buttons  # 上游套件（pip install -e），不是本 repo 的程式

    source = ArbiterCommandSource(arbiter, Buttons(), clock=clock, on_poll=on_poll)
    scripts_dir = runtime_dir / "scripts"
    replacements = {"XBoxController": lambda *a, **k: source, **(overrides or {})}
    if str(scripts_dir) not in sys.path:
        sys.path.append(str(scripts_dir))
    module = load_upstream_walk(runtime_dir / SCRIPT, replacements)
    if imu_mount and "Imu" not in (overrides or {}):
        from .imu_mount import mounted_imu_class

        module.Imu = mounted_imu_class(module.Imu)
    cwd = os.getcwd()
    os.chdir(scripts_dir)  # 上游用相對路徑讀 ./polynomial_coefficients.pkl
    try:
        kwargs = {"commands": True}
        if duck_config is not None:
            kwargs["duck_config_path"] = str(duck_config)
        rl_walk = module.RLWalk(str(onnx_model), **kwargs)
    finally:
        os.chdir(cwd)
    source.bind(rl_walk)
    return rl_walk, source, module
