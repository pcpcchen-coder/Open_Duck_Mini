"""C3：地圖格式與合成的家。驗證層級：單元測試。"""

import copy
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import MAP_PATH, NAV_DIR
from duck_nav.mapfile import MapError, load_map, parse_map
from duck_nav.navigator import BASE_TO_CONTACT_M


@pytest.fixture()
def doc():
    return json.loads(MAP_PATH.read_text(encoding="utf-8"))


def test_fixture_is_marked_synthetic(home, doc):
    assert home.synthetic is True
    assert "synthetic" in MAP_PATH.name
    assert "合成" in doc["description"]
    assert home.map_version.startswith("synthetic")


def test_fixture_matches_generator():
    r = subprocess.run([sys.executable, str(NAV_DIR / "maps" / "make_synthetic_home.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_contents(home):
    assert set(home.rooms) == {"living_room", "hallway", "brother_room", "study_room"}
    assert {"living_room", "brother_room", "brother_bedside", "study_room", "hallway", "dock"} <= set(home.places)
    assert len(home.doors) == 3
    assert any(z.kind == "stairs" for z in home.zones.values())
    assert home.grid.occ.shape == (144, 144) and home.grid.resolution == 0.05
    assert home.room_at(2.0, 3.5) == "hallway"
    assert home.zone_at(6.5, 3.5).kind == "stairs"
    assert home.nearest_place(2.6, 6.0) == "brother_bedside"
    assert sorted(o for o, _ in home.neighbors("hallway")) == ["brother_room", "living_room", "study_room"]
    # places 指令的資料只有 ID，沒有座標。
    for p in home.places_summary():
        assert set(p) == {"place", "room", "is_dock"}


def test_dock_matches_hardware_design(home):
    """充電座的標籤與觸點幾何要跟 hardware/dock 的 CAD 參數一致。"""
    sys.path.insert(0, str(NAV_DIR.parents[1] / "hardware" / "dock" / "cad"))
    from dock_cad import params as P

    tag = home.tags[home.dock.tag_id]
    assert tag.id == P.TAG_ID == 0 and tag.family == P.TAG_FAMILY
    assert tag.size_m == pytest.approx(P.TAG_BLACK_SIZE / 1000)
    assert tag.z == pytest.approx(P.TAG_CENTER_Z / 1000)
    # 機身原點到觸點凸台外表面：robot.xml 的 body_back 幾何 x = −0.019 m，凸台面在列印座標 x = BOSS_FACE_X。
    xml = (NAV_DIR.parents[2] / "mini_bdx/robots/open_duck_mini_v2/robot.xml").read_text()
    line = next(l for l in xml.splitlines() if 'mesh="body_back"' in l)
    gx = float(line.split('pos="')[1].split()[0])
    assert BASE_TO_CONTACT_M == pytest.approx(-(gx + P.BOSS_FACE_X / 1000), abs=1e-4)
    # 標籤在椅背正面（充電座座標 X = BACK_FRONT_X），面朝房間。
    assert tag.x - home.dock.pose.x == pytest.approx(P.BACK_FRONT_X / 1000, abs=2e-3)
    assert tag.yaw == pytest.approx(home.dock.pose.yaw)
    p = home.dock_base_pose(BASE_TO_CONTACT_M)
    assert (p.x, p.y) == pytest.approx((home.places["dock"].x, home.places["dock"].y), abs=1e-3)


def _expect(doc, text):
    with pytest.raises(MapError) as e:
        parse_map(doc)
    assert text in str(e.value), str(e.value)


def test_rejects_bad_maps(doc):
    d = copy.deepcopy(doc)
    d["format_version"] = 2
    _expect(d, "format_version")

    d = copy.deepcopy(doc)
    d["zones"] = [z for z in d["zones"] if z["kind"] != "stairs"]
    _expect(d, "樓梯必填")
    d["no_stairs"] = True
    parse_map(d)  # 明確宣告沒有樓梯就可以

    d = copy.deepcopy(doc)
    d["places"].append({"id": "Brother Room", "room": "brother_room", "pose": [2.0, 5.0]})
    _expect(d, "不符合")

    d = copy.deepcopy(doc)
    d["places"].append({"id": "in_wall", "room": "living_room", "pose": [3.0, 0.5]})  # 沙發裡
    _expect(d, "占據格")

    d = copy.deepcopy(doc)
    d["places"].append({"id": "on_stairs", "room": "hallway", "pose": [6.6, 3.5]})
    _expect(d, "禁區")

    d = copy.deepcopy(doc)
    d["tags"].append(copy.deepcopy(d["tags"][0]))
    _expect(d, "重複")

    d = copy.deepcopy(doc)
    d["doors"][0]["between"] = ["living_room", "garage"]
    _expect(d, "between")

    d = copy.deepcopy(doc)
    d["grid"]["rows"] = d["grid"]["rows"][:-1]
    _expect(d, "grid.rows")

    d = copy.deepcopy(doc)
    d["dock"]["tag_id"] = 99
    _expect(d, "dock.tag_id")


def test_grid_agrees_with_structures(home):
    g = home.grid
    for s in home.structures:
        cx, cy = (s.rect[0] + s.rect[2]) / 2, (s.rect[1] + s.rect[3]) / 2
        if (s.rect[2] - s.rect[0]) >= g.resolution and (s.rect[3] - s.rect[1]) >= g.resolution:
            assert g.occupied(cx, cy), s.id
    for d in home.doors.values():
        assert not g.occupied(*d.center)
    assert math.isclose(home.dock.staging_distance_m, 0.5)  # ADR-0004 §3：預備點約 50 cm
