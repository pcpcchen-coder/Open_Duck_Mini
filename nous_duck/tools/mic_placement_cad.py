"""麥克風陣列放置的 CAD 檢查：脖子後方的機身頂面 vs 頭頂。

用組裝檢視器 pipeline 的輸出（上游 CAD 的零件位置與網格），算三件事：

1. 板子放在脖子後方的機身頂面時，頭最多能抬幾度（和沒裝板子比）。頭頸 4 個關節取樣掃過，
   排除頭本來就會撞進機身的姿勢（脖子穿過機身頂面的開口不算碰撞），板子上方留 5 mm 安全距離。
2. 板子放在頭頂時，頭殼頂面平坦區的大小，以及左右天線在整個關節範圍擺動時離板子多遠。
3. 圓形陣列傾斜時、不做修正的方位角最大誤差（解析計算）。
4. 陣列中心偏離頭偏航轉軸時，近距離聲源的視差誤差（解析計算）。

限制：只用 CAD 網格（沒有線材、支架、螺絲）；網格取樣間距約 1.5 mm、高度圖格距 2 mm；
關節範圍用上游 robot.xml；板子當成平放的圓盤。驗證層級：CAD 幾何計算，不是實機。

用法（先執行 pipeline）：
    cd nous_duck/assembly_viewer/pipeline && python -m viewer_pipeline && cd -
    python3 -I nous_duck/tools/mic_placement_cad.py
需要 numpy。
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
BUILD = REPO / "nous_duck/assembly_viewer/dist/build"
GRID = 2.0
NECK_CHAIN = ("neck_pitch", "head_pitch", "head_yaw", "head_roll")
BOARDS = {  # 名稱: (直徑 mm, 板子連支撐的高度 mm)
    "XVF3800 標準版": (100.0, 7.0),
    "Flex Circular-4": (73.0, 5.0),
}
SAFETY_MM = 5.0
REALISTIC_YAW_DEG = 75  # 上游 experiments/real_robot/run.py：head_yaw = ±150°/2


def load():
    scene = json.loads((BUILD / "scene.json").read_text(encoding="utf-8"))
    buf = (BUILD / "meshes.bin").read_bytes()
    return scene, buf


def quat_matrix(q):
    x, y, z, w = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def axis_rot(axis, ang):
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)
    k = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + np.sin(ang) * k + (1 - np.cos(ang)) * k @ k


class Model:
    def __init__(self):
        self.scene, self.buf = load()
        self.parent = {b["name"]: b["parent"] for b in self.scene["bodies"]}
        self.joints = {j["name"]: j for j in self.scene["joints"]}
        self.body_joint = {j["body"]: j["name"] for j in self.scene["joints"]}

    def ancestors(self, body):
        out = []
        while body:
            out.append(body)
            body = self.parent[body]
        return out

    def surface(self, part, step=1.5):
        """零件表面取樣點（世界座標，mm）：頂點加三角形內部的重心座標格點。"""
        r = self.scene["meshes"][part["mesh"]]
        q = np.frombuffer(self.buf, "<u2", r["vertex_count"] * 3, r["vertex_offset"]).reshape(-1, 3)
        v = np.array(r["bbox_min_mm"]) + q * np.array(r["step_mm"])
        it = "<u2" if r["index_type"] == "uint16" else "<u4"
        idx = np.frombuffer(self.buf, it, r["index_count"], r["index_offset"]).reshape(-1, 3)
        w = v @ quat_matrix(part["quaternion_xyzw"]).T + np.array(part["position_mm"])
        t = w[idx]
        edge = np.maximum(np.linalg.norm(t[:, 1] - t[:, 0], axis=1), np.linalg.norm(t[:, 2] - t[:, 0], axis=1))
        n = np.clip(np.ceil(edge / step).astype(int), 1, 60)
        out = [w]
        for k in np.unique(n):
            sel = t[n == k]
            if k == 1:
                out.append(sel.mean(1))
                continue
            for i in range(k + 1):
                for j in range(k + 1 - i):
                    u, s = i / k, j / k
                    out.append(sel[:, 0] * (1 - u - s) + sel[:, 1] * u + sel[:, 2] * s)
        return np.vstack(out)


class HeightGrid:
    def __init__(self, x0, x1, z0, z1):
        self.xs = np.arange(x0, x1 + GRID, GRID)
        self.zs = np.arange(z0, z1 + GRID, GRID)
        self.X, self.Z = np.meshgrid(self.xs, self.zs, indexing="ij")

    def cells(self, pts):
        ix = np.round((pts[:, 0] - self.xs[0]) / GRID).astype(int)
        iz = np.round((pts[:, 2] - self.zs[0]) / GRID).astype(int)
        ok = (ix >= 0) & (ix < len(self.xs)) & (iz >= 0) & (iz < len(self.zs))
        return ix[ok], iz[ok], pts[ok, 1]

    def reduce(self, pts, fn, init):
        m = np.full(self.X.shape, init)
        a, b, y = self.cells(pts)
        fn.at(m, (a, b), y)
        return m

    def disc(self, d, xc, zc):
        return (self.X - xc) ** 2 + (self.Z - zc) ** 2 <= (d / 2) ** 2


def dilate(mask, it):
    m = mask.copy()
    for _ in range(it):
        n = m.copy()
        n[1:] |= m[:-1]
        n[:-1] |= m[1:]
        n[:, 1:] |= m[:, :-1]
        n[:, :-1] |= m[:, 1:]
        m = n
    return m


def neck_study(model: Model):
    sc = model.scene
    root = "neck_pitch_assembly"
    static = [p for p in sc["parts"] if root not in model.ancestors(p["body"])]
    moving = [p for p in sc["parts"] if root in model.ancestors(p["body"])]
    g = HeightGrid(-80, 80, -150, 90)
    S = np.vstack([model.surface(p) for p in static])
    S = S[S[:, 1] > 150]  # 機身（髖部以上）
    top = g.reduce(S, np.maximum, -np.inf)
    bot = g.reduce(S, np.minimum, np.inf)
    shell = np.vstack([model.surface(p) for p in static if p["mesh"].startswith("body_")])
    pts = {}
    for p in moving:
        w = model.surface(p)
        pts.setdefault(p["body"], []).append(w[:: max(1, len(w) // 2500)])
    pts = {k: np.vstack(v) for k, v in pts.items()}
    J = model.joints

    def pose(ang):
        out = []
        for body, P in pts.items():
            R, t = np.eye(3), np.zeros(3)
            for x in reversed(model.ancestors(body)):
                n = model.body_joint.get(x)
                if n in NECK_CHAIN:
                    Rj = axis_rot(J[n]["axis"], ang.get(n, 0.0))
                    pj = np.array(J[n]["position_mm"])
                    t = R @ (pj - Rj @ pj) + t
                    R = R @ Rj
            out.append(P @ R.T + t)
        return np.vstack(out)

    a, b, y = g.cells(pose({}))
    inside = (y < top[a, b] - 3) & (y > bot[a, b] + 3)
    opening = np.zeros(top.shape, bool)
    opening[a[inside], b[inside]] = True
    opening = dilate(opening, 3)

    def hits(ang, disc=None, ceil=None):
        """回傳 (撞機身, 撞板子)。"""
        a, b, y = g.cells(pose(ang))
        if ((y < top[a, b] - 3) & (y > bot[a, b] + 3) & ~opening[a, b]).any():
            return True, False
        return False, bool(disc is not None and (disc[a, b] & (y < ceil)).any())

    def look_up(npc, hp):
        v = axis_rot(J["neck_pitch"]["axis"], npc) @ axis_rot(J["head_pitch"]["axis"], hp) @ np.array([0, 0, 1.0])
        return float(np.degrees(np.arctan2(v[1], v[2])))

    neck_z = J["neck_pitch"]["position_mm"][2]
    placements = {"XVF3800 標準版": -50.0, "Flex Circular-4": -60.0}
    discs = {}
    for name, zc in placements.items():
        d, h = BOARDS[name]
        m = g.disc(d, 0.0, zc)
        if np.isinf(top[m]).any():
            raise SystemExit(f"{name} 放在 z={zc} 會超出機身頂面")
        base = top[m].max() + 2.0
        discs[name] = (m, base + h + SAFETY_MM, base + h, zc)

    print("## 1. 脖子後方的機身頂面")
    print(f"機身外殼：x {shell[:, 0].min():.0f}..{shell[:, 0].max():.0f} mm（寬 {np.ptp(shell[:, 0]):.0f} mm），"
          f"頂面 y={shell[:, 1].max():.0f} mm")
    zero = pose({})
    for name, (m, ceil, board_top, zc) in discs.items():
        a, b, y = g.cells(zero)
        sel = m[a, b]
        print(f"- {name}：圓心在脖子關節後方 {neck_z - zc:.0f} mm，板子頂面 y={board_top:.0f}；頭在零位時離板子 {y[sel].min() - board_top:.0f} mm")

    NP = np.radians(np.arange(-20, 26, 2.5))
    HP = np.radians(np.arange(-45, 46, 2.5))
    print("\n頭最多能抬幾度（頭前方向量的仰角；頸俯仰＋頭俯仰，側擺 0°）：")
    print("| 條件 | 沒裝板子 | " + " | ".join(discs) + " |")
    print("|---|---:|" + "---:|" * len(discs))
    for yaws, label in ((np.radians([0.0]), "頭朝正前（偏航 0°）"),
                        (np.radians(np.arange(-REALISTIC_YAW_DEG, REALISTIC_YAW_DEG + 1, 15)), f"偏航 ±{REALISTIC_YAW_DEG}° 內任何角度")):
        row = []
        for key in [None, *discs]:
            best = -90.0
            for npc, hp in itertools.product(NP, HP):
                up = look_up(npc, hp)
                if up <= best:
                    continue
                ok = True
                for yw in yaws:
                    body, board = hits({"neck_pitch": npc, "head_pitch": hp, "head_yaw": yw},
                                       *(discs[key][:2] if key else (None, None)))
                    if body or board:
                        ok = False
                        break
                if ok:
                    best = up
            row.append(f"{best:.0f}°")
        print(f"| {label} | " + " | ".join(row) + " |")
    return look_up


def head_study(model: Model):
    sc = model.scene
    J = model.joints
    head = next(p for p in sc["parts"] if p["mesh"] == "head")
    H = model.surface(head)
    g = HeightGrid(-110, 110, -110, 140)
    top = g.reduce(H, np.maximum, -np.inf)
    ymax = H[:, 1].max()
    flat = top > ymax - 1.5
    fx = g.xs[flat.any(1)]
    fz = g.zs[flat.any(0)]
    ant = []
    for side in ("left", "right"):
        j = J[f"{side}_antenna"]
        lo, hi = j["range_rad"]
        P = np.vstack([model.surface(p) for p in sc["parts"] if p["body"] == f"{side}_antenna_holder"])
        pj = np.array(j["position_mm"])
        for a in np.linspace(lo, hi, 37):
            ant.append((P - pj) @ axis_rot(j["axis"], a).T + pj)
    low_ant = g.reduce(np.vstack(ant), np.minimum, np.inf)
    yaw_z = J["head_yaw"]["position_mm"][2]
    print("\n## 2. 頭頂")
    print(f"頭殼外框 x {H[:,0].min():.0f}..{H[:,0].max():.0f}、z {H[:,2].min():.0f}..{H[:,2].max():.0f}（前方是 +z），頂面 y={ymax:.0f} mm")
    print(f"頂面平坦區（離最高點 1.5 mm 內）：x {fx.min():.0f}..{fx.max():.0f}、z {fz.min():.0f}..{fz.max():.0f}，約 {flat.sum()*GRID*GRID/100:.0f} cm²；頭偏航轉軸在 z={yaw_z:.0f}")
    d, _ = BOARDS["XVF3800 標準版"]
    print(f"\n{d:.0f} mm 圓板平放在頭頂（PCB 下 4 mm 支撐、零件最高 6.2 mm），天線在整個關節範圍（±90°）擺動時離板子的最近距離：")
    print("| 圓心 z | 和轉軸的前後距離 | 板子底下屬於頂面平坦區的比例 | 天線最近距離 |")
    print("|---:|---:|---|---:|")
    for zc in (-25, 0, yaw_z, 45, 70):
        m = g.disc(d, 0.0, zc)
        ceil = ymax + 4 + 6.2
        clr = (low_ant[m] - ceil).min()
        print(f"| {zc:.0f} | {zc - yaw_z:+.0f} mm | {flat[m].mean() * 100:.0f}% | {'碰不到' if np.isinf(clr) else f'{clr:.0f} mm'} |")


def tilt_table():
    print("\n## 3. 陣列傾斜、不做修正時的方位角最大誤差（水平方向的聲源）")
    print("| 傾斜 | 最大誤差 |")
    print("|---:|---:|")
    phi = np.radians(np.linspace(0, 360, 3601))
    for tau in (5, 10, 15, 20, 30):
        t = np.radians(tau)
        meas = np.arctan2(np.sin(phi) * np.cos(t), np.cos(phi))  # 繞前後軸傾斜 τ
        err = np.degrees(np.abs((meas - phi + np.pi) % (2 * np.pi) - np.pi)).max()
        print(f"| {tau}° | {err:.1f}° |")


def parallax_table():
    print("\n## 4. 陣列中心偏離頭偏航轉軸造成的方位角誤差（最壞情況 asin(r/D)）")
    print("| 偏離 r | 聲源 1 m | 聲源 2 m |")
    print("|---:|---:|---:|")
    for r in (22, 47):
        print(f"| {r} mm | {np.degrees(np.arcsin(r / 1000)):.1f}° | {np.degrees(np.arcsin(r / 2000)):.1f}° |")


def main():
    model = Model()
    neck_study(model)
    head_study(model)
    tilt_table()
    parallax_table()


if __name__ == "__main__":
    main()
