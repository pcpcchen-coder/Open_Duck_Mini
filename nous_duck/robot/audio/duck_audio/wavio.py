"""16-bit PCM wav 讀寫與重取樣（只用標準函式庫＋numpy）。內部一律用 float32、範圍 −1～1、單聲道。"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


def write_wav(path: Path | str, x: np.ndarray, rate: int) -> None:
    pcm = (np.clip(x, -1.0, 1.0) * 32767.0).round().astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1 if pcm.ndim == 1 else pcm.shape[1])
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def read_wav(path: Path | str) -> tuple[np.ndarray, int]:
    """讀 16-bit PCM wav，多聲道混成單聲道。"""
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError("只支援 16-bit PCM")
        n, ch, rate = w.getnframes(), w.getnchannels(), w.getframerate()
        x = np.frombuffer(w.readframes(n), dtype="<i2").astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, rate


def resample(x: np.ndarray, rate_in: int, rate_out: int) -> np.ndarray:
    """重取樣。降頻前先在頻域截掉新奈奎斯特頻率以上的成分（整段處理，離線用）。"""
    if rate_in == rate_out or len(x) == 0:
        return x.astype(np.float32)
    n_out = int(round(len(x) * rate_out / rate_in))
    spec = np.fft.rfft(x)
    n_keep = min(len(spec), n_out // 2 + 1)
    out_spec = np.zeros(n_out // 2 + 1, dtype=complex)
    out_spec[:n_keep] = spec[:n_keep]
    return (np.fft.irfft(out_spec, n_out) * (n_out / len(x))).astype(np.float32)
