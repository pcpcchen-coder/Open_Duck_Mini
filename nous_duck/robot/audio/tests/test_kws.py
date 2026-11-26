"""D7：喚醒設定與引擎包裝。邏輯用假的 spotter 測；有模型與 sherpa-onnx 時多跑一項合成語音的煙霧測試。

沒有麥克風：這裡沒有任何一項是喚醒率或誤喚醒率的驗證。
"""

import json
from pathlib import Path

import numpy as np
import pytest

from duck_audio.kws import AUDIO_ROOT, KWS_RATE, MODEL_DIRS, WakeConfig, WakeEngine, WakeRuntimeMissing, build_spotter
from duck_audio.wavio import read_wav

CONFIG = AUDIO_ROOT / "config" / "wake_keywords.candidates.json"


class FakeStream:
    def __init__(self):
        self.n = 0
        self.pending = []

    def accept_waveform(self, rate, x):
        assert rate == KWS_RATE and x.dtype == np.float32
        self.n += len(x)


class FakeSpotter:
    """每收到一塊就「可解一次」；`fire_at` 指定在哪幾塊回報哪個關鍵詞。"""

    def __init__(self, fire_at: dict[int, str]):
        self.fire_at = fire_at
        self.calls = 0
        self.ready = False
        self.resets = 0
        self.stream = FakeStream()
        self._last = ""

    def create_stream(self):
        return self.stream

    def is_ready(self, s):
        return self.ready

    def decode_stream(self, s):
        self.ready = False
        self._last = self.fire_at.get(self.calls, "")

    def get_result(self, s):
        r, self._last = self._last, ""
        return r

    def reset_stream(self, s):
        self.resets += 1


def feed(eng, spotter, chunks, loud=True):
    out = []
    for _ in range(chunks):
        spotter.calls += 1
        spotter.ready = True
        x = (np.full(1600, 0.1) if loud else np.zeros(1600)).astype(np.float32)
        out += eng.accept(x)
    return out


def cfg():
    return WakeConfig.load(CONFIG)


def test_candidate_config_is_marked_undecided_and_parses():
    c = cfg()
    assert c.status == "candidates_for_benchmark"  # 喚醒詞還沒決定
    assert c.model in MODEL_DIRS and c.num_threads == 1
    text = c.keywords_text()
    assert "h ēi y ā z i @HEI_YAZI\n" in text and "HH EY1 D AH1 K @HEY_DUCK\n" in text
    assert len(text.strip().splitlines()) == len(c.entries) == 5


def test_keyword_line_with_boost_and_threshold(tmp_path):
    d = json.loads(CONFIG.read_text(encoding="utf-8"))
    d["entries"] = [{"id": "X_1", "tokens": "HH EY1", "boost": 1.0, "threshold": 0.25}]
    p = tmp_path / "k.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    assert WakeConfig.load(p).keywords_text() == "HH EY1 :1.0 #0.25 @X_1\n"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(entries=[]),
        lambda d: d.update(entries=[d["entries"][0], d["entries"][0]]),
        lambda d: d.update(model="made-up"),
        lambda d: d["entries"][0].update(id="bad id"),
        lambda d: d["entries"][0].update(tokens="  "),
    ],
)
def test_bad_config_rejected(tmp_path, mutate):
    d = json.loads(CONFIG.read_text(encoding="utf-8"))
    mutate(d)
    p = tmp_path / "k.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(ValueError):
        WakeConfig.load(p)


def test_missing_models_raise_runtime_missing(tmp_path):
    pytest.importorskip("sherpa_onnx")
    with pytest.raises(WakeRuntimeMissing):
        build_spotter(cfg(), models_dir=tmp_path)


def test_events_carry_stream_time_and_reset_after_hit():
    sp = FakeSpotter({3: "HEY_DUCK"})
    eng = WakeEngine(cfg(), sp)
    ev = feed(eng, sp, 5)
    assert [(e.keyword_id, round(e.t_stream_s, 3)) for e in ev] == [("HEY_DUCK", 0.3)]
    assert sp.resets == 1 and eng.stream_time_s == pytest.approx(0.5)


def test_self_trigger_guard_while_playing_and_holdoff():
    sp = FakeSpotter({2: "HEY_DUCK", 6: "HEY_DUCK", 14: "HEY_DUCK"})
    eng = WakeEngine(cfg(), sp, holdoff_s=0.5)
    eng.set_playing(True)
    assert feed(eng, sp, 3) == [] and eng.suppressed == 1  # 鴨子自己在出聲：不算喚醒
    eng.set_playing(False)
    assert feed(eng, sp, 4) == [] and eng.suppressed == 2  # 停止後 0.5 秒內仍壓住
    ev = feed(eng, sp, 8)
    assert len(ev) == 1 and eng.suppressed == 2  # 之後恢復


def test_stream_reset_after_silence_only_once_per_quiet_period():
    sp = FakeSpotter({})
    eng = WakeEngine(cfg(), sp, reset_on_silence_s=0.7)
    feed(eng, sp, 5, loud=True)
    assert sp.resets == 0
    feed(eng, sp, 6, loud=False)
    assert sp.resets == 0  # 0.6 秒，還沒到
    feed(eng, sp, 10, loud=False)
    assert sp.resets == 1 and eng.silence_resets == 1  # 到了，而且長時間安靜不會一直重置
    feed(eng, sp, 2, loud=True)
    feed(eng, sp, 8, loud=False)
    assert sp.resets == 2
    off = WakeEngine(cfg(), FakeSpotter({}), reset_on_silence_s=None)
    feed(off, off._kws, 30, loud=False)
    assert off._kws.resets == 0


