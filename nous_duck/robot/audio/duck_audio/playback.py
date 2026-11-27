"""D5 播放路徑：兩個邏輯輸出 `duck_voice`（變聲）與 `duck_raw`（不變聲），都經過同一個閘門與音量上限。

依 ADR-0010 §2、§3.2、§7 與 ADR-0017（第一版不用 PipeWire，由這個行程直接寫 ALSA）：

    Nous 的語音 ─► play_voice ─► 閘門 ─► 變聲 ─┐
    本機音效   ─► play_raw／play_sfx ─► 閘門 ──┴─► 增益（≤ 本機上限）─► 限幅 ─► 48 kHz 雙聲道 ─► sink

- **閘門與音量上限在這裡執行**（資料產生處），不是靠 Nous 記得不說話；Nous 只能把音量調低，
  超過本機上限的要求會被夾到上限。
- 被擋下的播放回傳 `refused` 與原因，**不會假裝播了**。
- 聲音只在記憶體裡串流，不留檔（`WavSink` 只給測試與離線試聽檔用）。
- `levels`：實際送出聲音的音量包絡（10 Hz），給「說話時的動作」用；只有等級，不含聲音。

喇叭：USB 音效卡，裝置名由 `speaker.find_speaker()` 找（2026-11-25 的 `CD002` 與 2026-11-27 換上的 `CD002AUDIO`
都只支援 S16_LE、2 聲道、48000 Hz）。
驗證層級：單元測試；Pi 上只做過「音量 0＋靜音，送到裝置沒有錯誤」，**沒有人聽過**。
"""

from __future__ import annotations

import json
import queue
import subprocess
import threading
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

    def abort(self) -> None:
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

    `device` 例：`plughw:CARD=CD002AUDIO,DEV=0`（鴨子的 USB 喇叭；用 `speaker.find_speaker()` 取得）、`null`（ALSA 的丟棄裝置）。
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

    def abort(self) -> None:
        """立刻停止（丟掉還在緩衝裡的聲音）。"""
        self._proc.kill()
        self._proc.wait(timeout=5)

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


REF_DEVICE = "plughw:CARD=Array,DEV=0"
REF_RATE = 16000


class RefSink:
    """把同一段聲音送到 XVF3800 的 USB 播放端，當它的回音消除（AEC）參考訊號。

    XVF3800 的播放端只收 16 kHz 雙聲道；它自己的喇叭輸出沒有接東西，所以這裡不會出聲。
    輸入是 48 kHz 雙聲道（和喇叭那一路相同），每 3 個取樣取 1 個（語音頻帶夠用；沒有另外做抗混疊濾波）。
    """

    def __init__(self, device: str = REF_DEVICE) -> None:
        self.device = device
        self.frames = 0
        self._proc = subprocess.Popen(
            ["aplay", "-q", "-D", device, "-t", "raw", "-f", "S16_LE", "-r", str(REF_RATE), "-c", "2", "-"],
            stdin=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )

    def write(self, pcm: bytes) -> None:
        x = np.frombuffer(pcm, dtype="<i2").reshape(-1, OUT_CHANNELS)[::3]
        try:
            self._proc.stdin.write(x.tobytes())  # type: ignore[union-attr]
        except BrokenPipeError:
            pass  # 參考訊號送不出去不該讓喇叭那一路失敗；AEC 會變差，由量測發現
        self.frames += len(x)

    def abort(self) -> None:
        self._proc.kill()

    def close(self) -> None:
        try:
            self._proc.stdin.close()  # type: ignore[union-attr]
            self._proc.wait(timeout=10)
        except Exception:
            self._proc.kill()


class TeeSink:
    """同時寫到多個 sink（喇叭＋AEC 參考）。第一個是主要的：它出錯就整個失敗。"""

    def __init__(self, *sinks) -> None:
        self.sinks = sinks

    def write(self, pcm: bytes) -> None:
        for s in self.sinks:
            s.write(pcm)

    def abort(self) -> None:
        for s in self.sinks:
            s.abort()

    def close(self) -> None:
        err = None
        for s in self.sinks:
            try:
                s.close()
            except Exception as e:  # noqa: BLE001
                err = err or e
        if err is not None:
            raise err


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


# ---------------------------------------------------------------- 串流播放（Nous 的即時語音）


