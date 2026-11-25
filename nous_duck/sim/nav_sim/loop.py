"""建立「MuJoCo 身體＋mock 感測器＋導航器」的閉迴路，以及畫軌跡圖。"""

from __future__ import annotations

from pathlib import Path

from duck_nav.geometry import Pose2D
from duck_nav.mapfile import DuckMap, load_map
from duck_nav.mock_sensors import MockDockContact, MockTagCamera
from duck_nav.navigator import BASE_TO_CONTACT_M, NavConfig, Navigator
from duck_nav.testing import ClosedLoop

from .scene import MujocoBody

SYNTHETIC_HOME = Path(__file__).resolve().parents[2] / "robot/navigation/maps/synthetic_home.duckmap.json"


def sim_dock_trim() -> float:
    """模擬量到的回充橫向校正量（`duck_nav/data/dock_trim.sim.json`）。"""
    import json

    p = Path(__file__).resolve().parents[2] / "robot/navigation/duck_nav/data/dock_trim.sim.json"
    return float(json.loads(p.read_text(encoding="utf-8"))["dock_lateral_trim_m"])


def synthetic_home() -> DuckMap:
    return load_map(SYNTHETIC_HOME)


def make_mujoco_loop(duck_map: DuckMap | None = None, start: Pose2D | None = None, seed: int = 0, docked: bool = True, extra_boxes=(), config: NavConfig | None = None, use_gyro: bool = True, **body_kw) -> ClosedLoop:
    """`extra_boxes`：[(id, rect, height)]，地圖上沒有的障礙（關著的門、箱子）。mock 感測器也看得到它們。"""
    duck_map = duck_map or synthetic_home()
    if config is None:
        config = NavConfig(dock_lateral_trim_m=sim_dock_trim())
    body = MujocoBody(duck_map, start, seed=seed, extra_boxes=extra_boxes, **body_kw)
    nav = Navigator(duck_map, config=config, mock=True, clock_ms=lambda: int(1_795_600_000_000 + body.t * 1000))
    cam = MockTagCamera(duck_map, seed=seed + 1)
    cam.extra_boxes = [(rect, h) for _, rect, h in extra_boxes]
    dock = MockDockContact(duck_map, BASE_TO_CONTACT_M) if duck_map.dock else None
    loop = ClosedLoop(nav, body, cam, dock, use_gyro=use_gyro)
    if docked:
        nav.set_docked()
    return loop


def plot_runs(duck_map: DuckMap, traces: list[list[dict]], path: Path, title: str = "", labels: list[str] | None = None) -> None:
    """畫地圖（占據格、禁區、標籤、地點）與軌跡（真實位置實線、估計位置虛線）。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    g = duck_map.grid
    fig, ax = plt.subplots(figsize=(6.4, 6.4), dpi=110)
    ext = [g.origin[0], g.origin[0] + g.occ.shape[1] * g.resolution, g.origin[1], g.origin[1] + g.occ.shape[0] * g.resolution]
    ax.imshow(np.where(g.occ, 0.35, 1.0), cmap="gray", vmin=0, vmax=1, origin="lower", extent=ext, interpolation="nearest")
    for z in duck_map.zones.values():
        x0, y0, x1, y1 = z.rect
        ax.add_patch(plt.Rectangle((x0, y0), x1 - x0, y1 - y0, color="#d62728" if z.kind == "stairs" else "#ff7f0e", alpha=0.45, lw=0))
        ax.text((x0 + x1) / 2, (y0 + y1) / 2, z.id, ha="center", va="center", fontsize=5.5)
    for t in duck_map.tags.values():
        ax.plot(t.x, t.y, "s", color="#111", ms=3)
        ax.annotate(str(t.id), (t.x, t.y), xytext=(t.x + 0.12 * np.cos(t.yaw), t.y + 0.12 * np.sin(t.yaw)), fontsize=5.5, ha="center", va="center", color="#333")
    for p in duck_map.places.values():
        ax.plot(p.x, p.y, "*", color="#1f77b4", ms=7)
        ax.text(p.x + 0.08, p.y + 0.1, p.id, fontsize=6.5, color="#1f77b4")
    cmap = plt.get_cmap("tab10")
    for i, tr in enumerate(traces):
        if not tr:
            continue
        c = cmap(i % 10)
        ax.plot([r["x"] for r in tr], [r["y"] for r in tr], "-", color=c, lw=0.9, alpha=0.9, label=(labels[i] if labels else None))
        est = [(r["ex"], r["ey"]) for r in tr if r["ex"] is not None]
        if est:
            ax.plot([e[0] for e in est], [e[1] for e in est], ":", color=c, lw=0.7, alpha=0.8)
    ax.set_xlim(ext[0], ext[1])
    ax.set_ylim(ext[2], ext[3])
    ax.set_aspect("equal")
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    ax.set_title(title or f"{duck_map.map_version} (synthetic map, simulation)", fontsize=9)
    if labels:
        ax.legend(fontsize=6, loc="lower right")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
