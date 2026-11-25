"""C2：在模擬裡量走、停、轉。全部是**模擬值**，用來當安全上限的初始依據，不是實機量測。

    cd nous_duck/sim
    python -m walk_sim.measure --out ../docs/validation/data/walk-measure-2026-11-25.json
    python -m walk_sim.measure --quick      # 縮小樣本，給測試用

每個量測的做法寫在函式的說明裡；驗證紀錄引用這裡的輸出。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

from .model import CONTROL_DT, HEAD_SLICE, ModelOptions
from .sim import PHASE_PERIOD_STEPS, SimOptions, WalkSim

HZ = int(round(1 / CONTROL_DT))


def _wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


class Track:
    """累積機身座標系下的位移與偏航（不受 ±π 折返影響）。"""

    def __init__(self, sim: WalkSim):
        self.sim = sim
        self.x, self.y, self.yaw_prev = sim.base_pose()
        self.fwd = self.left = self.yaw = self.path = 0.0

    def update(self) -> None:
        x, y, yaw = self.sim.base_pose()
        dx, dy = x - self.x, y - self.y
        c, s = math.cos(self.yaw_prev), math.sin(self.yaw_prev)
        self.fwd += c * dx + s * dy
        self.left += -s * dx + c * dy
        self.path += math.hypot(dx, dy)
        self.yaw += _wrap(yaw - self.yaw_prev)
        self.x, self.y, self.yaw_prev = x, y, yaw


def ramp(cur: np.ndarray, target: np.ndarray, dv: float = 0.01, dw: float = 0.05) -> np.ndarray:
    """ADR-0009 §2.5 的加速度限制：每圈 vx／vy 最多變 0.01 m/s、yaw 最多變 0.05 rad/s。"""
    out = cur.copy()
    for i, lim in ((0, dv), (1, dv), (2, dw)):
        out[i] = cur[i] + max(-lim, min(lim, target[i] - cur[i]))
    return out


def run_segment(sim: WalkSim, cmd, seconds: float, limited: bool = False, cur=None):
    """執行一段指令；回傳（Track、每步的 StepInfo、最後送出的指令）。"""
    tr = Track(sim)
    infos = []
    target = np.zeros(7)
    target[: len(cmd)] = cmd
    cur = np.zeros(7) if cur is None else np.asarray(cur, dtype=float).copy()
    for _ in range(int(round(seconds * HZ))):
        if limited:
            cur = ramp(cur, target)
            cur[3:] = target[3:]
        else:
            cur = target
        info = sim.step(cur)
        tr.update()
        infos.append(info)
        if info.fallen:
            break
    return tr, infos, cur


def stepping_fraction(infos) -> float:
    """有一隻腳離地的時間比例（0＝一直雙腳著地，沒有在踏步）。"""
    if not infos:
        return 0.0
    return float(np.mean([not (i.contact_left and i.contact_right) for i in infos]))


# --------------------------------------------------------------------------- 量測
def velocity_tracking(phases: list[int], seconds: float = 8.0, **model_kw) -> list[dict]:
    """指令速度 vs 實際速度。

    每個指令從站立開始，在不同的步態相位下指令（站立 `50 + k` 步後才給指令，k 為相位），
    給 `seconds` 秒。前 3 秒當起步，後面算平均速度。`started`＝後段有在踏步的比例 > 0.2。
    """
    grid = (
        [("vx", v, [v, 0, 0]) for v in (-0.15, -0.12, -0.10, -0.08, -0.05, 0.03, 0.05, 0.08, 0.10, 0.12, 0.15)]
        + [("vy", v, [0, v, 0]) for v in (-0.20, -0.15, -0.10, -0.05, 0.05, 0.10, 0.15, 0.20)]
        + [("yaw_rate", v, [0, 0, v]) for v in (-1.0, -0.6, -0.3, -0.15, 0.15, 0.3, 0.6, 1.0)]
    )
    rows = []
    for axis, value, cmd in grid:
        got, started, fallen = [], 0, 0
        for k in phases:
            sim = WalkSim(SimOptions(model=ModelOptions(**model_kw)))
            run_segment(sim, [0, 0, 0], (50 + k) / HZ)
            run_segment(sim, cmd, 3.0)
            tr, infos, _ = run_segment(sim, cmd, seconds - 3.0)
            T = len(infos) * CONTROL_DT
            if infos[-1].fallen:
                fallen += 1
                continue
            if stepping_fraction(infos) > 0.2:
                started += 1
                got.append({"vx": tr.fwd / T, "vy": tr.left / T, "yaw_rate": tr.yaw / T}[axis])
        rows.append(
            {
                "axis": axis,
                "cmd": value,
                "n": len(phases),
                "started": started,
                "fallen": fallen,
                "actual_mean": round(float(np.mean(got)), 4) if got else None,
                "actual_min": round(float(np.min(got)), 4) if got else None,
                "actual_max": round(float(np.max(got)), 4) if got else None,
                "ratio": round(float(np.mean(got)) / value, 3) if got else None,
            }
        )
    return rows


def start_stop(phases: list[int], cmd=(0.15, 0, 0), limited: bool = False) -> dict:
    """起步與停下。

    起步：從給指令到第一次有腳離地的時間、到達穩態速度 90% 的時間與這段走的距離。
    停下：指令歸零後，到「兩腳著地且持續 0.3 s」（ADR-0009 §2.5 的暫停條件）的時間與滑行距離。
    """
    t_first, t_90, d_90, t_stop, d_stop, never = [], [], [], [], [], 0
    for k in phases:
        sim = WalkSim()
        run_segment(sim, [0, 0, 0], (50 + k) / HZ)
        tr, infos, cur = run_segment(sim, cmd, 8.0, limited=limited)
        if stepping_fraction(infos[-100:]) < 0.2:
            never += 1
            continue
        # 穩態速度：最後 3 秒。
        xs = np.array([[i.x, i.y] for i in infos])
        dist = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(xs, axis=0).T))])
        v_ss = (dist[-1] - dist[-150]) / (150 * CONTROL_DT)
        first = next(n for n, i in enumerate(infos) if not (i.contact_left and i.contact_right))
        t_first.append(first * CONTROL_DT)
        # 用 1 s 滑動窗的平均速度判斷「到 90%」。
        w = 50
        v = (dist[w:] - dist[:-w]) / (w * CONTROL_DT)
        idx = int(np.argmax(v >= 0.9 * v_ss))
        t_90.append((idx + w) * CONTROL_DT)
        d_90.append(float(dist[idx + w]))
        # 停下。
        tr2, infos2, _ = run_segment(sim, [0, 0, 0], 5.0, limited=limited, cur=cur)
        run_len, stop_i = 0, None
        for n, i in enumerate(infos2):
            run_len = run_len + 1 if (i.contact_left and i.contact_right) else 0
            if run_len >= int(0.3 * HZ):
                stop_i = n
                break
        if stop_i is None:
            t_stop.append(float("nan"))
            d_stop.append(float("nan"))
        else:
            t_stop.append((stop_i + 1) * CONTROL_DT)
            p = np.array([[i.x, i.y] for i in infos2[: stop_i + 1]])
            d_stop.append(float(np.hypot(*(p[-1] - p[0]))) if len(p) > 1 else 0.0)

    def stat(a):
        a = np.array(a, dtype=float)
        if len(a) == 0 or np.all(np.isnan(a)):
            return None
        return {"mean": round(float(np.nanmean(a)), 3), "max": round(float(np.nanmax(a)), 3)}

    return {
        "cmd": list(cmd),
        "limited": limited,
        "n": len(phases),
        "never_started": never,
        "t_first_step_s": stat(t_first),
        "t_to_90pct_s": stat(t_90),
        "dist_to_90pct_m": stat(d_90),
        "t_stop_both_feet_0p3s_s": stat(t_stop),
        "dist_stop_m": stat(d_stop),
        "stop_not_reached": int(np.sum(np.isnan(np.array(t_stop, dtype=float)))) if t_stop else 0,
    }


def zero_command(seconds: float = 20.0) -> dict:
    """速度指令為 0 時是否原地踏步，以及站著的漂移。"""
    out = {}
    for label, pre in (("from_reset", None), ("after_walking", [0.15, 0, 0])):
        sim = WalkSim()
        if pre is not None:
            run_segment(sim, pre, 4.0)
            run_segment(sim, [0, 0, 0], 2.0)
        tr, infos, _ = run_segment(sim, [0, 0, 0], seconds)
        out[label] = {
            "stepping_fraction": round(stepping_fraction(infos), 3),
            "drift_m": round(math.hypot(tr.fwd, tr.left), 4),
            "yaw_drift_deg": round(math.degrees(tr.yaw), 2),
            "tilt_max_deg": round(max(i.tilt_deg for i in infos), 2),
        }
    return out


def turn_in_place(phases: list[int]) -> list[dict]:
    """原地轉 90°／180°：用真實偏航當回授，到角度就把指令歸零；量時間、位移與超過的角度。"""
    rows = []
    for target_deg in (90, 180):
        for rate in (0.5, 1.0):
            for sign in (1, -1):
                ts, disp, over, failed = [], [], [], 0
                for k in phases:
                    sim = WalkSim()
                    run_segment(sim, [0, 0, 0], (50 + k) / HZ)
                    tr = Track(sim)
                    n = 0
                    while abs(tr.yaw) < math.radians(target_deg) and n < 40 * HZ:
                        sim.step([0, 0, sign * rate])
                        tr.update()
                        n += 1
                    if n >= 40 * HZ:
                        failed += 1
                        continue
                    t_turn = n * CONTROL_DT
                    for _ in range(2 * HZ):
                        sim.step([0, 0, 0])
                        tr.update()
                    ts.append(t_turn)
                    disp.append(math.hypot(tr.x - 0.0, tr.y - 0.0))
                    over.append(math.degrees(abs(tr.yaw)) - target_deg)
                rows.append(
                    {
                        "target_deg": target_deg,
                        "cmd_yaw_rate": sign * rate,
                        "n": len(phases),
                        "failed": failed,
                        "time_s_mean": round(float(np.mean(ts)), 2) if ts else None,
                        "time_s_max": round(float(np.max(ts)), 2) if ts else None,
                        "displacement_m_mean": round(float(np.mean(disp)), 3) if disp else None,
                        "displacement_m_max": round(float(np.max(disp)), 3) if disp else None,
                        "overshoot_deg_mean": round(float(np.mean(over)), 1) if over else None,
                        "overshoot_deg_max": round(float(np.max(over)), 1) if over else None,
                    }
                )
    return rows


def head_effect() -> list[dict]:
    """頭部指令對平衡的影響，以及兩種接法（runtime／policy）下頭實際轉到哪裡。"""
    rows = []
    cases = [
        ("head_yaw", 5, 0.5),
        ("head_yaw", 5, 1.5),
        ("head_yaw", 5, -1.5),
        ("neck_pitch", 3, 1.1),
        ("neck_pitch", 3, -0.34),
        ("head_pitch", 4, 0.78),
        ("head_pitch", 4, -0.78),
        ("head_roll", 6, 0.5),
    ]
    for mode in ("runtime", "policy"):
        for walking in (False, True):
            for name, idx, val in cases:
                sim = WalkSim(SimOptions(head_mode=mode))
                base = [0.15, 0, 0] if walking else [0, 0, 0]
                run_segment(sim, base, 3.0)
                cmd = np.zeros(7)
                cmd[:3] = base
                cmd[idx] = val
                tr, infos, _ = run_segment(sim, cmd, 5.0)
                q = sim.joint_positions()[HEAD_SLICE][idx - 3]
                T = len(infos) * CONTROL_DT
                rows.append(
                    {
                        "head_mode": mode,
                        "walking": walking,
                        "joint": name,
                        "cmd_rad": val,
                        "actual_rad": round(float(q), 3),
                        "tilt_max_deg": round(max(i.tilt_deg for i in infos), 1),
                        "fallen": bool(infos[-1].fallen),
                        "speed_m_s": round(tr.fwd / T, 3),
                    }
                )
    return rows


def accel_limit(phases: list[int]) -> list[dict]:
    """ADR-0009 §2.5 的加速度限制下是否穩定：同一組指令切換，比較「直接跳」與「限制斜率」。"""
    seq = [([0.15, 0, 0], 4), ([-0.15, 0, 0], 4), ([0, 0.2, 0], 4), ([0, 0, 1.0], 4), ([0.15, 0, -1.0], 4), ([0, 0, 0], 3)]
    rows = []
    for limited in (False, True):
        tilt, fallen = [], 0
        for k in phases:
            sim = WalkSim()
            run_segment(sim, [0, 0, 0], (50 + k) / HZ)
            cur = np.zeros(7)
            worst = 0.0
            for cmd, sec in seq:
                _, infos, cur = run_segment(sim, cmd, sec, limited=limited, cur=cur)
                worst = max(worst, max(i.tilt_deg for i in infos))
                if infos[-1].fallen:
                    fallen += 1
                    break
            tilt.append(worst)
        rows.append(
            {
                "limited": limited,
                "n": len(phases),
                "fallen": fallen,
                "tilt_max_deg_mean": round(float(np.mean(tilt)), 1),
                "tilt_max_deg_worst": round(float(np.max(tilt)), 1),
            }
        )
    return rows


def fall_rate(seeds: int, seconds: float = 60.0, **kw) -> dict:
    """多個隨機種子的跌倒率：每 2～5 秒換一次隨機指令（上游範圍內），加訓練等級的感測雜訊與起始擾動。"""
    label = kw.pop("label", "nominal")
    limits = kw.pop("limits", (0.15, 0.2, 1.0))
    model_kw = kw.pop("model_kw", {})
    falls, times, tilt = 0, [], []
    for seed in range(seeds):
        rng = np.random.default_rng(1000 + seed)
        sim = WalkSim(
            SimOptions(seed=seed, gyro_noise=0.1, accel_noise=0.05, init_vel_noise=0.05, init_yaw_noise=math.pi, model=ModelOptions(**model_kw))
        )
        t, worst, fell = 0.0, 0.0, False
        cur = np.zeros(7)
        while t < seconds and not fell:
            seg = rng.uniform(2, 5)
            cmd = [rng.uniform(-limits[0], limits[0]), rng.uniform(-limits[1], limits[1]), rng.uniform(-limits[2], limits[2])]
            if rng.random() < 0.2:
                cmd = [0, 0, 0]
            _, infos, cur = run_segment(sim, cmd, seg, limited=kw.get("limited", False), cur=cur)
            worst = max(worst, max(i.tilt_deg for i in infos))
            t += seg
            fell = infos[-1].fallen
        falls += int(fell)
        tilt.append(worst)
        if fell:
            times.append(round(sim.t, 1))
    return {
        "label": label,
        "seeds": seeds,
        "seconds_each": seconds,
        "falls": falls,
        "fall_rate": round(falls / seeds, 3),
        "fall_times_s": times,
        "tilt_max_deg_p50": round(float(np.median(tilt)), 1),
        "tilt_max_deg_worst": round(float(np.max(tilt)), 1),
    }


def odometry(phases: list[int]) -> dict:
    """為什麼不能只靠指令積分或步數算位置。

    同一段指令（前進 → 左轉 90° 的時間量 → 前進 → 側移），在不同條件下跑；
    「指令積分」把指令速度對時間積分當成位置；「步數」用名目條件下量到的每步距離 × 步數。
    回報兩種估計跟真實終點的差距。
    """
    script = [([0.15, 0, 0], 10.0), ([0, 0, 0.6], 2.6), ([0.15, 0, 0], 10.0), ([0, 0.2, 0], 5.0)]
    conds = [
        ("nominal", {}),
        ("floor_friction_0.3", {"floor_friction": 0.3}),
        ("floor_friction_1.0", {"floor_friction": 1.0}),
        ("extra_mass_0.2kg", {"extra_mass_kg": 0.2}),
        ("kp_minus_20pct", {"kp": 13.37 * 0.8}),
    ]

    def run(model_kw, k):
        sim = WalkSim(SimOptions(model=ModelOptions(**model_kw)))
        run_segment(sim, [0, 0, 0], (50 + k) / HZ)
        x0, y0, yaw0 = sim.base_pose()
        ex, ey, eyaw = x0, y0, yaw0  # 指令積分
        steps = 0
        prev = (True, True)
        path = 0.0
        px, py = x0, y0
        for cmd, sec in script:
            for _ in range(int(sec * HZ)):
                info = sim.step(cmd)
                ex += (math.cos(eyaw) * cmd[0] - math.sin(eyaw) * cmd[1]) * CONTROL_DT
                ey += (math.sin(eyaw) * cmd[0] + math.cos(eyaw) * cmd[1]) * CONTROL_DT
                eyaw += cmd[2] * CONTROL_DT
                now = (info.contact_left, info.contact_right)
                steps += int(now[0] and not prev[0]) + int(now[1] and not prev[1])
                prev = now
                path += math.hypot(info.x - px, info.y - py)
                px, py = info.x, info.y
        x, y, yaw = sim.base_pose()
        return {
            "true_end": (x, y, yaw),
            "cmd_end": (ex, ey, eyaw),
            "steps": steps,
            "path_m": path,
            "fallen": info.fallen,
        }

    rows = []
    nominal_step_len = None
    for label, kw in conds:
        errs, yaw_errs, paths, steps_all, step_errs = [], [], [], [], []
        for k in phases:
            r = run(kw, k)
            if r["fallen"]:
                continue
            errs.append(math.hypot(r["true_end"][0] - r["cmd_end"][0], r["true_end"][1] - r["cmd_end"][1]))
            yaw_errs.append(abs(math.degrees(_wrap(r["true_end"][2] - r["cmd_end"][2]))))
            paths.append(r["path_m"])
            steps_all.append(r["steps"])
        if label == "nominal":
            nominal_step_len = float(np.sum(paths) / max(1, np.sum(steps_all)))
        for p, s in zip(paths, steps_all):
            step_errs.append(abs(s * nominal_step_len - p))
        rows.append(
            {
                "condition": label,
                "n": len(errs),
                "path_m_mean": round(float(np.mean(paths)), 3),
                "path_m_min": round(float(np.min(paths)), 3),
                "path_m_max": round(float(np.max(paths)), 3),
                "cmd_integration_pos_err_m_mean": round(float(np.mean(errs)), 3),
                "cmd_integration_pos_err_m_max": round(float(np.max(errs)), 3),
                "cmd_integration_yaw_err_deg_mean": round(float(np.mean(yaw_errs)), 1),
                "cmd_integration_yaw_err_deg_max": round(float(np.max(yaw_errs)), 1),
                "steps_mean": round(float(np.mean(steps_all)), 1),
                "step_count_path_err_m_mean": round(float(np.mean(step_errs)), 3),
                "step_count_path_err_m_max": round(float(np.max(step_errs)), 3),
            }
        )
    cmd_path = sum(math.hypot(c[0], c[1]) * s for c, s in script)
    return {"script": script, "commanded_path_m": round(cmd_path, 3), "nominal_step_length_m": round(nominal_step_len, 4), "rows": rows}


def combo_grid(phases: list[int]) -> list[dict]:
    """前後速度與轉向一起下時的實際反應（導航的路徑追蹤要用的組合），以及前進時加側移。"""
    combos = [(vx, 0.0, w) for vx in (0.10, 0.12, 0.15, -0.12, -0.15) for w in (-1.0, -0.6, -0.3, 0.3, 0.6, 1.0)]
    combos += [(0.15, vy, 0.0) for vy in (-0.2, -0.1, 0.1, 0.2)] + [(-0.15, vy, 0.0) for vy in (-0.2, 0.2)]
    rows = []
    for vx, vy, w in combos:
        a, started, fallen = [], 0, 0
        for k in phases:
            sim = WalkSim()
            run_segment(sim, [0, 0, 0], (50 + k) / HZ)
            run_segment(sim, [vx, vy, w], 3.0)
            # 用機身座標的瞬時速度平均（有轉向時，位移投影到起始方向沒有意義）。
            tr, infos, _ = run_segment(sim, [vx, vy, w], 5.0)
            if infos[-1].fallen:
                fallen += 1
                continue
            if stepping_fraction(infos) > 0.2:
                started += 1
                T = len(infos) * CONTROL_DT
                a.append((float(np.mean([i.vx_body for i in infos])), float(np.mean([i.vy_body for i in infos])), tr.yaw / T))
        m = np.mean(a, axis=0) if a else [None] * 3
        rows.append(
            {
                "cmd": [vx, vy, w],
                "n": len(phases),
                "started": started,
                "fallen": fallen,
                "actual_vx": None if m[0] is None else round(float(m[0]), 4),
                "actual_vy": None if m[1] is None else round(float(m[1]), 4),
                "actual_yaw_rate": None if m[2] is None else round(float(m[2]), 4),
            }
        )
    return rows


def sustain(phases: list[int]) -> list[dict]:
    """已經在走的時候，把指令降到「起步門檻以下」還會不會繼續走。"""
    rows = []
    for pre, cmd in [
        ([0.15, 0, 0], [0.08, 0, 0]),
        ([0.15, 0, 0], [0.05, 0, 0]),
        ([-0.15, 0, 0], [-0.10, 0, 0]),
        ([-0.15, 0, 0], [-0.08, 0, 0]),
        ([0, 0, 1.0], [0, 0, 0.3]),
        ([0, 0, -1.0], [0, 0, -0.3]),
        ([0, 0, -1.0], [0, 0, -0.15]),
        ([0.15, 0, 0], [0, -0.2, 0]),
        ([0.15, 0, 0], [0, 0.1, 0]),
    ]:
        a, kept = [], 0
        for k in phases:
            sim = WalkSim()
            run_segment(sim, [0, 0, 0], (50 + k) / HZ)
            run_segment(sim, pre, 3.0)
            run_segment(sim, cmd, 2.0)
            tr, infos, _ = run_segment(sim, cmd, 5.0)
            if stepping_fraction(infos) > 0.2:
                kept += 1
                T = len(infos) * CONTROL_DT
                a.append((float(np.mean([i.vx_body for i in infos])), float(np.mean([i.vy_body for i in infos])), tr.yaw / T))
        m = np.mean(a, axis=0) if a else [None] * 3
        rows.append({"pre": pre, "cmd": cmd, "n": len(phases), "kept_walking": kept,
                     "actual": None if m[0] is None else [round(float(v), 4) for v in m]})
    return rows


def head_sweep() -> list[dict]:
    """頭部角度以 1 rad/s 慢慢轉到目標（runtime 接法）時的平衡與走路速度。"""
    rows = []
    cases = [("head_yaw", 5, v) for v in (0.3, 0.5, 0.8, 1.0, 1.5, -0.5, -1.0, -1.5)]
    cases += [("neck_pitch", 3, v) for v in (-0.34, -0.2, 0.3, 0.6, 0.9, 1.1)]
    cases += [("head_pitch", 4, v) for v in (-0.78, -0.4, 0.3, 0.78)]
    cases += [("head_roll", 6, v) for v in (-0.5, 0.5)]
    for walking in (False, True):
        for name, idx, val in cases:
            sim = WalkSim()
            base = [0.15, 0, 0] if walking else [0, 0, 0]
            run_segment(sim, base, 3.0)
            cmd = np.zeros(7)
            cmd[:3] = base
            worst = 0.0
            fallen = False
            n_ramp = int(abs(val) / 1.0 * HZ)
            for n in range(n_ramp):
                cmd[idx] = val * (n + 1) / n_ramp
                info = sim.step(cmd)
                worst = max(worst, info.tilt_deg)
            tr, infos, _ = run_segment(sim, cmd, 6.0)
            worst = max(worst, max(i.tilt_deg for i in infos))
            T = len(infos) * CONTROL_DT
            rows.append(
                {
                    "walking": walking,
                    "joint": name,
                    "cmd_rad": val,
                    "actual_rad": round(float(sim.joint_positions()[HEAD_SLICE][idx - 3]), 3),
                    "tilt_max_deg": round(worst, 1),
                    "fallen": bool(infos[-1].fallen),
                    "speed_m_s": round(tr.fwd / T, 3),
                    "stepping_fraction": round(stepping_fraction(infos), 2),
                }
            )
    return rows


def run_all(quick: bool = False) -> dict:
    phases = [0, 9, 18] if quick else list(range(0, PHASE_PERIOD_STEPS, 3))
    seeds = 4 if quick else 40
    secs = 20.0 if quick else 60.0
    out = {
        "simulated": True,
        "note": "MuJoCo 模擬值（上游策略 BEST_WALK_ONNX_2.onnx、本 repo 的 walk_sim 模型），不是實機量測",
        "onset_phases": phases,
    }
    out["velocity_tracking"] = velocity_tracking(phases)
    out["start_stop"] = [
        start_stop(phases, (0.15, 0, 0), False),
        start_stop(phases, (0.15, 0, 0), True),
        start_stop(phases, (0, 0, 1.0), False),
        start_stop(phases, (0, 0, 1.0), True),
    ]
    out["zero_command"] = zero_command(10.0 if quick else 20.0)
    out["turn_in_place"] = turn_in_place(phases)
    out["head_effect"] = head_effect()
    out["accel_limit"] = accel_limit(phases)
    out["fall_rate"] = [
        fall_rate(seeds, secs, label="上游範圍、指令直接跳"),
        fall_rate(seeds, secs, label="上游範圍、ADR-0009 加速度限制", limited=True),
        fall_rate(seeds, secs, label="室內上限（vx 0.10、vy 0.10、yaw 0.6）、加速度限制", limited=True, limits=(0.10, 0.10, 0.6)),
        fall_rate(seeds, secs, label="機身加 0.2 kg、上游範圍、加速度限制", limited=True, model_kw={"extra_mass_kg": 0.2}),
        fall_rate(seeds, secs, label="機身加 0.4 kg、上游範圍、加速度限制", limited=True, model_kw={"extra_mass_kg": 0.4}),
        fall_rate(seeds, secs, label="地板摩擦 0.3、上游範圍、加速度限制", limited=True, model_kw={"floor_friction": 0.3}),
    ]
    out["odometry"] = odometry(phases)
    out["combo_grid"] = combo_grid(phases)
    out["sustain"] = sustain(phases)
    out["head_sweep"] = head_sweep()
    return out



def gait_table(phases: list[int] | None = None) -> dict:
    """「指令 → 實際機身速度」的反應表，給導航當短程里程的模型（`duck_nav/data/gait_response.sim.json`）。

    每格從站立開始，在幾個步態相位下指令，3 秒後取 5 秒的機身座標平均速度。沒起步的格子記 0。
    **模擬值**；實機要用同樣的方法重量一次。

        python -c "from walk_sim.measure import write_gait_table; write_gait_table()"
    """
    phases = phases or list(range(0, PHASE_PERIOD_STEPS, 3))
    vxs = [-0.15, -0.12, 0.0, 0.10, 0.12, 0.15]
    ws = [-1.0, -0.6, -0.3, 0.0, 0.3, 0.6, 1.0]
    cells = []
    for vx in vxs:
        row = []
        for w in ws:
            acc, started = [], 0
            if vx == 0.0 and w == 0.0:
                row.append({"vx": 0.0, "vy": 0.0, "yaw_rate": 0.0, "started": 1.0})
                continue
            for k in phases:
                sim = WalkSim()
                run_segment(sim, [0, 0, 0], (50 + k) / HZ)
                run_segment(sim, [vx, 0, w], 3.0)
                tr, infos, _ = run_segment(sim, [vx, 0, w], 5.0)
                if stepping_fraction(infos) > 0.2 and not infos[-1].fallen:
                    started += 1
                    T = len(infos) * CONTROL_DT
                    acc.append((np.mean([i.vx_body for i in infos]), np.mean([i.vy_body for i in infos]), tr.yaw / T))
            frac = started / len(phases)
            if frac >= 0.99:
                m = np.mean(acc, axis=0)
                row.append({"vx": round(float(m[0]), 4), "vy": round(float(m[1]), 4), "yaw_rate": round(float(m[2]), 4), "started": 1.0})
            else:
                row.append({"vx": 0.0, "vy": 0.0, "yaw_rate": 0.0, "started": round(frac, 2)})
        cells.append(row)
    return {
        "simulated": True,
        "source": "nous_duck/sim/walk_sim/measure.py gait_table()；MuJoCo 模擬值，不是實機量測",
        "policy": "BEST_WALK_ONNX_2.onnx",
        "cmd_vx": vxs,
        "cmd_yaw_rate": ws,
        "cells": cells,
        "notes": "cells[i][j] 對應 cmd_vx[i]、cmd_yaw_rate[j]；started < 1 的格子從站立起步不可靠，導航不使用",
    }


def write_gait_table(path: Path | None = None) -> Path:
    from .model import REPO_ROOT

    path = path or REPO_ROOT / "nous_duck/robot/navigation/duck_nav/data/gait_response.sim.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    t = gait_table()
    lines = ["{"]
    for k, v in t.items():
        if k == "cells":
            lines.append(' "cells": [')
            lines += ["  " + json.dumps(r) + ("," if i < len(v) - 1 else "") for i, r in enumerate(v)]
            lines.append(" ],")
        else:
            lines.append(f' "{k}": {json.dumps(v, ensure_ascii=False)},')
    lines[-1] = lines[-1].rstrip(",")
    lines.append("}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m walk_sim.measure")
    p.add_argument("--quick", action="store_true")
    p.add_argument("--out", type=Path, default=None)
    a = p.parse_args(argv)
    res = run_all(a.quick)
    text = json.dumps(res, ensure_ascii=False, indent=1)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
