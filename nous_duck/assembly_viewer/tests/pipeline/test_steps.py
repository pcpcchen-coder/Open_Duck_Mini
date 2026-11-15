"""組裝步驟（data/steps.yaml → steps.json）的檢查，以及步驟裡引用的 CAD 幾何事實。"""
import copy
import re

import pytest
import yaml

from viewer_pipeline.steps import STEPS, StepsError, build_steps, load_steps, resolve_selector


@pytest.fixture(scope="module")
def steps_doc(repo_root):
    return yaml.safe_load((repo_root / STEPS).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def steps(repo_root, scene):
    return load_steps(repo_root, scene)


def _servo_ids(step, scene):
    servo_of = {pid: s["id"] for s in scene["servos"] for pid in s["parts"]}
    return {servo_of[pid] for pid in step["adds"] if pid in servo_of}


def test_every_part_added_exactly_once(steps, scene):
    added = [pid for s in steps["steps"] for pid in s["adds"]]
    assert len(added) == len(set(added)) == len(scene["parts"]) == 138


def test_step_order(steps):
    assert [s["id"] for s in steps["steps"]] == [
        "servo_setup", "trunk", "feet", "shins", "thighs", "hips", "neck", "head_mechanism",
        "body_electronics", "head_shell", "battery", "body_shell", "expression_kit", "wiring_power", "calibration",
    ]


def test_servos_installed_in_expected_steps(steps, scene):
    by_id = {s["id"]: s for s in steps["steps"]}
    expected = {
        "trunk": {30}, "feet": {14, 24}, "shins": {13, 23}, "thighs": {12, 22},
        "hips": {10, 11, 20, 21}, "neck": {31}, "head_mechanism": {32, 33},
    }
    for step_id, ids in expected.items():
        assert _servo_ids(by_id[step_id], scene) == ids, step_id
    others = set(by_id) - set(expected)
    assert all(not _servo_ids(by_id[k], scene) for k in others)


def test_head_bottom_sheet_and_middle_top_go_in_with_head_mechanism(steps, parts_by_id):
    step = next(s for s in steps["steps"] if s["id"] == "head_mechanism")
    meshes = {parts_by_id[pid]["mesh"] for pid in step["adds"]}
    assert {"head_bot_sheet", "body_middle_top"} <= meshes


def test_print_frame_parts_only_in_optional_expression_step(steps, parts_by_id):
    for s in steps["steps"]:
        frames = {parts_by_id[pid]["placement"] for pid in s["adds"]}
        if "print_frame" in frames:
            assert s["id"] == "expression_kit" and s["optional"]
            assert frames == {"print_frame"}


def test_sources_point_to_existing_files_and_anchors(steps, repo_root):
    def slug(heading: str) -> str:  # GitHub 標題錨點
        return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")

    for s in steps["steps"]:
        assert s["sources"], s["id"]
        for src in s["sources"]:
            if "url" in src:
                assert src["url"].startswith("https://github.com/apirrone/"), src
                continue
            path, _, anchor = src["path"].partition("#")
            f = repo_root / path
            assert f.exists(), src
            if anchor:
                headings = [slug(m) for m in re.findall(r"^#+\s+(.*)$", f.read_text(encoding="utf-8"), re.M)]
                assert anchor in headings, src


def test_resolve_selectors(scene):
    assert len(resolve_selector("servo:13", scene)) == 5
    assert len(resolve_selector("mesh:roll_motor_bottom", scene)) == 2
    assert resolve_selector("mesh:board@head_assembly", scene) == ["head_assembly/board"]
    assert len(resolve_selector("body:foot_assembly_2", scene)) == 4
    for bad in ("servo:99", "mesh:nope", "body:nope", "part:nope", "foo:bar", "servo", "servo:x"):
        with pytest.raises(StepsError):
            resolve_selector(bad, scene)


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d["steps"][1]["adds"].append("servo:14"), "同時在"),
        (lambda d: d["steps"][1]["adds"].remove("part:trunk_assembly/trunk_top"), "沒有在任何步驟裝上"),
        (lambda d: d["steps"][1].__setitem__("focus", ["servo:14"]), "還沒裝上"),
        (lambda d: d["steps"][1].__setitem__("adds", d["steps"][1]["adds"] + ["mesh:typo"]), "對不到"),
        (lambda d: d["steps"][2].__setitem__("id", "trunk"), "重複"),
        (lambda d: d["steps"][1].pop("check"), "缺少欄位"),
        (lambda d: d["steps"][1].__setitem__("colour", "red"), "不認得的欄位"),
        (lambda d: d["steps"][1]["sources"].append({"label": "x"}), "path、url 擇一"),
    ],
)
def test_validation_errors(steps_doc, scene, mutate, message):
    doc = copy.deepcopy(steps_doc)
    mutate(doc)
    with pytest.raises(StepsError, match=message):
        build_steps(doc, scene)


# ---- 步驟警語引用的 CAD 幾何事實（+X 是鴨子的左邊）----

def _horn_x(scene, sid):
    return next(s for s in scene["servos"] if s["id"] == sid)["horn_center_mm"][0]


def _leg_center_x(scene, side):
    feet = [p for p in scene["parts"] if p["mesh"] == "foot_bottom_tpu"]
    xs = [p["center_mm"][0] for p in feet]
    return max(xs) if side == "left" else min(xs)


def test_knee_and_ankle_servos_outside_on_left_inside_on_right(scene):
    left_c, right_c = _leg_center_x(scene, "left"), _leg_center_x(scene, "right")
    for sid in (23, 24):  # 左腿：舵盤在外側（x 比腿中心大）
        assert _horn_x(scene, sid) - left_c > 10
    for sid in (13, 14):  # 右腿：舵盤在內側（x 比腿中心大，靠近中線）
        assert _horn_x(scene, sid) - right_c > 10
    for sid in (12, 22):  # 髖俯仰左右都在外側
        c = left_c if sid == 22 else right_c
        assert abs(_horn_x(scene, sid)) > abs(c) + 10


def test_leg_sheet_assembly_rotated_180_on_right(scene):
    for body_l, body_r in (("knee_and_ankle_assembly", "knee_and_ankle_assembly_3"),
                           ("knee_and_ankle_assembly_2", "knee_and_ankle_assembly_4")):
        def x(body, mesh):
            return next(p for p in scene["parts"] if p["body"] == body and p["mesh"] == mesh)["center_mm"][0]
        # 左腿：right_sheet 靠中線（x 較小）；右腿：right_sheet 在外側（x 較小＝更往右）
        assert x(body_l, "left_knee_to_ankle_right_sheet") < x(body_l, "left_knee_to_ankle_left_sheet")
        assert abs(x(body_r, "left_knee_to_ankle_right_sheet")) > abs(x(body_r, "left_knee_to_ankle_left_sheet"))


def test_neck_horns_off_centerline(scene):
    for sid in (30, 31):
        assert _horn_x(scene, sid) == pytest.approx(16.6, abs=0.05)
