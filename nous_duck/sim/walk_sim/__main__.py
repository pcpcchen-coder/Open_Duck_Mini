"""無頭執行全身走路模擬，輸出軌跡 CSV 與截圖／短 GIF。

    cd nous_duck/sim
    python -m walk_sim --vx 0.15 --duration 10 --out /tmp/walk          # 直線
    python -m walk_sim --yaw-rate 0.5 --duration 8 --gif                 # 原地轉
    python -m walk_sim --script "2:0,0,0;8:0.15,0,0;3:0,0,0" --out out   # 分段指令（秒:vx,vy,yaw）

輸出的數字是**模擬值**，不是實機量測。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .model import CONTROL_DT, ModelOptions
from .sim import SimOptions, WalkSim


def parse_script(text: str) -> list[tuple[float, list[float]]]:
    out = []
    for seg in text.split(";"):
        dur, vals = seg.split(":")
        v = [float(x) for x in vals.split(",")]
        out.append((float(dur), v + [0.0] * (7 - len(v))))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m walk_sim", description=__doc__.split("\n")[0])
    p.add_argument("--vx", type=float, default=0.0)
    p.add_argument("--vy", type=float, default=0.0)
    p.add_argument("--yaw-rate", type=float, default=0.0)
    p.add_argument("--head", type=float, nargs=4, default=[0, 0, 0, 0], metavar=("NECK_PITCH", "HEAD_PITCH", "HEAD_YAW", "HEAD_ROLL"))
    p.add_argument("--duration", type=float, default=10.0, help="走路秒數（前面另有 --settle 秒站立）")
    p.add_argument("--settle", type=float, default=1.0)
    p.add_argument("--script", type=str, default=None, help='分段指令 "秒:vx,vy,yaw;..."，設了就忽略 --vx 等')
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--head-mode", choices=["runtime", "policy"], default="runtime")
    p.add_argument("--solver", choices=["default", "playground"], default="default")
    p.add_argument("--extra-mass", type=float, default=0.0, help="加在機身的額外質量（kg）")
    p.add_argument("--out", type=Path, default=Path("walk_sim_out"))
    p.add_argument("--png", action="store_true", help="輸出結束時的截圖")
    p.add_argument("--gif", action="store_true", help="輸出短 GIF（每 0.2 s 一格）")
    a = p.parse_args(argv)

    opt = SimOptions(seed=a.seed, head_mode=a.head_mode, model=ModelOptions(solver=a.solver, extra_mass_kg=a.extra_mass))
    sim = WalkSim(opt)
    script = parse_script(a.script) if a.script else [
        (a.settle, [0.0] * 7),
        (a.duration, [a.vx, a.vy, a.yaw_rate, *a.head]),
    ]
    a.out.mkdir(parents=True, exist_ok=True)
    snap = None
    if a.png or a.gif:
        from .render import Snapshotter

        snap = Snapshotter(sim.m, 320, 240) if a.gif else Snapshotter(sim.m)

    rows = []
    fell_at = None
    for dur, cmd in script:
        for _ in range(int(round(dur / CONTROL_DT))):
            info = sim.step(cmd)
            rows.append({**asdict(info), "cmd_vx": cmd[0], "cmd_vy": cmd[1], "cmd_yaw_rate": cmd[2]})
            if snap is not None and a.gif and sim.steps % 10 == 0:
                snap.grab(sim.d, lookat=[info.x, info.y, 0.15])
            if info.fallen and fell_at is None:
                fell_at = info.t
        if fell_at is not None:
            break

    csv_path = a.out / "trajectory.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    last = rows[-1]
    summary = {
        "simulated": True,
        "note": "MuJoCo 模擬值，不是實機量測",
        "duration_s": last["t"],
        "final": {k: round(last[k], 4) for k in ("x", "y", "z", "yaw", "tilt_deg")},
        "fell_at_s": fell_at,
        "script": script,
        "csv": str(csv_path),
    }
    if snap is not None:
        if a.png:
            snap.grab(sim.d, lookat=[last["x"], last["y"], 0.15], keep=not a.gif)
            snap.save_png(a.out / "final.png", snap.grab(sim.d, keep=False))
            summary["png"] = str(a.out / "final.png")
        if a.gif:
            snap.save_gif(a.out / "walk.gif")
            summary["gif"] = str(a.out / "walk.gif")
        snap.close()
    (a.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if fell_at is not None else 0


if __name__ == "__main__":
    sys.exit(main())
