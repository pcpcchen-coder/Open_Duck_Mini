"""D6 變聲（spike）：把 Nous 的聲音調成「小動物在說話」的候選處理器。只用 numpy。

依 ADR-0010 §3.3：升音高、共振峰保留或小幅上移、**不改語速**。兩個自己寫的候選，都能分塊串流處理：

| 類別 | 作法 | 共振峰 | 演算法延遲 |
|---|---|---|---|
| `DelayLineShifter` | 時域：兩個交叉淡化的移動讀取點（延遲線） | 跟著音高一起上移（「快轉」感） | 約半個視窗（預設 20 ms） |
| `PhaseVocoderShifter` | 頻域：相位聲碼器拉長時間再重取樣；可先用倒頻譜包絡預先修正共振峰 | 可設定：保留（1.0）、小幅上移（例如 1.12）、或跟著音高 | 一個 FFT 視窗＋緩衝（預設約 55 ms） |

另外兩個**系統工具**候選（Rubber Band、SoX）只在 `tools/bench_voice.py` 裡以外部指令比較，不在這裡：
Rubber Band 是 GPL，只能當系統套件用，不放進 repo、不連結進這個模組。

**還沒有人聽過任何一個**（夜間不出聲）。哪個好聽、哪組參數聽得懂，要等使用者試聽
`docs/validation/media/voice-*.wav`。這裡的測試只檢查：音高真的移了宣稱的量、長度不變、
共振峰照設定移動、分塊處理與整段處理結果一致。
"""

from __future__ import annotations

import math

import numpy as np


def semitones_to_ratio(semitones: float) -> float:
    return 2.0 ** (semitones / 12.0)


class DelayLineShifter:
    """時域音高平移：兩個讀取點在延遲線上以不同於寫入的速度移動，交叉淡化接起來。

    便宜、延遲低，但共振峰跟著音高一起移（聲音像快轉），視窗接縫處有輕微顫動。
    """

    name = "delay_line"

    def __init__(self, rate: int, semitones: float, window_s: float = 0.04) -> None:
        self.rate = rate
        self.ratio = semitones_to_ratio(semitones)
        self.window = int(round(window_s * rate))
        self._hist = np.zeros(self.window + 2, dtype=np.float64)
        self._phase = 0.0  # 0～1：第一個讀取點在視窗裡的位置

    @property
    def latency_s(self) -> float:
        """演算法延遲（平均）：讀取點平均落後半個視窗。"""
        return self.window / 2 / self.rate

    def process(self, block: np.ndarray) -> np.ndarray:
        n = len(block)
        if n == 0:
            return np.zeros(0, dtype=np.float32)
        W = self.window
        buf = np.concatenate([self._hist, block.astype(np.float64)])
        base = len(self._hist) + np.arange(n)  # 目前寫入位置
        # 音高升高：延遲隨時間變短（讀得比寫得快），每個取樣少 (ratio−1)
        step = (self.ratio - 1.0) / W
        ph1 = (self._phase - step * np.arange(1, n + 1)) % 1.0
        ph2 = (ph1 + 0.5) % 1.0
        out = np.zeros(n)
        for ph in (ph1, ph2):
            pos = base - ph * W - 1.0
            i0 = np.floor(pos).astype(np.int64)
            frac = pos - i0
            i0 = np.clip(i0, 0, len(buf) - 2)
            tap = buf[i0] * (1.0 - frac) + buf[i0 + 1] * frac
            out += tap * np.sin(np.pi * ph) ** 2  # 兩個讀取點的增益和恆為 1
        self._phase = float(ph1[-1])
        self._hist = buf[-(W + 2) :]
        return out.astype(np.float32)

    def flush(self) -> np.ndarray:
        return np.zeros(0, dtype=np.float32)


