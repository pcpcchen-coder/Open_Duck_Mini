"""加裝後的質量模型：比較上游模型與「單板 Pi 4＋加裝件」在模擬裡的步態。全部是**模擬值**。

    cd nous_duck/sim
    python -m walk_sim.mass_compare --out ../docs/validation/data/mass-model-2026-11-26.json
    python -m walk_sim.mass_compare --quick      # 縮小樣本，給測試用

質量預算在 `sim/mass_budget/p2_single_pi4.json`（每個元件的估計值、上下限與來源）。
每個「情境」是一組 `ModelOptions`；每個情境跑同一套量測（見 `measure_profile`）。

量測的選法：PR #32 的隨機指令跌倒率（`measure.fall_rate`）在機身加 0.2／0.4 kg 時都是 0 次，
分不出差別，所以這裡另外加了比較敏感的項目：起步門檻、頭部大角度、頭部加重與機身加重的
餘裕掃描（加到出問題為止），以及舵機變弱（kp −20%）的組合。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import mujoco
import numpy as np

from .mass import MassItem, budget_items, load_budget, model_summary
from .measure import HZ, Track, fall_rate, run_segment, stepping_fraction
from .model import CONTROL_DT, HEAD_SLICE, HOME_BASE_Z, HOME_POSE, ModelOptions, build_model
from .sim import PHASE_PERIOD_STEPS, SimOptions, WalkSim

BUDGET = "p2_single_pi4.json"
KP_NOMINAL = 13.37

#: 頭部大角度測試（站著、速度 0）：ADR-0011 的初版範圍，加上 PR #32 量到會跌倒的角度。
HEAD_CASES = [
    ("head_yaw", 5, 0.5),
    ("head_yaw", 5, -0.5),
    ("head_yaw", 5, 1.0),
    ("head_yaw", 5, -1.0),
    ("head_pitch", 4, 0.3),
    ("head_pitch", 4, -0.78),
    ("head_roll", 6, 0.5),
    ("head_roll", 6, -0.5),
    ("neck_pitch", 3, 0.5),
    ("neck_pitch", 3, -0.34),
]

#: 走路指令（每個指令在 `phases` 個起步相位各跑一次）。
WALK_CASES = [("vx", 0.15, [0.15, 0, 0]), ("vx", -0.15, [-0.15, 0, 0]), ("yaw_rate", 1.0, [0, 0, 1.0]), ("yaw_rate", -1.0, [0, 0, -1.0]), ("vy", 0.2, [0, 0.2, 0])]

#: 起步門檻（PR #32：前進 ≥ 0.10、後退 ≤ −0.12 才會起步）。
THRESHOLD_CASES = [0.06, 0.08, 0.10, 0.12, -0.10, -0.12, -0.15]


# --------------------------------------------------------------------------- 情境
def _pi4_moved(budget: dict, where: str) -> dict:
    """Pi 4 板子和散熱片一起移到 `placements.pi4_board[where]`。"""
    p = budget["placements"]["pi4_board"][where]
    return {"pi4_board": tuple(p), "pi4_heatsink": (p[0], p[1], p[2] + 0.009)}


def profiles(budget: dict) -> list[dict]:
    """要比較的情境。`items` 是 MassItem 清單，`model` 是其他 ModelOptions 參數。"""
    nominal = budget_items(budget, "nominal")
    rows = [
        {"name": "upstream", "label": "上游模型（沒有加裝件）", "items": [], "model": {}},
        {"name": "p2_low", "label": "單板 Pi 4＋加裝件（各元件取下限）", "items": budget_items(budget, "low"), "model": {}},
        {"name": "p2_nominal", "label": "單板 Pi 4＋加裝件（估計值）", "items": nominal, "model": {}},
        {"name": "p2_high", "label": "單板 Pi 4＋加裝件（各元件取上限）", "items": budget_items(budget, "high"), "model": {}},
    ]
    for where in ("top_front", "top_back", "low_mid"):
        rows.append(
            {
                "name": f"p2_nominal_pi4_{where}",
                "label": f"估計值，Pi 4 改放 {where}",
                "items": budget_items(budget, "nominal", placement=_pi4_moved(budget, where)),
                "model": {},
            }
        )
    rows.append({"name": "upstream_kp80", "label": "上游模型，舵機 kp −20%", "items": [], "model": {"kp": KP_NOMINAL * 0.8}})
    rows.append({"name": "p2_high_kp80", "label": "加裝件取上限，舵機 kp −20%", "items": budget_items(budget, "high"), "model": {"kp": KP_NOMINAL * 0.8}})
    return rows


def _opts(profile: dict, **extra) -> ModelOptions:
    kw = dict(profile["model"])
    kw.update(extra)
    return ModelOptions(mass_items=tuple(profile["items"]), **kw)


# --------------------------------------------------------------------------- 靜態
def neck_torque_sweep(m: mujoco.MjModel) -> dict:
    """頸頭在上游訓練範圍內轉動時，neck_pitch 與 head_pitch 的最大靜態重力力矩（N·m）。

    機身固定在起始姿勢，只改 neck_pitch（−0.34～1.1）與 head_pitch（−0.78～0.78）的格點；
    速度為 0 時 `qfrc_bias` 只剩重力項。
    """
    d = mujoco.MjData(m)
    q0 = m.jnt_qposadr[m.joint("floating_base").id]
    worst = {"neck_pitch": 0.0, "head_pitch": 0.0}
    for npitch in np.linspace(-0.34, 1.1, 9):
        for hpitch in np.linspace(-0.78, 0.78, 9):
            d.qpos[:] = 0
            d.qvel[:] = 0
            d.qpos[q0 : q0 + 7] = [0, 0, HOME_BASE_Z, 1, 0, 0, 0]
            for n, v in HOME_POSE.items():
                d.qpos[m.jnt_qposadr[m.joint(n).id]] = v
            d.qpos[m.jnt_qposadr[m.joint("neck_pitch").id]] = npitch
            d.qpos[m.jnt_qposadr[m.joint("head_pitch").id]] = hpitch
            mujoco.mj_forward(m, d)
            for jn in worst:
                worst[jn] = max(worst[jn], abs(float(d.qfrc_bias[m.jnt_dofadr[m.joint(jn).id]])))
    return {k: round(v, 4) for k, v in worst.items()}


# --------------------------------------------------------------------------- 動態
def stand(opts: ModelOptions, seconds: float) -> dict:
    sim = WalkSim(SimOptions(model=opts))
    tr, infos, _ = run_segment(sim, [0, 0, 0], seconds)
    return {
        "fallen": bool(infos[-1].fallen),
        "stepping_fraction": round(stepping_fraction(infos), 3),
        "drift_m": round(math.hypot(tr.fwd, tr.left), 4),
        "tilt_max_deg": round(max(i.tilt_deg for i in infos), 2),
        "base_z_mean_m": round(float(np.mean([i.z for i in infos])), 4),
    }


def walk(opts: ModelOptions, phases: list[int], seconds: float = 8.0) -> list[dict]:
    """同 `measure.velocity_tracking` 的做法：站立 50＋k 步後給指令，前 3 秒當起步，後面算平均速度。"""
    rows = []
    for axis, value, cmd in WALK_CASES:
        got, started, fallen, tilt = [], 0, 0, []
        for k in phases:
            sim = WalkSim(SimOptions(model=opts))
            run_segment(sim, [0, 0, 0], (50 + k) / HZ)
            _, i1, _ = run_segment(sim, cmd, 3.0)
            tr, infos, _ = run_segment(sim, cmd, seconds - 3.0)
            tilt.append(max(i.tilt_deg for i in i1 + infos))
            if infos[-1].fallen or i1[-1].fallen:
                fallen += 1
                continue
            if stepping_fraction(infos) > 0.2:
                started += 1
                T = len(infos) * CONTROL_DT
                got.append({"vx": tr.fwd / T, "vy": tr.left / T, "yaw_rate": tr.yaw / T}[axis])
        rows.append(
            {
                "axis": axis,
                "cmd": value,
                "n": len(phases),
                "started": started,
                "fallen": fallen,
                "actual_mean": round(float(np.mean(got)), 4) if got else None,
                "ratio": round(float(np.mean(got)) / value, 3) if got else None,
                "tilt_max_deg": round(float(np.max(tilt)), 1),
            }
        )
    return rows


def start_threshold(opts: ModelOptions, phases: list[int]) -> list[dict]:
    rows = []
    for v in THRESHOLD_CASES:
        started = fallen = 0
        for k in phases:
            sim = WalkSim(SimOptions(model=opts))
            run_segment(sim, [0, 0, 0], (50 + k) / HZ)
            _, infos, _ = run_segment(sim, [v, 0, 0], 6.0)
            if infos[-1].fallen:
                fallen += 1
            elif stepping_fraction(infos[-100:]) > 0.2:
                started += 1
        rows.append({"vx": v, "n": len(phases), "started": started, "fallen": fallen})
    return rows


def head_standing(opts: ModelOptions) -> list[dict]:
    """站著（速度 0）把頭以 1 rad/s 轉到目標、維持 5 秒（同 PR #32 `head_sweep` 的轉法）。"""
    rows = []
    for name, idx, val in HEAD_CASES:
        sim = WalkSim(SimOptions(model=opts))
        run_segment(sim, [0, 0, 0], 2.0)
        cmd = np.zeros(7)
        infos = []
        n_ramp = int(math.ceil(abs(val) / (1.0 * CONTROL_DT)))
        for s in range(n_ramp):
            cmd[idx] = val * (s + 1) / n_ramp
            infos.append(sim.step(cmd))
            if infos[-1].fallen:
                break
        if not infos[-1].fallen:
            _, more, _ = run_segment(sim, cmd, 5.0)
            infos += more
        rows.append(
            {
                "joint": name,
                "cmd_rad": val,
                "fallen": bool(infos[-1].fallen),
                "tilt_max_deg": round(max(i.tilt_deg for i in infos), 1),
                "actual_rad": round(float(sim.joint_positions()[HEAD_SLICE][idx - 3]), 3),
            }
        )
    return rows


