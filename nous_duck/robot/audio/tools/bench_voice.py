#!/usr/bin/env python3
"""D6：變聲候選在這台機器上的即時倍率、每塊處理時間、演算法延遲；並輸出變聲前後的試聽檔。

輸入是**合成語音 fixture**（`fixtures/speech_zh_synthetic_fixture.wav`）。不播放任何聲音，只算到檔案。

    python tools/bench_voice.py --out build/voice [--repeat 5]

- 自己寫的兩個（numpy）：以 20 ms 一塊串流處理，量每塊時間。CPU 以「處理時間 ÷ 音訊長度」表示
  （numpy 的 FFT 是單執行緒，所以 10% ＝ 即時播放時佔一顆核心的 10%）。
- 系統工具（有裝才量）：Rubber Band（GPL，`rubberband-cli`）與 SoX，以外部指令處理整個檔案，
  只能量整檔時間；它們的串流延遲沒有量。
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from duck_audio.voice import DelayLineShifter, PhaseVocoderShifter, estimate_f0, process_all  # noqa: E402
from duck_audio.wavio import read_wav, write_wav  # noqa: E402

def centroid_hz(y, rate, fmax=4000.0):
    """0～4 kHz 的頻譜重心（粗略的「明亮度」；共振峰往上移，重心也會往上）。"""
    spec = np.abs(np.fft.rfft(y)) ** 2
    f = np.fft.rfftfreq(len(y), 1 / rate)
    m = f <= fmax
    return round(float((f[m] * spec[m]).sum() / spec[m].sum()))


FIXTURE = ROOT / "fixtures" / "speech_zh_synthetic_fixture.wav"
BLOCK_S = 0.02


def own_candidates(rate: int):
    for st in (3, 5, 7):
        yield f"delay_line_p{st}", lambda st=st: DelayLineShifter(rate, st), {"semitones": st, "formant": "跟著音高"}
    for st in (3, 5, 7):
        yield f"pv_keep_formant_p{st}", lambda st=st: PhaseVocoderShifter(rate, st, 1.0), {"semitones": st, "formant": "保留（×1.0）"}
    yield "pv_formant112_p5", lambda: PhaseVocoderShifter(rate, 5, 1.12), {"semitones": 5, "formant": "小幅上移（×1.12）"}
    yield "pv_formant112_p7", lambda: PhaseVocoderShifter(rate, 7, 1.12), {"semitones": 7, "formant": "小幅上移（×1.12）"}
    yield "pv_keep_formant_p5_fft512", lambda: PhaseVocoderShifter(rate, 5, 1.0, n_fft=512), {"semitones": 5, "formant": "保留（×1.0），短視窗"}


def bench_own(name, make, meta, x, rate, repeat, out_dir):
    block = int(BLOCK_S * rate)
    times_total, block_times = [], []
    for _ in range(repeat):
        sh = make()
        t0 = time.perf_counter()
        for i in range(0, len(x), block):
            t = time.perf_counter()
            sh.process(x[i : i + block])
            block_times.append((time.perf_counter() - t) * 1000)
        times_total.append(time.perf_counter() - t0)
    sh = make()
    y = process_all(sh, x, block)
    write_wav(out_dir / f"voice-{name}.wav", y, rate)
    dur = len(x) / rate
    bt = sorted(block_times)
    f_in, f_out = estimate_f0(x, rate), estimate_f0(y, rate)
    return {
        "name": name,
        **meta,
        "kind": "own_numpy",
        "rtf": round(statistics.median(times_total) / dur, 4),
        "cpu_pct_one_core_realtime": round(statistics.median(times_total) / dur * 100, 1),
        "block_ms_mean": round(statistics.fmean(bt), 3),
        "block_ms_p95": round(bt[int(len(bt) * 0.95) - 1], 3),
        "block_ms_max": round(bt[-1], 3),
        "algorithmic_latency_ms": round(sh.latency_s * 1000, 1),
        "measured_pitch_ratio": None if not (f_in and f_out) else round(f_out / f_in, 3),
        "centroid_hz_0_4k": centroid_hz(y, rate),
        "out_peak": round(float(np.max(np.abs(y))), 3),
    }


def bench_cli(name, argv_fn, meta, x, rate, repeat, out_dir):
    out = out_dir / f"voice-{name}.wav"
    times = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        r = subprocess.run(argv_fn(str(FIXTURE), str(out)), capture_output=True, text=True)
        times.append(time.perf_counter() - t0)
        if r.returncode != 0:
            return {"name": name, **meta, "kind": "system_cli", "error": (r.stderr or r.stdout).strip()[-300:]}
    y, r2 = read_wav(out)
    dur = len(x) / rate
    f_in, f_out = estimate_f0(x, rate), estimate_f0(y, r2)
    return {
        "name": name,
        **meta,
        "kind": "system_cli",
        "rtf_whole_file_incl_process_start": round(statistics.median(times) / dur, 4),
        "measured_pitch_ratio": None if not (f_in and f_out) else round(f_out / f_in, 3),
        "centroid_hz_0_4k": centroid_hz(y, r2),
        "out_duration_s": round(len(y) / r2, 3),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=ROOT / "build" / "voice")
    ap.add_argument("--repeat", type=int, default=5)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    x, rate = read_wav(FIXTURE)
    write_wav(a.out / "voice-original.wav", x, rate)
    results = []
    load_before = os.getloadavg()
    for name, make, meta in own_candidates(rate):
        results.append(bench_own(name, make, meta, x, rate, a.repeat, a.out))
    if shutil.which("rubberband"):
        ver = subprocess.run(["rubberband", "--version"], capture_output=True, text=True)
        v = (ver.stdout + ver.stderr).strip().splitlines()[0] if (ver.stdout + ver.stderr).strip() else "?"
        for st in (5,):
            results.append(bench_cli(f"rubberband_formant_p{st}", lambda i, o, st=st: ["rubberband", "-q", "-p", str(st), "-F", i, o], {"semitones": st, "formant": "保留（-F）", "tool": v}, x, rate, a.repeat, a.out))
            results.append(bench_cli(f"rubberband_realtime_formant_p{st}", lambda i, o, st=st: ["rubberband", "-q", "-R", "-p", str(st), "-F", i, o], {"semitones": st, "formant": "保留（-F），即時模式 -R", "tool": v}, x, rate, a.repeat, a.out))
            results.append(bench_cli(f"rubberband_p{st}", lambda i, o, st=st: ["rubberband", "-q", "-p", str(st), i, o], {"semitones": st, "formant": "跟著音高", "tool": v}, x, rate, a.repeat, a.out))
    if shutil.which("sox"):
        results.append(bench_cli("sox_pitch_p5", lambda i, o: ["sox", i, o, "pitch", "500"], {"semitones": 5, "formant": "跟著音高", "tool": "sox pitch"}, x, rate, a.repeat, a.out))
    f_in = estimate_f0(x, rate)
    out = {
        "mock_input": True,
        "fixture": FIXTURE.name,
        "fixture_duration_s": round(len(x) / rate, 3),
        "fixture_f0_hz": None if f_in is None else round(f_in, 1),
        "fixture_centroid_hz_0_4k": centroid_hz(x, rate),
        "rate_hz": rate,
        "block_ms": BLOCK_S * 1000,
        "machine": platform.machine(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "loadavg_before": [round(v, 2) for v in load_before],
        "loadavg_after": [round(v, 2) for v in os.getloadavg()],
        "listened": False,
        "results": results,
    }
    (a.out / "bench_voice.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
