"""schema：每一項都有預設值與範圍、未實作的不能寫、安全項目不在裡面、和其他模組的常數一致。"""
import json
import re
from pathlib import Path

import pytest

from duck_settings import schema
from duck_settings.schema import BY_KEY, SETTINGS, SettingError

ROBOT = Path(__file__).resolve().parents[2]


def test_keys_are_unique_and_every_default_is_valid():
    assert len(BY_KEY) == len(SETTINGS)
    sections = {s[0] for s in schema.SECTIONS}
    for s in SETTINGS:
        assert re.fullmatch(r"[a-z_]+(\.[a-z_]+)+", s.key), s.key
        assert s.section in sections and s.key.split(".")[0] == s.section
        assert s.validate(s.default) == s.default, s.key
        assert s.label and s.description
        if s.type in ("number", "int"):
            assert s.min is not None and s.max is not None and s.min <= s.default <= s.max, s.key


def test_unimplemented_settings_say_why_and_have_no_consumer():
    for s in SETTINGS:
        if s.status == "implemented":
            assert s.consumer in ("duckd", "duck-doa", "duck-voice") and not s.blocked_by, s.key
        else:
            assert s.status in ("planned", "hardware_missing") and s.consumer is None and s.blocked_by and not s.writable, s.key
    assert sum(s.writable for s in SETTINGS) >= 20


def test_no_safety_items_can_be_settings():
    """關安全保護、安全上限、腿、扭力、緊急停止不上設定頁（ADR-0019 §2.6）。"""
    for s in SETTINGS:
        for part in schema.FORBIDDEN_KEY_PARTS:
            assert part not in s.key, (s.key, part)
    text = " ".join(s.key for s in SETTINGS)
    for word in ("estop", "torque", "leg", "safety", "temp", "volt"):
        assert word not in text


def test_head_ranges_stay_inside_duckd_hard_limits():
    """設定的上限不能超過 duckd 的硬上限；讀不到設定時的保守值等於預設值。"""
    src = (ROBOT / "duckd" / "duckd" / "limits.py").read_text(encoding="utf-8")
    hard_cap = float(re.search(r"head_speed_hard_cap: float = math\.radians\(([\d.]+)\)", src).group(1))
    assert BY_KEY["head.speed_deg_s"].max < hard_cap
    assert BY_KEY["head.presence_amplitude"].max == 1.0  # 只能調小
    fallback = (ROBOT / "duckd" / "duckd" / "settings_in.py").read_text(encoding="utf-8")
    m = re.search(r'CONSERVATIVE = \{"head.speed_deg_s": ([\d.]+), "head.window_deg": ([\d.]+)\}', fallback)
    assert (float(m.group(1)), float(m.group(2))) == (BY_KEY["head.speed_deg_s"].default, BY_KEY["head.window_deg"].default)


def test_values_out_of_range_are_rejected_not_clamped():
    s = BY_KEY["head.speed_deg_s"]
    for bad in (61, 4.9, 90, 1e9, -1, float("nan"), float("inf"), "30", True, None):
        with pytest.raises(SettingError):
            s.validate(bad)
    assert s.validate(60) == 60.0 and s.validate(5) == 5.0
    assert s.clamp(500) == 60.0 and s.clamp(-3) == 5.0 and s.clamp("x") == 30.0
    with pytest.raises(SettingError):
        BY_KEY["hearing.min_speech_samples"].validate(3.5)
    with pytest.raises(SettingError):
        BY_KEY["features.track_sound"].validate(1)
    with pytest.raises(SettingError):
        BY_KEY["calibration.mic.mount"].validate("ceiling")
    with pytest.raises(SettingError):
        BY_KEY["audio.night_start"].validate("25:00")


def test_cross_rule_settle_longer_than_doa_window():
    v = schema.defaults()
    assert schema.check_cross_rules(v) == []
    v["hearing.settle_s"], v["hearing.window_s"] = 0.6, 0.6
    assert len(schema.check_cross_rules(v)) == 1


def test_privacy_settings_declare_which_way_is_tighter():
    privacy = [s for s in SETTINGS if s.section == "privacy"]
    assert privacy and all(s.tighten and s.tighten[0] == s.default for s in privacy)
    s = BY_KEY["privacy.sound_direction"]
    assert s.is_looser(False, True) and not s.is_looser(True, False) and not s.is_looser(True, True)
    m = BY_KEY["privacy.mode"]
    assert m.is_looser("full", "guest") and not m.is_looser("guest", "night")
    assert not any(s.tighten for s in SETTINGS if s.section != "privacy")


def test_expression_lists_match_duck_eyes_and_duckd():
    import duck_eyes

    assert set(schema.EXPRESSIONS) == set(duck_eyes.EXPRESSIONS)
    assert set(schema.SOCIAL_EXPRESSIONS) == set(duck_eyes.NOUS_ALLOWED)
    src = (ROBOT / "duckd" / "duckd" / "presence.py").read_text(encoding="utf-8")
    block = src[src.index("EXPRESSION = {"):src.index("}", src.index("EXPRESSION = {"))]
    assert dict(re.findall(r'"(\w+)": "(\w+)"', block)) == schema.PRESENCE_DEFAULT_EXPRESSION
    for state, default in schema.PRESENCE_DEFAULT_EXPRESSION.items():
        allowed = {c[0] for c in BY_KEY[f"eyes.presence.{state}"].choices}
        assert default in allowed and allowed <= set(schema.SOCIAL_EXPRESSIONS) | {default}
    # 代表實際狀態的表情不能指給別的狀態
    assert "low_battery" not in {c[0] for c in BY_KEY["eyes.presence.idle"].choices}


def test_defaults_match_the_values_other_modules_ship_with():
    doa_json = json.loads((ROBOT / "audio" / "config" / "doa.json").read_text(encoding="utf-8"))
    from duck_settings.cli import DOA_JSON_KEYS

    for field, key in DOA_JSON_KEYS.items():
        if field in doa_json:
            assert BY_KEY[key].default == doa_json[field], key
    track = (ROBOT / "duckd" / "duckd" / "track.py").read_text(encoding="utf-8")
    assert f"settle_s: float = {BY_KEY['hearing.settle_s'].default}" in track
    assert f"recenter_s: float = {BY_KEY['hearing.recenter_s'].default}" in track
    assert f"deadzone: float = math.radians({BY_KEY['hearing.deadzone_deg'].default})" in track
    assert f"min_confidence: float = {BY_KEY['hearing.min_confidence'].default}" in track
    from duck_audio.doa import DoaConfig, SETTINGS_FIELDS

    for key, field in SETTINGS_FIELDS.items():
        assert key in BY_KEY and BY_KEY[key].consumer == "duck-doa" and field in DoaConfig.__dataclass_fields__
    for key in ("hearing.window_s", "hearing.min_speech_samples", "hearing.cluster_tolerance_deg"):
        assert BY_KEY[key].default == getattr(DoaConfig(), SETTINGS_FIELDS[key])


def test_public_view_has_what_the_page_needs():
    d = BY_KEY["head.speed_deg_s"].public()
    assert d["apply"] == "restart" and d["consumer"] == "duckd" and (d["min"], d["max"], d["default"]) == (5.0, 60.0, 30.0)
    b = BY_KEY["privacy.camera"].public()
    assert b["writable"] is False and b["status_label"] == "硬體未到" and b["blocked_by"]
