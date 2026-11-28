"""duckd 讀鴨子設定（ADR-0019）：啟動值、即時套用、功能開關、回報實際在用的值、讀不到時的保守值。

設定檔用真的 `duck_settings.store.Store` 寫；身體是模擬的（mock）。
"""
import argparse
import json
import math
import sys
from pathlib import Path

import pytest

from conftest import REPO, make_harness
from duckd import presence as pr
from duckd.limits import Limits
from duckd.settings_in import CONSERVATIVE, SettingsInput

sys.path.insert(0, str(REPO / "nous_duck" / "robot" / "settings"))
from duck_settings import schema  # noqa: E402
from duck_settings.store import Store  # noqa: E402


class FakeSource:
    def __init__(self, ok=True, mock=True, detail=""):
        self.ok, self.mock, self.detail = ok, mock, detail


class FakePercept:
    """假的感知輸入（mock）：只回答「聲音來源還在」。"""

    def source(self, kind, max_age):
        return FakeSource() if kind == "sound" else None

    def get(self, kind, max_age):
        return None


def test_fallback_matches_schema_defaults_and_limits_accept_every_allowed_value():
    assert CONSERVATIVE == {k: schema.BY_KEY[k].default for k in CONSERVATIVE}
    s = schema.BY_KEY["head.speed_deg_s"]
    for deg in (s.min, s.default, s.max):
        Limits(head_max_speed=math.radians(deg))  # 設定頁允許的範圍，duckd 的硬上限都收


def test_startup_values_come_from_settings_and_are_reported(tmp_path):
    store = Store(tmp_path)
    store.apply({"head.speed_deg_s": 45, "head.window_deg": 20, "hearing.settle_s": 1.4, "features.gestures": False}, "web")
    si = SettingsInput(tmp_path)
    assert si.startup == {"head.speed_deg_s": 45.0, "head.window_deg": 20.0} and si.status()["ok"]
    from duckd.eyes_out import EyesOutput

    h = make_harness(percept=FakePercept(), eyes=EyesOutput(None))  # 眼睛的設定只有眼睛渲染在跑時才回報
    assert si.poll(h.core, force=True)
    assert h.core.sound.cfg.settle_s == 1.4 and h.core.features["gestures"] is False
    report = json.loads((tmp_path / "applied" / "duckd.json").read_text())
    duckd_keys = {s.key for s in schema.SETTINGS if s.consumer == "duckd"}
    assert set(report["values"]) == duckd_keys  # 每一項 duckd 的設定都有回報
    assert report["values"]["head.speed_deg_s"] == 45.0 and report["values"]["hearing.settle_s"] == 1.4
    assert all(report["values"][k] == v for k, v in store.load().values.items() if k in duckd_keys)
    # 之後改了「要重啟」的項目：回報的仍是啟動時的值（設定頁才會顯示「要重啟」）
    store.apply({"head.speed_deg_s": 20, "hearing.recenter_s": 15}, "web")
    assert si.poll(h.core) and not si.poll(h.core)
    report = json.loads((tmp_path / "applied" / "duckd.json").read_text())
    assert report["values"]["head.speed_deg_s"] == 45.0 and report["values"]["hearing.recenter_s"] == 15.0
    assert h.core.sound.cfg.recenter_s == 15.0


def test_unreadable_settings_fall_back_to_conservative_head_limits(tmp_path, monkeypatch):
    (tmp_path / "settings.json").write_text('{"values": {"head.speed_deg_s": 9999, "head.window_deg": "wide"}}')
    si = SettingsInput(tmp_path)  # 檔案裡的值不合格：不採用
    assert si.startup == CONSERVATIVE and len(si.status()["problems"]) == 2
    import duckd.settings_in as mod

    monkeypatch.setattr(mod, "ensure_sibling_packages", lambda: (_ for _ in ()).throw(ImportError("no duck_settings")))
    si = SettingsInput(tmp_path)
    assert si.watcher is None and si.startup == CONSERVATIVE and si.status()["ok"] is False
    assert si.poll(make_harness().core, force=True) is False


def test_main_build_uses_settings_unless_command_line_overrides(tmp_path):
    from duckd.__main__ import build

    Store(tmp_path).apply({"head.speed_deg_s": 40, "head.window_deg": 10, "features.speaking_bob": False}, "web")

    def args(**over):
        base = dict(settings_dir=tmp_path, head_speed_deg=None, head_window_deg=None, body="mock", no_eyes=True, no_percept=True,
                    eyes_panel=None, eyes_fps=1.0, percept_port=0, schema=None, duck_id="duck1", hardware_profile="stock_head_direct_hold",
                    allow_unverified_gestures=False, url="ws://127.0.0.1:1/duck-link", serial="", duck_config=Path("/nonexistent"))
        return argparse.Namespace(**{**base, **over})

    core, _ = build(args())
    assert core.arbiter.limits.head_max_speed == pytest.approx(math.radians(40)) and core.arbiter.limits.head_window == pytest.approx(math.radians(10))
    assert core.features["speaking_bob"] is False and core.settings_status["ok"]
    core, _ = build(args(head_speed_deg=25.0))  # 命令列有給：用命令列，而且回報的是實際在用的 25
    assert core.arbiter.limits.head_max_speed == pytest.approx(math.radians(25))
    assert json.loads((tmp_path / "applied" / "duckd.json").read_text())["values"]["head.speed_deg_s"] == 25.0
    core, _ = build(args(settings_dir=None))  # 沒有設定來源：和以前一樣（30°/s、不設視窗）
    assert core.arbiter.limits.head_max_speed == pytest.approx(math.radians(30)) and core.arbiter.limits.head_window is None
    assert core.settings_status is None and core.features == {"track_sound": True, "gestures": True, "presence_head_motion": True, "speaking_bob": True, "head_auto_engage": False}


