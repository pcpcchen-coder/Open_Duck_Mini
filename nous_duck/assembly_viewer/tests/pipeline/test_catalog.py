from collections import Counter

import numpy as np
import pytest
import yaml

from test_geometry import quat_xyzw_to_matrix
from viewer_pipeline.catalog import load_catalog
from viewer_pipeline.geometry import read_binary_stl
from viewer_pipeline.scene import CATALOG, PRINT_DIR, PRINT_GUIDE
from viewer_pipeline.upstream import print_list


def test_print_guide_totals(repo_root):
    items = print_list(repo_root / PRINT_GUIDE)
    assert len(items) == 36
    assert sum(v["count"] for v in items.values()) == 51
    assert items["foot_bottom_tpu.stl"] == {"count": 2, "material": "TPU"}


def test_printed_pieces_match_print_guide(scene, repo_root):
    expected = {k: v["count"] for k, v in print_list(repo_root / PRINT_GUIDE).items()}
    got = Counter(p["print_stl"] for p in scene["parts"] if p["kind"] == "printed")
    assert dict(got) == expected


def test_part_kinds(scene):
    kinds = Counter(p["kind"] for p in scene["parts"])
    assert kinds == {"printed": 51, "servo_part": 70, "electronics": 9, "power": 3, "bearing": 3, "other": 2}


def test_every_part_is_named(scene):
    for p in scene["parts"]:
        assert p["name_zh"] and p["name_en"], p["id"]


def test_boards_identified_by_location(scene):
    boards = {p["body"]: p for p in scene["parts"] if p["mesh"] == "board"}
    assert boards["trunk_assembly"]["name_zh"] == "舵機驅動板"
    assert boards["head_assembly"]["name_zh"] == "5V 降壓模組（UBEC）"
    assert all("推定" in b["identification"] for b in boards.values())


def test_print_only_parts_are_marked_and_on_the_head(scene, repo_root):
    extras = [p for p in scene["parts"] if p["placement"] == "print_frame"]
    assert sorted(p["print_stl"] for p in extras) == sorted(
        f"{k}.stl"
        for k in ("left_eye", "right_eye", "bulb", "flash_light_module", "flash_reflector_interface", "speaker_interface", "speaker_stand")
    )
    for p in extras:
        assert p["identification"] and "CAD 沒有擺放位置" in p["identification"]

    head = next(p for p in scene["parts"] if p["mesh"] == "head")
    head_mesh = scene["meshes"]["head"]
    local = read_binary_stl(repo_root / head_mesh["source"]).reshape(-1, 3) * 1000.0
    world = local @ quat_xyzw_to_matrix(head["quaternion_xyzw"]).T + head["position_mm"]
    lo, hi = world.min(0) - 15.0, world.max(0) + 15.0  # 頭殼外框外加 15 mm
    by_name = {p["print_stl"]: p for p in extras}
    for p in extras:
        assert p["body"] == head["body"]
        assert np.all(p["center_mm"] >= lo) and np.all(p["center_mm"] <= hi), p["id"]
    # 眼睛在頭的前方（+Z），左眼在鴨子左邊（+X）、右眼在右邊
    for eye in ("left_eye.stl", "right_eye.stl"):
        assert by_name[eye]["center_mm"][2] > head["center_mm"][2]
    assert by_name["left_eye.stl"]["center_mm"][0] > head["center_mm"][0]
    assert by_name["right_eye.stl"]["center_mm"][0] < head["center_mm"][0]


def test_catalog_missing_mesh_fails(repo_root, tmp_path):
    data = yaml.safe_load((repo_root / CATALOG).read_text(encoding="utf-8"))
    del data["cad_meshes"]["bno055"]
    path = tmp_path / "cad_parts.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="bno055"):
        load_catalog(path, set(data["cad_meshes"]) | {"bno055"}, repo_root / PRINT_DIR)


def test_catalog_bad_print_file_fails(repo_root, tmp_path):
    data = yaml.safe_load((repo_root / CATALOG).read_text(encoding="utf-8"))
    data["cad_meshes"]["head"]["print_stl"] = "no_such_file.stl"
    path = tmp_path / "cad_parts.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="no_such_file"):
        load_catalog(path, set(data["cad_meshes"]), repo_root / PRINT_DIR)
