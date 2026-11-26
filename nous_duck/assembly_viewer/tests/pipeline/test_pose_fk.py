"""驗證舵機控制台 3D 擺姿勢的做法（console/pose_viewer.ts）：

用 scene.json 的 body 樹、關節位置與轉軸（零位世界座標、檢視器座標），以 product of exponentials
算每個 body 在任意關節角度下的位置與方向，和 MuJoCo 的正向運動學比對。
pose_viewer.ts 用同一個公式（平移(p)·旋轉(軸, q)·平移(−p)，由根往下相乘）。
"""
import numpy as np
import pytest

from viewer_pipeline.geometry import MUJOCO_TO_VIEWER
from viewer_pipeline.scene import ROBOT_DIR


def _rot(axis, q):
    axis = np.asarray(axis, float) / np.linalg.norm(axis)
    k = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    return np.eye(3) + np.sin(q) * k + (1 - np.cos(q)) * k @ k


def _poe(scene, qpos):
    """回傳每個 body 的 (R, t)：零位世界座標 → 目前世界座標（檢視器座標，mm）。"""
    bodies = {b["name"]: b for b in scene["bodies"]}
    joints = {j["name"]: j for j in scene["joints"]}
    out = {}

    def tf(name):
        if name in out:
            return out[name]
        b = bodies[name]
        R, t = (np.eye(3), np.zeros(3)) if b["parent"] is None else tf(b["parent"])
        if b["joint"]:
            j = joints[b["joint"]]
            p = np.array(j["position_mm"])
            Rl = _rot(j["axis"], qpos.get(j["name"], 0.0))
            tl = p - Rl @ p
            R, t = R @ Rl, R @ tl + t
        out[name] = (R, t)
        return out[name]

    for name in bodies:
        tf(name)
    return out


def test_pose_matches_mujoco(repo_root, scene):
    mujoco = pytest.importorskip("mujoco")
    model = mujoco.MjModel.from_xml_path(str(repo_root / ROBOT_DIR / "robot.xml"))
    data = mujoco.MjData(model)
    rv = MUJOCO_TO_VIEWER

    mujoco.mj_forward(model, data)
    names = [mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, i) for i in range(model.nbody)]
    zero_pos = {n: rv @ data.xpos[i] * 1000.0 for i, n in enumerate(names)}
    zero_rot = {n: rv @ data.xmat[i].reshape(3, 3) for i, n in enumerate(names)}
    # 檢視器座標有平移（腳底 Y=0、外框置中）：用零位的關節點算出來
    j0 = scene["joints"][0]
    jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, j0["name"])
    shift = np.array(j0["position_mm"]) - rv @ data.xanchor[jid] * 1000.0

    rng = np.random.default_rng(7)
    worst_pos = worst_ang = 0.0
    for _ in range(20):
        qpos = {}
        for j in scene["joints"]:
            lo, hi = j["range_rad"]
            q = float(rng.uniform(lo, hi))
            qpos[j["name"]] = q
            data.qpos[model.jnt_qposadr[mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, j["name"])]] = q
        mujoco.mj_forward(model, data)
        ours = _poe(scene, qpos)
        for i, n in enumerate(names):
            if n == "world":
                continue
            R, t = ours[n]
            p_ours = R @ (zero_pos[n] + shift) + t
            p_mj = rv @ data.xpos[i] * 1000.0 + shift
            worst_pos = max(worst_pos, float(np.linalg.norm(p_ours - p_mj)))
            R_mj = rv @ data.xmat[i].reshape(3, 3)
            R_ours = R @ zero_rot[n]
            cos = (np.trace(R_ours.T @ R_mj) - 1) / 2
            worst_ang = max(worst_ang, float(np.degrees(np.arccos(np.clip(cos, -1, 1)))))
    assert worst_pos < 1e-3, f"位置最大誤差 {worst_pos} mm"
    assert worst_ang < 1e-4, f"方向最大誤差 {worst_ang}°"
