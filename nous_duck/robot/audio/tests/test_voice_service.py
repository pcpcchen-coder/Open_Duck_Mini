"""duck-voice 服務的端到端（**全部是合成音訊與模擬的 Nous；沒有麥克風、沒有喇叭**）。

真的部分：VoiceSession、StreamPlayer（變聲、增益、限幅）、WebSocket 連線、設定讀取、模擬的 Nous 端。
假的部分：麥克風（直接呼叫 `_on_frame`／`_on_wake`）、喇叭（記憶體 sink）。
"""

import asyncio
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("websockets")
sys.path.append(str(Path(__file__).resolve().parents[2] / "settings"))

from duck_audio import voice_service as vs  # noqa: E402
from duck_audio.mock_nous import MockNous  # noqa: E402
from duck_audio.playback import CaptureSink, PlaybackGate, StreamPlayer  # noqa: E402
from duck_audio.session import State  # noqa: E402
from duck_audio.voice import make_voice_changer  # noqa: E402


def tone(dur, rate, f=300.0, amp=0.3):
    t = np.arange(int(dur * rate)) / rate
    return (amp * np.sin(2 * np.pi * f * t)).astype(np.float32)


# ---------------------------------------------------------------- StreamPlayer


def make_player(gate=None, changer="delay_line"):
    sinks, events = [], []

    def factory():
        sinks.append(CaptureSink())
        return sinks[-1]

    p = StreamPlayer(factory, gate or PlaybackGate(), (lambda r: make_voice_changer(changer, r, 5, 1.0)) if changer else None,
                     on_started=lambda: events.append("started"), on_done=lambda r: events.append(r))
    return p, sinks, events


def wait(cond, timeout=5.0):
    t0 = time.time()
    while not cond():
        assert time.time() - t0 < timeout, "逾時"
        time.sleep(0.01)


def test_stream_player_plays_chunks_with_cap_and_reports_done():
    gate = PlaybackGate()
    gate.request_volume(0.2)
    p, sinks, events = make_player(gate)
    assert p.begin() == (True, None)
    x = tone(1.0, 24000, amp=1.0)
    for i in range(0, len(x), 480):
        p.feed(x[i : i + 480])
    p.finish()
    wait(lambda: "finished" in events)
    y = sinks[0].samples()
    assert events == ["started", "finished"] and sinks[0].closed and not p.is_playing
    assert len(y) == pytest.approx(48000, abs=4800)  # 長度不變（升到 48 kHz）
    assert np.max(np.abs(y)) <= 0.2 + 1e-4  # 不超過要求的音量
    spec = np.abs(np.fft.rfft(y[9600:38400]))
    peak_hz = np.fft.rfftfreq(28800, 1 / 48000)[int(np.argmax(spec))]
    assert peak_hz == pytest.approx(300 * 2 ** (5 / 12), rel=0.05)  # 真的有變聲（+5 半音）


def test_stream_player_refused_by_gate_and_without_changer():
    gate = PlaybackGate()
    gate.state.hard_mute = True
    p, sinks, _ = make_player(gate)
    assert p.begin() == (False, "hard_mute") and sinks == []
    p2, sinks2, _ = make_player(changer=None)
    assert p2.begin() == (False, "voice_changer_missing") and sinks2 == []


def test_stream_player_flush_drops_queued_audio():
    p, sinks, events = make_player()
    p.begin()
    p.feed(tone(5.0, 24000))
    p.flush()
    assert events[-1] == "flushed" and not p.is_playing
    p.feed(tone(1.0, 24000))  # flush 之後再餵：不會播
    time.sleep(0.05)
    assert len(sinks) <= 1


# ---------------------------------------------------------------- 服務


def test_only_loopback_urls():
    assert vs.loopback_url("ws://127.0.0.1:8791/duck-voice")
    for bad in ("ws://192.168.1.10:8791/duck-voice", "wss://example.com/duck-voice", "http://127.0.0.1/x"):
        with pytest.raises(ValueError):
            vs.loopback_url(bad)


def test_energy_vad_adapts_to_noise_floor():
    vad = vs.EnergyVad()
    rng = np.random.default_rng(0)
    noise = lambda a: (rng.normal(0, a, 320)).astype(np.float32)
    assert not any(vad.update(noise(0.02)) for _ in range(100))  # 底噪高（自動增益）也不算語音
    assert vad.update(noise(0.2))  # 明顯比底噪大
    assert not any(vad.update(noise(0.02)) for _ in range(50))


