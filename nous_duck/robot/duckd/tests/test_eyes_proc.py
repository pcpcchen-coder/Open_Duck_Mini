"""眼睛子行程：狀態送得到、子行程死掉看得出來並重啟、capabilities 誠實。用真的 spawn 子行程（沒有硬體）。"""
import time

import pytest
from conftest import make_harness

from duckd import eyes_proc
from duckd.eyes_proc import EyesProcess


def wait_for(cond, timeout=20.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def proc(tmp_path):
    made = []

    def make(**kw):
        e = EyesProcess(tmp_path / "eyes.png", fps=10, **kw)
        made.append(e)
        e.start()
        return e

    yield make
    for e in made:
        e.stop()


def test_child_renders_and_follows_parent_state(proc, tmp_path):
    eyes = proc()
    assert wait_for(lambda: eyes.stats().get("frames", 0) > 0), eyes.stats()
    assert (tmp_path / "eyes.png").exists()
    st = eyes.stats()
    assert st["panel"] == "virtual_png" and st["process"]["alive"] and st["process"]["pid"]
    eyes.set_base("thinking")
    assert wait_for(lambda: eyes.stats().get("expression") == "thinking")
    assert eyes.expression == "thinking"  # 父行程讀回的表情
    eyes.express("happy", 2.5)  # express 到期由父行程決定（子行程每秒回報一次）
    assert wait_for(lambda: eyes.stats().get("expression") == "happy")
    assert wait_for(lambda: eyes.stats().get("expression") == "thinking")


def test_parent_never_renders(proc):
    eyes = proc()
    with pytest.raises(RuntimeError):
        eyes.render_once()


def test_hardware_open_failure_in_child_is_reported(proc):
    eyes = proc(hw_kwargs={"hz": 1_000_000})  # Mac／CI 沒有 spidev／gpiod：子行程打不開
    assert wait_for(lambda: eyes.stats().get("frames", 0) > 0)
    assert eyes.panel_kind == "virtual_png" and "open failed" in eyes.hardware_error
    cap = make_harness(eyes=eyes).sent[0]["capabilities"]["eyes"]
    assert cap["status"] == "mock" and "failed" in cap["reason"]


def test_child_death_is_detected_and_restarted(proc, monkeypatch):
    monkeypatch.setattr(eyes_proc, "RESTART_S", 0.3)
    eyes = proc()
    assert wait_for(lambda: eyes.stats().get("frames", 0) > 0)
    first = eyes._proc.pid
    eyes._proc.kill()
    assert wait_for(lambda: eyes.restarts == 1 and eyes._proc is not None and eyes._proc.pid != first)
    assert wait_for(lambda: eyes.stats().get("frames", 0) > 0)
    assert eyes.stats()["process"]["restarts"] == 1


def test_capability_degraded_only_while_child_reports_real_panels(proc):
    eyes = proc()
    eyes._child_stats, eyes._child_stats_at = {"panel": "gc9a01", "frames": 1}, time.monotonic()
    cap = make_harness(eyes=eyes).sent[0]["capabilities"]["eyes"]
    assert cap["status"] == "degraded"
    eyes._child_stats_at = time.monotonic() - 10  # 回報過期：不再說有實體螢幕
    assert eyes.panel_kind == "virtual_png"
