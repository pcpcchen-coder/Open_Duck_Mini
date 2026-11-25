"""D5 本機音效合成：依 `docs/eye_expressions.md` §5.3 的規格，用 numpy 產生 21 個短音效。

- **原創合成**：振盪器、滑音、共振峰濾波；沒有取樣任何錄音，也沒有使用上游 runtime 的 wav
  （上游沒有授權檔，ADR-0010 §1）。
- 輸出 24 kHz、單聲道、16-bit；播放時由 `playback` 轉成喇叭要的 48 kHz 雙聲道。
- 檔案峰值一律正規化到 −6 dBFS；「小／中」音量等級記在清單裡，由播放端套用增益。
- 頻率與時長照規格表；包絡、共振峰 Q 值等規格沒寫的細節是這裡定的初值。
  **沒有人聽過**（夜間不出聲），聽感要等使用者試聽後再調。

    python -m duck_audio.sfx_synth --out sounds     # 產生 wav 與 manifest.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .wavio import write_wav

RATE = 24000
PEAK = 10 ** (-6 / 20)  # −6 dBFS
SEMITONE = 2 ** (1 / 12)


# ---------------------------------------------------------------- 基本元件


def _n(dur_s: float) -> int:
    return int(round(dur_s * RATE))


def _phase(freq_hz: np.ndarray) -> np.ndarray:
    return 2 * np.pi * np.cumsum(freq_hz) / RATE


def glide(f0: float, f1: float, dur_s: float, exp: bool = False) -> np.ndarray:
    """頻率軌跡：f0 → f1（線性，或指數）。"""
    t = np.linspace(0.0, 1.0, _n(dur_s), endpoint=False)
    return f0 * (f1 / f0) ** t if exp else f0 + (f1 - f0) * t


def vibrato(freq: np.ndarray, depth_hz: float, rate_hz: float) -> np.ndarray:
    t = np.arange(len(freq)) / RATE
    return freq + depth_hz * np.sin(2 * np.pi * rate_hz * t)


def sine(freq: np.ndarray) -> np.ndarray:
    return np.sin(_phase(freq))


def triangle(freq: np.ndarray) -> np.ndarray:
    return 2 / np.pi * np.arcsin(np.sin(_phase(freq)))


def saw(freq: np.ndarray, harmonics: int = 24) -> np.ndarray:
    """帶限鋸齒波（加法合成；超過奈奎斯特頻率的泛音不加）。"""
    ph = _phase(freq)
    out = np.zeros_like(ph)
    fmax = float(np.max(freq))
    for k in range(1, harmonics + 1):
        if k * fmax >= RATE / 2:
            break
        out += np.sin(k * ph) / k
    return out * (2 / np.pi)


def soft_square(freq: np.ndarray) -> np.ndarray:
    """柔化方波：只取前幾個奇次泛音。"""
    ph = _phase(freq)
    return (np.sin(ph) + np.sin(3 * ph) / 3 + np.sin(5 * ph) / 5 * 0.6) * (4 / np.pi) * 0.8


def env(x: np.ndarray, attack_s: float = 0.006, release_s: float = 0.02, shape: np.ndarray | None = None) -> np.ndarray:
    """起音與收音的斜坡（避免爆音），可再乘一個自訂包絡。"""
    n = len(x)
    e = np.ones(n)
    a, r = min(_n(attack_s), n // 2), min(_n(release_s), n // 2)
    if a:
        e[:a] = 0.5 - 0.5 * np.cos(np.pi * np.arange(a) / a)
    if r:
        e[n - r :] = 0.5 + 0.5 * np.cos(np.pi * np.arange(r) / r)
    if shape is not None:
        e = e * shape
    return x * e


def _spectral(x: np.ndarray, gain) -> np.ndarray:
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / RATE)
    return np.fft.irfft(spec * gain(f), len(x))


def resonate(x: np.ndarray, peaks: tuple[tuple[float, float, float], ...]) -> np.ndarray:
    """並聯的帶通共振峰：(中心頻率 Hz, Q, 增益)。零相位（頻域）濾波。"""

    def gain(f):
        g = np.zeros_like(f)
        ff = np.maximum(f, 1.0)
        for f0, q, a in peaks:
            g += a / np.sqrt(1.0 + (q * (ff / f0 - f0 / ff)) ** 2)
        return g

    return _spectral(x, gain)


def lowpass(x: np.ndarray, cutoff_hz: float, order: int = 4) -> np.ndarray:
    return _spectral(x, lambda f: 1.0 / np.sqrt(1.0 + (f / cutoff_hz) ** (2 * order)))


def silence(dur_s: float) -> np.ndarray:
    return np.zeros(_n(dur_s))


def quack(freq: np.ndarray, hum: float = 0.12) -> np.ndarray:
    """合成鴨叫：鋸齒波基頻 → 兩個帶通共振峰（約 1.0 kHz 與 2.4 kHz）＋一點低頻嗡聲。"""
    src = saw(freq)
    body = resonate(src, ((1000.0, 4.0, 1.0), (2400.0, 6.0, 0.6)))
    body = body / (np.max(np.abs(body)) + 1e-9)
    n = len(freq)
    shape = np.minimum(1.0, np.linspace(1.6, 0.5, n))  # 前段飽滿、尾端稍弱
    return env(body + hum * sine(freq / 2), 0.008, 0.03, shape)


def cat(*parts: np.ndarray) -> np.ndarray:
    return np.concatenate(parts)


def const(f: float, dur_s: float) -> np.ndarray:
    return np.full(_n(dur_s), float(f))


# ---------------------------------------------------------------- 21 個音效（規格：eye_expressions.md §5.3）


def boot_chirp():
    return cat(env(sine(glide(1200, 2000, 0.07))), silence(0.04), env(sine(glide(1500, 2600, 0.07))))


def quack_hello():
    return quack(cat(glide(420, 360, 0.11), glide(360, 440, 0.14)))


def quack_happy():
    return cat(quack(const(440, 0.09)), silence(0.07), quack(const(440 * SEMITONE**3, 0.09)))


def giggle_trill():
    rng = np.random.default_rng(7)  # 固定種子：每次產生同一個檔
    parts = []
    for i in range(5):
        parts.append(quack(const(520 + rng.uniform(-20, 20), 0.04)) * (1.0 - 0.14 * i))
        if i < 4:
            parts.append(silence(0.055 - 0.04))
    return cat(*parts)


def coo_love():
    return env(sine(vibrato(glide(330, 392, 0.4), 6.0, 5.0)), 0.04, 0.10)


def sad_slide():
    return env(sine(vibrato(glide(520, 300, 0.6, exp=True), 5.0, 4.0)), 0.03, 0.20)


def sorry_hum():
    return cat(env(triangle(const(294, 0.12)), 0.01, 0.03), env(triangle(const(262, 0.22)), 0.01, 0.08))


def grumble():
    rng = np.random.default_rng(11)
    n = _n(0.35)
    # 8 Hz 的不規則調變：在 140～170 Hz 之間
    knots = rng.uniform(140, 170, int(0.35 * 8) + 2)
    f = np.interp(np.linspace(0, len(knots) - 1, n), np.arange(len(knots)), knots)
    am = 0.75 + 0.25 * np.sin(2 * np.pi * 8 * np.arange(n) / RATE + 1.0)
    return env(lowpass(saw(f), 900.0), 0.02, 0.06, am)


def surprise_up():
    return cat(env(sine(glide(400, 1100, 0.15)), 0.005, 0.01), quack(const(560, 0.06)))


def scared_wobble():
    return env(sine(vibrato(const(700, 0.3), 60.0, 12.0)), 0.01, 0.05)


def yawn():
    n = _n(0.8)
    swell = np.sin(np.pi * np.linspace(0, 1, n)) ** 0.8  # 漸強再漸弱
    return env(lowpass(saw(glide(380, 220, 0.8)), 1200.0), 0.05, 0.15, swell)


def curious_chirp():
    return env(sine(glide(900, 1500, 0.12)), 0.006, 0.03)


def confused_hm():
    return cat(env(triangle(const(330, 0.15)), 0.01, 0.02), env(triangle(glide(400, 440, 0.15)), 0.01, 0.05))


def listen_on():
    return cat(env(sine(const(880, 0.05)), 0.004, 0.012), env(sine(const(1320, 0.05)), 0.004, 0.02))


def listen_off():
    return cat(env(sine(const(1320, 0.05)), 0.004, 0.012), env(sine(const(880, 0.05)), 0.004, 0.02))


def dizzy_wobble():
    n = _n(0.8)
    am = 0.65 + 0.35 * np.sin(2 * np.pi * 3 * np.arange(n) / RATE)
    return env(sine(vibrato(const(600, 0.8), 150.0, 3.0)), 0.03, 0.12, am)


def proud_fanfare():
    notes = [env(soft_square(const(f, 0.08)), 0.004, 0.015) for f in (1047, 1319, 1568)]
    return cat(*notes, quack(const(523, 0.10)))


def help_call():
    q = quack(const(500, 0.15))
    return cat(q, silence(0.25), q, silence(0.25), q)


def battery_low():
    return cat(env(soft_square(const(660, 0.15)), 0.006, 0.03), env(soft_square(const(440, 0.15)), 0.006, 0.05))


def charge_start():
    return cat(*[env(sine(const(f, 0.07)), 0.004, 0.02) for f in (523, 659, 784)])


def wink_click():
    n = _n(0.05)
    return env(sine(const(1760, 0.05)), 0.001, 0.005, np.exp(-np.arange(n) / (0.012 * RATE)))


@dataclass(frozen=True)
class Sfx:
    name: str
    zh: str
    level: str  # "small"（小）或 "medium"（中）
    spec_duration_s: float  # 規格表寫的長度
    make: object
    #: 同一音效的最短重播間隔（秒）；規格 §5.1：一般 3 秒，help_call 20 秒、battery_low 5 分鐘。
    cooldown_s: float = 3.0


SFX: tuple[Sfx, ...] = (
    Sfx("boot_chirp", "開機啾啾", "small", 0.25, boot_chirp),
    Sfx("quack_hello", "打招呼鴨叫", "medium", 0.25, quack_hello),
    Sfx("quack_happy", "開心兩聲鴨叫", "medium", 0.3, quack_happy),
    Sfx("giggle_trill", "咯咯笑顫音", "medium", 0.35, giggle_trill),
    Sfx("coo_love", "撒嬌咕嚕", "small", 0.4, coo_love),
    Sfx("sad_slide", "下滑嗚", "small", 0.6, sad_slide),
    Sfx("sorry_hum", "低聲嗯…", "small", 0.35, sorry_hum),
    Sfx("grumble", "嘟囔", "small", 0.35, grumble),
    Sfx("surprise_up", "上揚「喔！」", "medium", 0.25, surprise_up),
    Sfx("scared_wobble", "顫抖嗚", "small", 0.3, scared_wobble),
    Sfx("yawn", "打哈欠", "small", 0.8, yawn),
    Sfx("curious_chirp", "好奇「啾？」", "small", 0.12, curious_chirp),
    Sfx("confused_hm", "疑問「嗯？」", "small", 0.3, confused_hm),
    Sfx("listen_on", "開始聽", "small", 0.12, listen_on),
    Sfx("listen_off", "聽完了", "small", 0.12, listen_off),
    Sfx("dizzy_wobble", "暈眩搖擺音", "small", 0.8, dizzy_wobble),
    Sfx("proud_fanfare", "小號角", "medium", 0.4, proud_fanfare),
    Sfx("help_call", "求救三聲", "medium", 0.95, help_call, cooldown_s=20.0),
    Sfx("battery_low", "沒電下降兩音", "medium", 0.3, battery_low, cooldown_s=300.0),
    Sfx("charge_start", "充電上升琶音", "small", 0.25, charge_start),
    Sfx("wink_click", "眨眼「叮」", "small", 0.05, wink_click),
)
SFX_BY_NAME = {s.name: s for s in SFX}

#: 播放端套用的等級增益（相對檔案峰值；**未試聽，初值**）。
LEVEL_GAIN_DB = {"small": -12.0, "medium": -6.0}


def render(name: str) -> np.ndarray:
    """產生一個音效（float32，峰值 −6 dBFS）。"""
    x = np.asarray(SFX_BY_NAME[name].make(), dtype=np.float64)
    x = x - float(np.mean(x))
    peak = float(np.max(np.abs(x)))
    if peak <= 0:
        raise ValueError(f"{name} 是空的")
    return (x / peak * PEAK).astype(np.float32)


def write_all(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for s in SFX:
        x = render(s.name)
        path = out_dir / f"{s.name}.wav"
        write_wav(path, x, RATE)
        entries.append(
            {
                "name": s.name,
                "zh": s.zh,
                "file": path.name,
                "level": s.level,
                "cooldown_s": s.cooldown_s,
                "duration_s": round(len(x) / RATE, 3),
                "spec_duration_s": s.spec_duration_s,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    manifest = {
        "comment": "由 duck_audio/sfx_synth.py 用 numpy 合成的自製音效（原創，沒有取樣任何錄音）。不要手改 wav；改程式後重新產生。尚未試聽。",
        "generator": "python -m duck_audio.sfx_synth --out sounds",
        "spec": "nous_duck/docs/eye_expressions.md §5.3",
        "rate_hz": RATE,
        "channels": 1,
        "peak_dbfs": -6,
        "level_gain_db": LEVEL_GAIN_DB,
        "listened": False,
        "sounds": entries,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "sounds")
    m = write_all(ap.parse_args().out)
    total = sum(e["duration_s"] for e in m["sounds"])
    print(f"產生 {len(m['sounds'])} 個音效，共 {total:.2f} 秒 → {ap.parse_args().out}")
