"""端到端示範（MuJoCo 模擬）：從充電座出發 → 走到房間 → `return_home` 倒退回充。

    cd nous_duck/sim
    python -m nav_sim.demo --trips 10 --out nav_demo_out
    python -m nav_sim.demo --trips 3 --place brother_room --seed 100 --topview

輸出：`trips.png`（軌跡圖：實線是真實位置、虛線是定位估計）、`summary.json`（每趟的結果與統計）。
**全部是模擬**：上游步態策略＋MuJoCo、合成的家、幾何合成的標籤觀測（mock）、mock 的充電訊號。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

from .loop import make_mujoco_loop, plot_runs, synthetic_home

PLACES = ["brother_room", "study_room", "brother_bedside", "living_room", "hallway"]


def run_trip(seed: int, place: str, duck_map=None, max_s: float = 600.0) -> tuple[dict, list[dict], object]:
    loop = make_mujoco_loop(duck_map, seed=seed)
    res: dict = {"seed": seed, "place": place, "simulated": True}
    loop.nav.go_to(place)
    n0 = len(loop.result.events)
    loop.run_until_idle(max_s)
    ev = loop.result.events[n0:]
    last = ev[-1] if ev else {"event": "timeout"}
    tp = loop.body.true_pose
    p = loop.nav.map.places[place]
    res["go_to"] = {
        "ok": last["event"] == "mission_done",
        "reason": last.get("reason"),
        "t_s": round(loop.body.t, 1),
        "arrival_error_m": round(math.hypot(tp.x - p.x, tp.y - p.y), 3),
    }
    t1 = loop.body.t
    loop.dock.reset()
    home_ok = False
    if res["go_to"]["ok"]:
        loop.nav.return_home()
        n0 = len(loop.result.events)
        loop.run_until_idle(max_s)
        ev = loop.result.events[n0:]
        last = ev[-1] if ev else {"event": "timeout"}
        home_ok = last["event"] == "mission_done"
        gap, lat, yaw = loop.dock.gap_and_offsets(loop.body.true_pose)
        res["return_home"] = {
            "ok": home_ok,
            "reason": last.get("reason"),
            "detail": (last.get("data") or {}).get("detail"),
            "t_s": round(loop.body.t - t1, 1),
            "attempts": (last.get("data") or {}).get("attempts"),
            "entries": [
                {"lateral_mm": round(e["lateral_m"] * 1000, 1), "yaw_deg": round(math.degrees(e["yaw_rad"]), 2), "captured": bool(e["captured"])}
                for e in loop.dock.entries
            ],
            "final_gap_mm": round(gap * 1000, 1),
            "charging_signal": "mock",
        }
    res["ok"] = bool(res["go_to"]["ok"] and home_ok)
    res["fallen"] = bool(loop.body.fallen)
    res["max_tilt_deg"] = round(loop.body.max_tilt_deg, 1)
    res["min_zone_distance_m"] = round(loop.result.min_zone_dist_m, 3)
    res["max_localization_error_m"] = round(loop.result.max_est_err_m, 3)
    res["sim_time_s"] = round(loop.body.t, 1)
    return res, loop.result.trace, loop


def summarize(trips: list[dict]) -> dict:
    n = len(trips)
    first = [t["return_home"]["entries"][0] for t in trips if t.get("return_home") and t["return_home"]["entries"]]
    lat = np.array([e["lateral_mm"] for e in first]) if first else np.array([0.0])
    yaw = np.array([e["yaw_deg"] for e in first]) if first else np.array([0.0])
    return {
        "trips": n,
        "round_trip_ok": sum(t["ok"] for t in trips),
        "go_to_ok": sum(t["go_to"]["ok"] for t in trips),
        "return_home_ok": sum(bool(t.get("return_home", {}).get("ok")) for t in trips),
        "docked_on_first_attempt": sum(1 for t in trips if t.get("return_home", {}).get("ok") and t["return_home"]["attempts"] == 1),
        "falls": sum(t["fallen"] for t in trips),
        "min_zone_distance_m": min(t["min_zone_distance_m"] for t in trips),
        "max_localization_error_m": max(t["max_localization_error_m"] for t in trips),
        "first_dock_entry": {
            "n": len(first),
            "lateral_mm_mean": round(float(lat.mean()), 1),
            "lateral_mm_std": round(float(lat.std()), 1),
            "lateral_mm_max_abs": round(float(np.abs(lat).max()), 1),
            "yaw_deg_mean": round(float(yaw.mean()), 2),
            "yaw_deg_std": round(float(yaw.std()), 2),
            "yaw_deg_max_abs": round(float(np.abs(yaw).max()), 2),
            "within_cad_capture": sum(bool(e["captured"]) for e in first),
            "cad_capture_range": "±34 mm、±5°（docs/validation/dock-cad-2026-11-13.md）",
        },
        "failures": [
            {"seed": t["seed"], "place": t["place"], "go_to": t["go_to"], "return_home": t.get("return_home")} for t in trips if not t["ok"]
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m nav_sim.demo", description=__doc__.split("\n")[0])
    ap.add_argument("--trips", type=int, default=5)
    ap.add_argument("--seed", type=int, default=100, help="第一趟的種子；之後每趟加 1")
    ap.add_argument("--place", default=None, help=f"固定目的地；不給就輪流去 {PLACES}")
    ap.add_argument("--out", type=Path, default=Path("nav_demo_out"))
    ap.add_argument("--plot-max", type=int, default=6, help="軌跡圖最多畫幾趟")
    ap.add_argument("--topview", action="store_true", help="另外輸出最後一趟結束時的俯視算圖")
    a = ap.parse_args(argv)

    duck_map = synthetic_home()
    if a.place is not None and a.place not in duck_map.places:
        print(f"沒有這個地點：{a.place}", file=sys.stderr)
        return 2
    a.out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    trips, traces, labels, loop = [], [], [], None
    for i in range(a.trips):
        place = a.place or PLACES[i % len(PLACES)]
        res, trace, loop = run_trip(a.seed + i, place, duck_map)
        trips.append(res)
        if len(traces) < a.plot_max:
            traces.append(trace)
            labels.append(f"seed {res['seed']} {place}: {'ok' if res['ok'] else 'FAIL'}")
        rh = res.get("return_home", {})
        print(f"[{i + 1}/{a.trips}] seed {res['seed']} dock → {place}: {'到達' if res['go_to']['ok'] else '失敗 ' + str(res['go_to']['reason'])}"
              f"（{res['go_to']['t_s']} s）；return_home: {'已回充（mock 訊號）' if rh.get('ok') else '失敗 ' + str(rh.get('reason'))}"
              f"（{rh.get('t_s')} s、嘗試 {rh.get('attempts')} 次）", flush=True)
    summary = {
        "simulated": True,
        "note": "MuJoCo 模擬＋合成的家＋mock 標籤觀測＋mock 充電訊號；不是實機結果",
        "map": duck_map.map_version,
        "wall_time_s": round(time.time() - t0, 1),
        **summarize(trips),
        "per_trip": trips,
    }
    (a.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    plot_runs(duck_map, traces, a.out / "trips.png", title=f"dock -> place -> return_home ({len(traces)} of {a.trips} trips; simulation, synthetic map)", labels=labels)
    if a.topview and loop is not None:
        import mujoco
        from PIL import Image

        r = mujoco.Renderer(loop.body.sim.m, height=480, width=480)
        r.update_scene(loop.body.sim.d, camera="top")
        Image.fromarray(r.render()).save(a.out / "topview.png", optimize=True)
        r.close()
    s = {k: v for k, v in summary.items() if k != "per_trip"}
    print(json.dumps(s, ensure_ascii=False, indent=1))
    return 0 if summary["round_trip_ok"] == a.trips else 1


if __name__ == "__main__":
    sys.exit(main())
