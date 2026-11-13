"""鴨子背殼改裝：在上游 `print/body_back.stl` 的平面背板加一個觸點凸台。

凸台上有：
- 兩條黃銅觸片的淺槽（+y 正極、-y 負極，直立長條，容許鴨子站高的誤差）
- 每片觸片下端一個小缺口，接到凸台下緣的走線槽
- 走線槽通到 -y 斜角的一個 Ø4 線孔，穿進機身（USB-C 充電板在那一側）
- 兩側 45° 導角：倒退進座時被充電座的 V 形槽推到正中間

座標沿用上游 print frame（mm），切片軟體會自動放到列印平台上，列印方向與原檔相同（底面朝下、背板直立）。
上游檔案只讀不改，輸出寫到 `nous_duck/hardware/dock/stl/`。
"""

from __future__ import annotations

from pathlib import Path

import trimesh
from manifold3d import Manifold

from . import params as P
from .geom import box, cyl, extrude_xy, from_trimesh, subtract_all

UPSTREAM_BODY_BACK = Path("print/body_back.stl")


def chamfer_outer_x(abs_y: float) -> float:
    """原版背殼外表面在某個 |y| 的 x（平面或 45° 斜角）。"""
    if abs_y <= P.BACK_FLAT_HALF_W:
        return P.BACK_FLAT_X
    return P.BACK_FLAT_X + (abs_y - P.BACK_FLAT_HALF_W)


def boss_solid() -> Manifold:
    """凸台本體（還沒挖槽），內側邊界埋進原壁 1.5 mm，聯集後與原殼融為一體。"""
    fx = P.BOSS_FACE_X
    hw, fw = P.BOSS_HALF_W, P.BOSS_FACE_HALF_W
    bevel_x = fx + (hw - fw)  # 45° 導角終點
    embed = 1.5
    inner_side = chamfer_outer_x(hw) + embed
    inner_center = P.BACK_FLAT_X + embed
    # 平面背板中央是 14.4 mm 的實心壁，再往內埋 5 mm 也還在壁裡，讓下緣與底部倒角接得密
    inner_center_deep = P.BACK_FLAT_X + 7.0
    pts = [
        (fx, -fw),
        (fx, fw),
        (bevel_x, hw),
        (inner_side, hw),
        (inner_center, P.BACK_FLAT_HALF_W),
        (inner_center_deep, 0.0),
        (inner_center, -P.BACK_FLAT_HALF_W),
        (inner_side, -hw),
        (bevel_x, -hw),
    ]
    solid = extrude_xy(pts, P.BOSS_Z0, P.BOSS_Z1)
    # 下緣做 45° 自我支撐面：外側越高、靠機身越低（不用支撐材）
    # 保留 z + x ≥ BOSS_Z0 + BACK_FLAT_X 的部分
    import math

    n = [1 / math.sqrt(2), 0.0, 1 / math.sqrt(2)]
    return solid.trim_by_plane(n, (P.BOSS_Z0 + P.BACK_FLAT_X) / math.sqrt(2))


