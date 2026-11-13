import copy
import csv
from collections import Counter

import pytest
import yaml

from viewer_pipeline.scene import BOM, PRINT_GUIDE, build
from viewer_pipeline.upstream import print_list

UPSTREAM_CSV = "nous_duck/docs/handoff/upstream_bom.csv"


def _upstream_rows(repo_root):
    with open(repo_root / UPSTREAM_CSV, encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


def _price(text):
    return float(text.replace(",", ".")) if text.strip() else None


def _bom_data(repo_root):
    return yaml.safe_load((repo_root / BOM).read_text(encoding="utf-8"))


def _build_with(repo_root, tmp_path, data):
    path = tmp_path / "bom.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return build(repo_root, bom_path=path)


def test_items_match_upstream_csv(scene, repo_root):
    """每個標註上游 BOM 的項目：名稱、數量、單價都要和 CSV 那一列完全相同。"""
    rows = _upstream_rows(repo_root)
    for item in scene["bom"]:
        up = item.get("upstream")
        if not up:
            continue
        row = rows[up["csv_row"] - 1]
        assert row[1].strip() == up["name"].strip(), item["id"]
        assert float(row[3]) == up["qty"], item["id"]
        assert _price(row[4]) == up["unit_price_eur"], item["id"]


def test_every_upstream_row_is_used_once(scene, repo_root):
    """反向檢查：上游 BOM 的每一列零件都要被剛好一個項目引用，沒有漏抄。"""
    rows = _upstream_rows(repo_root)
    part_rows = [i + 1 for i, r in enumerate(rows) if len(r) > 3 and r[1].strip() and r[3].strip() and r[1].strip() != "Part"]
    used = Counter(item["upstream"]["csv_row"] for item in scene["bom"] if item.get("upstream"))
    assert sorted(used) == part_rows
    assert all(n == 1 for n in used.values())
    assert len(part_rows) == 29


def test_printed_rows_follow_print_guide(scene, repo_root):
    printed = [r for r in scene["bom"] if r["category"] == "printed"]
    expected = print_list(repo_root / PRINT_GUIDE)
    assert {r["print_stl"]: r["qty"] for r in printed} == {k: v["count"] for k, v in expected.items()}
    assert {r["print_stl"]: r["material"] for r in printed}["foot_bottom_tpu.stl"] == "TPU"
    assert sum(r["qty"] for r in printed) == 51
    assert all(len(r["parts"]) == r["qty"] for r in printed)


def test_every_3d_part_has_exactly_one_owner(scene):
    owners = Counter()
    for row in scene["bom"]:
        owners.update(row["parts"])
    for entry in scene["cad_without_bom"]:
        owners.update(entry["parts"])
    assert set(owners) == {p["id"] for p in scene["parts"]}
    assert all(n == 1 for n in owners.values())
    # 零件上記錄的 bom_id 與 BOM 一致；天線不屬於任何 BOM 項目
    bom_of = {pid: row["id"] for row in scene["bom"] for pid in row["parts"]}
    for p in scene["parts"]:
        assert p["bom_id"] == bom_of.get(p["id"]), p["id"]
    assert [e["mesh"] for e in scene["cad_without_bom"]] == ["antenna"]


def test_scene_quantities(scene):
    by_id = {r["id"]: r for r in scene["bom"]}
    assert len(by_id["sts3215"]["parts"]) == 14 * 5
    assert len(by_id["cell_18650"]["parts"]) == 2
    assert len(by_id["bearing"]["parts"]) == 3
    parts = {p["id"]: p for p in scene["parts"]}
    assert {parts[pid]["body"] for pid in by_id["servo_driver"]["parts"]} == {"trunk_assembly"}
    assert {parts[pid]["body"] for pid in by_id["ubec_5v"]["parts"]} == {"head_assembly"}


def test_items_without_3d_explain_why(scene):
    for row in scene["bom"]:
        if row["category"] in ("printed", "material", "tool"):
            continue
        assert row["parts"] or row.get("scene_note_zh"), row["id"]
        if row["qty"] is None:
            assert row.get("qty_note_zh"), row["id"]


def test_expression_package_is_marked(scene):
    expression = {r["id"] for r in scene["bom"] if r["package"] == "expression"}
    assert {"speaker", "amplifier", "led", "eye_diffuser", "projector_reflector", "microphone", "pi_camera"} <= expression
    assert "print:left_eye.stl" in expression


def test_wrong_quantity_fails(repo_root, tmp_path):
    data = _bom_data(repo_root)
    next(i for i in data["items"] if i["id"] == "cell_18650")["qty"] = 3
    with pytest.raises(ValueError, match="qty 是 3"):
        _build_with(repo_root, tmp_path, data)


def test_double_claim_fails(repo_root, tmp_path):
    data = _bom_data(repo_root)
    dup = copy.deepcopy(next(i for i in data["items"] if i["id"] == "cell_18650"))
    dup["id"] = "cell_again"
    data["items"].append(dup)
    with pytest.raises(ValueError, match="同時屬於"):
        _build_with(repo_root, tmp_path, data)


def test_uncovered_part_fails(repo_root, tmp_path):
    data = _bom_data(repo_root)
    data["cad_without_bom"] = []
    with pytest.raises(ValueError, match="不屬於任何 BOM"):
        _build_with(repo_root, tmp_path, data)


def test_missing_scene_explanation_fails(repo_root, tmp_path):
    data = _bom_data(repo_root)
    item = next(i for i in data["items"] if i["id"] == "foot_switch")
    del item["scene_note_zh"], item["scene_note_en"]
    with pytest.raises(ValueError, match="擇一"):
        _build_with(repo_root, tmp_path, data)


def test_missing_translation_fails(repo_root, tmp_path):
    data = _bom_data(repo_root)
    del next(i for i in data["items"] if i["id"] == "sts3215")["note_en"]
    with pytest.raises(ValueError, match="note_en"):
        _build_with(repo_root, tmp_path, data)


def test_typo_in_selector_fails(repo_root, tmp_path):
    data = _bom_data(repo_root)
    next(i for i in data["items"] if i["id"] == "bms_2s")["scene"] = [{"mesh": "bmss"}]
    with pytest.raises(ValueError, match="bmss"):
        _build_with(repo_root, tmp_path, data)
