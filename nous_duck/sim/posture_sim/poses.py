"""蹲低／站立的關鍵姿勢（rad，關節順序與正負號同上游 runtime `376de65` 的 `init_pos`）。

- `STAND`：上游 runtime 的 `init_pos`（＝ `walk_sim.model.HOME_POSE`），也是舵機控制台的「站姿」。
- `CROUCH`：第一版的「坐下」＝原地蹲低。2026-11-28 在 MuJoCo 裡挑的：腳掌固定在原地、
  身體重心一直落在鞋底範圍內，所以**動作中任何時候停下來都站得住**（見 `sim.py` 與
  `docs/validation/posture-crouch-sim-2026-11-28.md`）。數字沒有實機驗證。
- 右腿的 hip_pitch 與左腿正負相反（上游關節軸的定義，`init_pos` 也是這樣）；膝、踝同號。
- 膝蓋 1.48 rad（84.8°）低於舵機控制台的上限 88°（上游 URDF 的 ±90° 再留 2°）。

`SIT3` 是使用者 2026-11-28 在舵機控制台存的姿勢「坐下3」（`~/duck/console_poses.json`），
只拿來在模擬裡對照「真的坐在地上」的情況，**不是**要上機的動作：模擬裡從它站不起來。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from walk_sim.model import HOME_POSE, POLICY_JOINTS

JOINTS = POLICY_JOINTS
STAND = dict(HOME_POSE)


def legs(hip_pitch: float, knee: float, ankle: float, base: dict | None = None) -> dict:
    """左右對稱的腿部姿勢：左腿用 (hip_pitch, knee, ankle)，右腿 hip_pitch 取負。"""
    p = dict(base or STAND)
    p["left_hip_pitch"], p["left_knee"], p["left_ankle"] = hip_pitch, knee, ankle
    p["right_hip_pitch"], p["right_knee"], p["right_ankle"] = -hip_pitch, knee, ankle
    return p


#: 蹲低時 head_pitch 設多少（rad），頭的俯仰角才會跟站姿差不多：`sim.head_level_offset()`
#: 在模擬裡二分搜尋得 0.506（測試會重算核對），取 0.5。身體前傾約 28°，頭抬回約 29°。
CROUCH_HEAD_PITCH = 0.5

CROUCH = {**legs(0.12, 1.48, -1.18), "head_pitch": CROUCH_HEAD_PITCH}
#: 頭不抬的版本（對照用）。
CROUCH_HEAD_DOWN = legs(0.12, 1.48, -1.18)

SIT3 = {
    "right_hip_yaw": -0.003,
    "right_hip_roll": -0.065,
    "right_hip_pitch": -0.2094,
    "right_knee": 1.5359,
    "right_ankle": 0.4102,
    "left_hip_yaw": 0.002,
    "left_hip_roll": 0.053,
    "left_hip_pitch": 0.2531,
    "left_knee": 1.5359,
    "left_ankle": 0.3578,
    "neck_pitch": -0.2793,
    "head_pitch": 0.3665,
    "head_yaw": 0.0,
    "head_roll": 0.0,
}


def as_array(pose: dict) -> np.ndarray:
    return np.array([pose[n] for n in JOINTS], dtype=float)


# --------------------------------------------------------------------------- duckd 用的姿勢檔
LEG_JOINTS = tuple(n for n in JOINTS if not n.startswith(("neck", "head")))
DUCKD_POSTURES = Path(__file__).resolve().parents[2] / "robot" / "duckd" / "duckd" / "postures" / "postures.json"


def duckd_postures() -> dict:
    """`robot/duckd/duckd/postures/postures.json` 的內容（只有腿；頭部補償第一版不用，見 ADR-0020 §2.3）。"""
    return {
        "schema": "nous-duck/postures@1",
        "source": "nous_duck/sim/posture_sim/poses.py（python -m posture_sim.poses 重新產生）",
        "verification": "simulation",
        "postures": {
            "stand": {"description": "上游 runtime init_pos", "legs": {n: STAND[n] for n in LEG_JOINTS}},
            "crouch": {"description": "原地蹲低（第一版「坐下」），模擬驗證", "legs": {n: CROUCH[n] for n in LEG_JOINTS}},
        },
    }


if __name__ == "__main__":
    DUCKD_POSTURES.write_text(json.dumps(duckd_postures(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"寫入 {DUCKD_POSTURES}")