def boss_cutters() -> list[Manifold]:
    fx = P.BOSS_FACE_X
    cuts: list[Manifold] = []
    hw = P.STRIP_W / 2 + P.STRIP_POCKET_CLEAR
    for sy in (+1, -1):
        cy = sy * P.STRIP_Y
        # 觸片淺槽
        cuts.append(
            box(fx - 1, fx + P.STRIP_POCKET_DEPTH, cy - hw, cy + hw, P.STRIP_Z0 - P.STRIP_POCKET_CLEAR, P.STRIP_Z1 + P.STRIP_POCKET_CLEAR)
        )
        # 觸片下端到走線槽的缺口（焊好的導線從觸片背面走出來）
        cuts.append(box(fx - 1, fx + 2.0, cy - 1.5, cy + 1.5, P.GROOVE_Z0, P.STRIP_Z0 + 2.0))
    # 走線槽：從 +y 觸片下方走到 -y 線孔
    cuts.append(box(fx - 1, fx + P.GROOVE_DEPTH, P.WIRE_HOLE_Y - 2.0, P.STRIP_Y + 3.0, P.GROOVE_Z0, P.GROOVE_Z1))
    # 線孔入口：導角面會碰到充電座的 V 形牆，導線不能露在外面，所以把槽延伸進導角裡
    #（停在原版斜角壁外 1.5 mm，不削原殼）
    cuts.append(
        box(fx - 7, chamfer_outer_x(P.BOSS_FACE_HALF_W) - 1.5, P.WIRE_HOLE_Y - 2.0, -P.BOSS_FACE_HALF_W + 0.5, P.GROOVE_Z0, P.GROOVE_Z1)
    )
    # 線孔：沿 +x 穿過凸台與斜角壁，進到機身內
    zc = (P.GROOVE_Z0 + P.GROOVE_Z1) / 2
    x_in = chamfer_outer_x(abs(P.WIRE_HOLE_Y)) + P.BACK_CHAMFER_WALL + 4.0
    cuts.append(cyl("x", (0, P.WIRE_HOLE_Y, zc), P.WIRE_HOLE_D / 2, fx - 10, x_in))
    # 原有斜角圓孔的通道：沿斜角法向 (-1,-1,0) 往外穿出凸台側面
    sx = chamfer_outer_x(abs(P.SIDE_HOLE_Y))
    tunnel = (
        Manifold.cylinder(30.0, P.SIDE_HOLE_CLEAR_D / 2, P.SIDE_HOLE_CLEAR_D / 2, 48)
        .rotate([0, 90, 0])  # 沿 +x，0..30
        .translate([-28.0, 0, 0])  # -28..2：大部分在殼外，只進殼面 2 mm（不碰原殼）
        .rotate([0, 0, 45])  # 軸線轉到 (1,1,0)：往外是 (-1,-1,0)
        .translate([sx, P.SIDE_HOLE_Y, P.SIDE_HOLE_Z])
    )
    cuts.append(tunnel)
    return cuts


#: 外掛觸點板的固定螺絲（在兩片觸片中間，y = 0）：M3 沉頭自攻螺絲鎖進原殼 14.4 mm 厚的背板。
PLATE_SCREW_Z = (-42.0, -16.0)


def plate_screw_cutters() -> list[Manifold]:
    fx = P.BOSS_FACE_X
    cuts = []
    for z in PLATE_SCREW_Z:
        cuts.append(cyl("x", (0, 0.0, z), P.M3_CLEAR_PLATE / 2, fx - 1, P.BACK_FLAT_X + 0.5))
        # 90° 沉頭：外表面 Ø6.4 → Ø3.4
        cone = Manifold.cylinder(1.5 + 0.01, 3.2, 1.7, 48).rotate([0, 90, 0]).translate([fx - 0.01, 0.0, z])
        cuts.append(cone)
        cuts.append(cyl("x", (0, 0.0, z), 3.2, fx - 1, fx))
    return cuts


def build_contact_plate(repo_root: Path) -> Manifold:
    """外掛觸點板（print frame）：凸台扣掉原殼，內面完全貼合已印好的原版背殼。"""
    orig = from_trimesh(trimesh.load(repo_root / UPSTREAM_BODY_BACK, force="mesh"))
    plate = subtract_all(boss_solid() - orig, boss_cutters() + plate_screw_cutters())
    pieces = sorted(plate.decompose(), key=lambda m: m.volume(), reverse=True)
    # 布林運算在貼合面可能留下極小的碎片，只保留主體
    return pieces[0]


def build_body_back_dock(repo_root: Path) -> tuple[Manifold, Manifold]:
    """回傳 (改裝後背殼, 原版背殼)，都在 print frame。"""
    orig_tm = trimesh.load(repo_root / UPSTREAM_BODY_BACK, force="mesh")
    orig = from_trimesh(orig_tm)
    modded = subtract_all(orig + boss_solid(), boss_cutters())
    return modded, orig


def strip_rects_print() -> list[dict]:
    """觸片在 print frame 的矩形（給測試與對位計算用）。"""
    out = []
    for sy, pole in ((+1, "+"), (-1, "-")):
        cy = sy * P.STRIP_Y
        out.append(
            {
                "pole": pole,
                "y0": cy - P.STRIP_W / 2,
                "y1": cy + P.STRIP_W / 2,
                "z0": P.STRIP_Z0,
                "z1": P.STRIP_Z1,
                "x": P.BOSS_FACE_X - (P.STRIP_T - P.STRIP_POCKET_DEPTH),
            }
        )
    return out