class PhaseVocoderShifter:
    """頻域音高平移：相位聲碼器把時間拉長 ratio 倍，再重取樣回原長度（音高 ×ratio、語速不變）。

    `formant_ratio`：共振峰（頻譜包絡）要移多少倍。
      - `None`：不處理，共振峰跟著音高移（等於 ×ratio）。
      - `1.0`：保留原本的共振峰（只有音高變高）。
      - 介於中間（例如 1.12）：聽起來身體小一點，但不到快轉。
    作法：在拉長之前，用倒頻譜（cepstrum）估頻譜包絡 E(f)，把每個頻率的振幅乘上
    E(f·ratio/formant_ratio)/E(f)；之後重取樣把頻率軸放大 ratio 倍，包絡就落在 E(f/formant_ratio)。
    """

    name = "phase_vocoder"

    def __init__(self, rate: int, semitones: float, formant_ratio: float | None = 1.0, n_fft: int = 1024, hop: int | None = None, lifter_hz: float = 500.0) -> None:
        self.rate = rate
        self.ratio = semitones_to_ratio(semitones)
        self.formant_ratio = formant_ratio
        self.n_fft = n_fft
        self.ha = hop or n_fft // 4
        self.hs = int(round(self.ha * self.ratio))
        self.stretch = self.hs / self.ha  # 實際的音高倍率（整數取樣造成的微小偏差）
        self.win = np.hanning(n_fft + 1)[:-1]
        self._norm = float(np.sum(self.win**2)) / self.hs
        self._omega = 2 * np.pi * np.arange(n_fft // 2 + 1) / n_fft
        #: 倒頻譜保留的係數個數：只留比 lifter_hz 慢的頻譜起伏（包絡），丟掉諧波細節
        self._lifter = max(8, int(rate / lifter_hz))
        self._in = np.zeros(0)
        self._ola = np.zeros(n_fft)
        self._stretched = np.zeros(0)
        self._read_pos = 0.0
        self._prev_phase: np.ndarray | None = None
        self._sum_phase: np.ndarray | None = None
        self._primed = False

    @property
    def latency_s(self) -> float:
        """演算法延遲：要湊滿一個 FFT 視窗才有輸出，再加重取樣需要的一小段緩衝。"""
        return (self.n_fft + self.ha) / self.rate

    def _envelope(self, mag: np.ndarray) -> np.ndarray:
        logm = np.log(np.maximum(mag, 1e-9))
        cep = np.fft.irfft(logm, self.n_fft)
        cep[self._lifter : self.n_fft - self._lifter + 1] = 0.0
        return np.exp(np.fft.rfft(cep, self.n_fft).real)

    def _frame(self, x: np.ndarray) -> np.ndarray:
        spec = np.fft.rfft(x * self.win)
        mag, phase = np.abs(spec), np.angle(spec)
        if self.formant_ratio is not None and abs(self.formant_ratio - self.stretch) > 1e-6:
            env = self._envelope(mag)
            bins = np.arange(len(mag), dtype=np.float64)
            warped = np.interp(bins * (self.stretch / self.formant_ratio), bins, env, right=env[-1])
            mag = mag * np.minimum(warped / np.maximum(env, 1e-9), 20.0)
        if self._prev_phase is None:
            self._sum_phase = phase.copy()
        else:
            # 每個頻率的真實瞬時頻率 → 以合成步距累積相位
            d = phase - self._prev_phase - self._omega * self.ha
            d -= 2 * np.pi * np.round(d / (2 * np.pi))
            self._sum_phase = self._sum_phase + (self._omega + d / self.ha) * self.hs  # type: ignore[operator]
        self._prev_phase = phase
        return np.fft.irfft(mag * np.exp(1j * self._sum_phase), self.n_fft) * self.win / self._norm

    def process(self, block: np.ndarray) -> np.ndarray:
        if not self._primed:
            # 前面補零，讓第一個取樣落在視窗中間（之後的延遲就是固定的）
            self._in = np.zeros(self.n_fft - self.ha)
            self._primed = True
        self._in = np.concatenate([self._in, block.astype(np.float64)])
        new = []
        while len(self._in) >= self.n_fft:
            y = self._frame(self._in[: self.n_fft])
            self._in = self._in[self.ha :]
            self._ola += y
            new.append(self._ola[: self.hs].copy())
            self._ola = np.concatenate([self._ola[self.hs :], np.zeros(self.hs)])
        if new:
            self._stretched = np.concatenate([self._stretched, *new])
        return self._resample_out()

    def _resample_out(self) -> np.ndarray:
        """把拉長後的訊號以 stretch 倍的速度讀出（線性內插），長度回到原本。"""
        avail = len(self._stretched) - 1 - self._read_pos
        n = int(math.floor(avail / self.stretch))
        if n <= 0:
            return np.zeros(0, dtype=np.float32)
        pos = self._read_pos + self.stretch * np.arange(n)
        i0 = np.floor(pos).astype(np.int64)
        frac = pos - i0
        out = self._stretched[i0] * (1 - frac) + self._stretched[i0 + 1] * frac
        self._read_pos = float(pos[-1] + self.stretch)
        drop = int(math.floor(self._read_pos))
        self._stretched = self._stretched[drop:]
        self._read_pos -= drop
        return out.astype(np.float32)

    def flush(self) -> np.ndarray:
        """送完之後把還在緩衝裡的尾巴推出來。"""
        return self.process(np.zeros(self.n_fft, dtype=np.float32))


def make_voice_changer(kind: str, rate: int, semitones: float, formant_ratio: float | None = 1.0):
    if kind == "delay_line":
        return DelayLineShifter(rate, semitones)
    if kind == "phase_vocoder":
        return PhaseVocoderShifter(rate, semitones, formant_ratio)
    raise ValueError(f"不認得的變聲器：{kind}")


def process_all(shifter, x: np.ndarray, block: int = 480) -> np.ndarray:
    """以固定大小的塊餵完一整段，回傳與輸入等長的結果（已扣掉演算法延遲、對齊到原訊號）。"""
    parts = [shifter.process(x[i : i + block]) for i in range(0, len(x), block)]
    parts.append(shifter.flush())
    y = np.concatenate(parts)
    lead = 0
    if isinstance(shifter, PhaseVocoderShifter):
        lead = int(round((shifter.n_fft - shifter.ha) / 1))  # 開頭補的零
    y = y[lead : lead + len(x)]
    if len(y) < len(x):
        y = np.concatenate([y, np.zeros(len(x) - len(y), dtype=np.float32)])
    return y.astype(np.float32)


# ---------------------------------------------------------------- 量測用（測試與 bench 共用）


def estimate_f0(x: np.ndarray, rate: int, fmin: float = 70.0, fmax: float = 600.0) -> float | None:
    """整段的基頻中位數（自相關法；無聲的音框略過）。"""
    n = int(0.04 * rate)
    lo, hi = int(rate / fmax), int(rate / fmin)
    out = []
    thresh = 0.1 * float(np.sqrt(np.mean(x**2)) + 1e-12)
    for s in range(0, len(x) - n, n // 2):
        f = x[s : s + n].astype(np.float64)
        if np.sqrt(np.mean(f**2)) < thresh:
            continue
        f = f - f.mean()
        ac = np.correlate(f, f, "full")[n - 1 :]
        if ac[0] <= 0:
            continue
        k = lo + int(np.argmax(ac[lo:hi]))
        if ac[k] / ac[0] > 0.5:
            out.append(rate / k)
    return float(np.median(out)) if out else None


def spectral_envelope_peak(x: np.ndarray, rate: int, lo: float, hi: float) -> float:
    """lo～hi Hz 之間，平滑後的長時頻譜的峰值頻率（粗估共振峰位置）。"""
    n = 2048
    acc = np.zeros(n // 2 + 1)
    w = np.hanning(n)
    for s in range(0, len(x) - n, n // 2):
        acc += np.abs(np.fft.rfft(x[s : s + n] * w)) ** 2
    f = np.fft.rfftfreq(n, 1 / rate)
    k = max(3, int(250 / (rate / n)))  # 約 250 Hz 的平滑
    sm = np.convolve(acc, np.hanning(2 * k + 1), "same")
    m = (f >= lo) & (f <= hi)
    return float(f[m][int(np.argmax(sm[m]))])
