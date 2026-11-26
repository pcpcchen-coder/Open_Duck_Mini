"""全身走路模擬（C1）與量測工具（C2）的測試。驗證層級：模擬。"""

import math

import numpy as np
import pytest

pytest.importorskip("onnxruntime")

from walk_sim import measure
from walk_sim.model import CONTROL_DT, HOME_POSE, POLICY_JOINTS, ModelOptions, build_model
from walk_sim.sim import OBS_DIM, PHASE_PERIOD_STEPS, SimOptions, WalkSim, clamp_command


def test_model_matches_policy_layout():
    m = build_model()
    assert m.nu == 16  # 14 個策略關節＋2 個天線
    assert m.nq == 7 + 16
    assert abs(m.opt.timestep * 10 - CONTROL_DT) < 1e-12
    for n in POLICY_JOINTS:
        a = m.actuator(n)
        assert a.gainprm[0] == pytest.approx(13.37)
        assert a.forcerange[1] == pytest.approx(3.23)
    assert set(HOME_POSE) == set(POLICY_JOINTS)
    # 只有鞋底與簡化外殼會碰撞。
    colliding = [m.geom(i).name for i in range(m.ngeom) if m.geom_contype[i] or m.geom_conaffinity[i]]
    assert sorted(colliding) == sorted(["floor", "left_foot_bottom_tpu", "right_foot_bottom_tpu", "hull_trunk", "hull_head"])


def test_observation_layout():
    sim = WalkSim()
    cmd = clamp_command([0.1, -0.05, 0.3, 0.1, 0.2, 0.3, 0.4])
    obs = sim.observation(cmd)
    assert obs.shape == (OBS_DIM,)
    assert np.allclose(obs[6:13], cmd)
    assert np.allclose(obs[13:27], 0, atol=0.05)  # 起始姿勢
    assert np.allclose(obs[83:97], [HOME_POSE[n] for n in POLICY_JOINTS])
    assert PHASE_PERIOD_STEPS == int(0.54 * 50)


def test_clamp_command_uses_upstream_ranges():
    c = clamp_command([1, -1, 5, 9, 9, 9, 9])
    assert list(c) == [0.15, -0.2, 1.0, 1.1, 0.78, 1.5, 0.5]


def test_stands_still_on_zero_command():
    sim = WalkSim()
    infos = [sim.step() for _ in range(250)]
    assert not infos[-1].fallen
    assert max(i.tilt_deg for i in infos) < 10
    assert math.hypot(infos[-1].x, infos[-1].y) < 0.03
    # 模擬裡速度指令為 0 時策略不踏步（兩腳一直著地）。
    assert measure.stepping_fraction(infos[100:]) == 0.0


def test_walks_forward_and_is_deterministic():
    def run():
        sim = WalkSim(SimOptions(seed=0))
        for _ in range(50):
            sim.step()
        for _ in range(400):
            info = sim.step([0.15, 0, 0])
        return info

    a, b = run(), run()
    assert (a.x, a.y, a.yaw) == (b.x, b.y, b.yaw)
    assert not a.fallen
    assert 0.6 < a.x < 1.1  # 8 秒、指令 0.15 m/s；模擬量到約 0.115 m/s
    assert abs(a.y) < 0.25


def test_turn_direction_and_backward():
    sim = WalkSim()
    tr, infos, _ = measure.run_segment(sim, [0, 0, 1.0], 4.0)
    assert tr.yaw > 2.0  # 正的 yaw_rate 是逆時針
    assert not infos[-1].fallen
    sim = WalkSim()
    tr, infos, _ = measure.run_segment(sim, [-0.15, 0, 0], 6.0)
    assert tr.fwd < -0.15


def test_small_commands_do_not_start_walking():
    """已知現象（模擬）：小於起步門檻的指令，策略留在原地。導航的速度選擇依這個結果。"""
    sim = WalkSim()
    measure.run_segment(sim, [0, 0, 0], 1.0)
    tr, infos, _ = measure.run_segment(sim, [0.05, 0, 0], 6.0)
    assert measure.stepping_fraction(infos) < 0.05
    assert abs(tr.fwd) < 0.02


def test_ramp_respects_adr0009_limits():
    cur = np.zeros(7)
    cur = measure.ramp(cur, np.array([0.15, -0.2, 1.0, 0, 0, 0, 0]))
    assert cur[0] == pytest.approx(0.01) and cur[1] == pytest.approx(-0.01) and cur[2] == pytest.approx(0.05)


def test_extra_mass_option_changes_total_mass():
    base = float(build_model().body_mass.sum())
    heavy = float(build_model(ModelOptions(extra_mass_kg=0.2)).body_mass.sum())
    assert heavy - base == pytest.approx(0.2, abs=1e-6)
    assert base == pytest.approx(2.0615, abs=1e-3)


def test_cli_writes_csv(tmp_path):
    from walk_sim.__main__ import main

    rc = main(["--vx", "0.15", "--duration", "2", "--settle", "0.5", "--out", str(tmp_path)])
    assert rc == 0
    lines = (tmp_path / "trajectory.csv").read_text().splitlines()
    assert len(lines) == 1 + 125
    assert "simulated" in (tmp_path / "summary.json").read_text()


@pytest.mark.slow
def test_measure_quick_runs():
    res = measure.run_all(quick=True)
    assert res["simulated"] is True
    assert all(r["falls"] == 0 for r in res["fall_rate"])