def test_hit_in_the_resetting_chunk_is_not_lost():
    sp = FakeSpotter({12: "HEI_YAZI"})
    eng = WakeEngine(cfg(), sp, reset_on_silence_s=0.7)
    feed(eng, sp, 5, loud=True)
    ev = feed(eng, sp, 7, loud=False)  # 第 12 塊同時是「安靜滿 0.7 秒」的那一塊
    assert [e.keyword_id for e in ev] == ["HEI_YAZI"]


def test_module_never_writes_audio():
    text = (AUDIO_ROOT / "duck_audio" / "kws.py").read_text(encoding="utf-8")
    for banned in ("write_wav", "wave.open", "np.save", "tofile(", "socket"):
        assert banned not in text


def _have_runtime():
    try:
        import sherpa_onnx  # noqa: F401
    except ImportError:
        return False
    name = MODEL_DIRS[cfg().model][0]
    return (AUDIO_ROOT / "models" / name / "tokens.txt").exists()


@pytest.mark.skipif(not _have_runtime(), reason="沒有 sherpa-onnx 或 KWS 模型（tools/fetch_models.py kws-zh-en）")
def test_smoke_real_engine_on_synthetic_fixtures():
    """煙霧測試：真的引擎吃得下合成語音 fixture、不含關鍵詞的句子不觸發。**不是喚醒率。**"""
    eng = WakeEngine(cfg())
    man = json.loads((AUDIO_ROOT / "fixtures" / "manifest.json").read_text(encoding="utf-8"))
    events = []
    for f in man["files"]:
        if f["role"] != "negative":
            continue
        x, rate = read_wav(AUDIO_ROOT / "fixtures" / f["file"])
        assert rate == KWS_RATE
        stream = np.concatenate([np.zeros(8000, np.float32), x, np.zeros(16000, np.float32)])
        for i in range(0, len(stream), 1600):
            events += eng.accept(stream[i : i + 1600])
    assert events == []
    assert eng.stream_time_s > 10 and eng.silence_resets >= 4


WAKE = AUDIO_ROOT / "config" / "wake_keywords.json"


def test_product_keyword_list_groups_and_sensitivity():
    """鴨子實際用的喚醒詞清單：依 group 選一句；Hey Nous 有三種念法；門檻倍數只影響門檻。"""
    full = WakeConfig.load(WAKE)
    groups = {e.get("group", e["id"]) for e in full.entries}
    assert {"HEY_YAZI", "HEY_NOUS", "HELLO_NOUS", "HEI_YAZI", "HEY_DUCK"} <= groups
    nous = WakeConfig.load(WAKE, only_group="HEY_NOUS")
    assert len(nous.entries) == 3 and nous.keywords_text().count(":1.0 #0.25 @HEY_NOUS_") == 3  # 與 AIOS 相同的提升分數與門檻
    yazi = WakeConfig.load(WAKE, only_group="HEY_YAZI")
    assert yazi.keywords_text() == "HH EY1 y ā z i @HEY_YAZI\n"
    strict = WakeConfig.load(WAKE, only_group="HEY_YAZI", threshold_scale=2.0)
    assert strict.keywords_text() == "HH EY1 y ā z i #0.3 @HEY_YAZI\n"
    assert WakeConfig.load(WAKE, only_group="HEY_NOUS", threshold_scale=2.0).keywords_text().count("#0.5 ") == 3
    with pytest.raises(ValueError):
        WakeConfig.load(WAKE, only_group="NOPE")


def test_settings_choices_match_keyword_file():
    """設定頁能選的喚醒詞，都在清單裡（反過來不一定：清單可以有還沒開放的候選）。"""
    import sys

    sys.path.append(str(AUDIO_ROOT.parent / "settings"))
    from duck_settings.schema import BY_KEY

    groups = {e.get("group", e["id"]) for e in WakeConfig.load(WAKE).entries}
    s = BY_KEY["audio.wake_keyword"]
    assert {c[0] for c in s.choices} <= groups and s.default in groups and s.default == "HEY_YAZI"


def test_engine_group_and_external_quiet_flag():
    sp = FakeSpotter({})
    c = WakeConfig.load(WAKE, only_group="HEY_NOUS")
    eng = WakeEngine(c, sp, reset_on_silence_s=0.3)
    assert eng.group_of("HEY_NOUS_AW") == "HEY_NOUS" and eng.group_of("X") == "X"
    loud = np.full(1600, 0.2, np.float32)  # 很大聲，但呼叫端說是安靜（例如自動增益放大的底噪）
    sp.calls += 1
    sp.ready = True
    eng.accept(loud, quiet=False)  # 先有一段聲音，之後的安靜才需要重置
    for _ in range(5):
        sp.calls += 1
        sp.ready = True
        eng.accept(loud, quiet=True)
    assert sp.resets == 1
    eng.reset()
    assert sp.resets == 2
