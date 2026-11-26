"""duck-voice：鴨子端的語音服務。麥克風 → 本機喚醒詞 → 喚醒後把語音送給 Nous → 把 Nous 的回話變聲後從喇叭播出。

    python -m duck_audio.voice_service --url ws://127.0.0.1:8791/duck-voice --settings-dir ~/duck/settings

- 介面：`protocol/proposals/d-duck-voice-media-channel.md`（duck-voice v0）。規則在 `session.py`。
- 麥克風：XVF3800 的處理後聲道（ch0）；喇叭：CD002，同時把播出的聲音送給 XVF3800 當回音消除的參考。
- 設定：只從「鴨子設定」（`robot/settings`，ADR-0019）讀，每秒看一次；`privacy.wake_listening` 關掉時**不開麥克風**。
- 隱私（ADR-0003 §6）：喚醒前的音訊只經過喚醒引擎，在記憶體裡用完就丟；這個檔案沒有任何寫檔的程式；
  log 只有狀態與計數，沒有音訊、沒有辨識文字。只有 `LISTENING` 狀態的音訊會離開這個行程，而且只送到 loopback。
- 不碰舵機、不呼叫 duckd 的內部函式。要讓 duckd 做動作，用 `--notify-duckd` 把狀態用 UDP 丟給它
  （duckd 那一端還沒做，預設關；見 `docs/validation/voice-duck-side-2026-11-26.md` 給 A 線的清單）。

驗證層級見 `robot/audio/README.md`。
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import logging
import signal
import socket
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import numpy as np

from .capture import ArecordSource, CaptureError
from .kws import AUDIO_ROOT, KWS_RATE, WakeConfig, WakeEngine, WakeRuntimeMissing
from .playback import AplaySink, DuckAudioOut, GateConfig, PlaybackGate, RefSink, StreamPlayer, TeeSink
from .session import Action, SessionConfig, State, VoiceSession
from .voice import make_voice_changer

log = logging.getLogger("duck-voice")
PROTOCOL = 0
UPLINK = {"rate": KWS_RATE, "format": "s16le", "channels": 1, "frame_ms": 20}
DOWNLINK = {"rate": 24000, "format": "s16le", "channels": 1}
SPEAKER = "plughw:CARD=CD002,DEV=0"
SETTINGS_SERVICE = "duck-voice"
WAKE_CONFIG = AUDIO_ROOT / "config" / "wake_keywords.json"

#: 設定鍵 → 這個服務用到的值（登記在 robot/settings/duck_settings/schema.py）。
KEYS = (
    "features.wake_word", "privacy.wake_listening", "audio.wake_keyword", "audio.wake_sensitivity",
    "audio.volume", "audio.volume_cap_day", "audio.volume_cap_night", "audio.mute",
    "audio.voice_changer", "audio.voice_semitones", "audio.voice_formant_ratio",
    "audio.listen_no_speech_s", "audio.listen_end_silence_s", "audio.listen_max_s", "audio.reply_timeout_s",
    "audio.aec_reference", "audio.barge_in", "features.sound_effects",
)


class EnergyVad:
    """依底噪調整的能量門檻（XVF3800 的 ch0 有自動增益，固定門檻不能用）。只回答「這一框像不像有人在說話」。

    底噪＝最近的最小 RMS（往下立刻跟、往上慢慢漲）。**未校準**：倍數與下限是 2026-11-26 在一個房間裡看讀值定的。
    """

    def __init__(self, ratio: float = 3.0, floor_min: float = 1e-4, rise: float = 1.002) -> None:
        self.ratio, self.floor_min, self.rise = ratio, floor_min, rise
        self.floor = 0.0

    def update(self, frame: np.ndarray) -> bool:
        rms = float(np.sqrt(np.mean(frame * frame)))
        if self.floor <= 0.0 or rms < self.floor:
            self.floor = max(rms, self.floor_min)
        else:
            self.floor = min(self.floor * self.rise, rms)
        return rms > self.floor * self.ratio


def loopback_url(url: str) -> str:
    """語音只能送到 loopback（經 SSH 通道到 Mac）；其他位址直接拒絕。"""
    u = urlparse(url)
    host = u.hostname or ""
    ok = host == "localhost"
    if not ok:
        try:
            ok = ipaddress.ip_address(host).is_loopback
        except ValueError:
            ok = False
    if u.scheme != "ws" or not ok:
        raise ValueError(f"duck-voice 只連 loopback 的 ws://（收到 {url}）")
    return url


class VoiceService:
    def __init__(self, url: str, settings_dir: Path | None, mic_device: str | None = None, speaker: str = SPEAKER,
                 notify_duckd: tuple[str, int] | None = None, models_dir: Path | None = None) -> None:
        self.url = loopback_url(url)
        self.mic_device, self.speaker = mic_device, speaker
        self.models_dir = models_dir
        self.session = VoiceSession()
        self.gate = PlaybackGate()
        self.values: dict = {}
        self.watcher = self._make_watcher(settings_dir)
        self.loop: asyncio.AbstractEventLoop | None = None
        self.ws = None
        self.kws_on = threading.Event()
        self.kws_reload = threading.Event()
        self.mic_wanted = threading.Event()
        self.stop = threading.Event()
        self.sfx = DuckAudioOut(self._sink, self.gate)
        self.player = StreamPlayer(self._sink, self.gate, self._shifter, in_rate=DOWNLINK["rate"],
                                   on_started=lambda: self._post(self._on_play_started),
                                   on_done=lambda reason: self._post(self._on_play_done, reason),
                                   on_level=self._on_level)
        self._notify_addr = notify_duckd
        self._notify_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) if notify_duckd else None
        self._level = 0.0
        self.mic_status = "off"
        self.wakes = 0

    # ---- 設定 ----

    def _make_watcher(self, directory: Path | None):
        sibling = Path(__file__).resolve().parents[2] / "settings"
        if (sibling / "duck_settings").is_dir() and str(sibling) not in sys.path:
            sys.path.append(str(sibling))
        from duck_settings.reader import Watcher  # noqa: PLC0415

        w = Watcher(directory, SETTINGS_SERVICE)
        w.poll(force=True)
        return w

    def apply_settings(self, t: float) -> list[Action]:
        v = {k: self.watcher.view.values[k] for k in KEYS}
        old, self.values = self.values, v
        self.gate.cfg = GateConfig(volume_cap_day=v["audio.volume_cap_day"], volume_cap_night=v["audio.volume_cap_night"])
        self.gate.state.hard_mute = bool(v["audio.mute"])
        self.gate.request_volume(v["audio.volume"])
        s = self.session.cfg
        s.no_speech_timeout_s, s.end_silence_s = v["audio.listen_no_speech_s"], v["audio.listen_end_silence_s"]
        s.max_listen_s, s.reply_timeout_s, s.barge_in = v["audio.listen_max_s"], v["audio.reply_timeout_s"], bool(v["audio.barge_in"])
        if any(old.get(k) != v[k] for k in ("audio.wake_keyword", "audio.wake_sensitivity")):
            self.kws_reload.set()
        enabled = bool(v["features.wake_word"]) and bool(v["privacy.wake_listening"])
        (self.mic_wanted.set if enabled else self.mic_wanted.clear)()
        self.watcher.report({**v, "privacy.wake_listening": enabled and bool(v["privacy.wake_listening"])})
        return self.session.set_enabled(enabled, t)

    def _sink(self):
        main = AplaySink(self.speaker)
        return TeeSink(main, RefSink()) if self.values.get("audio.aec_reference", True) else main

    def _shifter(self, rate: int):
        v = self.values
        return make_voice_changer(v["audio.voice_changer"], rate, v["audio.voice_semitones"], v["audio.voice_formant_ratio"])

    # ---- 執行緒之間 ----

    def _post(self, fn, *args) -> None:
        if self.loop is not None:
            self.loop.call_soon_threadsafe(fn, *args)

    def _on_level(self, level: float) -> None:
        self._level = level

    # ---- 麥克風執行緒：喚醒詞在這裡算；音訊不離開這個函式，除非主迴圈說可以上行 ----

    def mic_thread(self) -> None:
        engine: WakeEngine | None = None
        vad = EnergyVad()
        while not self.stop.is_set():
            if not self.mic_wanted.is_set():
                self.mic_status = "off"  # 設定關掉：不開麥克風
                time.sleep(0.2)
                continue
            try:
                if engine is None or self.kws_reload.is_set():
                    self.kws_reload.clear()
                    cfg = WakeConfig.load(WAKE_CONFIG, only_group=self.values["audio.wake_keyword"],
                                          threshold_scale=self.values["audio.wake_sensitivity"])
                    from .kws import build_spotter  # noqa: PLC0415

                    engine = WakeEngine(cfg, build_spotter(cfg, self.models_dir))
                    log.info("喚醒詞：%s（門檻倍數 %.2f）", self.values["audio.wake_keyword"], self.values["audio.wake_sensitivity"])
                src = ArecordSource(self.mic_device) if self.mic_device else ArecordSource()
            except (CaptureError, WakeRuntimeMissing, ValueError) as e:
                self.mic_status = f"error: {e}"
                log.error("麥克風或喚醒引擎起不來：%s（5 秒後再試）", e)
                time.sleep(5)
                continue
            self.mic_status = "on"
            block: list[np.ndarray] = []
            was_on = False
            try:
                while not self.stop.is_set() and self.mic_wanted.is_set() and not self.kws_reload.is_set():
                    frame = src.read()[:, 0]  # ch0：處理後（回音消除、波束、降噪）
                    speech = vad.update(frame)
                    self._post(self._on_frame, frame, speech)
                    on = self.kws_on.is_set()
                    if on and not was_on:
                        engine.reset()
                        block.clear()
                    was_on = on
                    if not on:
                        continue
                    block.append(frame)
                    if len(block) == 5:  # 100 ms
                        chunk = np.concatenate(block)
                        block.clear()
                        for ev in engine.accept(chunk, quiet=not speech):
                            self._post(self._on_wake, engine.group_of(ev.keyword_id))
            except CaptureError as e:
                self.mic_status = f"error: {e}"
                log.error("收音中斷：%s（2 秒後重開）", e)
                time.sleep(2)
            finally:
                src.close()
        self.mic_status = "off"

    # ---- 主迴圈上的事件 ----

    def _now(self) -> float:
        return time.monotonic()

    def _on_frame(self, frame: np.ndarray, speech: bool) -> None:
        if self.sfx.is_playing:
            return  # 提示音播完才開始送（eye_expressions §5.1）
        if self.session.on_mic_frame(self._now(), speech) and self.ws is not None:
            pcm = (np.clip(frame, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
            asyncio.ensure_future(self._send_bytes(pcm))

    def _on_wake(self, keyword: str) -> None:
        self.wakes += 1
        log.info("喚醒詞 %s（第 %d 次）", keyword, self.wakes)
        self.perform(self.session.on_wake(self._now(), keyword))

    def _on_play_started(self) -> None:
        self.perform(self.session.on_playback_started())

    def _on_play_done(self, reason: str) -> None:
        if reason == "error":
            log.error("播放失敗")
        self.perform(self.session.on_playback_done(self._now()))

    async def _send_bytes(self, data: bytes) -> None:
        try:
            if self.ws is not None:
                await self.ws.send(data)
        except Exception:  # noqa: BLE001  連線問題由接收迴圈處理
            pass

    def perform(self, actions: list[Action]) -> None:
        for a in actions:
            if a.kind == "send":
                if self.ws is not None:
                    asyncio.ensure_future(self._send_text(a.data))
            elif a.kind == "sfx":
                if self.values.get("features.sound_effects", True):
                    self.loop.run_in_executor(None, self._play_sfx, a.data["name"])  # type: ignore[union-attr]
            elif a.kind == "flush_playback":
                self.loop.run_in_executor(None, self.player.flush)  # type: ignore[union-attr]
            elif a.kind == "kws":
                (self.kws_on.set if a.data["on"] else self.kws_on.clear)()
            elif a.kind == "notify":
                log.info("狀態 → %s（第 %s 輪）%s", a.data.get("state"), a.data.get("turn_id"), a.data.get("reason", ""))
                if self._notify_sock is not None:
                    msg = {"v": 1, "kind": "voice_state", "t_ms": int(self._now() * 1000), **a.data}
                    try:
                        self._notify_sock.sendto(json.dumps(msg, separators=(",", ":")).encode(), self._notify_addr)
                    except OSError:
                        pass

    def _play_sfx(self, name: str) -> None:
        try:
            r = self.sfx.play_sfx(name)
            if r.status != "played":
                log.info("音效 %s 沒播：%s", name, r.reason)
        except Exception as e:  # noqa: BLE001
            log.error("音效 %s 播放失敗：%s", name, e)

    async def _send_text(self, data: dict) -> None:
        try:
            if self.ws is not None:
                await self.ws.send(json.dumps(data, separators=(",", ":")))
        except Exception:  # noqa: BLE001
            pass

    def handle_text(self, text: str) -> None:
        try:
            msg = json.loads(text)
        except ValueError:
            return
        if not isinstance(msg, dict):
            return
        before = self.session.state
        acts = self.session.on_remote(msg, self._now())
        if msg.get("type") == "speak_start" and self.session.state is State.SPEAKING and before is not State.SPEAKING:
            ok, reason = self.player.begin()
            if not ok:
                log.info("回話被本機閘門擋下：%s", reason)
                acts.append(Action("send", {"type": "playback", "turn_id": self.session.turn_id, "state": "refused", "reason": reason}))
                acts += self.session.on_remote({"type": "session_end"}, self._now())
        elif msg.get("type") == "speak_end" and self.session.state is State.SPEAKING:
            self.player.finish()
        self.perform(acts)

    def handle_binary(self, data: bytes) -> None:
        if self.session.accepts_downlink() and self.player.is_playing and len(data) % 2 == 0:
            self.player.feed(np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0)

    # ---- 連線 ----

    async def link_loop(self) -> None:
        import websockets  # noqa: PLC0415

        delay = 1.0
        while not self.stop.is_set():
            try:
                async with websockets.connect(self.url, max_size=1 << 20, ping_interval=10, ping_timeout=10) as ws:
                    self.ws = ws
                    delay = 1.0
                    await ws.send(json.dumps({"type": "hello", "v": PROTOCOL, "uplink": UPLINK, "downlink": DOWNLINK}))
                    log.info("已連上 %s", self.url)
                    self.perform(self.session.on_link(True, self._now()))
                    async for message in ws:
                        if isinstance(message, bytes):
                            self.handle_binary(message)
                        else:
                            self.handle_text(message)
            except (OSError, asyncio.TimeoutError, websockets.WebSocketException) as e:  # type: ignore[attr-defined]
                log.info("連不上或斷線：%s（%.0f 秒後重試）", type(e).__name__, delay)
            finally:
                self.ws = None
                self.perform(self.session.on_link(False, self._now()))
            await asyncio.sleep(delay)
            delay = min(delay * 2, 15.0)

    async def tick_loop(self) -> None:
        n = 0
        while not self.stop.is_set():
            await asyncio.sleep(0.1)
            self.perform(self.session.tick(self._now()))
            n += 1
            if n % 10 == 0 and self.watcher.poll() is not None:
                self.perform(self.apply_settings(self._now()))

    async def run(self) -> None:
        self.loop = asyncio.get_running_loop()
        try:  # 測試用的本機手動喚醒：在鴨子上 `sudo systemctl kill -s USR1 duck-voice`（等於按一下「開始聽」）
            self.loop.add_signal_handler(signal.SIGUSR1, self._on_wake, "MANUAL")
        except (NotImplementedError, RuntimeError, ValueError):
            pass
        self.perform(self.apply_settings(self._now()))
        if self.session.state is State.IDLE:
            self.kws_on.set()
        threading.Thread(target=self.mic_thread, name="duck-voice-mic", daemon=True).start()
        try:
            await asyncio.gather(self.link_loop(), self.tick_loop())
        finally:
            self.stop.set()
            self.player.flush()


def main() -> int:
    ap = argparse.ArgumentParser(description="duck-voice：鴨子端語音服務")
    ap.add_argument("--url", default="ws://127.0.0.1:8791/duck-voice", help="Nous 端的 duck-voice 端點（只接受 loopback）")
    ap.add_argument("--settings-dir", type=Path, default=None, help="鴨子設定資料夾（預設 ~/duck/settings）")
    ap.add_argument("--mic-device", default=None)
    ap.add_argument("--speaker", default=SPEAKER)
    ap.add_argument("--models-dir", type=Path, default=None)
    ap.add_argument("--notify-duckd", default=None, metavar="HOST:PORT", help="把語音狀態用 UDP 丟給 duckd（duckd 端尚未實作；預設關）")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s duck-voice %(message)s")
    notify = None
    if a.notify_duckd:
        host, port = a.notify_duckd.rsplit(":", 1)
        if not ipaddress.ip_address(host).is_loopback:
            ap.error("--notify-duckd 只能是 loopback")
        notify = (host, int(port))
    svc = VoiceService(a.url, a.settings_dir, a.mic_device, a.speaker, notify, a.models_dir)
    try:
        asyncio.run(svc.run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
