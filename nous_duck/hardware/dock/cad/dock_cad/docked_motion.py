"""鴨子坐在充電座上時，頭、頸、天線可以動多少（幾何與靜力層級）。

問題：充電時鴨子還要能對話、轉頭、做表情（ADR-0018）。頭頸會不會撞到椅背、屋頂？
頭往前伸時重心會不會跑出腳底、把背後的觸點拉開？

作法（只唯讀上游 `robot.xml`）：

1. 腿固定在 `home` 站姿（與 `duck.py` 相同），只改頭頸 4 軸與天線 2 軸，用 MuJoCo 正向運動學算每個網格的位置。
2. 頭頸天線網格的頂點＋表面取樣點，和充電座全部零件的表面取樣點算最近距離（KD-tree）；
   距離很近的點再用 `contains` 判斷是否穿進去。
3. 全身重心（上游 `inertial` 的質量，總重約 2.06 kg）投影到地面，和兩腳 TPU 底面的凸包比較。
4. 頂針彈簧把鴨子往前推：靜力平衡時壓力中心往前移 F·h／W，從重心餘裕裡扣掉。

限制（誠實標示）：

- 鴨子是剛體、腿完全不動；**沒有**模擬舵機的彈性與背隙造成的身體晃動，那要實機量。
- 質量只有上游 CAD 的值；Pi 4、AR0144、麥克風陣列、觸點板都還沒算進去（ADR-0005 §2.4 的待辦）。
- 頂針彈力是參數（買到零件後改），不是量測值。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from itertools import product

import numpy as np
import trimesh
from scipy.spatial import ConvexHull, cKDTree

from .duck import HOME_POSE, ROBOT_DIR, default_repo_root, load_duck
from .fit import load_fit

G = 9.81

#: 頭頸天線的關節（MuJoCo 名稱 → 舵機 ID；天線是 9g 小舵機，沒有匯流排 ID）。
HEAD_JOINTS = ("neck_pitch", "head_pitch", "head_yaw", "head_roll")
ANTENNA_JOINTS = ("left_antenna", "right_antenna")
SERVO_ID = {"neck_pitch": 30, "head_pitch": 31, "head_yaw": 32, "head_roll": 33}

#: 上游 runtime 手把對頭頸的指令範圍（`mini_bdx_runtime/xbox_controller.py`，v2 commit 376de65；
#: 見 docs/architecture.md §4）。站著走路時上游自己就只用這個範圍，所以拿它當起點。
RUNTIME_RANGE = {
    "neck_pitch": (-0.34, 1.1),
    "head_pitch": (-0.78, 0.3),
    "head_yaw": (-0.5, 0.5),
    "head_roll": (-0.5, 0.5),
}

#: 坐在充電座上時，頭頸到充電座任何零件至少要留的距離（mm）。
#: 吸收列印公差、身體晃動與 V 形座 ±15 mm 調整；數字是建議值，實機後再定。
MIN_CLEARANCE_MM = 15.0

#: 重心投影到腳底凸包邊緣至少要留的距離（mm，已扣掉頂針推力造成的壓力中心位移）。
MIN_COM_MARGIN_MM = 15.0

#: 頂針彈力：4 支 × 每支 0.6 N（常見 pogo pin 壓縮到行程中段約 50–80 gf）。**參數，不是量測值**。
PIN_COUNT = 4
#: 取樣解析度（mm）：最近距離小於這個值就當成碰到。
SAMPLE_RES_MM = 5.0
#: 最近距離只算到這裡為止（超過就記成這個值），加快 KD-tree 查詢。
FAR_MM = 30.0
PIN_FORCE_N = 0.6


#: `summary()` 算出來的結果（2026-11-26，上游 robot.xml、本檔的門檻與頂針參數）。
#: robot/ 之後的設定要用這組數字；改了模型、門檻或充電座參數，要重跑 `python -m dock_cad.docked_motion`
#: 並更新這裡，測試會檢查它仍然成立。單位 rad。
DOCKED_HEAD_LIMITS = {
    "neck_pitch": (-0.34, 0.08),
    "head_pitch": (-0.78, 0.3),
    "head_yaw": (-0.5, 0.5),
    "head_roll": (-0.5, 0.5),
}
#: 頭頸在上面範圍內任何位置時，天線可用的範圍（往後擺會碰椅背，所以往後是 0）。
DOCKED_ANTENNA_LIMITS = {"left_antenna": (-1.571, 0.0), "right_antenna": (0.0, 1.571)}


@dataclass(frozen=True)
class PoseCheck:
    pose: dict[str, float]
    clearance_mm: float  # 頭頸天線到充電座的最近距離（取樣點之間）
    collides: bool  # 最近距離小於取樣解析度＝碰到或穿進去
    com_xy_mm: tuple[float, float]  # 充電座座標
    com_margin_mm: float  # 重心到腳底凸包邊緣（正＝在裡面），未扣頂針推力
    com_margin_with_pins_mm: float  # 扣掉頂針推力造成的壓力中心前移之後

    @property
    def ok(self) -> bool:
        return (not self.collides) and self.clearance_mm >= MIN_CLEARANCE_MM and self.com_margin_with_pins_mm >= MIN_COM_MARGIN_MM


@dataclass
class _Model:
    m: object
    d: object
    moving_bodies: list[int]
    #: 每個要檢查的網格：(geom id, 局部座標的點 (N,3) m)
    local_points: list[tuple[int, np.ndarray]]
    world_to_dock: np.ndarray  # mm
    total_mass: float
    moving_mass: float


def _descendants(m, root: int) -> list[int]:
    out = []
    for i in range(m.nbody):
        p = i
        while p > 0:
            if p == root:
                out.append(i)
                break
            p = m.body_parentid[p]
    return out


@lru_cache(maxsize=1)
def _model() -> _Model:
    import mujoco

    m = mujoco.MjModel.from_xml_path(str(default_repo_root() / ROBOT_DIR / "robot.xml"))
    d = mujoco.MjData(m)
    moving = _descendants(m, m.body("neck_pitch_assembly").id)
    pts = []
    for gi in range(m.ngeom):
        if m.geom_bodyid[gi] not in moving or m.geom_type[gi] != mujoco.mjtGeom.mjGEOM_MESH:
            continue
        mid = m.geom_dataid[gi]
        vadr, vnum = m.mesh_vertadr[mid], m.mesh_vertnum[mid]
        fadr, fnum = m.mesh_faceadr[mid], m.mesh_facenum[mid]
        v = m.mesh_vert[vadr : vadr + vnum].astype(float)
        f = m.mesh_face[fadr : fadr + fnum]
        tm = trimesh.Trimesh(v * 1000.0, f, process=False)
        n = int(max(200, tm.area / 9.0))  # 約 3 mm 間距（上游網格頂點很密，只用表面取樣點）
        s, _ = trimesh.sample.sample_surface(tm, n, seed=0)
        pts.append((gi, s / 1000.0))
    total = float(m.body_mass.sum())
    moving_mass = float(m.body_mass[moving].sum())
    return _Model(m, d, moving, pts, load_duck().world_to_dock.astype(float), total, moving_mass)


@lru_cache(maxsize=1)
def _dock_surface() -> tuple[cKDTree, dict[str, trimesh.Trimesh]]:
    meshes = load_fit().dock_meshes
    samples = []
    for mesh in meshes.values():
        n = int(max(500, mesh.area / 2.25))  # 約 1.5 mm 間距
        s, _ = trimesh.sample.sample_surface(mesh, n, seed=1)
        samples.append(np.vstack([mesh.vertices, s]))
    return cKDTree(np.vstack(samples)), meshes


@lru_cache(maxsize=1)
def support_polygon() -> np.ndarray:
    """兩腳 TPU 鞋底的外形投影到地面後的凸包（充電座座標，mm，逆時針）。

    上游 `home` 姿態在軀幹水平時，鞋底前高後低約 1.5°（只有腳尖碰地）。實際站在地上時鞋底會貼平、
    軀幹往後仰約 1.5°；這裡假設鞋底貼平，取鞋底最低 5 mm 內的頂點當腳印（TPU 鞋底厚約 14 mm）。
    """
    pts = []
    for p in load_duck().parts:
        if p.name == "foot_bottom_tpu":
            zmin = p.vertices[:, 2].min()
            pts.append(p.vertices[p.vertices[:, 2] < zmin + 5.0][:, :2])
    xy = np.vstack(pts)
    hull = ConvexHull(xy)
    return xy[hull.vertices]


def sole_tilt_deg() -> float:
    """home 姿態（軀幹水平）時鞋底的前後傾角；負＝腳尖比腳跟低。"""
    out = []
    for p in load_duck().parts:
        if p.name == "foot_bottom_tpu":
            v = p.vertices
            low = v[v[:, 2] < v[:, 2].min() + 4.0]
            a = np.c_[low[:, 0], low[:, 1], np.ones(len(low))]
            c, *_ = np.linalg.lstsq(a, low[:, 2], rcond=None)
            out.append(np.degrees(np.arctan(c[0])))
    return float(np.mean(out))


def _polygon_margin(poly: np.ndarray, p: np.ndarray) -> float:
    """點到凸多邊形邊緣的距離；在裡面為正。"""
    best = np.inf
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        e = b - a
        normal = np.array([e[1], -e[0]]) / np.linalg.norm(e)  # 逆時針多邊形的外法向
        best = min(best, -float(np.dot(p - a, normal)))
    return best


def contact_height_mm() -> float:
    return float(load_fit().result.contact_z)


def pin_cop_shift_mm(pin_force_n: float = PIN_FORCE_N, pin_count: int = PIN_COUNT) -> float:
    """頂針把背後往前推，靜力平衡下腳底壓力中心往前移多少（mm）。F·h／W。"""
    w = _model().total_mass * G
    return pin_force_n * pin_count * contact_height_mm() / w


def max_pin_force_n(limits: dict[str, tuple[float, float]] | None = None, n: int = 3) -> float:
    """每支頂針的彈力最多多少（N），範圍內所有格點姿勢的重心餘裕（含頂針推力）仍 ≥ MIN_COM_MARGIN_MM。
    推力只讓壓力中心往前移，所以看「重心最前面」的姿勢就夠；這裡仍掃格點，不假設哪個姿勢最前。"""
    limits = limits or DOCKED_HEAD_LIMITS
    axes = [_grid(*limits[j], n) for j in HEAD_JOINTS]
    poly = support_polygon()
    per_newton = pin_cop_shift_mm(1.0)
    best = np.inf
    for vals in product(*axes):
        c = check_pose(dict(zip(HEAD_JOINTS, vals)), pin_force_n=0.0)
        # 二分找這個姿勢允許的最大推力（餘裕對推力是單調的，往前移到前緣為止）
        lo, hi = 0.0, 5.0
        for _ in range(30):
            mid = (lo + hi) / 2
            m = _polygon_margin(poly, np.array(c.com_xy_mm) + np.array([per_newton * mid, 0.0]))
            lo, hi = (mid, hi) if m >= MIN_COM_MARGIN_MM else (lo, mid)
        best = min(best, lo)
    return float(best)


def _posed(pose: dict[str, float]):
    import mujoco

    mdl = _model()
    m, d = mdl.m, mdl.d
    d.qpos[:] = 0
    for k, v in {**HOME_POSE, **pose}.items():
        d.qpos[m.jnt_qposadr[m.joint(k).id]] = v
    mujoco.mj_kinematics(m, d)
    mujoco.mj_comPos(m, d)
    return mdl


def moving_points(pose: dict[str, float]) -> np.ndarray:
    mdl = _posed(pose)
    d = mdl.d
    out = []
    for gi, local in mdl.local_points:
        w = local @ d.geom_xmat[gi].reshape(3, 3).T + d.geom_xpos[gi]
        out.append(w * 1000.0 - mdl.world_to_dock)
    return np.vstack(out)


def check_pose(pose: dict[str, float], pin_force_n: float = PIN_FORCE_N) -> PoseCheck:
    tree, meshes = _dock_surface()
    pts = moving_points(pose)
    near = np.zeros(len(pts), dtype=bool)
    for mesh in meshes.values():  # 先用外框篩掉離充電座很遠的點，KD-tree 只查剩下的
        lo, hi = mesh.bounds
        near |= np.all((pts >= lo - FAR_MM) & (pts <= hi + FAR_MM), axis=1)
    clearance = FAR_MM
    if near.any():
        dist, _ = tree.query(pts[near], distance_upper_bound=FAR_MM, workers=-1)
        clearance = float(min(dist.min(), FAR_MM))
    # 兩個表面相交時，交線附近一定有取樣點（頭頸約 3 mm、充電座約 1.5 mm 間距），
    # 所以穿進去時最近距離一定小於取樣解析度；不用逐點做 inside 判斷（太慢）。
    collides = clearance < SAMPLE_RES_MM
    mdl = _model()
    com = mdl.d.subtree_com[0] * 1000.0 - mdl.world_to_dock
    poly = support_polygon()
    margin = _polygon_margin(poly, com[:2])
    # 頂針推力讓壓力中心往 +x（鴨子前方）移；用「壓力中心＝重心往前移 shift」來算餘裕
    shifted = com[:2] + np.array([pin_cop_shift_mm(pin_force_n), 0.0])
    margin_pins = _polygon_margin(poly, shifted)
    return PoseCheck(dict(pose), clearance, collides, (float(com[0]), float(com[1])), margin, margin_pins)


def head_com_height_mm(pose: dict[str, float] | None = None) -> float:
    mdl = _posed(pose or {})
    root = mdl.m.body("neck_pitch_assembly").id
    return float(mdl.d.subtree_com[root][2] * 1000.0 - mdl.world_to_dock[2])


def max_head_accel(margin_mm: float, pose: dict[str, float] | None = None) -> float:
    """準靜態估計：頭頸水平加速度 a 的反作用力讓壓力中心移 m_h·a·h／W。
    要讓壓力中心留在 margin_mm 以內，a 最多多少（m/s²）。剛體、腿不動、不含舵機彈性。"""
    mdl = _model()
    h = head_com_height_mm(pose) / 1000.0
    return (margin_mm / 1000.0) * mdl.total_mass * G / (mdl.moving_mass * h)


#: 每個頭頸關節帶動的第一個 body（它和它底下的 body 一起轉）。
_JOINT_BODY = {
    "neck_pitch": "neck_pitch_assembly",
    "head_pitch": "head_pitch_to_yaw",
    "head_yaw": "neck_yaw_assembly",
    "head_roll": "head_assembly",
}


def joint_lever(joint: str, pose: dict[str, float] | None = None) -> tuple[float, float]:
    """(被帶動的質量 kg, 質心到關節軸的垂直距離 m)。"""
    mdl = _posed(pose or {})
    m, d = mdl.m, mdl.d
    jid = m.joint(joint).id
    b = m.body(_JOINT_BODY[joint]).id
    bodies = _descendants(m, b)
    mass = float(m.body_mass[bodies].sum())
    r = d.subtree_com[b] - d.xanchor[jid]
    axis = d.xaxis[jid]
    return mass, float(np.linalg.norm(r - np.dot(r, axis) * axis))


def max_joint_accel(joint: str, margin_mm: float, safety_factor: float = 2.0) -> float:
    """單一關節的角加速度上限（rad/s²）：被帶動的質量 × 質心線加速度，不超過 `max_head_accel` 允許的水平力，
    再除以安全係數。只有 pitch 兩軸會往前後甩、影響腳底壓力中心；yaw、roll 主要是左右，左右餘裕很大（約 99 mm），
    所以這裡算出來很大，實際上仍受舵機速度與上游限速限制。"""
    mdl = _model()
    force = max_head_accel(margin_mm) * mdl.moving_mass  # 允許的水平反作用力 N
    mass, lever = joint_lever(joint)
    return force / (mass * lever) / safety_factor


def min_move_time(joint: str, delta_rad: float, margin_mm: float, safety_factor: float = 2.0) -> float:
    """用 minimum-jerk 軌跡轉 delta_rad，最短要多久（s）。min-jerk 的最大角加速度＝5.77·Δθ／T²。"""
    return float(np.sqrt(5.7735 * abs(delta_rad) / max_joint_accel(joint, margin_mm, safety_factor)))


def _grid(lo: float, hi: float, n: int) -> np.ndarray:
    return np.linspace(lo, hi, n)


def sweep(n_per_joint: int = 5, ranges: dict[str, tuple[float, float]] | None = None) -> list[PoseCheck]:
    """在頭頸 4 軸的範圍內取格點，全部組合都檢查（天線另外檢查）。"""
    ranges = ranges or RUNTIME_RANGE
    axes = [_grid(*ranges[j], n_per_joint) for j in HEAD_JOINTS]
    return [check_pose(dict(zip(HEAD_JOINTS, vals))) for vals in product(*axes)]


def first_unsafe(joint: str, step: float = 0.01) -> float:
    """其他關節都在 0 時，這個關節從 0 往正方向轉，第一個不通過 `PoseCheck.ok` 的角度（rad）。"""
    hi = RUNTIME_RANGE[joint][1]
    a = 0.0
    while a <= hi:
        if not check_pose({joint: a}).ok:
            return a
        a += step
    return float("inf")


def _slice_ok(box: dict[str, list[float]], joint: str, value: float, n: int) -> bool:
    """joint 固定在 value，其他三軸在 box 裡取格點，全部組合都通過嗎。"""
    others = [j for j in HEAD_JOINTS if j != joint]
    axes = [_grid(*box[j], n) for j in others]
    return all(check_pose({**dict(zip(others, vals)), joint: value}).ok for vals in product(*axes))


def docked_envelope(n_per_joint: int = 5, step: float = 0.02) -> dict[str, tuple[float, float]]:
    """坐在充電座上可以用的頭頸範圍（rad）。

    從上游 runtime 的範圍開始：整個方盒取格點檢查，找出最常出問題的端點，
    把那一端往內縮（每次 step），直到「那一端的切面」全部通過；重複到整個方盒的格點都通過 `PoseCheck.ok`。
    格點之間沒有檢查，所以門檻（15 mm、15 mm）要留得比格點間距造成的誤差大。
    """
    box = {k: list(v) for k, v in RUNTIME_RANGE.items()}
    for _ in range(50):
        bad = [c for c in sweep(n_per_joint, {k: tuple(v) for k, v in box.items()}) if not c.ok]
        if not bad:
            return {k: (round(v[0], 3), round(v[1], 3)) for k, v in box.items()}
        votes: dict[tuple[str, int], int] = {}
        for c in bad:
            for j in HEAD_JOINTS:
                for end in (0, 1):
                    if np.isclose(c.pose[j], box[j][end]):
                        votes[(j, end)] = votes.get((j, end), 0) + 1
        (j, end), _ = max(votes.items(), key=lambda kv: kv[1])
        sign = 1.0 if end == 0 else -1.0
        while not _slice_ok(box, j, box[j][end], n_per_joint):
            box[j][end] += sign * step
            if box[j][0] >= box[j][1]:
                raise RuntimeError(f"{j} 縮到沒有範圍；請檢查模型或門檻")
    raise RuntimeError("找不到可用範圍")


#: 天線關節範圍（robot.xml）。左天線正方向、右天線負方向是往後擺（往椅背）。
ANTENNA_RANGE = (-1.5708, 1.5708)
ANTENNA_BACKWARD_SIGN = {"left_antenna": 1.0, "right_antenna": -1.0}


def antenna_envelope(head_env: dict[str, tuple[float, float]], step: float = 0.02) -> dict[str, tuple[float, float]]:
    """頭頸在 head_env 方盒的所有角落時，每支天線往後最多能擺多少（另一支在 0）。往前（遠離椅背）不限制。"""
    corners = [dict(zip(HEAD_JOINTS, v)) for v in product(*[head_env[j] for j in HEAD_JOINTS])]
    corners.append({})
    out = {}
    for ant, sign in ANTENNA_BACKWARD_SIGN.items():
        a = 0.0
        while abs(a + sign * step) <= ANTENNA_RANGE[1] and all(check_pose({**c, ant: a + sign * step}).ok for c in corners):
            a += sign * step
        lo, hi = (ANTENNA_RANGE[0], a) if sign > 0 else (a, ANTENNA_RANGE[1])
        out[ant] = (round(lo, 3), round(hi, 3))
    return out


def summary(n_per_joint: int = 5) -> dict:
    mdl = _model()
    home = check_pose({})
    env = docked_envelope(n_per_joint)
    corners = [dict(zip(HEAD_JOINTS, v)) for v in product(*[env[j] for j in HEAD_JOINTS])]
    antennas = antenna_envelope(env)
    worst_corner = min((check_pose(p) for p in corners), key=lambda c: min(c.clearance_mm, c.com_margin_with_pins_mm))
    return {
        "total_mass_kg": round(mdl.total_mass, 3),
        "moving_mass_kg": round(mdl.moving_mass, 3),
        "contact_height_mm": round(contact_height_mm(), 1),
        "pin_cop_shift_mm": round(pin_cop_shift_mm(), 1),
        "max_pin_force_n_each": round(max_pin_force_n(), 2),
        "home": {
            "clearance_mm": round(home.clearance_mm, 1),
            "com_xy_mm": tuple(round(v, 1) for v in home.com_xy_mm),
            "com_margin_mm": round(home.com_margin_mm, 1),
            "com_margin_with_pins_mm": round(home.com_margin_with_pins_mm, 1),
        },
        "runtime_range": RUNTIME_RANGE,
        "docked_envelope": env,
        "antenna_envelope": antennas,
        "antenna_envelope_head_neutral": antenna_envelope({j: (0.0, 0.0) for j in HEAD_JOINTS}),
        "single_joint_collision_rad": {"neck_pitch": round(first_unsafe("neck_pitch"), 3)},
        "sole_tilt_deg": round(sole_tilt_deg(), 2),
        "worst_corner": {
            "pose": {k: round(v, 3) for k, v in worst_corner.pose.items()},
            "clearance_mm": round(worst_corner.clearance_mm, 1),
            "com_margin_with_pins_mm": round(worst_corner.com_margin_with_pins_mm, 1),
        },
        "max_head_accel_m_s2_at_home": round(max_head_accel(home.com_margin_with_pins_mm - MIN_COM_MARGIN_MM), 2),
        "joints": {
            j: {
                "moved_mass_kg": round(joint_lever(j)[0], 3),
                "lever_mm": round(joint_lever(j)[1] * 1000, 1),
                "max_accel_rad_s2": round(max_joint_accel(j, home.com_margin_with_pins_mm - MIN_COM_MARGIN_MM), 1),
                "min_time_full_range_s": round(
                    min_move_time(j, env[j][1] - env[j][0], home.com_margin_with_pins_mm - MIN_COM_MARGIN_MM), 2
                ),
            }
            for j in HEAD_JOINTS
        },
    }


if __name__ == "__main__":  # pragma: no cover
    import json

    print(json.dumps(summary(), ensure_ascii=False, indent=2))