def test_track_sound_switch_refuses_and_ends_tracking():
    h = make_harness(percept=FakePercept())
    assert h.cmd("track", {"target": "sound"})["status"] == "accepted" and h.core.tracking == "sound"
    h.core.apply_settings({"features.track_sound": False})
    assert h.core.tracking == "none"
    h.run(0.1)
    lost = h.events("tracking_lost")[-1]
    assert lost["reason"] == "disabled" and lost["data"] == {"target": "sound"}
    ack = h.cmd("track", {"target": "sound"})
    assert (ack["status"], ack["reason"]) == ("rejected", "unsupported") and "disabled in duck settings" in ack["detail"]
    assert h.core.capabilities()["tracking_sound"] == {"status": "unsupported", "reason": "disabled in duck settings"}
    assert h.cmd("track", {"target": "none"})["status"] == "accepted"
    h.core.apply_settings({"features.track_sound": True})
    assert h.cmd("track", {"target": "sound"})["status"] == "accepted"


def test_gesture_switch_refuses_and_hides_the_list():
    h = make_harness()
    assert "nod" in h.core.listed_gestures()
    assert h.cmd("gesture", {"name": "nod"})["status"] == "accepted"
    h.core.apply_settings({"features.gestures": False})
    h.run(0.1)
    done = h.events("gesture_done")[-1]
    assert done["data"]["completed"] is False  # 進行中的被中止
    ack = h.cmd("gesture", {"name": "nod"})
    assert (ack["status"], ack["reason"]) == ("rejected", "unsupported") and "disabled in duck settings" in ack["detail"]
    assert h.core.listed_gestures() == []


def test_presence_motion_switches_and_amplitude(h):
    p = pr.PresenceState()
    p.set("listening", None, 0.0)
    assert pr.head_target(p, 1.0)["head_roll"] == pytest.approx(0.12)
    assert pr.head_target(p, 1.0, amplitude=0.5)["head_roll"] == pytest.approx(0.06)
    assert pr.head_target(p, 1.0, amplitude=3.0)["head_roll"] == pytest.approx(0.12)  # 只能調小
    assert pr.head_target(p, 1.0, motion=False) == pr.ZERO
    p.set("speaking", 1.0, 0.0)
    bob = pr.head_target(p, 0.3)["head_pitch"]
    assert bob < 0 and pr.head_target(p, 0.3, speaking_bob=False) == pr.ZERO
    assert pr.head_target(p, 0.3, motion=False)["head_pitch"] == bob  # 兩個開關各管各的
    # 接到核心：關掉小動作後，聽的時候頭回正
    h.cmd("presence", {"state": "listening"})
    h.run(1.5)
    assert h.body.head["head_roll"] == pytest.approx(0.12, abs=0.01)
    h.core.apply_settings({"features.presence_head_motion": False})
    h.run(1.5)
    assert h.body.head["head_roll"] == pytest.approx(0.0, abs=0.005)


def test_sound_track_numbers_apply_live_and_keep_the_yaw_limit(h):
    limit = h.core.sound.cfg.yaw_limit
    applied = h.core.apply_settings({"hearing.settle_s": 2.0, "hearing.recenter_s": 20, "hearing.deadzone_deg": 12, "hearing.min_confidence": 0.5,
                                     "hearing.settle_s_typo": 9, "head.speed_deg_s": 60})
    cfg = h.core.sound.cfg
    assert (cfg.settle_s, cfg.recenter_s, cfg.min_confidence, cfg.yaw_limit) == (2.0, 20.0, 0.5, limit)
    assert cfg.deadzone == pytest.approx(math.radians(12)) and applied["hearing.deadzone_deg"] == pytest.approx(12.0)
    assert "head.speed_deg_s" not in applied  # 要重啟的項目不在這裡套用
    assert h.arbiter.limits.head_max_speed == pytest.approx(math.radians(30))


def test_presence_expression_map(tmp_path):
    from duckd.eyes_out import EyesOutput

    h = make_harness(eyes=EyesOutput(None))
    h.cmd("presence", {"state": "thinking"})
    assert h.core.eyes.expression == "thinking"
    h.core.apply_settings({"eyes.presence.thinking": "curious", "eyes.presence.idle": "no_such_expression"})
    h.tick()
    assert h.core.eyes.expression == "curious" and h.core.expression_map["idle"] == "neutral"  # 不認得的表情不採用
    assert h.last_state()["expression"] == "curious"


def test_local_express_preview_command(tmp_path):
    from duckd import localctl
    from duckd.eyes_out import EyesOutput

    h = make_harness(eyes=EyesOutput(None))
    st = localctl.handle(h.core, None, {"cmd": "status"})
    assert st["can_express"] is True
    r = localctl.handle(h.core, None, {"cmd": "express", "name": "happy", "duration_s": 500})
    assert r == {"ok": True, "expression": "happy", "seconds": 10.0, "panel": "virtual_png"} and h.core.eyes.expression == "happy"
    assert localctl.handle(h.core, None, {"cmd": "express", "name": "nope"})["ok"] is False
    bare = make_harness()
    assert localctl.handle(bare.core, None, {"cmd": "status"})["can_express"] is False
    assert localctl.handle(bare.core, None, {"cmd": "express", "name": "happy"}) == {"ok": False, "error": "eyes renderer is not running"}
