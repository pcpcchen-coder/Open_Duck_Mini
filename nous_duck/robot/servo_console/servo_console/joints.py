"""關節表：舵機 ID、中文名稱、範圍、上游的站姿。

- 關節名稱與 ID：上游 Open_Duck_Mini_Runtime（commit 376de65）mini_bdx_runtime/rustypot_position_hwi.py。
- 站姿 STANCE：同檔案的 HWI.init_pos（上游走路前的預備姿勢）。
- 範圍：上游 mini_bdx/robots/open_duck_mini_v2/robot.xml 的關節 range，由組裝檢視器 pipeline 匯出成
  console_joints.json（build_console.mjs 產生），伺服器啟動時讀入。

角度單位：關節空間（joint space）的 radian，跟上游 runtime 與 MuJoCo 一致：
舵機角度 = 關節角度 + 偏移（duck_config.json 的 joints_offsets）。
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class JointInfo:
    name: str
    servo_id: int
    zh: str
    group: str  # right_leg / left_leg / head
    lo: float  # rad，已扣掉安全邊界
    hi: float


# ID 順序
JOINT_TABLE: list[tuple[str, int, str, str]] = [
    ("right_hip_yaw", 10, "右髖・左右轉", "right_leg"),
    ("right_hip_roll", 11, "右髖・側擺", "right_leg"),
    ("right_hip_pitch", 12, "右髖・前後擺", "right_leg"),
    ("right_knee", 13, "右膝", "right_leg"),
    ("right_ankle", 14, "右踝", "right_leg"),
    ("left_hip_yaw", 20, "左髖・左右轉", "left_leg"),
    ("left_hip_roll", 21, "左髖・側擺", "left_leg"),
    ("left_hip_pitch", 22, "左髖・前後擺", "left_leg"),
    ("left_knee", 23, "左膝", "left_leg"),
    ("left_ankle", 24, "左踝", "left_leg"),
    ("neck_pitch", 30, "脖子・俯仰", "head"),
    ("head_pitch", 31, "頭・俯仰", "head"),
    ("head_yaw", 32, "頭・左右轉", "head"),
    ("head_roll", 33, "頭・側傾", "head"),
]

# 上游 HWI.init_pos（rad）
STANCE: dict[str, float] = {
    "left_hip_yaw": 0.002,
    "left_hip_roll": 0.053,
    "left_hip_pitch": -0.63,
    "left_knee": 1.368,
    "left_ankle": -0.784,
    "neck_pitch": 0.0,
    "head_pitch": 0.0,
    "head_yaw": 0.0,
    "head_roll": 0.0,
    "right_hip_yaw": -0.003,
    "right_hip_roll": -0.065,
    "right_hip_pitch": 0.635,
    "right_knee": 1.379,
    "right_ankle": -0.796,
}

ZERO: dict[str, float] = {name: 0.0 for name, *_ in JOINT_TABLE}

# robot.xml 的範圍往內縮 2°，避免頂到模擬模型的邊界
LIMIT_MARGIN_RAD = math.radians(2.0)


def load_joints(path: Path) -> list[JointInfo]:
    """讀 console_joints.json，回傳依 ID 排序的關節資訊。缺任何一個關節或範圍就報錯。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != "nous-duck/console-joints@1":
        raise ValueError(f"{path} 不是 console-joints@1")
    ranges = {j["name"]: j for j in data["joints"]}
    out: list[JointInfo] = []
    for name, servo_id, zh, group in JOINT_TABLE:
        j = ranges.get(name)
        if j is None or not j.get("range_rad"):
            raise ValueError(f"{path} 缺少 {name} 的範圍")
        if j.get("servo_id") != servo_id:
            raise ValueError(f"{name} 的舵機 ID 是 {j.get('servo_id')}，預期 {servo_id}")
        lo, hi = j["range_rad"]
        out.append(JointInfo(name, servo_id, zh, group, lo + LIMIT_MARGIN_RAD, hi - LIMIT_MARGIN_RAD))
    for name, value in STANCE.items():
        info = next(j for j in out if j.name == name)
        if not info.lo <= value <= info.hi:
            raise ValueError(f"上游站姿的 {name}={value} 超出範圍 {info.lo:.3f}～{info.hi:.3f}")
    return out
