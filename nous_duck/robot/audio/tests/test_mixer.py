"""喇叭硬體音量（`duck_audio.mixer`）與語音服務的套用：用假的 amixer（mock），不碰任何音效卡。"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "settings"))

from duck_audio import mixer as mx  # noqa: E402
from duck_audio.mixer import MixerError, SpeakerMixer, card_of, parse_percent, parse_playback_controls  # noqa: E402

# 2026-11-28 在 Pi 上讀到的 CD002-AUDIO（`amixer -c CD002AUDIO scontents`、`-M sget PCM`）
SCONTENTS = """Simple mixer control 'PCM',0
  Capabilities: pvolume pswitch pswitch-joined
  Playback channels: Front Left - Front Right
  Limits: Playback 0 - 147
  Mono:
  Front Left: Playback 147 [100%] [-0.94dB] [on]
  Front Right: Playback 147 [100%] [-0.94dB] [on]
"""


class FakeCard:
    """假的 amixer（mock）：記住音量與靜音，回傳和真的 amixer 同格式的文字。"""

    def __init__(self, card="CD002AUDIO", percent=100, muted=False, scontents=SCONTENTS, stuck=None):
        self.card, self.percent, self.muted, self.scontents, self.stuck = card, percent, muted, scontents, stuck
        self.calls = []

    def sget(self):
        sw = "off" if self.muted else "on"
        return (f"Simple mixer control 'PCM',0\n  Front Left: Playback 99 [{self.percent}%] [-5.00dB] [{sw}]\n"
                f"  Front Right: Playback 99 [{self.percent}%] [-5.00dB] [{sw}]\n")

    def __call__(self, cmd):
        self.calls.append(cmd)
        assert cmd[:3] == ["amixer", "-c", self.card], cmd
        args = cmd[3:]
        if args == ["scontents"]:
            return self.scontents
        if args[-2:-1] == ["sget"] or args[1:2] == ["sget"]:
            return self.sget()
        if "sset" in args:
            pct = int(re.match(r"(\d+)%", args[args.index("sset") + 2]).group(1))
            self.percent = self.stuck if self.stuck is not None else pct
            if "unmute" in args:
                self.muted = False
            return ""
        raise AssertionError(cmd)


def test_card_and_parsing():
    assert card_of("plughw:CARD=CD002AUDIO,DEV=0") == "CD002AUDIO" and card_of("hw:2,0") == "2"
    with pytest.raises(MixerError):
        card_of("default")
    assert parse_playback_controls(SCONTENTS) == ["PCM"]
    assert parse_percent(SCONTENTS) == 100
    two = "Simple mixer control 'Mic',0\n  Capabilities: cvolume\nSimple mixer control 'Speaker',0\n  Capabilities: pvolume\n" \
          "Simple mixer control 'Headphone',0\n  Capabilities: pvolume pswitch\n"
    assert parse_playback_controls(two) == ["Speaker", "Headphone"]
    with pytest.raises(MixerError):
        parse_percent("nothing here")


def test_set_uses_mapped_volume_unmutes_and_reads_back():
    card = FakeCard(percent=100, muted=True)
    m = SpeakerMixer("CD002AUDIO", run=card)
    assert m.pick_control() == "PCM" and m.get() == 100 and m.muted()
    assert m.set(60) == 60 and not card.muted
    sset = next(c for c in card.calls if "sset" in c)
    assert sset == ["amixer", "-c", "CD002AUDIO", "-q", "-M", "sset", "PCM", "60%", "unmute"]  # -M：照聽感換算
    for bad in (-1, 101, True):
        with pytest.raises(MixerError):
            m.set(bad)


def test_prefers_speaker_controls_and_fails_without_any():
    sc = "Simple mixer control 'Headphone',0\n  Capabilities: pvolume\nSimple mixer control 'Speaker',0\n  Capabilities: pvolume\n"
    assert SpeakerMixer("X", run=FakeCard(card="X", scontents=sc)).pick_control() == "Speaker"
    with pytest.raises(MixerError, match="沒有可以調播放音量"):
        SpeakerMixer("X", run=FakeCard(card="X", scontents="Simple mixer control 'Mic',0\n  Capabilities: cvolume\n")).pick_control()


def test_real_amixer_errors_become_mixer_errors(monkeypatch):
    import subprocess

    def missing(*a, **k):
        raise FileNotFoundError("amixer")

    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(MixerError, match="找不到 amixer"):
        SpeakerMixer("CD002AUDIO").get()

    class R:
        returncode, stdout, stderr = 1, "", "amixer: Cannot find the given element from control default"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    with pytest.raises(MixerError, match="Cannot find"):
        SpeakerMixer("CD002AUDIO").get()


# ---------------------------------------------------------------- 語音服務套用設定
from duck_settings.store import Store  # noqa: E402


class _LazyVs:
    """語音服務要 websockets；沒裝時只略過這幾項，上面的混音器測試照跑。"""

    def __getattr__(self, name):
        pytest.importorskip("websockets")
        from duck_audio import voice_service  # noqa: PLC0415

        return getattr(voice_service, name)


vs = _LazyVs()


def make_service(tmp_path, monkeypatch, card, speaker="plughw:CARD=CD002AUDIO,DEV=0"):
    pytest.importorskip("websockets")
    from duck_audio import voice_service  # noqa: PLC0415

    monkeypatch.setattr(voice_service.VoiceService, "mic_thread", lambda self: None)
    svc = voice_service.VoiceService("ws://127.0.0.1:9/duck-voice", tmp_path, speaker=speaker, mode="wake", wake_udp=None, control_udp=None)
    svc.mixer_factory = lambda c: SpeakerMixer(c, run=card)
    return svc


def report(tmp_path):
    return json.loads((tmp_path / "applied" / "duck-voice.json").read_text(encoding="utf-8"))


def test_voice_service_applies_speaker_volume_and_reports_readback(tmp_path, monkeypatch):
    card = FakeCard(percent=100)
    svc = make_service(tmp_path, monkeypatch, card)
    svc.apply_settings(0.0)
    assert card.percent == 100 and not any("sset" in c for c in card.calls)  # 預設 100：和現況一樣就不寫
    assert report(tmp_path)["values"]["audio.speaker_volume"] == 100
    Store(tmp_path).apply({"audio.speaker_volume": 40}, "web")
    assert svc.watcher.poll() is not None
    svc.apply_settings(1.0)
    assert card.percent == 40 and svc.speaker_volume_actual == 40
    assert report(tmp_path)["values"]["audio.speaker_volume"] == 40 and report(tmp_path)["note"] == ""


def test_voice_service_reapplies_after_replug_or_manual_change(tmp_path, monkeypatch):
    card = FakeCard(percent=100)
    svc = make_service(tmp_path, monkeypatch, card)
    Store(tmp_path).apply({"audio.speaker_volume": 55}, "web")
    svc.watcher.poll()
    svc.apply_settings(0.0)
    card.percent, card.muted = 100, True  # 喇叭拔插後回到驅動預設；或有人用 alsamixer 改了
    svc.apply_speaker_volume()  # tick_loop 每 5 秒做一次
    assert card.percent == 55 and not card.muted


def test_voice_service_reports_failure_honestly(tmp_path, monkeypatch):
    stuck = FakeCard(percent=100, stuck=100)  # 寫了沒反應（例如別的程式一直改回去）
    svc = make_service(tmp_path, monkeypatch, stuck)
    Store(tmp_path).apply({"audio.speaker_volume": 30}, "web")
    svc.watcher.poll()
    svc.apply_settings(0.0)
    assert report(tmp_path)["values"]["audio.speaker_volume"] == 100  # 回報實際的值，不是設定值

    def no_card(*a, **k):
        raise vs.SpeakerNotFound("分不出哪一張是喇叭")

    svc2 = make_service(tmp_path / "b", monkeypatch, FakeCard(), speaker=None)
    monkeypatch.setattr(sys.modules["duck_audio.voice_service"], "find_speaker", no_card)
    svc2.apply_settings(0.0)
    rep = report(tmp_path / "b")
    assert rep["values"]["audio.speaker_volume"] is None and "分不出哪一張是喇叭" in rep["note"]
    assert svc2.speaker_volume_error and svc2.speaker_volume_actual is None


def test_settings_page_shows_applied_and_failed(tmp_path, monkeypatch):
    from duck_settings import status as st
    from duck_settings.reader import load

    card = FakeCard(percent=100)
    svc = make_service(tmp_path, monkeypatch, card)
    Store(tmp_path).apply({"audio.speaker_volume": 70}, "web")
    svc.watcher.poll()
    svc.apply_settings(0.0)
    eff = st.effects(load(tmp_path), tmp_path, {"duck-voice": {"state": "active"}})
    assert eff["audio.speaker_volume"]["state"] == "applied"
    monkeypatch.setattr(sys.modules["duck_audio.voice_service"], "find_speaker", lambda: (_ for _ in ()).throw(vs.SpeakerNotFound("喇叭沒接")))
    svc.speaker = None
    svc._mixer = None
    svc.apply_speaker_volume()
    eff = st.effects(load(tmp_path), tmp_path, {"duck-voice": {"state": "active"}})
    assert eff["audio.speaker_volume"]["state"] == "failed" and "喇叭沒接" in eff["audio.speaker_volume"]["label"]


def test_mixer_cli(monkeypatch, capsys):
    card = FakeCard(percent=80)
    monkeypatch.setattr(mx, "SpeakerMixer", lambda c: SpeakerMixer(c, run=card))
    monkeypatch.setenv("DUCK_SPEAKER_DEVICE", "plughw:CARD=CD002AUDIO,DEV=0")
    assert mx.main([]) == 0 and "80%" in capsys.readouterr().out
    assert mx.main(["35"]) == 0 and "回讀 35%" in capsys.readouterr().out and card.percent == 35