def margin_sweep(base_items: list[MassItem], where: str, masses_g: list[float], phases: list[int], model_kw: dict) -> list[dict]:
    """在估計值之外再加一顆點質量（頭的前方，或機身頂面），看走路與起步從哪裡開始出問題。"""
    body, pos, size = {
        "head_front": ("head_assembly", (0.09, 0.0, 0.215), (0.02, 0.06, 0.03)),
        "trunk_top": ("trunk_assembly", (-0.045, 0.0, 0.10), (0.08, 0.06, 0.02)),
    }[where]
    rows = []
    for g in masses_g:
        items = list(base_items)
        if g > 0:
            items.append(MassItem(f"margin_{where}", body, g / 1000.0, pos, size))
        opts = ModelOptions(mass_items=tuple(items), **model_kw)
        w = walk(opts, phases, seconds=8.0)
        th = start_threshold(opts, phases)
        hs = head_standing(opts)
        st = stand(opts, 10.0)
        rows.append(
            {
                "extra_g": g,
                "stand_fallen": st["fallen"],
                "walk_fallen": int(sum(r["fallen"] for r in w)),
                "walk_runs": int(sum(r["n"] for r in w)),
                "vx_0p15_ratio": next(r["ratio"] for r in w if r["axis"] == "vx" and r["cmd"] == 0.15),
                "vx_0p10_started": next(r["started"] for r in th if r["vx"] == 0.10),
                "vx_0p08_started": next(r["started"] for r in th if r["vx"] == 0.08),
                "head_cases_fallen": [f"{r['joint']} {r['cmd_rad']:+}" for r in hs if r["fallen"]],
                "walk_tilt_max_deg": max(r["tilt_max_deg"] for r in w),
            }
        )
    return rows


