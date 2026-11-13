"""對位與干涉計算：鴨子（上游 CAD，home 站姿）放進充電座時會不會撞到、頂針會不會落在觸片上。

這是**幾何層級**的驗證：鴨子當成剛體、站姿固定，沒有模擬步態晃動、腳底打滑或外殼公差。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import trimesh

from . import params as P
from .body_back_mod import strip_rects_print
from .build import BuildResult, build
from .dock_parts import pin_positions
from .duck import DuckPart, load_duck
from .geom import to_trimesh

#: 頂針尖端半徑（接觸面積的保守估計）。
PIN_TIP_R = 1.0


@dataclass
class Fit:
    result: BuildResult
    dock_meshes: dict[str, trimesh.Trimesh]
    duck_parts: list[DuckPart]  # 背殼已換成改裝件


@lru_cache(maxsize=1)
def load_fit() -> Fit:
    res = build()
    duck = load_duck()
    dock = {p.key: to_trimesh(p.solid) for p in res.parts}
    bb = to_trimesh(res.body_back_dock)
    parts = [p for p in duck.parts if p.name != "body_back"]
    parts.append(DuckPart("body_back_dock", duck.print_to_dock(bb.vertices), bb.faces))
    return Fit(res, dock, parts)


def _sample_points(part: DuckPart, spacing: float = 5.0) -> np.ndarray:
    """頂點＋表面取樣點（大平面只有角落有頂點，要補點才抓得到碰撞）。"""
    tm = trimesh.Trimesh(part.vertices, part.faces, process=False)
    n = int(max(100, tm.area / (spacing**2)))
    pts, _ = trimesh.sample.sample_surface(tm, n, seed=0)
    return np.vstack([part.vertices, pts])


@lru_cache(maxsize=1)
def _duck_samples() -> dict[str, np.ndarray]:
    fit = load_fit()
    return {p.name: _sample_points(p) for p in fit.duck_parts}


def collisions(dx: float = 0.0, dy: float = 0.0, dz: float = 0.0, yaw_deg: float = 0.0, pitch_deg: float = 0.0) -> list[tuple[str, str, int]]:
    """回傳 (鴨子零件, 充電座零件, 侵入點數)。只要 >0 就是干涉。"""
    fit = load_fit()
    samples = _duck_samples()
    yaw, pitch = np.radians(yaw_deg), np.radians(pitch_deg)
    rz = np.array([[np.cos(yaw), -np.sin(yaw), 0], [np.sin(yaw), np.cos(yaw), 0], [0, 0, 1]])
    ry = np.array([[np.cos(pitch), 0, np.sin(pitch)], [0, 1, 0], [-np.sin(pitch), 0, np.cos(pitch)]])
    r = rz @ ry
    pivot = np.array([162.0, 0.0, 0.0])
    out = []
    for name, pts in samples.items():
        v = (pts - pivot) @ r.T + pivot + np.array([dx, dy, dz])
        for key, mesh in fit.dock_meshes.items():
            lo, hi = mesh.bounds
            sel = np.all((v >= lo - 0.01) & (v <= hi + 0.01), axis=1)
            if not sel.any():
                continue
            inside = mesh.contains(v[sel])
            if inside.any():
                out.append((name, key, int(inside.sum())))
    return out


def min_clearance(dock_key: str, exclude_duck: tuple[str, ...] = ()) -> float:
    """站姿停好時，鴨子到某個充電座零件的最近距離（mm）。"""
    fit = load_fit()
    mesh = fit.dock_meshes[dock_key]
    best = np.inf
    for name, pts in _duck_samples().items():
        if name in exclude_duck:
            continue
        lo, hi = mesh.bounds
        sel = np.all((pts >= lo - 60) & (pts <= hi + 60), axis=1)
        if not sel.any():
            continue
        _, dist, _ = trimesh.proximity.closest_point(mesh, pts[sel])
        best = min(best, float(dist.min()))
    return best


def contact_margins(dy: float = 0.0, dz: float = 0.0, pitch_deg: float = 0.0) -> dict[str, float]:
    """每一極「最好的那支頂針」離觸片邊緣的最小餘裕（mm，已扣掉頂針尖端半徑）。負值＝沒接觸。

    鴨子相對站姿平移 dy、dz，並繞地板上的鴨子原點 pitch（低頭為正）。
    """
    res = load_fit().result
    duck = load_duck()
    pins = pin_positions(res.contact_z)
    pitch = np.radians(pitch_deg)
    margins = {}
    for s in strip_rects_print():
        corners = np.array([[P.BOSS_FACE_X, s["y0"], s["z0"]], [P.BOSS_FACE_X, s["y1"], s["z1"]]])
        c = duck.print_to_dock(corners)
        # pitch：觸片繞鴨子原點下方的地板轉，對高度的影響近似為 X 距離 × sin(pitch)
        lever = 162.0
        shift_z = -lever * np.sin(pitch)
        y0, y1 = sorted((c[0, 1] + dy, c[1, 1] + dy))
        z0, z1 = sorted((c[0, 2] + dz + shift_z, c[1, 2] + dz + shift_z))
        best = -np.inf
        for p in pins:
            if p["pole"] != s["pole"]:
                continue
            m = min(p["y"] - y0, y1 - p["y"], p["z"] - z0, z1 - p["z"]) - PIN_TIP_R
            best = max(best, m)
        margins[s["pole"]] = float(best)
    return margins


def cross_pole_safe(dy: float) -> bool:
    """鴨子左右偏 dy 時，任何一支頂針都不會碰到「另一極」的觸片。"""
    res = load_fit().result
    pins = pin_positions(res.contact_z)
    for s in strip_rects_print():
        y0, y1 = s["y0"] + dy, s["y1"] + dy
        for p in pins:
            if p["pole"] != s["pole"] and (y0 - PIN_TIP_R) < p["y"] < (y1 + PIN_TIP_R):
                return False
    return True


def seated_lateral_play() -> float:
    """凸台完全坐進 V 形槽時的左右間隙（單邊，mm）。V 牆與 45° 導角平行、沿 X 留 CRADLE_CLEAR。"""
    return P.CRADLE_CLEAR


def full_capture_half_width() -> float:
    """凸台整條導角都還落在 V 形牆上的最大左右偏移（mm）。"""
    return P.CRADLE_TIP_HALF_W - P.BOSS_HALF_W


def first_contact(dy: float = 0.0, yaw_deg: float = 0.0, dz: float = 0.0, start: float = 80.0, step: float = 2.0) -> tuple[float, list[tuple[str, str, int]]]:
    """鴨子從 X = start 慢慢倒退，回傳第一次發生干涉時的 dx 與干涉清單（都沒碰到回傳 (nan, [])）。"""
    dx = start
    while dx >= -1.0:
        hits = collisions(dx=dx, dy=dy, dz=dz, yaw_deg=yaw_deg)
        if hits:
            return dx, hits
        dx -= step
    return float("nan"), []


def z_tolerance() -> dict[str, tuple[float, float]]:
    """鴨子站高（相對 home 站姿）可以偏多少，頂針仍在觸片上。

    回傳 {"both_pins": (下限, 上限), "one_pin": (下限, 上限)}，單位 mm。
    """
    res = load_fit().result
    duck = load_duck()
    s = strip_rects_print()[0]
    z0 = duck.print_to_dock(np.array([0, 0, s["z0"]]))[2]
    z1 = duck.print_to_dock(np.array([0, 0, s["z1"]]))[2]
    zs = sorted({p["z"] for p in pin_positions(res.contact_z)})
    # 鴨子往上 dz：觸片變成 [z0+dz, z1+dz]，頂針 z 要在 [z0+dz+r, z1+dz-r]
    per_pin = [(z - z1 + PIN_TIP_R, z - z0 - PIN_TIP_R) for z in zs]
    both = (max(a for a, _ in per_pin), min(b for _, b in per_pin))
    one = (min(a for a, _ in per_pin), max(b for _, b in per_pin))
    return {"both_pins": both, "one_pin": one}


def y_tolerance() -> float:
    """頂針離觸片左右邊緣的餘裕（站姿置中時，mm，已扣頂針尖端半徑）。"""
    return P.STRIP_W / 2 - PIN_TIP_R
