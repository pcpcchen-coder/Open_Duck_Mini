"""充電座「屋形靠背扶手椅」的零件（全部在充電座座標建模，輸出時再轉成列印方向）。

零件：
- cradle：V 形導引座＋4 支彈簧頂針（功能件，可上下微調 ±15 mm）
- backrest_lower：下椅背＝電子艙（背面開口，裝後蓋）
- backrest_upper：上椅背，正面有 AprilTag 凹槽
- roof：屋頂山牆（窗戶後面裝狀態燈、煙囪）
- arm_left／arm_right：扶手（含連接椅背的側翼）
- rear_cover：電子艙後蓋（USB 線缺口、散熱孔）
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from manifold3d import Manifold

from . import params as P
from .geom import box, cyl, extrude_xy, extrude_xz, extrude_yz, slot, subtract_all, union_all


@dataclass
class Part:
    key: str
    title: str
    solid: Manifold  # 充電座座標
    #: 轉成列印方向（度，manifold3d 的 rotate：先 X 再 Y 再 Z；繞 Y +90° 會把 +X 轉到 -Z）
    print_rot: tuple[float, float, float]
    note: str
    color: str
    explode: tuple[float, float, float] = (0.0, 0.0, 0.0)

    def printable(self) -> Manifold:
        m = self.solid.rotate(list(self.print_rot))
        x0, y0, z0, x1, y1, z1 = m.bounding_box()
        return m.translate([-(x0 + x1) / 2, -(y0 + y1) / 2, -z0])


# ---------------------------------------------------------------------------
# 觸點位置（由背殼觸片在站姿下的高度決定）
# ---------------------------------------------------------------------------
def contact_center_z(print_to_dock_z: float) -> float:
    """觸片中心在充電座座標的高度。print_to_dock_z 來自 duck.load_duck()。"""
    return (P.STRIP_Z0 + P.STRIP_Z1) / 2 + print_to_dock_z


def pin_positions(zc: float) -> list[dict]:
    """四支頂針：+Y 兩支接正極、-Y 兩支接負極（以鴨子的左右為準）。"""
    out = []
    for sy, pole in ((+1, "+"), (-1, "-")):
        for dz in (-P.PIN_Z_SPACING / 2, P.PIN_Z_SPACING / 2):
            out.append({"pole": pole, "y": sy * P.STRIP_Y, "z": zc + dz})
    return out


# ---------------------------------------------------------------------------
# V 形導引座
# ---------------------------------------------------------------------------
def cradle_v_x(abs_y: float) -> float:
    """V 形牆表面的 X（|Y| 的函數）：與凸台 45° 導角平行，留 CRADLE_CLEAR。"""
    bevel_line = abs_y - P.BOSS_FACE_HALF_W  # 凸台導角：X = |Y| - 28
    return max(P.CRADLE_BASE_X, bevel_line - P.CRADLE_CLEAR)


def build_cradle(zc: float) -> Manifold:
    z0, z1 = zc - P.CRADLE_HEIGHT / 2, zc + P.CRADLE_HEIGHT / 2
    bx = P.BACK_FRONT_X
    tip_x = cradle_v_x(P.CRADLE_TIP_HALF_W)
    # 底面半寬：V 形牆在 X = CRADLE_BASE_X 的位置
    base_hw = P.CRADLE_BASE_X + P.BOSS_FACE_HALF_W + P.CRADLE_CLEAR
    pts = [
        (bx, -P.CRADLE_HALF_W),
        (tip_x, -P.CRADLE_HALF_W),
        (tip_x, -P.CRADLE_TIP_HALF_W),
        (P.CRADLE_BASE_X, -base_hw),
        (P.CRADLE_BASE_X, base_hw),
        (tip_x, P.CRADLE_TIP_HALF_W),
        (tip_x, P.CRADLE_HALF_W),
        (bx, P.CRADLE_HALF_W),
    ]
    # 凸角修 3 mm 圓角（尖端不傷鴨子、不卡外殼）
    body = extrude_xy(pts, z0, z1, round_r=3.0)

    cuts = []
    # 頂針孔
    for p in pin_positions(zc):
        cuts.append(cyl("x", (0, p["y"], p["z"]), P.PIN_BORE / 2, bx - 1, P.CRADLE_BASE_X + 1))
    # 背面熱熔螺帽孔（從後面鎖，椅背上是長槽孔可上下調）
    for y, z in cradle_insert_points(zc):
        cuts.append(cyl("x", (0, y, z), P.INSERT_D / 2, bx - 1, bx + P.INSERT_DEPTH))
    # 背面頂針尾端走線凹槽
    cuts.append(box(bx - 1, bx + 2.0, -P.STRIP_Y - 4, P.STRIP_Y + 4, zc - 22, zc + 22))
    return subtract_all(body, cuts)


def cradle_insert_points(zc: float) -> list[tuple[float, float]]:
    z0, z1 = zc - P.CRADLE_HEIGHT / 2, zc + P.CRADLE_HEIGHT / 2
    return [(y, z) for y in (-50.0, 50.0) for z in (z0 + 14, z1 - 14)]


# ---------------------------------------------------------------------------
# 椅背：底座（電子艙）→ 中椅背（裝 V 形導引座）→ 上椅背（AprilTag）→ 屋頂
# ---------------------------------------------------------------------------
ARM_JOIN_X = (P.BACK_REAR_X + P.BACK_FRONT_X) / 2
#: 扶手側翼連接螺絲高度：第一顆鎖在底座、後兩顆鎖在中椅背。
ARM_JOIN_Z = (P.PLINTH_TOP_Z / 2, 85.0, 115.0)
PLINTH_MID_JOIN = [(ARM_JOIN_X, -80.0), (ARM_JOIN_X, 80.0), (ARM_JOIN_X, -35.0), (ARM_JOIN_X, 35.0)]  # (X, Y)
MID_UPPER_JOIN = [(-27.0, -80.0), (-27.0, 80.0), (-27.0, -35.0), (-27.0, 35.0)]
UPPER_ROOF_JOIN = [(-27.0, -60.0), (-27.0, 60.0)]
#: 走線孔（頂針線往下到電子艙、狀態燈線往上到屋頂）。
WIRE_PASS = (-27.0, 0.0)
COVER_SCREWS = [(-88.0, 12.0), (88.0, 12.0), (-88.0, P.PLINTH_TOP_Z - 12.0), (88.0, P.PLINTH_TOP_Z - 12.0)]  # (Y, Z)


def _shell(rx: float, z0: float, z1: float) -> Manifold:
    """後面開口的殼：正面厚 FRONT_WALL，其餘 WALL。"""
    fx, hw, w = P.BACK_FRONT_X, P.BACK_HALF_W, P.WALL
    return box(rx, fx, -hw, hw, z0, z1) - box(rx - 1, fx - P.FRONT_WALL, -hw + w, hw - w, z0 + w, z1 - w)


def _bosses_down(points, z_plate: float, rx_cut: float) -> tuple[list[Manifold], list[Manifold]]:
    """在底板上方加螺絲柱＋熱熔螺帽孔（螺絲從下面那一段往上鎖）。"""
    adds, cuts = [], []
    for x, y in points:
        adds.append(cyl("z", (x, y, 0), 5.0, z_plate, z_plate + P.WALL + 8))
        cuts.append(cyl("z", (x, y, 0), P.INSERT_D / 2, z_plate - 1, z_plate + P.INSERT_DEPTH))
    return adds, cuts


def _clear_up(points, z_top: float) -> list[Manifold]:
    """頂板上的 M3 穿孔。"""
    return [cyl("z", (x, y, 0), P.M3_CLEAR / 2, z_top - P.WALL - 1, z_top + 1) for x, y in points]


def _arm_holes(z0: float, z1: float) -> list[Manifold]:
    hw, w = P.BACK_HALF_W, P.WALL
    cuts = []
    for z in ARM_JOIN_Z:
        if z0 + 6 < z < z1 - 6:
            cuts.append(cyl("y", (ARM_JOIN_X, 0, z), P.M3_CLEAR / 2, hw - w - 1, hw + 1))
            cuts.append(cyl("y", (ARM_JOIN_X, 0, z), P.M3_CLEAR / 2, -hw - 1, -hw + w + 1))
    return cuts


def build_plinth() -> Manifold:
    """底座＝電子艙：後面開口，用後蓋封住；USB 線從後蓋下緣進來。"""
    rx, fx, top = P.BACK_REAR_X, P.BACK_FRONT_X, P.PLINTH_TOP_Z
    shell = _shell(rx, 0, top)
    adds = [cyl("x", (0, y, z), 5.0, rx, fx - P.FRONT_WALL) for y, z in COVER_SCREWS]
    shell = union_all([shell] + adds)
    cuts = [cyl("x", (0, y, z), P.INSERT_D / 2, rx - 1, rx + P.INSERT_DEPTH) for y, z in COVER_SCREWS]
    cuts += _clear_up(PLINTH_MID_JOIN, top)
    cuts += _arm_holes(0, top)
    cuts.append(cyl("z", (WIRE_PASS[0] - 10, WIRE_PASS[1], 0), 6.0, top - P.WALL - 1, top + 1))
    return subtract_all(shell, cuts)


def build_backrest_mid(zc: float) -> Manifold:
    """中椅背：正面有 V 形導引座的長槽孔與頂針窗；後面開口方便從後面鎖導引座。"""
    rx, fx = P.BACK_REAR_X, P.BACK_FRONT_X
    z0, z1 = P.PLINTH_TOP_Z, P.MID_TOP_Z
    shell = _shell(rx, z0, z1)
    adds, cuts = _bosses_down(PLINTH_MID_JOIN, z0, rx)
    shell = union_all([shell] + adds)
    cuts += _clear_up(MID_UPPER_JOIN, z1)
    cuts += _arm_holes(z0, z1)
    # V 形導引座：長槽孔（M3，可上下調 ±CRADLE_ADJUST）與頂針窗
    for y, z in cradle_insert_points(zc):
        cuts.append(slot("x", (0, y, z - P.CRADLE_ADJUST), (0, y, z + P.CRADLE_ADJUST), P.M3_CLEAR / 2, fx - P.FRONT_WALL - 1, fx + 1))
    win_h = P.PIN_Z_SPACING + 2 * P.CRADLE_ADJUST + 16
    cuts.append(box(fx - P.FRONT_WALL - 1, fx + 1, -P.STRIP_Y - 8, P.STRIP_Y + 8, zc - win_h / 2, zc + win_h / 2))
    for z in (z0, z1):
        cuts.append(cyl("z", (WIRE_PASS[0] - (10 if z == z0 else 0), WIRE_PASS[1], 0), 6.0 if z == z0 else 5.0, z - P.WALL - 1, z + P.WALL + 1))
    return subtract_all(shell, cuts)


def tag_outer_size() -> float:
    return P.TAG_BLACK_SIZE * 10 / 8


def build_backrest_upper() -> Manifold:
    fx, rx, hw = P.BACK_FRONT_X, P.UPPER_REAR_X, P.BACK_HALF_W
    z0, z1, w = P.MID_TOP_Z, P.UPPER_TOP_Z, P.WALL
    shell = _shell(rx, z0, z1)
    adds, cuts = _bosses_down(MID_UPPER_JOIN, z0, rx)
    shell = union_all([shell] + adds)
    cuts += _clear_up(UPPER_ROOF_JOIN, z1)
    # AprilTag 對位框：紙貼在框內。只做 1.2 mm 寬的淺溝（整片凹槽在正面朝下列印時會大面積懸空）
    s = tag_outer_size() / 2 + P.TAG_RECESS_MARGIN
    g = P.TAG_GUIDE_GROOVE
    zc = P.TAG_CENTER_Z
    for a, b, c, d in ((-s - g, s + g, zc + s, zc + s + g), (-s - g, s + g, zc - s - g, zc - s), (-s - g, -s, zc - s, zc + s), (s, s + g, zc - s, zc + s)):
        cuts.append(box(fx - P.TAG_RECESS_DEPTH, fx + 1, a, b, c, d))
    # 椅背飾條：正面一圈淺溝，看起來像沙發靠墊的縫線
    g, inset, depth = 1.6, 7.0, 0.8
    y0, y1, za, zb = -hw + inset, hw - inset, z0 + inset, z1 - inset
    for a, b, c, d in ((y0, y1, za, za + g), (y0, y1, zb - g, zb), (y0, y0 + g, za, zb), (y1 - g, y1, za, zb)):
        cuts.append(box(fx - depth, fx + 1, a, b, c, d))
    for z in (z0, z1):
        cuts.append(cyl("z", (WIRE_PASS[0], WIRE_PASS[1], 0), 5.0, z - w - 1, z + w + 1))
    return subtract_all(shell, cuts)


def roof_profile() -> list[tuple[float, float]]:
    hw = P.BACK_HALF_W
    return [(-hw, P.UPPER_TOP_Z), (hw, P.UPPER_TOP_Z), (hw, P.ROOF_EAVE_Z), (0.0, P.ROOF_RIDGE_Z), (-hw, P.ROOF_EAVE_Z)]


def build_roof() -> Manifold:
    fx, rx, w = P.BACK_FRONT_X, P.UPPER_REAR_X, P.WALL
    hw = P.BACK_HALF_W
    outer = extrude_yz(roof_profile(), rx, fx)
    # 內腔：輪廓內縮 w
    slope = (P.ROOF_RIDGE_Z - P.ROOF_EAVE_Z) / hw
    import math

    k = w * math.sqrt(1 + slope**2)
    inner_pts = [
        (-hw + w, P.UPPER_TOP_Z + w),
        (hw - w, P.UPPER_TOP_Z + w),
        (hw - w, P.ROOF_EAVE_Z + slope * w - k),
        (0.0, P.ROOF_RIDGE_Z - k),
        (-hw + w, P.ROOF_EAVE_Z + slope * w - k),
    ]
    inner = extrude_yz(inner_pts, rx - 1, fx - w)
    shell = outer - inner
    # 煙囪（鴨子的 -Y 側）：前後貫通、正面與屋頂正面齊平（正面朝下列印時不懸空）
    cy0, cy1 = -72.0, -52.0
    chimney_top = P.ROOF_EAVE_Z + slope * (hw - abs(cy0)) + 22
    chimney = box(rx, fx, cy0, cy1, P.ROOF_EAVE_Z, chimney_top) + box(rx, fx, cy0 - 2, cy1 + 2, chimney_top - 5, chimney_top)
    adds = [shell, chimney]
    for x, y in UPPER_ROOF_JOIN:
        adds.append(cyl("z", (x, y, 0), 5.0, P.UPPER_TOP_Z, P.UPPER_TOP_Z + w + 8))
    solid = union_all(adds)
    cuts = []
    for x, y in UPPER_ROOF_JOIN:
        cuts.append(cyl("z", (x, y, 0), P.INSERT_D / 2, P.UPPER_TOP_Z - 1, P.UPPER_TOP_Z + P.INSERT_DEPTH))
    # 屋簷線：沿兩道斜邊的淺溝（正面的裝飾都做成凹的，正面朝下列印才不會懸空）
    band, g, depth = 9.0, 1.4, 0.8
    k2 = math.sqrt(1 + slope**2)
    for sy in (+1, -1):
        pts = [
            (sy * hw, P.ROOF_EAVE_Z - band * k2),
            (0.0, P.ROOF_RIDGE_Z - band * k2),
            (0.0, P.ROOF_RIDGE_Z - (band + g) * k2),
            (sy * hw, P.ROOF_EAVE_Z - (band + g) * k2),
        ]
        cuts.append(extrude_yz(pts, fx - depth, fx + 1))
    cuts.append(box(fx - depth, fx + 1, -hw, hw, P.UPPER_TOP_Z + 6, P.UPPER_TOP_Z + 6 + g))
    # 圓窗（四格窗櫺），後面裝狀態燈
    wr = P.WINDOW_D / 2
    window = cyl("x", (0, 0, P.WINDOW_Z), wr, fx - w - 1, fx + 5)
    bars = box(fx - w - 2, fx + 6, -1.2, 1.2, P.WINDOW_Z - wr, P.WINDOW_Z + wr) + box(fx - w - 2, fx + 6, -wr, wr, P.WINDOW_Z - 1.2, P.WINDOW_Z + 1.2)
    cuts.append(window - bars)
    # 窗框：外圈淺溝
    cuts.append(cyl("x", (0, 0, P.WINDOW_Z), wr + 4.0, fx - depth, fx + 1) - cyl("x", (0, 0, P.WINDOW_Z), wr + 2.6, fx - 2, fx + 2))
    solid = subtract_all(solid, cuts)
    # 走線孔
    solid = subtract_all(solid, [cyl("z", (WIRE_PASS[0], WIRE_PASS[1], 0), 5.0, P.UPPER_TOP_Z - 1, P.UPPER_TOP_Z + w + 1)])
    return solid


# ---------------------------------------------------------------------------
# 扶手
# ---------------------------------------------------------------------------
def build_arm(side: int) -> Manifold:
    """side = +1 左扶手（+Y）、-1 右扶手（-Y）。先建左邊再鏡射。"""
    rx, fx, hw = P.BACK_REAR_X, P.BACK_FRONT_X, P.BACK_HALF_W
    yi, yo = P.ARM_INNER_Y, P.ARM_INNER_Y + P.ARM_THICK
    top, r, front = P.ARM_TOP_Z, P.ARM_ROLL_R, P.ARM_FRONT_X
    ym = (yi + yo) / 2
    rc = 22.0  # 扶手前上角的圓弧半徑
    # 側翼：中空、底部開口（直立列印時不用填充，省線材）；連接面留螺絲柱
    w = P.WALL
    # 內腔頂做成 45° 尖頂（直立列印時不用架橋）
    cy0, cy1 = hw + w, yi - w
    peak = top - w - (cy1 - cy0) / 2
    cavity = Manifold.batch_hull([box(rx + w, fx - w, cy0, cy1, -1, peak), box(rx + w, fx - w, (cy0 + cy1) / 2 - 0.5, (cy0 + cy1) / 2 + 0.5, -1, top - w)])
    wing = box(rx, fx, hw, yi + 1, 0, top) - cavity
    wing = union_all([wing] + [cyl("y", (ARM_JOIN_X, 0, z), 5.0, hw, hw + P.INSERT_DEPTH + 3) for z in ARM_JOIN_Z])
    # 側板：前上角是圓弧（XZ 輪廓沿 Y 擠出）
    import math

    arc = [(front - rc + rc * math.cos(a), top - rc + rc * math.sin(a)) for a in np.linspace(0, math.pi / 2, 16)]
    profile = [(rx, 0.0), (front, 0.0)] + arc + [(rx, top)]
    panel = extrude_xz(profile, yi, yo)
    # 頂端的扶手捲邊：沿 X 的圓柱
    roll = cyl("x", (0, ym, top), r, rx, front - rc)
    # 外側的渦卷飾片
    scroll = cyl("y", (front - rc, 0, top - rc), 15.0, yo - 1, yo + 2.0) - cyl("y", (front - rc, 0, top - rc), 8.0, yo - 2, yo + 3)
    body = union_all([wing, panel, roll, scroll])

    cuts = []
    for z in ARM_JOIN_Z:
        cuts.append(cyl("y", (ARM_JOIN_X, 0, z), P.INSERT_D / 2, hw - 1, hw + P.INSERT_DEPTH))
    # 側板中空、底部開口（直立列印只印牆，省線材）
    cuts.append(box(rx + w, front - rc - 2, yi + w, yo - w, -1, top - w))
    body = subtract_all(body, cuts)
    if side < 0:
        body = body.mirror([0, 1, 0])
    return body


def build_rear_cover() -> Manifold:
    rx, hw = P.BACK_REAR_X, P.BACK_HALF_W
    t = 2.0
    plate = box(rx - t, rx, -hw + 0.5, hw - 0.5, 0.5, P.PLINTH_TOP_Z - 0.5)
    cuts = []
    for y, z in COVER_SCREWS:
        cuts.append(cyl("x", (0, y, z), P.M3_CLEAR / 2, rx - t - 1, rx + 1))
    # USB 線缺口（下緣中央）
    cuts.append(box(rx - t - 1, rx + 1, -7, 7, 0, 10))
    # 散熱孔
    for z in (24.0, 36.0):
        cuts.append(slot("x", (0, -60, z), (0, 60, z), 2.5, rx - t - 1, rx + 1))
    return subtract_all(plate, cuts)


# ---------------------------------------------------------------------------
def build_all(print_to_dock_z: float) -> list[Part]:
    zc = contact_center_z(print_to_dock_z)
    blue, dark = "#7aa6c2", "#5c7f96"
    return [
        Part("dock_cradle", "V 形導引座（含頂針孔）", build_cradle(zc), (0, -90, 0), "背面（貼椅背那面）朝下，免支撐", "#e9b44c", (70, 0, 0)),
        Part("dock_plinth", "底座／電子艙", build_plinth(), (0, 90, 0), "正面朝下、開口朝上，免支撐", dark, (0, 0, -40)),
        Part("dock_backrest_mid", "中椅背（V 形座安裝面）", build_backrest_mid(zc), (0, 90, 0), "正面朝下、開口朝上，免支撐", blue, (0, 0, 0)),
        Part("dock_backrest_upper", "上椅背（AprilTag 凹槽）", build_backrest_upper(), (0, 90, 0), "正面朝下、開口朝上，免支撐", blue, (0, 0, 50)),
        Part("dock_roof", "屋頂山牆（窗戶＝狀態燈、煙囪）", build_roof(), (0, 90, 0), "正面朝下（正面裝飾都是凹槽），免支撐", "#c0504d", (0, 0, 100)),
        Part("dock_arm_left", "左扶手", build_arm(+1), (0, 0, 0), "底面朝下直立列印，免支撐", blue, (0, 80, 0)),
        Part("dock_arm_right", "右扶手", build_arm(-1), (0, 0, 0), "底面朝下直立列印，免支撐", blue, (0, -80, 0)),
        Part("dock_rear_cover", "電子艙後蓋", build_rear_cover(), (0, 90, 0), "平放", dark, (-60, 0, -40)),
    ]


def assembled_bounds(parts: list[Part]) -> np.ndarray:
    bb = np.array([p.solid.bounding_box() for p in parts])
    return np.array([bb[:, :3].min(0), bb[:, 3:].max(0)])
