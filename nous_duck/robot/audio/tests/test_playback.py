"""D5：播放路徑、閘門、音量上限。全部用記憶體或 null sink，不出聲。"""

import shutil

import numpy as np
import pytest

from duck_audio.playback import (
    AplaySink,
    CaptureSink,
    DuckAudioOut,
    GateConfig,
    GateState,
    NullSink,
    PlaybackError,
    PlaybackGate,
    WavSink,
    limit,
)
from duck_audio.wavio import read_wav, resample


def tone(freq=440.0, dur=0.5, rate=24000, amp=0.5):
    t = np.arange(int(dur * rate)) / rate
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32), rate


class Out:
    def __init__(self, **kw):
        self.sinks = []
        self.t = 0.0

        def factory():
            s = CaptureSink()
            self.sinks.append(s)
            return s

        self.out = DuckAudioOut(factory, clock=lambda: self.t, **kw)


def test_gate_default_allows_and_caps_volume():
    g = PlaybackGate()
    d = g.decide("voice")
    assert d.allowed and d.gain == GateConfig().volume_cap_day
    assert g.request_volume(0.2) == 0.2 and g.decide("voice").gain == 0.2
    # 只能收緊：要求比上限大，實際仍是上限
    assert g.request_volume(1.0) == 0.5 and g.request_volume(7) == 0.5
    assert g.decide("voice").gain == 0.5


@pytest.mark.parametrize(
    "state,kind,allowed,reason",
    [
        (dict(hard_mute=True), "safety", False, "hard_mute"),
        (dict(hard_mute=True), "voice", False, "hard_mute"),
        (dict(privacy_switch_off=True), "safety", False, "privacy_switch_off"),
        (dict(room_silent=True), "voice", False, "privacy_policy"),
        (dict(room_silent=True), "sfx", False, "privacy_policy"),
        (dict(room_silent=True), "safety", True, None),
        (dict(night=True), "sfx", False, "night_mode"),
        (dict(night=True), "voice", True, None),
        (dict(night=True), "safety", False, "night_mode"),
    ],
)
def test_gate_rules(state, kind, allowed, reason):
    d = PlaybackGate(state=GateState(**state)).decide(kind)
    assert (d.allowed, d.reason) == (allowed, reason)
    if not allowed:
        assert d.gain == 0.0


def test_night_cap_is_lower_and_safety_at_night_is_configurable():
    g = PlaybackGate(state=GateState(night=True))
    assert g.decide("voice").gain == GateConfig().volume_cap_night < GateConfig().volume_cap_day
    g2 = PlaybackGate(GateConfig(safety_audible_at_night=True), GateState(night=True))
    assert g2.decide("safety").allowed and g2.decide("safety").gain == GateConfig().volume_cap_night


def test_zero_volume_is_refused_not_faked():
    g = PlaybackGate()
    g.request_volume(0.0)
    assert g.decide("voice").reason == "volume_zero"
    assert PlaybackGate().decide("sfx").allowed
    with pytest.raises(ValueError):
        g.decide("music")


def test_limiter_never_exceeds_ceiling():
    x = np.linspace(-5, 5, 1001).astype(np.float32)
    assert np.max(np.abs(limit(x, 0.3))) <= 0.3
    assert np.allclose(limit(np.array([0.01], np.float32), 0.5), 0.01, atol=1e-5)
    assert not limit(x, 0.0).any()


def test_play_raw_outputs_48k_stereo_within_cap():
    o = Out()
    x, rate = tone(amp=1.0)  # 滿刻度輸入
    r = o.out.play_raw(x, rate)
    assert (r.status, r.output, r.kind) == ("played", "duck_raw", "sfx")
    sink = o.sinks[0]
    assert sink.closed and sink.frames == 24000 == r.frames and r.duration_s == pytest.approx(0.5)
    y = sink.samples()
    assert np.max(np.abs(y)) <= 0.5 + 1e-4 and r.peak <= 0.5  # 不超過本機上限
    raw = np.frombuffer(b"".join(sink.chunks), dtype="<i2").reshape(-1, 2)
    assert np.array_equal(raw[:, 0], raw[:, 1])  # 雙聲道同訊號
    spec = np.abs(np.fft.rfft(y))
    assert np.fft.rfftfreq(len(y), 1 / 48000)[int(np.argmax(spec))] == pytest.approx(440, abs=4)
    assert len(r.levels) == 5 and all(0 < v < 0.5 for v in r.levels)
    assert o.out.is_playing is False


