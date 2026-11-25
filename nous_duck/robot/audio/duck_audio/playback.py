"""D5 播放路徑：兩個邏輯輸出 `duck_voice`（變聲）與 `duck_raw`（不變聲），都經過同一個閘門與音量上限。

依 ADR-0010 §2、§3.2、§7 與 ADR-0017（第一版不用 PipeWire，由這個行程直接寫 ALSA）：

    Nous 的語音 ─► play_voice ─► 閘門 ─► 變聲 ─┐
    本機音效   ─► play_raw／play_sfx ─► 閘門 ──┴─► 增益（≤ 本機上限）─► 限幅 ─► 48 kHz 雙聲道 ─► sink

- **閘門與音量上限在這裡執行**（資料產生處），不是靠 Nous 記得不說話；Nous 只能把音量調低，
  超過本機上限的要求會被夾到上限。
- 被擋下的播放回傳 `refused` 與原因，**不會假裝播了**。
- 聲音只在記憶體裡串流，不留檔（`WavSink` 只給測試與離線試聽檔用）。
- `levels`：實際送出聲音的音量包絡（10 Hz），給「說話時的動作」用；只有等級，不含聲音。

喇叭（2026-11-25 在 Pi 上查）：USB `CD002`，只支援 S16_LE、2 聲道、48000 Hz。
驗證層級：單元測試；Pi 上只做過「音量 0＋靜音，送到裝置沒有錯誤」，**沒有人聽過**。
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

import numpy as np

from .wavio import read_wav, resample, write_wav

OUT_RATE = 48000
OUT_CHANNELS = 2
LEVEL_HZ = 10
SOUNDS_DIR = Path(__file__).resolve().parents[1] / "sounds"


class PlaybackError(RuntimeError):
    pass


# ---------------------------------------------------------------- sink


class Sink(Protocol):
    def write(self, pcm_s16le_stereo: bytes) -> None: ...
    def close(self) -> None: ...


class NullSink:
    """丟掉所有聲音，只計數（測試與夜間用）。"""

    def __init__(self) -> None:
        self.frames = 0
        self.closed = False

    def write(self, pcm: bytes) -> None:
        self.frames += len(pcm) // (2 * OUT_CHANNELS)

    def close(self) -> None:
        self.closed = True


class CaptureSink(NullSink):
    """把送出的聲音留在記憶體（測試用）。"""

    def __init__(self) -> None:
        super().__init__()
        self.chunks: list[bytes] = []

    def write(self, pcm: bytes) -> None:
        super().write(pcm)
        self.chunks.append(pcm)

    def samples(self) -> np.ndarray:
        """左聲道，float −1～1。"""
        x = np.frombuffer(b"".join(self.chunks), dtype="<i2").reshape(-1, OUT_CHANNELS)
        return x[:, 0].astype(np.float32) / 32768.0


class WavSink(NullSink):
    """寫成 wav 檔（只給離線試聽檔與測試用；鴨子上的即時語音不經過這裡）。"""

    def __init__(self, path: Path | str) -> None:
        super().__init__()
        self.path = Path(path)
        self._chunks: list[bytes] = []

    def write(self, pcm: bytes) -> None:
        super().write(pcm)
        self._chunks.append(pcm)

    def close(self) -> None:
        x = np.frombuffer(b"".join(self._chunks), dtype="<i2").reshape(-1, OUT_CHANNELS).astype(np.float32) / 32768.0
        write_wav(self.path, x, OUT_RATE)
        super().close()


class AplaySink:
    """用系統的 `aplay`（alsa-utils）把 48 kHz 雙聲道 S16_LE 送到 ALSA 裝置。

    `device` 例：`plughw:CARD=CD002,DEV=0`（鴨子的 USB 喇叭）、`null`（ALSA 的丟棄裝置）。
    """

    def __init__(self, device: str) -> None:
        self.device = device
        self.frames = 0
        try:
            self._proc = subprocess.Popen(
                ["aplay", "-q", "-D", device, "-t", "raw", "-f", "S16_LE", "-r", str(OUT_RATE), "-c", str(OUT_CHANNELS), "-"],
                stdin=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as e:
            raise PlaybackError("找不到 aplay（需要 alsa-utils）") from e

    def write(self, pcm: bytes) -> None:
        assert self._proc.stdin is not None
        try:
            self._proc.stdin.write(pcm)
        except BrokenPipeError as e:
            raise PlaybackError(f"aplay 中斷：{self._stderr()}") from e
        self.frames += len(pcm) // (2 * OUT_CHANNELS)

    def _stderr(self) -> str:
        try:
            return (self._proc.stderr.read() or b"").decode("utf-8", "replace").strip()  # type: ignore[union-attr]
        except Exception:
            return ""

    def close(self) -> None:
        assert self._proc.stdin is not None
        try:
            self._proc.stdin.close()
        except BrokenPipeError:
            pass
        rc = self._proc.wait(timeout=30)
        err = self._stderr()
        if rc != 0:
            raise PlaybackError(f"aplay 結束碼 {rc}：{err}")


# ---------------------------------------------------------------- 閘門


@dataclass
class GateConfig:
    """本機設定（Nous 不能改）。音量是線性增益 0～1，乘在滿刻度上；**未校準**（還沒對著喇叭量過音量）。"""

    volume_cap_day: float = 0.5
    volume_cap_night: float = 0.15
    #: 夜間模式下安全提示要不要出聲：ADR-0010 待決第 5 項。預設不出聲（保守），等使用者決定。
    safety_audible_at_night: bool = False


@dataclass
class GateState:
    """目前的狀態，由鴨子本機的來源設定（時段、房間規則、實體開關、本機靜音）。"""

    night: bool = False
    #: 所在房間禁止出聲（ADR-0006）。
    room_silent: bool = False
    #: 實體隱私開關關閉（麥克風與喇叭一起斷電；這裡同步擋下，回報真實原因）。
    privacy_switch_off: bool = False
    #: 本機強制靜音（例如夜間開發時）。擋下所有聲音，包含安全提示。
    hard_mute: bool = False


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reason: str | None  # 被擋下的原因代碼
    gain: float  # 實際套用的線性增益（已夾到上限）


KINDS = ("voice", "sfx", "safety")


class PlaybackGate:
    def __init__(self, config: GateConfig | None = None, state: GateState | None = None) -> None:
        self.cfg = config or GateConfig()
        self.state = state or GateState()
        #: Nous 或使用者要求的音量（0～1）；只能在上限以內。
        self._requested = 1.0

    def request_volume(self, volume: float) -> float:
        """設定要求的音量；回傳實際會用的值（夾到目前上限）。超過上限不是錯誤，只是不會更大聲。"""
        self._requested = float(min(1.0, max(0.0, volume)))
        return min(self._requested, self.cap)

    @property
    def cap(self) -> float:
        return self.cfg.volume_cap_night if self.state.night else self.cfg.volume_cap_day

    def decide(self, kind: str) -> GateDecision:
        if kind not in KINDS:
            raise ValueError(f"kind 必須是 {KINDS}")
        s = self.state
        gain = min(self._requested, self.cap)
        if s.hard_mute:
            return GateDecision(False, "hard_mute", 0.0)
        if s.privacy_switch_off:
            return GateDecision(False, "privacy_switch_off", 0.0)
        if kind == "safety":
            # 安全提示：房間禁止出聲時仍可出聲（ADR-0010 §7），但仍受音量上限限制
            if s.night and not self.cfg.safety_audible_at_night:
                return GateDecision(False, "night_mode", 0.0)
            return GateDecision(True, None, self.cap)
        if s.room_silent:
            return GateDecision(False, "privacy_policy", 0.0)
        if s.night and kind == "sfx":
            return GateDecision(False, "night_mode", 0.0)  # eye_expressions §1 第 7 點：夜間不播音效
        if gain <= 0.0:
            return GateDecision(False, "volume_zero", 0.0)
        return GateDecision(True, None, gain)


# ---------------------------------------------------------------- 輸出


@dataclass(frozen=True)
class PlayResult:
    #: "played"＝已送到 sink（**不代表有人聽到**）；"refused"＝被閘門或冷卻時間擋下。
    status: str
    output: str  # "duck_voice" 或 "duck_raw"
    kind: str
    reason: str | None = None
    frames: int = 0
    duration_s: float = 0.0
    gain: float = 0.0
    peak: float = 0.0
    #: 實際送出聲音的音量包絡（每 0.1 秒的 RMS，0～1）。
    levels: tuple[float, ...] = ()


def limit(x: np.ndarray, ceiling: float) -> np.ndarray:
    """軟限幅：峰值不超過 ceiling（tanh 曲線；小訊號幾乎不變）。"""
    if ceiling <= 0:
        return np.zeros_like(x)
    return (np.tanh(x / ceiling) * ceiling).astype(np.float32)


def to_pcm(x: np.ndarray) -> bytes:
    s = (np.clip(x, -1.0, 1.0) * 32767.0).round().astype("<i2")
    return np.repeat(s[:, None], OUT_CHANNELS, axis=1).tobytes()


def envelope(x: np.ndarray, rate: int = OUT_RATE, hz: int = LEVEL_HZ) -> tuple[float, ...]:
    hop = rate // hz
    return tuple(round(float(np.sqrt(np.mean(x[i : i + hop] ** 2))), 4) for i in range(0, len(x), hop))


class DuckAudioOut:
    """鴨子的聲音輸出。`sink_factory` 每次播放開一個 sink（實機用 `lambda: AplaySink(裝置)`）。"""

    def __init__(
        self,
        sink_factory: Callable[[], Sink],
        gate: PlaybackGate | None = None,
        voice_changer: Callable[[np.ndarray, int], np.ndarray] | None = None,
        sounds_dir: Path = SOUNDS_DIR,
        clock: Callable[[], float] = time.monotonic,
        on_level: Callable[[float], None] | None = None,
    ) -> None:
        self.sink_factory = sink_factory
        self.gate = gate or PlaybackGate()
        self.voice_changer = voice_changer
        self.sounds_dir = Path(sounds_dir)
        self.clock = clock
        self.on_level = on_level
        #: 正在出聲（給喚醒詞的自我觸發防護用）。
        self.is_playing = False
        self._last_played: dict[str, float] = {}
        self._manifest: dict | None = None

    # ---- 兩個邏輯輸出 ----

    def play_voice(self, samples: np.ndarray, rate: int) -> PlayResult:
        """`duck_voice`：Nous 的語音，先變聲再播。沒有設定變聲器時**拒絕**（不會用原聲冒充鴨子的聲音）。"""
        d = self.gate.decide("voice")
        if not d.allowed:
            return PlayResult("refused", "duck_voice", "voice", d.reason)
        if self.voice_changer is None:
            return PlayResult("refused", "duck_voice", "voice", "voice_changer_missing")
        return self._emit(self.voice_changer(samples, rate), rate, "duck_voice", "voice", d.gain)

    def play_raw(self, samples: np.ndarray, rate: int, kind: str = "sfx", level_db: float = 0.0) -> PlayResult:
        """`duck_raw`：已經做好的本機聲音（音效、預錄提示），不變聲。"""
        d = self.gate.decide(kind)
        if not d.allowed:
            return PlayResult("refused", "duck_raw", kind, d.reason)
        return self._emit(samples * (10 ** (level_db / 20)), rate, "duck_raw", kind, d.gain)

    def play_sfx(self, name: str) -> PlayResult:
        """播一個自製音效（`sounds/manifest.json` 裡的名字），套用等級增益與冷卻時間。"""
        m = self._load_manifest()
        entry = next((e for e in m["sounds"] if e["name"] == name), None)
        if entry is None:
            raise KeyError(f"沒有這個音效：{name}")
        now = self.clock()
        last = self._last_played.get(name)
        if last is not None and now - last < entry["cooldown_s"]:
            return PlayResult("refused", "duck_raw", "sfx", "cooldown")
        x, rate = read_wav(self.sounds_dir / entry["file"])
        res = self.play_raw(x, rate, "sfx", m["level_gain_db"][entry["level"]])
        if res.status == "played":
            self._last_played[name] = now
        return res

    # ---- 內部 ----

    def _load_manifest(self) -> dict:
        if self._manifest is None:
            self._manifest = json.loads((self.sounds_dir / "manifest.json").read_text(encoding="utf-8"))
        return self._manifest

    def _emit(self, samples: np.ndarray, rate: int, output: str, kind: str, gain: float) -> PlayResult:
        x = resample(np.asarray(samples, dtype=np.float32), rate, OUT_RATE)
        # 增益後再限幅到「上限」：不管輸入多大聲，送出的峰值都不超過 gain
        x = limit(x * gain, gain)
        levels = envelope(x)
        sink = self.sink_factory()
        self.is_playing = True
        try:
            hop = OUT_RATE // LEVEL_HZ
            for i, start in enumerate(range(0, len(x), hop)):
                sink.write(to_pcm(x[start : start + hop]))
                if self.on_level is not None:
                    self.on_level(levels[i])
        finally:
            self.is_playing = False
            sink.close()
            if self.on_level is not None:
                self.on_level(0.0)
        peak = float(np.max(np.abs(x))) if len(x) else 0.0
        return PlayResult("played", output, kind, None, len(x), len(x) / OUT_RATE, gain, round(peak, 4), levels)
