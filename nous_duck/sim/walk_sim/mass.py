"""加裝件的質量模型：把元件加進（或移出）上游模型的 body 慣量，不改上游 `robot.xml`。

用途：ADR-0005 §2.4、ADR-0008 §4.3——Pi 4 改裝在機身、頭上加 AR0144 等元件之後，
上游步態策略在模擬裡還穩不穩。

每個元件（`MassItem`）寫成：

- `body`：元件固定在哪個 body 上（例如 `trunk_assembly`、`head_assembly`），隨該 body 一起動。
- `pos_base`：元件質心在 **起始姿勢（`HOME_POSE`）時的 base 座標**（x 向前、y 向左、z 向上，m）。
  這樣寫比 body 自己的座標直觀；程式在起始姿勢做一次正向運動學，換算到 body 座標。
- `size_base`：元件外形的長方體邊長（base 座標的 x、y、z，m），只用來算元件自己的轉動慣量。
- `mass_kg`：正數＝加上去；負數＝從 body 拿掉（例如上游頭裡的 Pi Zero 2 W）。

合併方式：把 body 原本的慣量和元件的慣量都換算成「對 body 原點」的慣量張量（平行軸定理），
相加或相減後求新的質心，再換回「對質心」的張量並做特徵分解，寫回 `MjsBody` 的
`mass`、`ipos`、`iquat`、`inertia`。拿掉元件時若結果不合理（質量 ≤ 0、慣量不是正定、
不滿足三角不等式），直接丟出錯誤，不偷偷修正。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import mujoco
import numpy as np

from .model import HOME_BASE_Z, HOME_POSE

#: 質量預算檔放在 `sim/mass_budget/`。
BUDGET_DIR = Path(__file__).resolve().parents[1] / "mass_budget"


@dataclass(frozen=True)
class MassItem:
    id: str
    body: str
    mass_kg: float
    pos_base: tuple[float, float, float]
    size_base: tuple[float, float, float] = (0.01, 0.01, 0.01)


# --------------------------------------------------------------------------- 慣量運算
def _skew_parallel(m: float, p: np.ndarray) -> np.ndarray:
    """質點 m 在位置 p 對原點的慣量貢獻：m (|p|² E − p pᵀ)。"""
    return m * (float(p @ p) * np.eye(3) - np.outer(p, p))


def _box_inertia(m: float, size: np.ndarray) -> np.ndarray:
    a, b, c = (float(s) for s in size)
    return (m / 12.0) * np.diag([b * b + c * c, a * a + c * c, a * a + b * b])


def _quat_to_mat(q) -> np.ndarray:
    R = np.zeros(9)
    mujoco.mju_quat2Mat(R, np.asarray(q, dtype=np.float64))
    return R.reshape(3, 3)


def _mat_to_quat(R: np.ndarray) -> np.ndarray:
    q = np.zeros(4)
    mujoco.mju_mat2Quat(q, np.ascontiguousarray(R, dtype=np.float64).reshape(9))
    return q


@dataclass
class Inertial:
    """body 座標下的慣量：質量、質心、對質心的 3×3 張量。"""

    mass: float
    com: np.ndarray
    I_com: np.ndarray

    @classmethod
    def from_body(cls, b: mujoco.MjsBody) -> "Inertial":
        if not b.explicitinertial:
            # 沒有明寫慣量的 body（例如 base）先視為空的，元件會成為它唯一的質量。
            return cls(0.0, np.zeros(3), np.zeros((3, 3)))
        if not np.isnan(b.fullinertia[0]):
            f = b.fullinertia
            I = np.array([[f[0], f[3], f[4]], [f[3], f[1], f[5]], [f[4], f[5], f[2]]])
        else:
            R = _quat_to_mat(b.iquat)
            I = R @ np.diag(b.inertia) @ R.T
        return cls(float(b.mass), np.array(b.ipos, dtype=float), I)

    def about_origin(self) -> np.ndarray:
        return self.I_com + _skew_parallel(self.mass, self.com)

    def combine(self, m: float, p: np.ndarray, I_own: np.ndarray, sign: float) -> "Inertial":
        M = self.mass + sign * m
        if M <= 1e-9:
            raise ValueError(f"移除後質量 ≤ 0（原 {self.mass:.4f} kg，移除 {m:.4f} kg）")
        C = (self.mass * self.com + sign * m * p) / M
        I_O = self.about_origin() + sign * (I_own + _skew_parallel(m, p))
        I_C = I_O - _skew_parallel(M, C)
        return Inertial(M, C, 0.5 * (I_C + I_C.T))

    def write_to(self, b: mujoco.MjsBody, name: str) -> None:
        w, V = np.linalg.eigh(self.I_com)
        if np.any(w <= 0):
            raise ValueError(f"{name}：慣量不是正定 {w}")
        a, bb, c = w
        if a + bb < c * (1 - 1e-9) or a + c < bb * (1 - 1e-9) or bb + c < a * (1 - 1e-9):
            raise ValueError(f"{name}：主慣量不滿足三角不等式 {w}")
        if np.linalg.det(V) < 0:
            V[:, 0] = -V[:, 0]
        b.explicitinertial = True
        b.mass = self.mass
        b.ipos = self.com.tolist()
        b.iquat = _mat_to_quat(V).tolist()
        b.inertia = w.tolist()
        b.fullinertia = [float("nan"), 0, 0, 0, 0, 0]


# --------------------------------------------------------------------------- 起始姿勢的 body 位姿
def home_body_frames(spec: mujoco.MjSpec) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """編譯一份複本、放到起始姿勢，回傳每個 body 在 base 座標的（位置, 旋轉矩陣）。"""
    m = spec.copy().compile()
    d = mujoco.MjData(m)
    fj = m.joint("floating_base")
    q0 = m.jnt_qposadr[fj.id]
    d.qpos[q0 : q0 + 7] = [0, 0, HOME_BASE_Z, 1, 0, 0, 0]
    for name, val in HOME_POSE.items():
        d.qpos[m.jnt_qposadr[m.joint(name).id]] = val
    mujoco.mj_kinematics(m, d)
    b0 = m.body("base").id
    Rb, pb = d.xmat[b0].reshape(3, 3), d.xpos[b0]
    out = {}
    for i in range(m.nbody):
        R = Rb.T @ d.xmat[i].reshape(3, 3)
        out[m.body(i).name] = (Rb.T @ (d.xpos[i] - pb), R)
    return out


def apply_mass_items(spec: mujoco.MjSpec, items) -> list[dict]:
    """把元件合進 spec 的 body 慣量（原地修改）；回傳每個元件換算後的 body 座標，給紀錄用。"""
    items = list(items)
    if not items:
        return []
    frames = home_body_frames(spec)
    by_body: dict[str, list[MassItem]] = {}
    for it in items:
        if it.body not in frames:
            raise KeyError(f"{it.id}：找不到 body {it.body!r}")
        by_body.setdefault(it.body, []).append(it)
    log = []
    for body_name, its in by_body.items():
        b = spec.body(body_name)
        pB, RB = frames[body_name]
        inert = Inertial.from_body(b)
        # 先加後減，避免中途質量變成負的。
        for it in sorted(its, key=lambda x: x.mass_kg < 0):
            m = abs(it.mass_kg)
            p_local = RB.T @ (np.asarray(it.pos_base, dtype=float) - pB)
            I_own = RB.T @ _box_inertia(m, np.asarray(it.size_base, dtype=float)) @ RB
            inert = inert.combine(m, p_local, I_own, 1.0 if it.mass_kg > 0 else -1.0)
            log.append({"id": it.id, "body": body_name, "mass_kg": it.mass_kg, "pos_body": np.round(p_local, 4).tolist()})
        inert.write_to(b, body_name)
    return log


# --------------------------------------------------------------------------- 質量預算檔
def load_budget(path: Path | str) -> dict:
    """讀質量預算 JSON（格式見 `sim/mass_budget/README.md`）。"""
    p = Path(path)
    if not p.is_absolute() and not p.exists():
        p = BUDGET_DIR / p
    data = json.loads(p.read_text(encoding="utf-8"))
    ids = [c["id"] for c in data["components"]]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{p.name}：元件 id 重複")
    for c in data["components"]:
        lo, nom, hi = c["mass_g"]["low"], c["mass_g"]["nominal"], c["mass_g"]["high"]
        if not (0 <= lo <= nom <= hi):
            raise ValueError(f"{c['id']}：mass_g 必須 0 ≤ low ≤ nominal ≤ high")
        if c["action"] not in ("add", "remove"):
            raise ValueError(f"{c['id']}：action 必須是 add 或 remove")
        if c["source"]["kind"] not in ("measured", "datasheet", "retailer", "repo_estimate", "guess"):
            raise ValueError(f"{c['id']}：source.kind 不在允許的列舉裡")
    return data


def budget_items(
    budget: dict,
    level: str = "nominal",
    placement: dict[str, tuple[float, float, float]] | None = None,
    include: set[str] | None = None,
) -> list[MassItem]:
    """依質量等級（low／nominal／high）產生元件清單。

    `placement` 可以覆寫某些元件的位置（例如 Pi 4 放在機身的不同位置）；
    `include` 只取部分元件。拿掉的元件（remove）在 `high` 時取 `low`、在 `low` 時取 `high`，
    讓 `high` 一定是「最重」的情況。
    """
    out = []
    for c in budget["components"]:
        if include is not None and c["id"] not in include:
            continue
        g = c["mass_g"]
        if c["action"] == "remove":
            lv = {"low": "high", "high": "low"}.get(level, level)
            mass = -g[lv] / 1000.0
        else:
            mass = g[level] / 1000.0
        if mass == 0:
            continue
        pos = tuple((placement or {}).get(c["id"], c["pos_base_m"]))
        out.append(MassItem(c["id"], c["body"], mass, pos, tuple(c.get("size_base_m", (0.01, 0.01, 0.01)))))
    return out


def model_summary(m: mujoco.MjModel) -> dict:
    """總質量、起始姿勢的整體質心（base 座標）、頭部（neck_pitch 以下）質量與質心。"""
    d = mujoco.MjData(m)
    fj = m.joint("floating_base")
    q0 = m.jnt_qposadr[fj.id]
    d.qpos[q0 : q0 + 7] = [0, 0, HOME_BASE_Z, 1, 0, 0, 0]
    for name, val in HOME_POSE.items():
        d.qpos[m.jnt_qposadr[m.joint(name).id]] = val
    mujoco.mj_forward(m, d)
    b0 = m.body("base").id
    pb = d.xpos[b0]
    neck = m.body("neck_pitch_assembly").id
    head = m.body("head_assembly").id
    # 頸頭關節的靜態重力力矩：速度為 0 時 qfrc_bias 只剩重力，等於該關節以上那串零件的重量
    # 對關節軸的力矩（機身靜止、起始姿勢）。腿的關節站立時要扛整個機身，力矩取決於足底接觸，
    # 這個算法不適用，所以不列。
    tau = {}
    for jn in ("neck_pitch", "head_pitch", "head_yaw", "head_roll"):
        tau[jn] = round(float(d.qfrc_bias[m.jnt_dofadr[m.joint(jn).id]]), 4)
    return {
        "total_mass_kg": round(float(m.body_subtreemass[b0]), 4),
        "com_base_m": np.round(d.subtree_com[b0] - pb, 4).tolist(),
        "head_chain_mass_kg": round(float(m.body_subtreemass[neck]), 4),
        "head_chain_com_base_m": np.round(d.subtree_com[neck] - pb, 4).tolist(),
        "head_assembly_mass_kg": round(float(m.body_subtreemass[head]), 4),
        "gravity_torque_home_Nm": tau,
    }