def test_refused_playback_opens_no_sink():
    o = Out(gate=PlaybackGate(state=GateState(room_silent=True)))
    r = o.out.play_raw(*tone())
    assert (r.status, r.reason, r.frames) == ("refused", "privacy_policy", 0)
    assert o.sinks == []


def test_voice_requires_voice_changer_and_applies_it():
    o = Out()
    r = o.out.play_voice(*tone())
    assert (r.status, r.reason) == ("refused", "voice_changer_missing") and o.sinks == []
    calls = []

    def changer(x, rate):
        calls.append(rate)
        return x * 0.0 + 0.1

    o2 = Out(voice_changer=changer)
    r = o2.out.play_voice(*tone())
    assert r.status == "played" and r.output == "duck_voice" and calls == [24000]
    assert np.allclose(o2.sinks[0].samples()[100:-100], np.tanh(0.1 * 0.5 / 0.5) * 0.5, atol=2e-3)
    # play_raw 不經過變聲
    o2.out.play_raw(*tone())
    assert calls == [24000]


def test_sfx_levels_and_cooldown():
    o = Out()
    r1 = o.out.play_sfx("listen_on")
    assert r1.status == "played" and r1.kind == "sfx"
    assert r1.peak <= 0.5 * 10 ** (-6 / 20) * 10 ** (-12 / 20) + 1e-3  # 上限 × 檔案峰值 × 「小」
    assert o.out.play_sfx("listen_on").reason == "cooldown"
    o.t = 3.1
    assert o.out.play_sfx("listen_on").status == "played"
    assert o.out.play_sfx("help_call").status == "played"
    o.t = 20.0
    assert o.out.play_sfx("help_call").reason == "cooldown"
    with pytest.raises(KeyError):
        o.out.play_sfx("nope")


def test_refused_sfx_does_not_start_cooldown():
    o = Out(gate=PlaybackGate(state=GateState(night=True)))
    assert o.out.play_sfx("listen_on").reason == "night_mode"
    o.out.gate.state.night = False
    assert o.out.play_sfx("listen_on").status == "played"


def test_on_level_reports_real_envelope_then_zero():
    seen = []
    o = Out(on_level=seen.append)
    o.out.play_raw(*tone(dur=0.3))
    assert len(seen) == 4 and seen[-1] == 0.0 and all(v > 0 for v in seen[:3])


def test_wav_sink_and_resample_roundtrip(tmp_path):
    path = tmp_path / "out.wav"
    out = DuckAudioOut(lambda: WavSink(path))
    out.play_raw(*tone(freq=1000, dur=0.2))
    y, rate = read_wav(path)
    assert rate == 48000 and len(y) == 9600
    x, _ = tone(freq=1000, dur=0.2, rate=48000)
    assert len(resample(x, 48000, 16000)) == 3200


@pytest.mark.skipif(shutil.which("aplay") is None, reason="這台機器沒有 aplay（Mac）；Pi 上會跑")
def test_aplay_null_device():
    sink = AplaySink("null")
    DuckAudioOut(lambda: sink).play_raw(*tone(dur=0.2))
    assert sink.frames == 9600


@pytest.mark.skipif(shutil.which("aplay") is None, reason="這台機器沒有 aplay")
def test_aplay_bad_device_reports_error():
    with pytest.raises(PlaybackError):
        s = AplaySink("plughw:CARD=NoSuchCard,DEV=0")
        s.write(b"\0" * 19200)
        s.close()
