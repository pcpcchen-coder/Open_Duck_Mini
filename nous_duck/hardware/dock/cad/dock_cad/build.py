"""產生全部 STL、AprilTag SVG 與摘要 JSON。

    cd nous_duck/hardware/dock/cad
    python -m dock_cad            # 輸出到 ../stl/
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import params as P
from .body_back_mod import build_body_back_dock, build_contact_plate, strip_rects_print
from .dock_parts import Part, build_all, contact_center_z, pin_positions
from .duck import default_repo_root, load_duck
from .geom import to_trimesh
from .tag import tag_svg

OUT_DIR = Path(__file__).resolve().parents[2] / "stl"

#: 線材估算用：PLA 密度、外殼（牆＋頂底層）等效厚度、填充率。只是估算，以切片軟體為準。
PLA_DENSITY = 1.24  # g/cm³
SHELL_T = 1.2  # mm
INFILL = 0.15


def estimate_grams(volume_mm3: float, area_mm2: float) -> float:
    shell = min(volume_mm3, area_mm2 * SHELL_T)
    return (shell + max(0.0, volume_mm3 - shell) * INFILL) / 1000.0 * PLA_DENSITY


@dataclass
class BuildResult:
    parts: list[Part]
    body_back_dock: object  # Manifold（print frame）
    body_back_orig: object
    contact_plate: object  # Manifold（print frame）
    print_to_dock: np.ndarray
    contact_z: float
    summary: dict


def build(repo_root: Path | None = None) -> BuildResult:
    repo_root = Path(repo_root or default_repo_root())
    duck = load_duck(repo_root)
    dz = float(duck.print_to_dock_offset[2])
    parts = build_all(dz)
    modded, orig = build_body_back_dock(repo_root)
    plate = build_contact_plate(repo_root)
    zc = contact_center_z(dz)

    entries = []
    for p in parts:
        pm = p.printable()
        bb = pm.bounding_box()
        entries.append(
            {
                "file": f"{p.key}.stl",
                "title": p.title,
                "print_size_mm": [round(bb[3] - bb[0], 1), round(bb[4] - bb[1], 1), round(bb[5] - bb[2], 1)],
                "solid_volume_cm3": round(pm.volume() / 1000, 1),
                "estimated_pla_g": round(estimate_grams(pm.volume(), pm.surface_area()), 0),
                "orientation": p.note,
            }
        )
    pp = plate_printable(plate)
    bb = pp.bounding_box()
    entries.append(
        {
            "file": "body_back_contact_plate.stl",
            "title": "外掛觸點板（貼在已印好的原版 body_back 上）— 建議",
            "print_size_mm": [round(bb[3] - bb[0], 1), round(bb[4] - bb[1], 1), round(bb[5] - bb[2], 1)],
            "solid_volume_cm3": round(pp.volume() / 1000, 1),
            "estimated_pla_g": round(estimate_grams(pp.volume(), pp.surface_area()), 0),
            "orientation": "觸點面朝下（觸片槽、走線槽在底面），免支撐",
        }
    )
    bb = modded.bounding_box()
    added = modded.volume() - orig.volume()
    entries.append(
        {
            "file": "body_back_dock.stl",
            "title": "一體式改裝背殼（要重印 body_back 時才用）",
            "print_size_mm": [round(bb[3] - bb[0], 1), round(bb[4] - bb[1], 1), round(bb[5] - bb[2], 1)],
            "solid_volume_cm3": round(modded.volume() / 1000, 1),
            "estimated_pla_g": round(estimate_grams(modded.volume(), modded.surface_area()), 0),
            "orientation": "與上游 body_back 相同（沿用上游座標，切片軟體會自動落到平台）",
        }
    )
    strips = []
    for s in strip_rects_print():
        lo = duck.print_to_dock(np.array([0, s["y0"], s["z0"]]))
        hi = duck.print_to_dock(np.array([0, s["y1"], s["z1"]]))
        strips.append({"pole": s["pole"], "y": [round(lo[1], 2), round(hi[1], 2)], "z": [round(lo[2], 2), round(hi[2], 2)]})
    summary = {
        "generated_by": "nous_duck/hardware/dock/cad (python -m dock_cad)",
        "frame": "dock frame: X 朝前、Y 朝鴨子左邊、Z 朝上，Z=0 地板，X=0 停好時的觸點凸台表面",
        "duck_pose": "上游 Open_Duck_Playground home keyframe（未含實機站姿誤差）",
        "contact_center_z_mm": round(zc, 2),
        "duck_strips_dock_frame": strips,
        "dock_pins_dock_frame": [{**p, "z": round(p["z"], 2)} for p in pin_positions(zc)],
        "cradle_adjust_mm": P.CRADLE_ADJUST,
        "body_back_added_volume_cm3": round(added / 1000, 1),
        "parts": entries,
        "estimate_note": f"線材為估算：PLA {PLA_DENSITY} g/cm³、外殼等效 {SHELL_T} mm、填充 {INFILL:.0%}；以切片軟體為準",
    }
    return BuildResult(parts, modded, orig, plate, duck.print_to_dock_offset, zc, summary)


def plate_printable(plate):
    """觸點面（-x）朝下：繞 Y 轉 -90°（manifold3d 會把 -X 轉到 -Z）。"""
    m = plate.rotate([0, -90, 0])
    x0, y0, z0, x1, y1, z1 = m.bounding_box()
    return m.translate([-(x0 + x1) / 2, -(y0 + y1) / 2, -z0])


def write_outputs(result: BuildResult, out_dir: Path = OUT_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for p in result.parts:
        path = out_dir / f"{p.key}.stl"
        to_trimesh(p.printable()).export(path)
        written.append(path)
    path = out_dir / "body_back_contact_plate.stl"
    to_trimesh(plate_printable(result.contact_plate)).export(path)
    written.append(path)
    path = out_dir / "body_back_dock.stl"
    to_trimesh(result.body_back_dock).export(path)
    written.append(path)
    path = out_dir / f"dock_apriltag_{P.TAG_FAMILY}_id{P.TAG_ID}.svg"
    path.write_text(tag_svg(), encoding="utf-8")
    written.append(path)
    path = out_dir / "parts.json"
    path.write_text(json.dumps(result.summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    written.append(path)
    return written


def main() -> None:
    result = build()
    for path in write_outputs(result):
        print(path.relative_to(OUT_DIR.parents[3]))
    dock = sum(e["estimated_pla_g"] for e in result.summary["parts"] if e["file"].startswith("dock_"))
    print(f"觸片中心高度 Z = {result.contact_z:.1f} mm；充電座線材估算合計約 {dock:.0f} g")


if __name__ == "__main__":
    main()
