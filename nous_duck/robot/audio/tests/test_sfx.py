"""D5：自製音效合成。"""

import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pytest

from duck_audio import sfx_synth
from duck_audio.wavio import read_wav

AUDIO = Path(__file__).resolve().parents[1]
SOUNDS = AUDIO / "sounds"
SPEC = AUDIO.parents[1] / "docs" / "eye_expressions.md"


def dominant_hz(x, rate=sfx_synth.RATE):
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return float(np.fft.rfftfreq(len(x), 1 / rate)[int(np.argmax(spec))])


def spec_names():
    text = SPEC.read_text(encoding="utf-8")
    table = text.split("### 5.3 音效規格")[1].split("\n## ")[0]
    return re.findall(r"^\| `([a-z_]+)` \|", table, flags=re.M)


@pytest.mark.skipif(not SPEC.exists(), reason="這台機器上沒有規格文件（Pi 只同步 robot/audio）")
def test_every_spec_sound_exists_and_no_extras():
    names = spec_names()
    assert len(names) == 21
    assert [s.name for s in sfx_synth.SFX] == names


@pytest.mark.parametrize("s", sfx_synth.SFX, ids=lambda s: s.name)
def test_sound_is_sane(s):
    x = sfx_synth.render(s.name)
    assert x.dtype == np.float32 and np.isfinite(x).all()
    assert np.max(np.abs(x)) == pytest.approx(sfx_synth.PEAK, rel=1e-4)  # −6 dBFS
    assert abs(float(np.mean(x))) < 1e-3
    dur = len(x) / sfx_synth.RATE
    assert 0.6 * s.spec_duration_s <= dur <= 1.2 * s.spec_duration_s + 0.01
    assert abs(x[0]) < 0.05 and abs(x[-1]) < 0.05  # 頭尾沒有爆音
    assert s.level in ("small", "medium")


def test_pitches_follow_spec():
    r = sfx_synth.RATE
    on = sfx_synth.render("listen_on")
    assert dominant_hz(on[: int(0.05 * r)]) == pytest.approx(880, abs=25)
    assert dominant_hz(on[int(0.05 * r) :]) == pytest.approx(1320, abs=25)
    off = sfx_synth.render("listen_off")
    assert dominant_hz(off[: int(0.05 * r)]) == pytest.approx(1320, abs=25)
    assert dominant_hz(sfx_synth.render("wink_click")) == pytest.approx(1760, abs=40)
    low = sfx_synth.render("battery_low")
    assert dominant_hz(low[: int(0.15 * r)]) == pytest.approx(660, abs=10)
    assert dominant_hz(low[int(0.15 * r) :]) == pytest.approx(440, abs=10)
    chirp = sfx_synth.render("curious_chirp")
    half = len(chirp) // 2
    assert dominant_hz(chirp[:half]) < dominant_hz(chirp[half:])  # 往上揚
    sad = sfx_synth.render("sad_slide")
    assert dominant_hz(sad[: len(sad) // 3]) > dominant_hz(sad[-len(sad) // 3 :])  # 往下滑


def test_quack_has_formant_energy():
    """合成鴨叫：能量集中在 1.0 kHz 與 2.4 kHz 兩個共振峰附近。"""
    x = sfx_synth.quack(sfx_synth.const(440, 0.2))
    spec = np.abs(np.fft.rfft(x)) ** 2
    f = np.fft.rfftfreq(len(x), 1 / sfx_synth.RATE)
    band = lambda lo, hi: float(spec[(f >= lo) & (f < hi)].sum())
    assert band(700, 1400) > band(4000, 8000) * 5
    assert band(2000, 2900) > band(4000, 8000)


def test_deterministic():
    for name in ("giggle_trill", "grumble", "quack_hello"):
        assert np.array_equal(sfx_synth.render(name), sfx_synth.render(name))


def test_committed_wavs_match_generator_and_manifest(tmp_path):
    """進版控的 wav 就是程式產生的（沒有手改、沒有混進別的來源）。"""
    committed = json.loads((SOUNDS / "manifest.json").read_text(encoding="utf-8"))
    fresh = sfx_synth.write_all(tmp_path)
    assert committed["listened"] is False
    assert sorted(p.name for p in SOUNDS.glob("*.wav")) == sorted(e["file"] for e in committed["sounds"])
    for a, b in zip(committed["sounds"], fresh["sounds"]):
        assert a == b
        assert hashlib.sha256((SOUNDS / a["file"]).read_bytes()).hexdigest() == a["sha256"]
        x, rate = read_wav(SOUNDS / a["file"])
        assert rate == 24000 and len(x) / rate == pytest.approx(a["duration_s"], abs=1e-3)
    assert sum((SOUNDS / e["file"]).stat().st_size for e in committed["sounds"]) < 500_000


def test_cooldowns_follow_spec():
    by = sfx_synth.SFX_BY_NAME
    assert by["help_call"].cooldown_s == 20 and by["battery_low"].cooldown_s == 300 and by["listen_on"].cooldown_s == 3
