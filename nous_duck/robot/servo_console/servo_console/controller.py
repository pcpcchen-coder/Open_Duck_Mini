"""控制核心：連線、讀值、平滑移動、安全規則、偏移與姿勢。

全部規則在伺服器端執行，瀏覽器只送「目標」。主要安全規則：

- 目標角度一律夾在 robot.xml 的關節範圍內（往內縮 2°）。
- 目標不會直接寫給舵機：控制迴圈以「最高速度」（預設 30°/s）一步步逼近。
- 開扭力前先把目標設成舵機目前的位置，開扭力的瞬間不會跳。
- 緊急停止：全部關扭力並鎖住；沒連線時也會臨時開序列埠關扭力。要按「解除」才能再開扭力。
- 溫度、電壓超過門檻：自動緊急停止（門檻是暫定值，見下方常數）。
- 連續讀取失敗：停止移動（維持目前指令）並警告。
- 瀏覽器超過 2 秒沒有回應：停止移動，維持目前姿勢（不關扭力，避免懸空時摔下來）。

角度：對外與對內都用關節空間的 radian（跟上游 runtime、MuJoCo 一致）；
寫給舵機時換成舵機角度（degree）= degrees(關節角度 + 偏移)。
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .bus import BusError
from .joints import STANCE, ZERO, JointInfo

# 暫定門檻：沒有實機依據，只是保守的起點（見 README）
TEMP_WARN_C = 55
TEMP_STOP_C = 65
VOLT_WARN_V = 6.6  # 2S 鋰電每顆 3.3 V
VOLT_STOP_V = 6.0  # 每顆 3.0 V
READ_FAIL_LIMIT = 5
HEARTBEAT_S = 2.0
STATUS_PERIOD_S = 0.5
SPEED_CHOICES_DEG = (15, 30, 60, 90)
DEFAULT_SPEED_DEG = 30
KP_CHOICES = (2, 8, 16, 32)
OFFSET_STEP_MAX_DEG = 2.0
OFFSET_ABS_MAX_DEG = 20.0

BUILTIN_POSES: dict[str, tuple[str, dict[str, float]]] = {
    "zero": ("零點（全部 0°）", ZERO),
    "stance": ("站姿（上游 init_pos）", STANCE),
}
POSE_NAME = re.compile(r"^[\w\-一-鿿 ]{1,30}$")


class CommandError(Exception):
    """使用者的指令不能執行（狀態不允許或參數不對）。訊息直接給使用者看。"""


@dataclass
class Joint:
    info: JointInfo
    actual: float | None = None  # 關節角度（rad），舵機回讀扣掉偏移
    target: float | None = None  # 使用者要的角度
    cmd: float | None = None  # 目前寫給舵機的角度（往 target 逼近）
    torque: bool | None = None
    temperature: int | None = None
    voltage: float | None = None
    load: float | None = None
    kp: int | None = None


def scan_port_users(paths: list[str]) -> list[tuple[int, str]]:
    """找出其他正在開這些裝置的程序（讀 /proc/*/fd）。只在 Linux 有效，其他系統回傳空清單。"""
    real = {os.path.realpath(p) for p in paths if os.path.exists(p)}
    users: list[tuple[int, str]] = []
    proc = Path("/proc")
    if not real or not proc.exists():
        return users
    me = os.getpid()
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) == me:
            continue
        try:
            for fd in (entry / "fd").iterdir():
                if os.path.realpath(fd) in real:
                    cmd = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
                    users.append((int(entry.name), cmd[:120]))
                    break
        except (PermissionError, FileNotFoundError, ProcessLookupError):
            continue
    return users


class Controller:
    def __init__(
        self,
        joints: list[JointInfo],
        bus_factory: Callable[[], object],
        config_path: Path,
        poses_path: Path,
        clock: Callable[[], float] = time.monotonic,
        port_users: Callable[[], list[tuple[int, str]]] = lambda: [],
        mock: bool = False,
    ):
        self.joints: dict[str, Joint] = {j.name: Joint(j) for j in joints}
        self.ids = [j.servo_id for j in joints]
        self.name_of = {j.servo_id: j.name for j in joints}
        self.bus_factory = bus_factory
        self.bus = None
        self.config_path = Path(config_path)
        self.poses_path = Path(poses_path)
        self.clock = clock
        self.port_users = port_users
        self.mock = mock
        self.lock = threading.RLock()
        self.speed = math.radians(DEFAULT_SPEED_DEG)
        self.estop_reason: str | None = None
        self.alarms: dict[str, tuple[str, str]] = {}  # key -> (level, message)
        self.events: deque = deque(maxlen=200)
        self.fail_count = 0
        self.last_status = -math.inf
        self.last_tick: float | None = None
        self.last_client = clock()
        self.heartbeat_frozen = False
        self.offsets: dict[str, float] = {}
        self.offsets_saved: dict[str, float] = {}
        self._load_offsets()

    # ------------------------------------------------------------------ 共用
    def log(self, level: str, message: str) -> None:
        self.events.append({"t": time.time(), "level": level, "message": message})

    @property
    def connected(self) -> bool:
        return self.bus is not None

    def _require_connected(self) -> None:
        if not self.connected:
            raise CommandError("還沒連線匯流排")

    def _require_no_estop(self) -> None:
        if self.estop_reason:
            raise CommandError(f"緊急停止中（{self.estop_reason}），先按「解除緊急停止」")

    def _joint(self, name: str) -> Joint:
        if name not in self.joints:
            raise CommandError(f"沒有這個關節：{name}")
        return self.joints[name]

    def _servo_deg(self, name: str, joint_rad: float) -> float:
        return math.degrees(joint_rad + self.offsets.get(name, 0.0))

    def _joint_rad(self, name: str, servo_deg: float) -> float:
        return math.radians(servo_deg) - self.offsets.get(name, 0.0)

    def client_seen(self) -> None:
        with self.lock:
            self.last_client = self.clock()
            if self.heartbeat_frozen:
                self.heartbeat_frozen = False

    # ------------------------------------------------------------------ 偏移
    def _load_offsets(self) -> None:
        offsets = {name: 0.0 for name in self.joints}
        try:
            config = json.loads(self.config_path.read_text(encoding="utf-8"))
            for name, value in config.get("joints_offsets", {}).items():
                if name in offsets:
                    offsets[name] = float(value)
            self.log("info", f"讀取偏移：{self.config_path}")
        except FileNotFoundError:
            self.log("warn", f"找不到 {self.config_path}，偏移全部當 0")
        except (ValueError, json.JSONDecodeError) as exc:
            self.log("warn", f"{self.config_path} 讀不了（{exc}），偏移全部當 0")
        self.offsets = offsets
        self.offsets_saved = dict(offsets)

    def adjust_offset(self, name: str, delta_deg: float) -> None:
        with self.lock:
            j = self._joint(name)
            if not math.isfinite(delta_deg) or abs(delta_deg) > OFFSET_STEP_MAX_DEG:
                raise CommandError(f"每次最多調 ±{OFFSET_STEP_MAX_DEG}°")
            new = self.offsets[name] + math.radians(delta_deg)
            if abs(math.degrees(new)) > OFFSET_ABS_MAX_DEG:
                raise CommandError(f"偏移不能超過 ±{OFFSET_ABS_MAX_DEG}°（可能是舵盤裝錯一齒）")
            self.offsets[name] = new
            # 關節角度不變、偏移變了：出力中的舵機會轉 delta 度
            if self.connected and j.torque and j.cmd is not None:
                self._write({j.info.servo_id: self._servo_deg(name, j.cmd)})
            self.log("info", f"ID {j.info.servo_id} 偏移調 {delta_deg:+.1f}° → {math.degrees(new):+.2f}°（還沒存檔）")

    def save_offsets(self) -> str:
        with self.lock:
            if self.config_path.exists():
                backup = self.config_path.with_name(f"{self.config_path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
                shutil.copy2(self.config_path, backup)
                config = json.loads(self.config_path.read_text(encoding="utf-8"))
            else:
                backup = None
                config = {}
            target = config.setdefault("joints_offsets", {})
            changed = []
            for name, value in self.offsets.items():
                rounded = round(value, 4)
                if target.get(name) != rounded:
                    changed.append(name)
                target[name] = rounded
            tmp = self.config_path.with_name(self.config_path.name + ".tmp")
            tmp.write_text(json.dumps(config, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(tmp, self.config_path)
            # 檔案存的是四捨五入到 0.0001 rad 的值；記憶體裡也換成一樣的值（差 < 0.003°）
            self.offsets = {n: round(v, 4) for n, v in self.offsets.items()}
            self.offsets_saved = dict(self.offsets)
            note = f"，備份 {backup.name}" if backup else ""
            self.log("info", f"偏移已寫入 {self.config_path.name}（改了 {len(changed)} 個{note}）")
            return backup.name if backup else ""

    def reload_offsets(self) -> None:
        with self.lock:
            self._load_offsets()
            for name, j in self.joints.items():
                if self.connected and j.torque and j.cmd is not None:
                    self._write({j.info.servo_id: self._servo_deg(name, j.cmd)})

    # ------------------------------------------------------------------ 連線
    def connect(self) -> None:
        with self.lock:
            if self.connected:
                return
            users = self.port_users()
            if users:
                who = "；".join(f"PID {pid} {cmd}" for pid, cmd in users)
                raise CommandError(f"序列埠／I2C／GPIO 正被其他程式使用：{who}。先停掉它（例如上游的走路程式）再連線")
            bus = self.bus_factory()
            try:
                bus.open()
                found = bus.ping(self.ids)
                missing = [i for i in self.ids if i not in found]
                if missing:
                    raise CommandError(f"沒有回應的舵機 ID：{missing}（舵機電源有開嗎？）")
                positions = bus.read_positions(self.ids)
                status = bus.read_status(self.ids)
                kps = bus.read_kp(self.ids)
            except BusError as exc:
                bus.close()
                raise CommandError(f"連線失敗：{exc}") from exc
            except CommandError:
                bus.close()
                raise
            except Exception as exc:  # 例如序列埠打不開
                try:
                    bus.close()
                finally:
                    raise CommandError(f"連線失敗：{exc}") from exc
            self.bus = bus
            for i, servo_id in enumerate(self.ids):
                j = self.joints[self.name_of[servo_id]]
                j.actual = self._joint_rad(j.info.name, positions[i])
                j.cmd = j.target = j.actual
                j.kp = kps[i]
            self._apply_status(status)
            self.fail_count = 0
            self.last_status = self.clock()
            self.last_tick = None
            on = sum(1 for j in self.joints.values() if j.torque)
            self.log("info", f"已連線：14 顆都回應，{on} 顆出力中" + ("（模擬匯流排）" if self.mock else ""))

    def release(self) -> None:
        with self.lock:
            if not self.connected:
                return
            on = sum(1 for j in self.joints.values() if j.torque)
            try:
                self.bus.close()
            finally:
                self.bus = None
            for j in self.joints.values():
                j.target = j.cmd
            self.alarms.pop("comm", None)
            self.log("info", f"已釋放序列埠。扭力狀態不變（{on} 顆出力中）")

    # ------------------------------------------------------------------ 緊急停止
    def estop(self, reason: str = "使用者按下緊急停止") -> None:
        with self.lock:
            self.estop_reason = reason
            ok = self._torque_off_all()
            self.log("error", f"緊急停止：{reason}" + ("" if ok else "（關扭力失敗，請直接關舵機電源）"))

    def _torque_off_all(self) -> bool:
        try:
            if self.connected:
                self.bus.set_torque(self.ids, False)
            else:
                bus = self.bus_factory()
                bus.open()
                try:
                    bus.set_torque(self.ids, False)
                finally:
                    bus.close()
        except Exception as exc:  # noqa: BLE001 安全優先：記下來，不中斷
            self.log("error", f"關扭力失敗：{exc}")
            return False
        for j in self.joints.values():
            j.torque = False
            j.target = j.cmd = j.actual
        return True

    def reset_estop(self) -> None:
        with self.lock:
            stops = [msg for level, msg in self.alarms.values() if level == "stop"]
            if stops:
                raise CommandError("還有停止等級的警報：" + "；".join(stops))
            if self.estop_reason:
                self.log("info", f"解除緊急停止（原因：{self.estop_reason}）。扭力維持關閉")
            self.estop_reason = None

    # ------------------------------------------------------------------ 指令
    def set_torque(self, names: list[str], on: bool) -> None:
        with self.lock:
            self._require_connected()
            if on:
                self._require_no_estop()
            joints = [self._joint(n) for n in names]
            ids = [j.info.servo_id for j in joints]
            try:
                if on:
                    # 先讀目前位置、把目標設成目前位置，開扭力的瞬間才不會跳
                    positions = self.bus.read_positions(ids)
                    self.bus.write_goals(dict(zip(ids, positions)))
                    for j, pos in zip(joints, positions):
                        j.actual = self._joint_rad(j.info.name, pos)
                        j.cmd = j.target = j.actual
                    self.bus.set_torque(ids, True)
                else:
                    self.bus.set_torque(ids, False)
            except BusError as exc:
                raise CommandError(f"設定扭力失敗：{exc}") from exc
            for j in joints:
                j.torque = on
                if not on:
                    j.target = j.cmd = j.actual
            label = "全部" if len(ids) == len(self.ids) else "ID " + "、".join(map(str, ids))
            self.log("info", f"{label} {'出力' if on else '放鬆'}")

    def set_targets(self, targets: dict[str, float]) -> list[str]:
        """設定目標（rad）。回傳提示（被夾住或跳過的關節）。"""
        with self.lock:
            self._require_connected()
            self._require_no_estop()
            if "comm" in self.alarms:
                raise CommandError("匯流排讀取一直失敗，先檢查連線")
            notes = []
            for name, value in targets.items():
                j = self._joint(name)
                if not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise CommandError(f"{name} 的角度不是數字")
                if not j.torque:
                    notes.append(f"ID {j.info.servo_id} 沒有出力，略過")
                    continue
                clamped = min(max(float(value), j.info.lo), j.info.hi)
                if clamped != value:
                    notes.append(f"ID {j.info.servo_id} 超出範圍，夾到 {math.degrees(clamped):.1f}°")
                j.target = clamped
            self.heartbeat_frozen = False
            return notes

    def hold(self) -> None:
        with self.lock:
            for j in self.joints.values():
                j.target = j.cmd
            self.log("info", "停止移動，維持目前姿勢")

    def set_speed(self, deg_s: float) -> None:
        with self.lock:
            if deg_s not in SPEED_CHOICES_DEG:
                raise CommandError(f"速度只能是 {SPEED_CHOICES_DEG} °/s")
            self.speed = math.radians(deg_s)
            self.log("info", f"最高速度 {deg_s}°/s")

    def set_kp(self, names: list[str], kp: int) -> None:
        with self.lock:
            self._require_connected()
            if kp not in KP_CHOICES:
                raise CommandError(f"kp 只能是 {KP_CHOICES}")
            joints = [self._joint(n) for n in names]
            try:
                self.bus.set_kp({j.info.servo_id: kp for j in joints})
            except BusError as exc:
                raise CommandError(f"設定 kp 失敗：{exc}") from exc
            for j in joints:
                j.kp = kp
            label = "全部" if len(joints) == len(self.ids) else "ID " + "、".join(str(j.info.servo_id) for j in joints)
            self.log("info", f"{label} kp 設為 {kp}")

    # ------------------------------------------------------------------ 姿勢
    def _read_poses(self) -> dict[str, dict[str, float]]:
        try:
            data = json.loads(self.poses_path.read_text(encoding="utf-8"))
            return {k: v for k, v in data.get("poses", {}).items() if isinstance(v, dict)}
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            return {}

    def poses(self) -> list[dict]:
        out = [{"key": k, "label": label, "builtin": True} for k, (label, _) in BUILTIN_POSES.items()]
        out += [{"key": f"user:{k}", "label": k, "builtin": False} for k in sorted(self._read_poses())]
        return out

    def apply_pose(self, key: str) -> list[str]:
        if key in BUILTIN_POSES:
            pose = BUILTIN_POSES[key][1]
        elif key.startswith("user:") and key[5:] in self._read_poses():
            pose = self._read_poses()[key[5:]]
        else:
            raise CommandError(f"沒有這個姿勢：{key}")
        notes = self.set_targets({k: float(v) for k, v in pose.items() if k in self.joints})
        self.log("info", f"套用姿勢：{key}")
        return notes

    def save_pose(self, name: str) -> None:
        name = name.strip()
        if not POSE_NAME.match(name):
            raise CommandError("姿勢名稱 1–30 字，只能用中英文、數字、空白、- 和 _")
        with self.lock:
            pose = {}
            for n, j in self.joints.items():
                value = j.target if j.target is not None else j.actual
                if value is None:
                    raise CommandError("還沒讀到全部關節的角度")
                pose[n] = round(value, 4)
            poses = self._read_poses()
            poses[name] = pose
            self._write_poses(poses)
            self.log("info", f"儲存姿勢：{name}")

    def delete_pose(self, name: str) -> None:
        with self.lock:
            poses = self._read_poses()
            if poses.pop(name, None) is None:
                raise CommandError(f"沒有這個姿勢：{name}")
            self._write_poses(poses)
            self.log("info", f"刪除姿勢：{name}")

    def _write_poses(self, poses: dict) -> None:
        self.poses_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.poses_path.with_name(self.poses_path.name + ".tmp")
        tmp.write_text(json.dumps({"schema": "nous-duck/console-poses@1", "poses": poses}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, self.poses_path)

    # ------------------------------------------------------------------ 控制迴圈
    def _write(self, goals: dict[int, float]) -> None:
        try:
            self.bus.write_goals(goals)
        except BusError as exc:
            self._read_failed(f"寫入失敗：{exc}")

    def _read_failed(self, why: str) -> None:
        self.fail_count += 1
        if self.fail_count >= READ_FAIL_LIMIT and "comm" not in self.alarms:
            self.alarms["comm"] = ("warn", f"匯流排連續 {self.fail_count} 次失敗（{why}），停止移動")
            for j in self.joints.values():
                j.target = j.cmd
            self.log("error", self.alarms["comm"][1])

    def _apply_status(self, status: dict[str, list]) -> None:
        for i, servo_id in enumerate(self.ids):
            j = self.joints[self.name_of[servo_id]]
            j.temperature = status["temperature"][i]
            j.voltage = status["voltage"][i]
            j.load = status["load"][i]
            j.torque = status["torque"][i]
        self._check_limits()

    def _set_alarm(self, key: str, level: str | None, message: str = "") -> None:
        if level is None:
            if self.alarms.pop(key, None):
                self.log("info", f"警報解除：{key}")
            return
        if self.alarms.get(key) != (level, message):
            self.alarms[key] = (level, message)
            self.log("error" if level == "stop" else "warn", message)

    def _check_limits(self) -> None:
        temps = [(j.temperature, j.info.servo_id) for j in self.joints.values() if j.temperature is not None]
        if temps:
            t, sid = max(temps)
            if t >= TEMP_STOP_C:
                self._set_alarm("temp", "stop", f"ID {sid} 溫度 {t} °C ≥ {TEMP_STOP_C} °C")
            elif t >= TEMP_WARN_C:
                self._set_alarm("temp", "warn", f"ID {sid} 溫度 {t} °C ≥ {TEMP_WARN_C} °C")
            else:
                self._set_alarm("temp", None)
        volts = [(j.voltage, j.info.servo_id) for j in self.joints.values() if j.voltage]
        if volts:
            v, sid = min(volts)
            if v < VOLT_STOP_V:
                self._set_alarm("volt", "stop", f"ID {sid} 電壓 {v:.1f} V < {VOLT_STOP_V} V（電池快沒電）")
            elif v < VOLT_WARN_V:
                self._set_alarm("volt", "warn", f"ID {sid} 電壓 {v:.1f} V < {VOLT_WARN_V} V")
            else:
                self._set_alarm("volt", None)
        stops = [msg for level, msg in self.alarms.values() if level == "stop"]
        if stops and not self.estop_reason:
            self.estop("自動：" + "；".join(stops))

    def tick(self) -> None:
        with self.lock:
            if not self.connected:
                return
            now = self.clock()
            dt = 0.02 if self.last_tick is None else min(max(now - self.last_tick, 0.0), 0.1)
            self.last_tick = now
            try:
                positions = self.bus.read_positions(self.ids)
            except BusError as exc:
                self._read_failed(str(exc))
                return
            self.fail_count = 0
            if "comm" in self.alarms:
                self._set_alarm("comm", None)
            for i, servo_id in enumerate(self.ids):
                j = self.joints[self.name_of[servo_id]]
                j.actual = self._joint_rad(j.info.name, positions[i])

            if now - self.last_status >= STATUS_PERIOD_S:
                self.last_status = now
                try:
                    self._apply_status(self.bus.read_status(self.ids))
                except BusError as exc:
                    self._read_failed(str(exc))

            if now - self.last_client > HEARTBEAT_S and not self.heartbeat_frozen:
                moving = [j for j in self.joints.values() if j.torque and j.target != j.cmd]
                if moving:
                    for j in moving:
                        j.target = j.cmd
                    self.log("warn", f"瀏覽器超過 {HEARTBEAT_S:.0f} 秒沒有回應，停止移動（維持目前姿勢）")
                self.heartbeat_frozen = True

            goals = {}
            step = self.speed * dt
            for name, j in self.joints.items():
                if not j.torque or self.estop_reason:
                    j.target = j.cmd = j.actual
                    continue
                if j.cmd is None or j.target is None:
                    continue
                diff = j.target - j.cmd
                if abs(diff) < 1e-6:
                    continue
                j.cmd += max(-step, min(step, diff))
                goals[j.info.servo_id] = self._servo_deg(name, j.cmd)
            if goals:
                self._write(goals)

    # ------------------------------------------------------------------ 狀態
    def snapshot(self) -> dict:
        def deg(v):
            return None if v is None else round(math.degrees(v), 2)

        with self.lock:
            joints = []
            for name, j in self.joints.items():
                joints.append(
                    {
                        "name": name,
                        "id": j.info.servo_id,
                        "zh": j.info.zh,
                        "group": j.info.group,
                        "lo_deg": deg(j.info.lo),
                        "hi_deg": deg(j.info.hi),
                        "actual_deg": deg(j.actual),
                        "target_deg": deg(j.target),
                        "cmd_deg": deg(j.cmd),
                        "torque": j.torque,
                        "temperature": j.temperature,
                        "voltage": j.voltage,
                        "load": None if j.load is None else round(j.load, 1),
                        "kp": j.kp,
                        "offset_deg": round(math.degrees(self.offsets[name]), 3),
                        "offset_saved_deg": round(math.degrees(self.offsets_saved.get(name, 0.0)), 3),
                    }
                )
            return {
                "mock": self.mock,
                "connected": self.connected,
                "estop": self.estop_reason,
                "alarms": [{"key": k, "level": lv, "message": m} for k, (lv, m) in self.alarms.items()],
                "speed_deg": round(math.degrees(self.speed)),
                "speed_choices": list(SPEED_CHOICES_DEG),
                "kp_choices": list(KP_CHOICES),
                "offsets_dirty": any(abs(self.offsets[n] - self.offsets_saved.get(n, 0.0)) > 1e-6 for n in self.offsets),
                "config_path": str(self.config_path),
                "joints": joints,
                "poses": self.poses(),
                "limits": {
                    "temp_warn_c": TEMP_WARN_C,
                    "temp_stop_c": TEMP_STOP_C,
                    "volt_warn_v": VOLT_WARN_V,
                    "volt_stop_v": VOLT_STOP_V,
                    "heartbeat_s": HEARTBEAT_S,
                },
                "events": list(self.events)[-60:],
            }
