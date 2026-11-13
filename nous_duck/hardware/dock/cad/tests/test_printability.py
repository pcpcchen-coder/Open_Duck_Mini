"""每個零件都要是封閉實體、放得進 200 mm 列印範圍，而且 repo 裡的 STL 與程式產生的一致。"""


import numpy as np
import pytest
import trimesh

from dock_cad import params as P
from dock_cad.body_back_mod import boss_solid
from dock_cad.build import OUT_DIR
from dock_cad.geom import to_trimesh

PART_KEYS = [
    "dock_cradle",
    "dock_plinth",
    "dock_backrest_mid",
    "dock_backrest_upper",
    "dock_roof",
    "dock_arm_left",
    "dock_arm_right",
    "dock_rear_cover",
]


def test_part_list(result):
    assert [p.key for p in result.parts] == PART_KEYS


@pytest.mark.parametrize("key", PART_KEYS)
def test_part_is_closed_solid_and_fits_bed(result, key):
    part = next(p for p in result.parts if p.key == key)
    assert part.solid.status().name == "NoError"
    pm = part.printable()
    tm = to_trimesh(pm)
    assert tm.is_watertight and tm.is_volume
    x0, y0, z0, x1, y1, z1 = pm.bounding_box()
    assert z0 == pytest.approx(0.0, abs=1e-6)
    for size in (x1 - x0, y1 - y0, z1 - z0):
        assert size <= P.BED_LIMIT + 1e-6, f"{key} 超過列印範圍：{size:.1f} mm"


def test_body_back_dock_is_closed_and_only_grows_backwards(result):
    mod, orig = result.body_back_dock, result.body_back_orig
    assert to_trimesh(mod).is_watertight
    mb, ob = np.array(mod.bounding_box()), np.array(orig.bounding_box())
    assert mb[0] == pytest.approx(P.BOSS_FACE_X)  # 只往背後長
    assert np.allclose(mb[1:], ob[1:])  # 其他方向外框不變


def test_body_back_dock_keeps_original_material(result):
    """原殼只被線孔穿過斜角壁（設計上的唯一切口），其他地方原封不動。"""
    removed = (result.body_back_orig - result.body_back_dock).volume()
    hole_through_wall = np.pi * (P.WIRE_HOLE_D / 2) ** 2 * (P.BACK_CHAMFER_WALL * 2**0.5 + 2)
    assert removed < hole_through_wall, f"原殼被削掉 {removed:.0f} mm³"


def test_boss_does_not_enter_the_battery_bay(result):
    """凸台只填在殼外與殼壁裡，不能伸進電池艙或原殼的凹陷（原殼凸包內、原殼以外的空間）。"""
    hull = result.body_back_orig.hull()
    intrusion = ((result.body_back_dock ^ hull) - result.body_back_orig).volume()
    assert intrusion < 5.0, f"凸台伸進機身內 {intrusion:.1f} mm³"


def test_original_side_hole_stays_open(result):
    """-y 斜角上原有的 Ø6 圓孔：從外面沿孔軸看進去，改裝件不能擋住。"""
    from dock_cad.body_back_mod import chamfer_outer_x

    tm = to_trimesh(result.body_back_dock)
    d = np.array([1.0, 1.0, 0.0]) / np.sqrt(2)
    sx = chamfer_outer_x(abs(P.SIDE_HOLE_Y))
    for dy, dz in [(0, 0), (1.5, 0), (-1.5, 0), (0, 1.5), (0, -1.5)]:
        target = np.array([sx, P.SIDE_HOLE_Y + dy, P.SIDE_HOLE_Z + dz])
        origin = target - d * 40
        locs, _, _ = tm.ray.intersects_location([origin], [d])
        first = np.min(np.linalg.norm(locs - origin, axis=1)) if len(locs) else np.inf
        assert first > 40 + 5, "孔被擋住了"


def test_boss_leaves_side_screws_reachable():
    """背殼側面的固定螺絲在 |y| ≈ 41–50（沉頭孔），凸台不能蓋到，也要留起子空間。"""
    x0, y0, z0, x1, y1, z1 = boss_solid().bounding_box()
    assert max(abs(y0), abs(y1)) <= 39.0


def test_contact_plate_fits_the_printed_original(result):
    """外掛觸點板：單一實體、跟原殼零重疊（貼合）、觸點面在 BOSS_FACE_X、螺絲在兩片觸片中間。"""
    from dock_cad.body_back_mod import PLATE_SCREW_Z, strip_rects_print
    from dock_cad.build import plate_printable

    plate = result.contact_plate
    assert len(plate.decompose()) == 1
    assert (plate ^ result.body_back_orig).volume() < 0.5
    assert plate.bounding_box()[0] == pytest.approx(P.BOSS_FACE_X)
    tm = to_trimesh(plate_printable(plate))
    assert tm.is_watertight
    assert max(tm.extents) <= P.BED_LIMIT
    # 貼合面積：板子內面與原殼外表面要大面積接觸（膠合用），以兩者距離 < 0.05 mm 的面積估算
    inner = to_trimesh(plate)
    orig = to_trimesh(result.body_back_orig)
    centers = inner.triangles_center
    _, dist, _ = trimesh.proximity.closest_point(orig, centers)
    glue_area = inner.area_faces[dist < 0.05].sum()
    assert glue_area > 2500.0, f"貼合面積只有 {glue_area:.0f} mm²"
    # 沉頭螺絲在 y = 0，頭部 Ø6.4 不能碰到觸片槽
    for s in strip_rects_print():
        assert min(abs(s["y0"]), abs(s["y1"])) - P.STRIP_POCKET_CLEAR > 3.2
    assert all(P.STRIP_Z0 < z < P.STRIP_Z1 for z in PLATE_SCREW_Z)


@pytest.mark.parametrize("name", [f"{k}.stl" for k in PART_KEYS] + ["body_back_dock.stl", "body_back_contact_plate.stl"])
def test_committed_stl_matches_generator(result, name):
    """repo 裡的 STL 要跟程式重新產生的一樣（改了參數卻忘了重新輸出，會在這裡抓到）。"""
    path = OUT_DIR / name
    assert path.exists(), f"缺少 {path}，請執行 python -m dock_cad"
    committed = trimesh.load(path, force="mesh")
    if name == "body_back_dock.stl":
        fresh = result.body_back_dock
    elif name == "body_back_contact_plate.stl":
        from dock_cad.build import plate_printable

        fresh = plate_printable(result.contact_plate)
    else:
        fresh = next(p for p in result.parts if f"{p.key}.stl" == name).printable()
    assert committed.volume == pytest.approx(fresh.volume(), rel=1e-4)
    assert np.allclose(committed.bounds.flatten(), np.array(fresh.bounding_box()).reshape(2, 3).flatten(), atol=1e-3)