def measure_profile(args) -> dict:
    profile, phases, seeds, secs, stand_secs = args
    opts = _opts(profile)
    m = build_model(_opts(profile))
    summary = model_summary(m)
    summary["neck_torque_max_Nm"] = neck_torque_sweep(m)
    return {
        "name": profile["name"],
        "label": profile["label"],
        "model": {k: v for k, v in profile["model"].items()},
        "items": [{"id": i.id, "body": i.body, "mass_g": round(i.mass_kg * 1000, 1), "pos_base_m": list(i.pos_base)} for i in profile["items"]],
        "static": summary,
        "stand": stand(opts, stand_secs),
        "walk": walk(opts, phases),
        "start_threshold": start_threshold(opts, phases),
        "head_standing": head_standing(opts),
        "fall_rate": fall_rate(seeds, secs, label=profile["name"], limited=True, model_kw={"mass_items": tuple(profile["items"]), **profile["model"]}),
    }


def _margin_job(args) -> tuple[str, list[dict]]:
    key, base_items, where, masses, phases, model_kw = args
    return key, margin_sweep(base_items, where, masses, phases, model_kw)


def run_all(quick: bool = False, workers: int | None = None) -> dict:
    budget = load_budget(BUDGET)
    phases = [0, 9, 18] if quick else list(range(0, PHASE_PERIOD_STEPS, 3))
    seeds = 3 if quick else 40
    secs = 10.0 if quick else 60.0
    stand_secs = 5.0 if quick else 20.0
    profs = profiles(budget)
    if quick:
        profs = [p for p in profs if p["name"] in ("upstream", "p2_nominal")]
    workers = workers or min(len(profs), os.cpu_count() or 1)
    nominal = budget_items(budget, "nominal")
    head_masses = [0, 50] if quick else [0, 25, 50, 75, 100, 150, 200]
    trunk_masses = [0, 200] if quick else [0, 100, 200, 400, 600, 800]
    margin_jobs = [
        ("head_front", nominal, "head_front", head_masses, phases, {}),
        ("trunk_top", nominal, "trunk_top", trunk_masses, phases, {}),
    ]
    if not quick:
        margin_jobs.append(("head_front_kp80", nominal, "head_front", head_masses, phases, {"kp": KP_NOMINAL * 0.8}))
    with ProcessPoolExecutor(max_workers=workers) as ex:
        prof_f = [ex.submit(measure_profile, (p, phases, seeds, secs, stand_secs)) for p in profs]
        margin_f = [ex.submit(_margin_job, j) for j in margin_jobs]
        results = [f.result() for f in prof_f]
        margins = dict(f.result() for f in margin_f)
    return {
        "simulated": True,
        "note": "MuJoCo 模擬值（上游策略 BEST_WALK_ONNX_2.onnx、walk_sim 模型）；加裝件的重量與位置都是估計，沒有秤過，不是實機量測",
        "budget": {"file": f"sim/mass_budget/{BUDGET}", "version": budget["version"], "date": budget["date"]},
        "onset_phases": phases,
        "fall_rate_seeds": seeds,
        "fall_rate_seconds": secs,
        "profiles": results,
        "margin": margins,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--workers", type=int, default=None)
    a = ap.parse_args(argv)
    out = run_all(quick=a.quick, workers=a.workers)
    text = json.dumps(out, ensure_ascii=False, indent=1)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text + "\n", encoding="utf-8")
        print(f"寫入 {a.out}")
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
