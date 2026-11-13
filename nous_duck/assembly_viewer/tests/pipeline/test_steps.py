from collections import Counter

import pytest
import yaml

from viewer_pipeline.scene import STEPS, build


def _steps_data(repo_root):
    return yaml.safe_load((repo_root / STEPS).read_text(encoding="utf-8"))


def _build_with(repo_root, tmp_path, data):
    path = tmp_path / "steps.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return build(repo_root, steps_path=path)


def _step(scene, step_id):
    return next(s for s in scene["steps"] if s["id"] == step_id)


def _servos_added(scene, step_id):
    parts = {p["id"]: p for p in scene["parts"]}
    return {parts[pid]["servo_id"] for pid in _step(scene, step_id)["adds"] if parts[pid]["servo_id"] is not None}


def test_every_part_added_exactly_once(scene):
    added = Counter(pid for s in scene["steps"] for pid in s["adds"])
    assert set(added) == {p["id"] for p in scene["parts"]}
    assert all(n == 1 for n in added.values())
    for p in scene["parts"]:
        assert p["id"] in scene["steps"][p["step"]]["adds"]


def test_step_order_follows_upstream(scene):
    order = [s["id"] for s in scene["steps"]]
    assert order[0] == "configure_motors"
    assert order[-1] == "power_on"
    # 上游順序：軀幹 → 腳 → 小腿 → 大腿 → 髖 → 頸 → 頭部關節 → 驅動板 → IMU → 電池 → 頭 → 機身
    upstream = ["trunk", "feet", "shins", "thighs", "hips", "neck", "head_mechanism", "servo_driver", "imu", "battery_pack", "head", "body"]
    assert [i for i in order if i in upstream] == upstream


def test_servos_go_where_the_upstream_guide_says(scene):
    assert _servos_added(scene, "trunk") == {30}  # 上游：「Mount the middle motor」
    assert _servos_added(scene, "feet") == {14, 24}
    assert _servos_added(scene, "shins") == {13, 23}
    assert _servos_added(scene, "thighs") == {12, 22}
    assert _servos_added(scene, "hips") == {10, 11, 20, 21}
    assert _servos_added(scene, "neck") == {31}
    assert _servos_added(scene, "head_mechanism") == {32, 33}


def test_configure_step_focuses_all_servos(scene):
    step = _step(scene, "configure_motors")
    assert step["adds"] == []
    parts = {p["id"]: p for p in scene["parts"]}
    assert {parts[pid]["servo_id"] for pid in step["focus"]} == set(range(10, 15)) | set(range(20, 25)) | set(range(30, 34))


def test_bom_references_exist(scene):
    bom_ids = {r["id"] for r in scene["bom"]}
    for step in scene["steps"]:
        assert set(step["bom"]) <= bom_ids, step["id"]


def test_every_bom_part_is_used_in_some_step(scene):
    """每個 BOM 零件都要在某一步用到。例外：材料與工具、上游註明尚未整合的零件，
    以及「其他 M3 螺絲」（整個組裝過程都會用到，上游沒寫用在哪一步）。"""
    used = {b for s in scene["steps"] for b in s["bom"]}
    for row in scene["bom"]:
        if row["category"] in ("material", "tool") or row.get("upstream_status_zh") or row["id"] == "m3_screws_other":
            continue
        assert row["id"] in used, row["id"]


def test_images_and_links(scene, repo_root):
    for step in scene["steps"]:
        assert step["upstream_url"].startswith("https://github.com/apirrone/Open_Duck_Mini/blob/v2/docs/")
        for img in step["images"]:
            assert img["url"].startswith("https://github.com/"), img
            if img["kind"] == "repo_file":
                assert (repo_root / img["path"]).is_file()


def test_bilingual_lists_have_same_length(scene):
    for step in scene["steps"]:
        assert len(step["tasks_zh"]) == len(step["tasks_en"]) > 0, step["id"]


def test_deviations_and_optional_are_marked(scene):
    assert _step(scene, "wiring")["deviation_zh"]
    assert _step(scene, "body")["deviation_zh"]
    assert _step(scene, "expression")["optional"] is True
    assert sum(s["optional"] for s in scene["steps"]) == 1


def test_part_added_twice_fails(repo_root, tmp_path):
    data = _steps_data(repo_root)
    next(s for s in data["steps"] if s["id"] == "body")["adds"].append({"mesh": "trunk_top"})
    with pytest.raises(ValueError, match="已經在第"):
        _build_with(repo_root, tmp_path, data)


def test_part_never_added_fails(repo_root, tmp_path):
    data = _steps_data(repo_root)
    step = next(s for s in data["steps"] if s["id"] == "imu")
    step["adds"] = []
    with pytest.raises(ValueError, match="沒有在任何步驟裝上"):
        _build_with(repo_root, tmp_path, data)


def test_unknown_bom_reference_fails(repo_root, tmp_path):
    data = _steps_data(repo_root)
    next(s for s in data["steps"] if s["id"] == "imu")["bom"] = ["imu_mpu6050"]
    with pytest.raises(ValueError, match="imu_mpu6050"):
        _build_with(repo_root, tmp_path, data)


def test_bad_image_fails(repo_root, tmp_path):
    data = _steps_data(repo_root)
    next(s for s in data["steps"] if s["id"] == "imu")["images"] = ["docs/no_such_photo.png"]
    with pytest.raises(ValueError, match="no_such_photo"):
        _build_with(repo_root, tmp_path, data)


def test_mismatched_translation_fails(repo_root, tmp_path):
    data = _steps_data(repo_root)
    next(s for s in data["steps"] if s["id"] == "trunk")["tasks_en"].pop()
    with pytest.raises(ValueError, match="項目數不同"):
        _build_with(repo_root, tmp_path, data)
