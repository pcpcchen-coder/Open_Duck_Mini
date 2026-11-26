"""加裝件質量模型（walk_sim.mass）與比較腳本（walk_sim.mass_compare）的測試。

驗證層級：單元測試（慣量合併的數學、預算檔格式）與模擬（`--runslow` 的快速比較）。
"""

import mujoco
import numpy as np
import pytest

from walk_sim.mass import (
    Inertial,
    MassItem,
    _box_inertia,
    apply_mass_items,
    budget_items,
    home_body_frames,
    load_budget,
    model_summary,
)
from walk_sim.model import ModelOptions, build_model, build_spec

BUDGET = "p2_single_pi4.json"


def _subtree(m):
    b0 = m.body("base").id
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    return float(m.body_subtreemass[b0])


def test_add_then_remove_restores_body_inertia():
    spec = build_spec(ModelOptions())
    before = Inertial.from_body(spec.body("head_assembly"))
    item = MassItem("x", "head_assembly", 0.05, (0.09, 0.02, 0.21), (0.02, 0.06, 0.03))
    apply_mass_items(spec, [item])
    apply_mass_items(spec, [MassItem("x_out", "head_assembly", -0.05, item.pos_base, item.size_base)])
    after = Inertial.from_body(spec.body("head_assembly"))
    assert after.mass == pytest.approx(before.mass, abs=1e-12)
    assert np.allclose(after.com, before.com, atol=1e-12)
    assert np.allclose(after.I_com, before.I_com, atol=1e-12)


def test_combine_matches_point_mass_formula():
    """兩個質點合併：質心是加權平均，慣量等於各自對新質心的平行軸和。"""
    a = Inertial(1.0, np.array([0.0, 0, 0]), np.zeros((3, 3)))
    c = a.combine(1.0, np.array([0.2, 0, 0]), np.zeros((3, 3)), 1.0)
    assert c.mass == 2.0
    assert np.allclose(c.com, [0.1, 0, 0])
    # 兩個 1 kg 質點相距 0.2 m，對中點：Iyy = Izz = 2 × 1 × 0.1² = 0.02，Ixx = 0。
    assert np.allclose(np.diag(c.I_com), [0, 0.02, 0.02])


def test_box_inertia():
    I = _box_inertia(1.2, np.array([0.1, 0.2, 0.3]))
    assert np.allclose(np.diag(I), [0.1 * (0.04 + 0.09), 0.1 * (0.01 + 0.09), 0.1 * (0.01 + 0.04)])


def test_item_position_is_base_frame_at_home_pose():
    """加在頭上的元件，編譯後在起始姿勢的世界位置要等於 pos_base（base 在原點上方 HOME_BASE_Z）。"""
    pos = (0.09, 0.0, 0.21)
    spec = build_spec(ModelOptions())
    frames = home_body_frames(spec)
    pB, RB = frames["head_assembly"]
    # 頭的座標跟 base 不同向（上游 CAD 轉了 90°），換算必須用到旋轉。
    assert not np.allclose(RB, np.eye(3))
    log = apply_mass_items(spec, [MassItem("x", "head_assembly", 0.1, pos)])
    back = pB + RB @ np.array(log[0]["pos_body"])
    assert np.allclose(back, pos, atol=1e-4)


def test_removing_too_much_raises():
    spec = build_spec(ModelOptions())
    with pytest.raises(ValueError):
        apply_mass_items(spec, [MassItem("too_much", "head_assembly", -5.0, (0.0, 0.0, 0.2))])


def test_unknown_body_raises():
    spec = build_spec(ModelOptions())
    with pytest.raises(KeyError):
        apply_mass_items(spec, [MassItem("x", "no_such_body", 0.01, (0, 0, 0))])


def test_budget_file_is_consistent():
    b = load_budget(BUDGET)
    ids = {c["id"] for c in b["components"]}
    assert "pi_zero_2w" in ids and "pi4_board" in ids
    for c in b["components"]:
        assert c["source"]["kind"] != "measured", "目前沒有任何元件秤過；秤過之後再改這個測試"
    # high 一定是最重、low 一定最輕（拿掉的元件反向取值）。
    tot = {lv: sum(i.mass_kg for i in budget_items(b, lv)) for lv in ("low", "nominal", "high")}
    assert tot["low"] < tot["nominal"] < tot["high"]


def test_budget_total_mass_matches_sum():
    b = load_budget(BUDGET)
    items = budget_items(b, "nominal")
    up = _subtree(build_model(ModelOptions()))
    p2 = _subtree(build_model(ModelOptions(mass_items=tuple(items))))
    assert p2 - up == pytest.approx(sum(i.mass_kg for i in items), abs=1e-9)
    # 估計值的增量：手算 −15＋50＋10＋15＋30＋20＋42＋10＋15＋5＋8.4＋8.4＋10＋0 = 208.8 g。
    assert p2 - up == pytest.approx(0.2088, abs=1e-6)


def test_model_summary_moves_head_mass():
    b = load_budget(BUDGET)
    up = model_summary(build_model(ModelOptions()))
    p2 = model_summary(build_model(ModelOptions(mass_items=tuple(budget_items(b, "nominal")))))
    # 頭部（head_assembly 以下）：拿掉 Pi Zero 15 g，加上鏡頭、補光、雙眼、線材共 46.8 g → 淨增 31.8 g。
    assert p2["head_assembly_mass_kg"] - up["head_assembly_mass_kg"] == pytest.approx(0.0318, abs=1e-4)


@pytest.mark.slow
def test_quick_compare_runs():
    pytest.importorskip("onnxruntime")
    from walk_sim import mass_compare

    out = mass_compare.run_all(quick=True, workers=2)
    names = [p["name"] for p in out["profiles"]]
    assert names == ["upstream", "p2_nominal"]
    for p in out["profiles"]:
        assert not p["stand"]["fallen"]
        assert all(r["fallen"] == 0 for r in p["walk"])
    assert out["simulated"] is True
