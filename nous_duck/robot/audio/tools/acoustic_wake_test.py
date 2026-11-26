#!/usr/bin/env python3
"""實機聲學測試（Pi）：喇叭播**合成語音**的喚醒詞 → 空氣 → XVF3800 → 喚醒引擎。會出聲。

用途：確認「麥克風 → 喚醒引擎」這條路在實機上通，量延遲與 CPU，並看鴨子自己的喇叭會不會觸發（自我觸發）。

**這不是喚醒率**：聲源是離麥克風十幾公分的小喇叭播的合成語音，不是人在 1～3 m 外說話。
收到的音訊只在記憶體裡經過喚醒引擎，不寫檔。合成語音檔由 `tools/make_say_fixture.sh` 產生、測完從 Pi 刪掉。

    python tools/acoustic_wake_test.py play --volume 0.15 [--reference]     # 逐句播放並記錄有沒有回報
    python tools/acoustic_wake_test.py ambient --seconds 300 [--only HEY_YAZI]  # 不播放，只聽環境，數誤觸發
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from duck_audio.capture import ArecordSource  # noqa: E402
from duck_audio.kws import WakeConfig, WakeEngine, build_spotter  # noqa: E402
from duck_audio.playback import AplaySink, DuckAudioOut, PlaybackGate, RefSink, TeeSink  # noqa: E402
from duck_audio.voice_service import SPEAKER, EnergyVad  # noqa: E402
from duck_audio.wavio import read_wav  # noqa: E402


class Listener(threading.Thread):
    def __init__(self, cfg, models_dir, channel=0):
        super().__init__(daemon=True)
        self.channel = channel
        self.engine = WakeEngine(cfg, build_spotter(cfg, models_dir))
        self.events: list[tuple[float, str]] = []
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.level_db: list[float] = []

    def run(self):
        src = ArecordSource()
        vad = EnergyVad()
        block = []
        try:
            while not self.stop.is_set():
                f = src.read()[:, self.channel]
                speech = vad.update(f)
                block.append(f)
                if len(block) == 5:
                    chunk = np.concatenate(block)
                    block.clear()
                    self.level_db.append(20 * np.log10(max(float(np.sqrt(np.mean(chunk**2))), 1e-9)))
                    for ev in self.engine.accept(chunk, quiet=not speech):
                        self.events.append((time.monotonic(), self.engine.group_of(ev.keyword_id)))
                    self.ready.set()
        finally:
            src.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", choices=("play", "ambient"))
    ap.add_argument("--volume", type=float, default=0.15)
    ap.add_argument("--reference", action="store_true", help="同時把聲音送給 XVF3800 當回音消除參考（測自我觸發防護）")
    ap.add_argument("--seconds", type=float, default=300)
    ap.add_argument("--only", default=None, help="只啟用一個喚醒詞（group）")
    ap.add_argument("--models-dir", type=Path, default=None)
    ap.add_argument("--channel", type=int, default=0, help="XVF3800 的哪個收音聲道")
    ap.add_argument("--preroll", type=float, default=0.0, help="每句前面先播這麼久的極小聲雜訊，讓 USB 喇叭先醒來")
    ap.add_argument("--keywords-only", action="store_true")
    ap.add_argument("--fixtures", type=Path, default=ROOT / "build" / "say_kws")
    a = ap.parse_args()
    cfg = WakeConfig.load(ROOT / "config" / "wake_keywords.json", only_group=a.only)
    lis = Listener(cfg, a.models_dir, a.channel)
    c0, w0 = time.process_time(), time.monotonic()
    lis.start()
    lis.ready.wait(10)
    out: dict = {"mode": a.mode, "keywords": sorted({e.get("group", e["id"]) for e in cfg.entries}), "recordings_saved": False,
                 "loadavg_before": [round(v, 2) for v in os.getloadavg()]}
    if a.mode == "ambient":
        time.sleep(a.seconds)
        out.update({"seconds": a.seconds, "triggers": [g for _, g in lis.events], "trigger_count": len(lis.events)})
    else:
        gate = PlaybackGate()
        gate.request_volume(a.volume)
        factory = (lambda: TeeSink(AplaySink(SPEAKER), RefSink())) if a.reference else (lambda: AplaySink(SPEAKER))
        player = DuckAudioOut(factory, gate)
        items = [json.loads(l) for l in (a.fixtures / "manifest.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        rows, delays = [], []
        if a.keywords_only:
            items = [it for it in items if it["keyword_id"]]
        rng = np.random.default_rng(0)
        for it in items:
            x, rate = read_wav(a.fixtures / it["file"])
            n0 = len(lis.events)
            x = x / max(1e-9, float(np.max(np.abs(x))))
            if a.preroll > 0:
                x = np.concatenate([rng.normal(0, 0.003, int(a.preroll * rate)).astype(np.float32), x])
            player.play_raw(x, rate, kind="voice")
            t_end = time.monotonic()
            time.sleep(1.6)
            got = lis.events[n0:]
            hit = next((t for t, g in got if g == it["keyword_id"]), None) if it["keyword_id"] else None
            if hit is not None:
                delays.append(round((hit - t_end) * 1000))
            rows.append({"file": it["file"], "expect": it["keyword_id"], "got": [g for _, g in got]})
        per: dict[str, list[int]] = {}
        for r in rows:
            if r["expect"]:
                p = per.setdefault(r["expect"], [0, 0])
                p[1] += 1
                p[0] += r["expect"] in r["got"]
        negs = [r for r in rows if not r["expect"]]
        out.update({
            "volume": a.volume, "reference": a.reference, "channel": a.channel, "preroll_s": a.preroll,
            "reported_per_keyword": {k: f"{v[0]}/{v[1]}" for k, v in sorted(per.items())},
            "other_keyword_instead": sum(1 for r in rows if r["expect"] and any(g != r["expect"] for g in r["got"])),
            "negatives": len(negs), "triggers_on_negatives": sum(len(r["got"]) for r in negs),
            "negative_triggers_detail": [(r["file"], r["got"]) for r in negs if r["got"]],
            "delay_after_playback_end_ms": {"n": len(delays), "min": min(delays), "median": int(np.median(delays)), "max": max(delays)} if delays else None,
            "note": "延遲從 aplay 結束算起，含喇叭緩衝、空氣、XVF3800、arecord 緩衝與引擎；aplay 結束時聲音可能還沒播完，所以偏小",
        })
    lis.stop.set()
    lis.join(3)
    wall = time.monotonic() - w0
    out.update({"cpu_pct_of_one_core": round((time.process_time() - c0) / wall * 100, 1), "wall_s": round(wall, 1),
                "mic_level_dbfs_p10_p50_p90": [round(float(np.percentile(lis.level_db, q)), 1) for q in (10, 50, 90)],
                "silence_resets": lis.engine.silence_resets, "loadavg_after": [round(v, 2) for v in os.getloadavg()]})
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
