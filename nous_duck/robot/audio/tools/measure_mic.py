#!/usr/bin/env python3
"""實機量測（Pi）：XVF3800 兩個收音聲道的底噪，以及喇叭播放時麥克風收到多少回授。

收到的音訊**只在記憶體裡**算統計值（RMS、dBFS），不寫檔、不送出；程式結束就沒有了。

    python tools/measure_mic.py quiet --seconds 4
    python tools/measure_mic.py echo --volume 0.1 [--reference]   # 會出聲：播合成語音 fixture

`--reference`：同一段聲音同時送到 XVF3800 的 USB 播放端（它的回音消除參考訊號），再看殘留差多少。
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from duck_audio.capture import ArecordSource  # noqa: E402
from duck_audio.playback import AplaySink, DuckAudioOut, PlaybackGate, RefSink, TeeSink  # noqa: E402
from duck_audio.wavio import read_wav  # noqa: E402

SPEAKER = "plughw:CARD=CD002,DEV=0"


def db(x: float) -> float:
    return round(20 * np.log10(max(x, 1e-9)), 1)


def capture(seconds: float) -> np.ndarray:
    src = ArecordSource()
    frames = []
    try:
        for _ in range(int(seconds * 50)):
            frames.append(src.read())
    finally:
        src.close()
    return np.concatenate(frames)


def stats(x: np.ndarray) -> dict:
    return {f"ch{c}": {"rms_dbfs": db(float(np.sqrt(np.mean(x[:, c] ** 2)))), "peak_dbfs": db(float(np.max(np.abs(x[:, c]))))} for c in range(x.shape[1])}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", choices=("quiet", "echo"))
    ap.add_argument("--seconds", type=float, default=4.0)
    ap.add_argument("--volume", type=float, default=0.1)
    ap.add_argument("--reference", action="store_true")
    a = ap.parse_args()
    out: dict = {"mode": a.mode, "recordings_saved": False}
    if a.mode == "quiet":
        out["quiet"] = stats(capture(a.seconds)[8000:])
    else:
        x, rate = read_wav(ROOT / "fixtures" / "speech_zh_synthetic_fixture.wav")
        gate = PlaybackGate()
        gate.request_volume(a.volume)
        factory = (lambda: TeeSink(AplaySink(SPEAKER), RefSink())) if a.reference else (lambda: AplaySink(SPEAKER))
        player = DuckAudioOut(factory, gate)
        result = {}
        rec: list[np.ndarray] = []
        t = threading.Thread(target=lambda: rec.append(capture(len(x) / rate + 2.5)))
        t.start()
        time.sleep(1.2)
        r = player.play_raw(x, rate, kind="voice")
        t.join()
        y = rec[0]
        n0 = int(0.3 * 16000)
        q = y[n0 : int(1.0 * 16000)]
        p = y[int(1.6 * 16000) : int((1.2 + len(x) / rate) * 16000)]
        out.update({"volume": a.volume, "reference": a.reference, "played": r.status, "play_peak": r.peak,
                    "before_playback": stats(q), "during_playback": stats(p)})
        out["rise_db"] = {f"ch{c}": round(out["during_playback"][f"ch{c}"]["rms_dbfs"] - out["before_playback"][f"ch{c}"]["rms_dbfs"], 1) for c in range(2)}
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
