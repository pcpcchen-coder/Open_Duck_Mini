"""D6：變聲器的客觀檢查（音高、長度、共振峰、分塊一致）。好不好聽、聽不聽得懂**沒有驗證**。"""

import numpy as np
import pytest

from duck_audio.sfx_synth import resonate as _unused  # noqa: F401  （確認套件可匯入）
from duck_audio.voice import (
    DelayLineShifter,
    PhaseVocoderShifter,
    estimate_f0,
    make_voice_changer,
    process_all,
    semitones_to_ratio,
    spectral_envelope_peak,
)

RATE = 24000


def vowel(f0=150.0, dur=1.2, formants=((700, 80), (1200, 90), (2600, 120))):
    """合成母音（fixture）：諧波源＋三個共振峰。不是錄音。"""
    t = np.arange(int(dur * RATE)) / RATE
    f = f0 * (1 + 0.02 * np.sin(2 * np.pi * 3 * t))
    ph = 2 * np.pi * np.cumsum(f) / RATE
    src = sum(np.sin(k * ph) / k for k in range(1, int(RATE / 2 / (f0 * 1.05))))
    spec = np.fft.rfft(src)
    fr = np.fft.rfftfreq(len(src), 1 / RATE)
    gain = sum(1.0 / np.sqrt(1 + ((fr - fc) / bw) ** 2) for fc, bw in formants)
    x = np.fft.irfft(spec * gain, len(src))
    return (0.3 * x / np.max(np.abs(x))).astype(np.float32)


def test_semitone_ratio():
    assert semitones_to_ratio(12) == pytest.approx(2.0) and semitones_to_ratio(0) == 1.0


@pytest.mark.parametrize("kind", ["delay_line", "phase_vocoder"])
@pytest.mark.parametrize("st", [3, 5, 7])
def test_pitch_shift_amount_and_length(kind, st):
    x = vowel()
    y = process_all(make_voice_changer(kind, RATE, st), x)
    assert len(y) == len(x) and np.isfinite(y).all()
    f_in, f_out = estimate_f0(x, RATE), estimate_f0(y[2400:], RATE)
    assert f_in == pytest.approx(150, rel=0.03)
    assert f_out / f_in == pytest.approx(semitones_to_ratio(st), rel=0.04)
    rms = lambda a: float(np.sqrt(np.mean(a[4800:-4800] ** 2)))
    assert 0.4 < rms(y) / rms(x) < 2.0  # 音量沒有爆掉或消失


def test_zero_shift_is_near_identity():
    x = vowel()
    y = process_all(PhaseVocoderShifter(RATE, 0.0, formant_ratio=None), x)
    seg = slice(4800, -4800)
    assert np.corrcoef(x[seg], y[seg])[0, 1] > 0.98


def test_formant_control():
    """共振峰：delay_line 與 formant_ratio=None 會跟著音高移；formant_ratio=1.0 留在原處；1.12 介於中間。"""
    x = vowel(f0=120.0, formants=((900, 90), (2600, 150)))
    r = semitones_to_ratio(7)  # 1.498
    f1 = spectral_envelope_peak(x, RATE, 500, 1800)
    assert f1 == pytest.approx(900, abs=80)
    peak = lambda sh: spectral_envelope_peak(process_all(sh, x)[4800:], RATE, 500, 1800)
    assert peak(DelayLineShifter(RATE, 7)) == pytest.approx(900 * r, rel=0.12)
    assert peak(PhaseVocoderShifter(RATE, 7, formant_ratio=None)) == pytest.approx(900 * r, rel=0.12)
    kept = peak(PhaseVocoderShifter(RATE, 7, formant_ratio=1.0))
    assert kept == pytest.approx(900, rel=0.14)
    mid = peak(PhaseVocoderShifter(RATE, 7, formant_ratio=1.12))
    assert kept < mid < 900 * r * 0.95


@pytest.mark.parametrize("kind", ["delay_line", "phase_vocoder"])
def test_block_size_does_not_change_output(kind):
    """串流：每次餵 20 ms、5 ms 或不規則大小，結果都一樣（狀態有正確帶到下一塊）。"""
    x = vowel(dur=0.6)
    ref = process_all(make_voice_changer(kind, RATE, 5), x, block=480)
    for block in (120, 777, len(x)):
        y = process_all(make_voice_changer(kind, RATE, 5), x, block=block)
        assert np.allclose(ref, y, atol=1e-5)


def test_latency_reported():
    assert DelayLineShifter(RATE, 5).latency_s == pytest.approx(0.02)
    pv = PhaseVocoderShifter(RATE, 5)
    assert pv.latency_s == pytest.approx((1024 + 256) / RATE)
    assert PhaseVocoderShifter(RATE, 5, n_fft=512).latency_s < pv.latency_s


def test_silence_in_silence_out():
    z = np.zeros(RATE // 2, dtype=np.float32)
    for kind in ("delay_line", "phase_vocoder"):
        assert float(np.max(np.abs(process_all(make_voice_changer(kind, RATE, 5), z)))) < 1e-6


def test_unknown_kind():
    with pytest.raises(ValueError):
        make_voice_changer("robot", RATE, 5)