class Harness:
    def __init__(self, tmp_path, monkeypatch, settings=None):
        self.sinks = []
        self.dir = tmp_path / "settings"
        self.dir.mkdir()
        if settings:
            (self.dir / "settings.json").write_text(json.dumps({"schema": 1, "revision": 1, "values": settings}), encoding="utf-8")
        monkeypatch.setattr(vs.VoiceService, "mic_thread", lambda self: None)  # 沒有麥克風

    def service(self, port):
        svc = vs.VoiceService(f"ws://127.0.0.1:{port}/duck-voice", self.dir)

        def sink():
            self.sinks.append(CaptureSink())
            return self.sinks[-1]

        svc._sink = sink
        svc.sfx.sink_factory = sink
        svc.player.sink_factory = sink
        return svc


async def until(cond, timeout=8.0):
    t0 = time.time()
    while not cond():
        assert time.time() - t0 < timeout, "逾時"
        await asyncio.sleep(0.02)


def test_end_to_end_wake_uplink_reply_playback(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch, {"audio.volume": 0.1})

    async def scenario():
        nous = MockNous(reply=tone(0.6, 24000, amp=0.9), realtime=False)
        server = await nous.serve(0)
        port = server.sockets[0].getsockname()[1]
        svc = h.service(port)
        task = asyncio.ensure_future(svc.run())
        await until(lambda: svc.session.connected)
        assert nous.hello["uplink"] == {"rate": 16000, "format": "s16le", "channels": 1, "frame_ms": 20}
        # 待命：有人說話也不上行
        for _ in range(50):
            svc._on_frame(tone(0.02, 16000), True)
        await asyncio.sleep(0.1)
        assert nous.turns == [] and svc.session.frames_up == 0
        # 喚醒 → 提示音 → 上行
        svc._on_wake("HEY_YAZI")
        await until(lambda: len(h.sinks) >= 1 and not svc.sfx.is_playing and nous.turns)
        assert svc.session.state is State.LISTENING and not svc.kws_on.is_set()
        for _ in range(60):
            svc._on_frame(tone(0.02, 16000, amp=0.2), True)
        for _ in range(60):
            svc._on_frame(np.zeros(320, np.float32), False)
            await asyncio.sleep(0.001)
        await until(lambda: svc.session.state is State.IDLE and svc.kws_on.is_set(), timeout=10)
        types = [m["type"] for m in nous.messages]
        assert types[:2] == ["hello", "turn_start"] and "turn_end" in types
        assert [m["state"] for m in nous.messages if m["type"] == "playback"] == ["started", "finished"]
        assert 60 <= nous.turns[0]["frames"] <= 120  # 只有這一輪的音訊到了對面
        reply = h.sinks[-1].samples()
        assert len(reply) > 0.5 * 48000 and np.max(np.abs(reply)) <= 0.1 + 1e-4
        # 回到待命後，音訊又不上行了
        before = nous.turns[0]["frames"]
        for _ in range(30):
            svc._on_frame(tone(0.02, 16000), True)
        await asyncio.sleep(0.1)
        assert nous.turns[0]["frames"] == before and len(nous.turns) == 1
        svc.stop.set()
        task.cancel()
        server.close()

    asyncio.run(scenario())


def test_settings_disable_listening_and_mute(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch, {"privacy.wake_listening": False})

    async def scenario():
        nous = MockNous(reply=tone(0.3, 24000), realtime=False)
        server = await nous.serve(0)
        svc = h.service(server.sockets[0].getsockname()[1])
        task = asyncio.ensure_future(svc.run())
        await until(lambda: svc.session.connected)
        assert svc.session.state is State.DISABLED and not svc.mic_wanted.is_set() and not svc.kws_on.is_set()
        svc._on_wake("HEY_YAZI")
        await asyncio.sleep(0.1)
        assert nous.turns == [] and h.sinks == []
        applied = json.loads((h.dir / "applied" / "duck-voice.json").read_text(encoding="utf-8"))
        assert applied["values"]["privacy.wake_listening"] is False
        svc.stop.set()
        task.cancel()
        server.close()

    asyncio.run(scenario())


def test_no_file_writing_in_voice_modules():
    """紅線：收音、喚醒、服務這幾個模組的原始碼裡沒有任何寫音訊檔的呼叫。"""
    pkg = Path(vs.__file__).parent
    for name in ("capture.py", "voice_service.py", "session.py", "kws.py", "mock_nous.py"):
        text = (pkg / name).read_text(encoding="utf-8")
        for banned in ("write_wav", "wave.open", "np.save", ".tofile(", "write_bytes", "write_text"):
            assert banned not in text, f"{name} 不應該有 {banned}"
        assert not re.search(r"(?<![.\w])open\(", text), f"{name} 不應該直接開檔"