class StreamPlayer:
    """`duck_voice` 的串流版：邊收邊變聲邊播。一次只播一段（一輪回話）。

        ok, reason = player.begin()      # 問閘門；被擋下就不要 feed
        player.feed(samples)             # 任意長度的 float32（in_rate，單聲道）；不阻塞
        player.finish()                  # 沒有更多資料；播完後呼叫 on_done("finished")
        player.flush()                   # 立刻停、丟掉還沒播的；呼叫 on_done("flushed")

    聲音只在記憶體的佇列裡，播完就沒有了。`on_started`／`on_done`／`on_level` 都在播放執行緒裡被呼叫。
    48 kHz 輸出用線性內插把 24 kHz 升 2 倍（沒有另外做抗鏡像濾波；語音夠用，音質要等試聽）。
    """

    def __init__(
        self,
        sink_factory: Callable[[], Sink],
        gate: PlaybackGate,
        shifter_factory: Callable[[int], object] | None,
        in_rate: int = 24000,
        on_level: Callable[[float], None] | None = None,
        on_started: Callable[[], None] | None = None,
        on_done: Callable[[str], None] | None = None,
    ) -> None:
        if OUT_RATE % in_rate:
            raise ValueError("in_rate 必須能整除 48000")
        self.sink_factory, self.gate, self.shifter_factory = sink_factory, gate, shifter_factory
        self.in_rate = in_rate
        self.on_level, self.on_started, self.on_done = on_level, on_started, on_done
        self.is_playing = False
        self._q: queue.Queue | None = None
        self._thread: threading.Thread | None = None
        self._abort = threading.Event()
        self._sink: Sink | None = None
        self.frames_out = 0
        self.peak = 0.0

    def begin(self) -> tuple[bool, str | None]:
        d = self.gate.decide("voice")
        if not d.allowed:
            return False, d.reason
        if self.shifter_factory is None:
            return False, "voice_changer_missing"
        self.flush()
        self._abort = threading.Event()
        self._q = queue.Queue()
        self.frames_out, self.peak = 0, 0.0
        self.is_playing = True
        self._thread = threading.Thread(target=self._run, args=(self._q, self._abort, d.gain), name="duck-voice-play", daemon=True)
        self._thread.start()
        return True, None

    def feed(self, samples: np.ndarray) -> None:
        if self._q is not None and self.is_playing:
            self._q.put(np.asarray(samples, dtype=np.float32))

    def finish(self) -> None:
        if self._q is not None:
            self._q.put(None)

    def flush(self) -> None:
        t = self._thread
        if t is None or not t.is_alive():
            return
        self._abort.set()
        if self._q is not None:
            self._q.put(None)
        sink = self._sink
        if sink is not None and hasattr(sink, "abort"):
            try:
                sink.abort()
            except Exception:  # noqa: BLE001
                pass
        t.join(timeout=5)

    def _run(self, q: "queue.Queue", abort: threading.Event, gain: float) -> None:
        up = OUT_RATE // self.in_rate
        shifter = self.shifter_factory(self.in_rate)  # type: ignore[misc]
        sink = None
        last = 0.0
        pend = np.zeros(0, dtype=np.float32)
        hop = OUT_RATE // LEVEL_HZ
        reason = "finished"
        try:
            while not abort.is_set():
                item = q.get()
                done = item is None
                y = shifter.flush() if done else shifter.process(item)  # type: ignore[attr-defined]
                if len(y):
                    if up > 1:  # 線性內插升頻
                        prev = np.concatenate([[last], y[:-1]])
                        steps = [prev + (y - prev) * (k + 1) / up for k in range(up)]
                        last = float(y[-1])
                        y = np.stack(steps, axis=1).reshape(-1).astype(np.float32)
                    pend = np.concatenate([pend, limit(y * gain, gain)])
                while len(pend) >= hop or (done and len(pend)):
                    block, pend = pend[:hop], pend[hop:]
                    if sink is None:
                        sink = self._sink = self.sink_factory()
                        if self.on_started:
                            self.on_started()
                    sink.write(to_pcm(block))
                    self.frames_out += len(block)
                    self.peak = max(self.peak, float(np.max(np.abs(block))))
                    if self.on_level:
                        self.on_level(float(np.sqrt(np.mean(block**2))))
                    if abort.is_set():
                        break
                if done:
                    break
            if abort.is_set():
                reason = "flushed"
        except PlaybackError:
            reason = "flushed" if abort.is_set() else "error"
        finally:
            if sink is not None:
                try:
                    sink.abort() if abort.is_set() and hasattr(sink, "abort") else sink.close()
                except Exception:  # noqa: BLE001
                    reason = "flushed" if abort.is_set() else "error"
            self._sink = None
            self.is_playing = False
            if self.on_level:
                self.on_level(0.0)
            if self.on_done:
                self.on_done(reason)
