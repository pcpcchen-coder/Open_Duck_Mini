#!/usr/bin/env python3
"""產生合成的家（fixture）：`synthetic_home.duckmap.json`。

**這不是任何真實住家的格局**，尺寸與擺設都是為了測試編的：客廳、走廊、兩個房間、
走廊盡頭的樓梯禁區、客廳西牆邊的充電座。地點只用 ID。

    python nous_duck/robot/navigation/maps/make_synthetic_home.py          # 重新產生
    python nous_duck/robot/navigation/maps/make_synthetic_home.py --check  # 確認檔案跟產生器一致
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from duck_nav.mapfile import parse_map, rasterize  # noqa: E402

OUT = HERE / "synthetic_home.duckmap.json"
RES = 0.05
T = 0.05  # 內牆半厚
BOUNDS = [-0.1, -0.1, 7.1, 7.1]
WALL_H = 1.0  # 模擬裡牆的高度（夠擋住鴨子與鏡頭視線就好）

#: 充電座座標原點（停好時鴨子背後觸點面的位置）與朝向。尺寸取自 hardware/dock/cad/dock_cad/params.py。
DOCK = (0.07, 1.5, 0.0)


def build() -> dict:
    s = []  # structures

    def box(id_, kind, x0, y0, x1, y1, h=WALL_H):
        s.append({"id": id_, "kind": kind, "rect": [round(v, 4) for v in (x0, y0, x1, y1)], "height_m": h})

    # 外牆（bounds 邊緣 0.1 m）。
    box("wall_outer_w", "wall", -0.1, -0.1, 0.0, 7.1)
    box("wall_outer_e", "wall", 7.0, -0.1, 7.1, 7.1)
    box("wall_outer_s", "wall", -0.1, -0.1, 7.1, 0.0)
    box("wall_outer_n", "wall", -0.1, 7.0, 7.1, 7.1)
    # 東南角是地圖外的實心區。
    box("solid_se", "wall", 4.0 - T, 0.0, 7.0, 3.0 + T)
    # 客廳／走廊之間（y = 3），門口 x 1.5～2.5。
    box("wall_living_hall_a", "wall", 0.0, 3.0 - T, 1.5, 3.0 + T)
    box("wall_living_hall_b", "wall", 2.5, 3.0 - T, 4.0, 3.0 + T)
    # 走廊／房間之間（y = 4），門口 x 1.2～2.0 與 5.0～5.8。
    box("wall_hall_rooms_a", "wall", 0.0, 4.0 - T, 1.2, 4.0 + T)
    box("wall_hall_rooms_b", "wall", 2.0, 4.0 - T, 5.0, 4.0 + T)
    box("wall_hall_rooms_c", "wall", 5.8, 4.0 - T, 7.0, 4.0 + T)
    # 兩個房間之間（x = 3.5）。
    box("wall_rooms", "wall", 3.5 - T, 4.0, 3.5 + T, 7.0)
    # 家具。
    box("sofa", "furniture", 2.6, 0.2, 3.8, 0.9, 0.40)
    box("table", "furniture", 2.6, 1.7, 3.2, 2.3, 0.45)
    box("bed", "furniture", 0.2, 5.6, 2.2, 6.8, 0.40)
    box("desk", "furniture", 5.6, 6.3, 6.8, 6.9, 0.70)
    # 充電座（椅背與兩個扶手；V 形導引座在機身高度，不畫進平面圖）。
    dx, dy, _ = DOCK
    box("dock_backrest", "dock", 0.0, dy - 0.10, dx - 0.012, dy + 0.10, 0.51)
    box("dock_arm_left", "dock", 0.0, dy + 0.165, dx + 0.136, dy + 0.181, 0.125)
    box("dock_arm_right", "dock", 0.0, dy - 0.181, dx + 0.136, dy - 0.165, 0.125)

    def tag(i, x, y, yaw, size=0.15, z=0.35):
        return {"id": i, "family": "tag36h11", "size_m": size, "pose": {"x": x, "y": y, "z": z, "yaw": round(yaw, 6)}}

    E_, N_, W_, S_ = 0.0, math.pi / 2, math.pi, -math.pi / 2  # 標籤面朝的方向
    e = 0.001
    tags = [
        tag(0, dx - 0.012 + e, dy, E_, size=0.10, z=0.34),  # 充電座椅背（hardware/dock：ID 0、黑框 100 mm、離地 340 mm）
        tag(1, 4.0 - T - e, 1.3, W_),
        tag(2, 1.8, e, N_),
        tag(3, 3.2, 3.0 - T - e, S_),
        tag(4, e, 2.5, E_),
        tag(5, 2.5, 4.0 - T - e, S_),
        tag(6, 4.6, 3.0 + T + e, N_),
        tag(7, e, 3.5, E_),
        tag(8, 0.8, 3.0 + T + e, N_),
        tag(9, 2.8, 7.0 - e, S_),
        tag(10, 3.5 - T - e, 5.2, W_),
        tag(11, e, 4.8, E_),
        tag(12, 5.2, 7.0 - e, S_),
        tag(13, 7.0 - e, 5.4, W_),
        tag(14, 3.5 + T + e, 5.4, E_),
        tag(15, 4.4, 4.0 - T - e, S_),
        tag(16, 2.6, 4.0 + T + e, N_),
        tag(17, 4.4, 4.0 + T + e, N_),
        tag(18, 7.0 - e, 3.5, W_),  # 走廊東端的牆（樓梯禁區後面），沿走廊往東走時看得到
    ]

    doc = {
        "format": "duck-map",
        "format_version": 1,
        "map_version": "synthetic-home-1",
        "synthetic": True,
        "description": "合成的家（fixture）：不是任何真實住家的格局，只給模擬與測試用。",
        "bounds": BOUNDS,
        "rooms": [
            {"id": "living_room", "rect": [0.0, 0.0, 4.0, 3.0]},
            {"id": "hallway", "rect": [0.0, 3.0, 7.0, 4.0]},
            {"id": "brother_room", "rect": [0.0, 4.0, 3.5, 7.0]},
            {"id": "study_room", "rect": [3.5, 4.0, 7.0, 7.0]},
        ],
        "doors": [
            {"id": "door_living_hall", "between": ["living_room", "hallway"], "center": [2.0, 3.0], "width_m": 1.0, "axis": "x"},
            {"id": "door_hall_brother", "between": ["hallway", "brother_room"], "center": [1.6, 4.0], "width_m": 0.8, "axis": "x"},
            {"id": "door_hall_study", "between": ["hallway", "study_room"], "center": [5.4, 4.0], "width_m": 0.8, "axis": "x"},
        ],
        "places": [
            {"id": "living_room", "room": "living_room", "pose": [1.6, 1.5]},
            {"id": "hallway", "room": "hallway", "pose": [3.2, 3.5]},
            {"id": "brother_room", "room": "brother_room", "pose": [2.6, 5.0]},
            {"id": "brother_bedside", "room": "brother_room", "pose": [2.7, 6.2, math.pi]},
            {"id": "study_room", "room": "study_room", "pose": [5.2, 5.4]},
            {"id": "dock", "room": "living_room", "pose": [round(dx + 0.162, 4), dy, 0.0]},
        ],
        "zones": [
            {"id": "stairs_hall_east", "kind": "stairs", "rect": [6.2, 3.0 + T, 7.0, 4.0 - T]},
            {"id": "cable_corner", "kind": "no_go", "rect": [3.2, 0.0, 4.0 - T, 0.2]},
        ],
        "tags": tags,
        "dock": {"place": "dock", "pose": [dx, dy, 0.0], "tag_id": 0, "staging_distance_m": 0.5},
        "structures": s,
    }
    rows = rasterize(BOUNDS, RES, [b["rect"] for b in s])
    doc["grid"] = {
        "resolution_m": RES,
        "origin": BOUNDS[:2],
        "width": len(rows[0]),
        "height": len(rows),
        "encoding": "rows-bottom-up",
        "rows": rows,
    }
    return doc


def dumps(doc: dict) -> str:
    """精簡但可讀的 JSON：清單裡的小物件各佔一行。"""
    lines = ["{"]
    keys = list(doc)
    for k in keys:
        v = doc[k]
        comma = "," if k != keys[-1] else ""
        if isinstance(v, list) and v and isinstance(v[0], dict):
            lines.append(f' "{k}": [')
            lines += [f"  {json.dumps(e, ensure_ascii=False)}{',' if i < len(v) - 1 else ''}" for i, e in enumerate(v)]
            lines.append(f" ]{comma}")
        elif k == "grid":
            g = dict(v)
            rows = g.pop("rows")
            head = json.dumps(g, ensure_ascii=False)[:-1]
            lines.append(f' "grid": {head}, "rows": [')
            lines += [f'  "{r}"{"," if i < len(rows) - 1 else ""}' for i, r in enumerate(rows)]
            lines.append(f" ]}}{comma}")
        else:
            lines.append(f' "{k}": {json.dumps(v, ensure_ascii=False)}{comma}')
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true")
    a = p.parse_args()
    text = dumps(build())
    parse_map(json.loads(text))  # 產生的檔案必須通過驗證
    if a.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.name} 跟產生器不一致，請重新產生", file=sys.stderr)
            return 1
        print("一致")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"寫入 {OUT}（{len(text) / 1024:.1f} KB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
