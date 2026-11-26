#!/usr/bin/env python3
"""D7：喚醒詞引擎（sherpa-onnx KWS）在這台機器上的運算量測。**輸入是檔案（合成語音），沒有麥克風。**

量的是：模型載入時間、常駐記憶體、即時倍率、以即時速度餵音訊時的 CPU、每 100 ms 一塊的處理時間、
從關鍵詞說完到引擎回報之間的延遲（音訊時間＋運算時間）。

**不是**喚醒率或誤喚醒率的量測：語音是少數幾個合成聲音、沒有房間聲學、沒有噪音、沒有麥克風。
輸出裡的「偵測到幾個」只用來說明延遲統計的樣本數。

    python tools/bench_kws.py --set say      # build/say_kws/（先在 Mac 跑 tools/make_say_fixture.sh，再同步到 Pi）
    python tools/bench_kws.py --set melo     # fixtures/kws/（進版控的 MeloTTS 合成檔）
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import statistics
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from duck_audio.kws import KWS_RATE, WakeConfig, WakeEngine, build_spotter  # noqa: E402
from duck_audio.wavio import read_wav  # noqa: E402

CHUNK_S = 0.1
GAP_S = 1.2


def rss_mb() -> float:
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    return float("nan")


def rss_mb_any() -> float:
    if Path("/proc/self/status").exists():
        return rss_mb()
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)  # macOS：最大值，bytes


def load_set(name: str) -> list[dict]:
    if name == "say":
        d = ROOT / "build" / "say_kws"
        items = [json.loads(l) for l in (d / "manifest.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        return [{"path": d / it["file"], "keyword_id": it["keyword_id"], "label": it["file"]} for it in items]
    d = ROOT / "fixtures"
    m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    key2id = {"hei_yazi": "HEI_YAZI", "hey_duck": "HEY_DUCK", "xiaoya_xiaoya": "XIAOYA_XIAOYA"}
    return [
        {"path": d / f["file"], "keyword_id": key2id.get(f["key"]) if f["role"] == "keyword" else None, "label": f["file"]}
        for f in m["files"]
        if f["role"] in ("keyword", "negative")
    ]


def build_stream(items: list[dict], seed: int = 0):
    """把所有句子接成一條音訊，中間隔 GAP_S 的近似靜音；回傳音訊與每句的起訖（秒）。"""
    rng = np.random.default_rng(seed)
    parts, marks, t = [], [], 0
    for it in items:
        gap = (rng.normal(0, 1e-4, int(GAP_S * KWS_RATE))).astype(np.float32)
        x, rate = read_wav(it["path"])
        assert rate == KWS_RATE, it["path"]
        idx = np.nonzero(np.abs(x) > 0.02 * float(np.max(np.abs(x))))[0]
        parts += [gap, x]
        start = t + len(gap)
        marks.append({**it, "start_s": start / KWS_RATE, "speech_end_s": (start + int(idx[-1])) / KWS_RATE, "end_s": (start + len(x)) / KWS_RATE})
        t = start + len(x)
    parts.append(np.zeros(int(2.0 * KWS_RATE), dtype=np.float32))
    return np.concatenate(parts), marks


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", choices=("say", "melo"), default="say")
    ap.add_argument("--config", type=Path, default=ROOT / "config" / "wake_keywords.candidates.json")
    ap.add_argument("--threads", type=int, default=None)
    ap.add_argument("--realtime-seconds", type=float, default=40.0)
    ap.add_argument("--no-silence-reset", action="store_true", help="關掉「安靜就重置串流」（對照用）")
    a = ap.parse_args()

    cfg = WakeConfig.load(a.config)
    if a.threads:
        cfg = WakeConfig(cfg.model, cfg.keywords_score, cfg.keywords_threshold, a.threads, cfg.entries, cfg.status)
    load_before = os.getloadavg()
    rss0 = rss_mb_any()
    t0 = time.perf_counter()
    spotter = build_spotter(cfg)
    load_s = time.perf_counter() - t0
    rss_loaded = rss_mb_any()

    items = load_set(a.set)
    audio, marks = build_stream(items)
    dur = len(audio) / KWS_RATE
    chunk = int(CHUNK_S * KWS_RATE)

    # ---- A：盡快餵完，量即時倍率與偵測延遲 ----
    reset_s = None if a.no_silence_reset else 0.7
    eng = WakeEngine(cfg, spotter, reset_on_silence_s=reset_s)
    events, chunk_ms = [], []
    c0, w0 = time.process_time(), time.perf_counter()
    for i in range(0, len(audio), chunk):
        t = time.perf_counter()
        evs = eng.accept(audio[i : i + chunk])
        dt = (time.perf_counter() - t) * 1000
        chunk_ms.append(dt)
        for e in evs:
            events.append({"keyword_id": eng.group_of(e.keyword_id), "t_stream_s": e.t_stream_s, "compute_ms": dt})
    wall = time.perf_counter() - w0
    cpu_fast = (time.process_time() - c0) / wall * 100

    detected, wrong, false_triggers, delays = 0, 0, 0, []
    per_kw: dict[str, list[int]] = {}
    used = set()
    for k, m in enumerate(marks):
        nxt = marks[k + 1]["start_s"] if k + 1 < len(marks) else dur
        mine = [j for j, e in enumerate(events) if m["start_s"] <= e["t_stream_s"] < nxt + 0.3 and j not in used]
        used.update(mine)
        if m["keyword_id"] is None:
            false_triggers += len(mine)
            continue
        pk = per_kw.setdefault(m["keyword_id"], [0, 0])
        pk[1] += 1
        hit = next((events[j] for j in mine if events[j]["keyword_id"] == m["keyword_id"]), None)
        if hit:
            detected += 1
            pk[0] += 1
            delays.append((hit["t_stream_s"] - m["speech_end_s"]) * 1000 + hit["compute_ms"])
        wrong += sum(1 for j in mine if events[j]["keyword_id"] != m["keyword_id"])
    cs = sorted(chunk_ms)

    # ---- B：以即時速度餵（每 100 ms 一塊），量常駐 CPU ----
    eng2 = WakeEngine(cfg, spotter, reset_on_silence_s=reset_s)
    n_chunks = int(a.realtime_seconds / CHUNK_S)
    c0, w0 = time.process_time(), time.perf_counter()
    late = 0
    for k in range(n_chunks):
        i = (k * chunk) % (len(audio) - chunk)
        eng2.accept(audio[i : i + chunk])
        target = w0 + (k + 1) * CHUNK_S
        now = time.perf_counter()
        if now < target:
            time.sleep(target - now)
        else:
            late += 1
    wall_rt = time.perf_counter() - w0
    cpu_rt = (time.process_time() - c0) / wall_rt * 100

    out = {
        "mock_input": True,
        "input": f"檔案（合成語音，{a.set}）",
        "microphone": False,
        "machine": platform.machine(),
        "python": platform.python_version(),
        "sherpa_onnx": __import__("sherpa_onnx").__version__,
        "model": cfg.model,
        "num_threads": cfg.num_threads,
        "keywords": [e["id"] for e in cfg.entries],
        "keywords_score": cfg.keywords_score,
        "keywords_threshold": cfg.keywords_threshold,
        "reset_on_silence_s": reset_s,
        "loadavg_before": [round(v, 2) for v in load_before],
        "model_load_s": round(load_s, 2),
        "rss_before_load_mb": round(rss0, 1),
        "rss_after_load_mb": round(rss_loaded, 1),
        "rss_after_run_mb": round(rss_mb_any(), 1),
        "stream_s": round(dur, 1),
        "fast": {
            "rtf": round(wall / dur, 4),
            "cpu_pct_while_running": round(cpu_fast),
            "chunk_ms_mean": round(statistics.fmean(cs), 2),
            "chunk_ms_p95": round(cs[int(len(cs) * 0.95) - 1], 2),
            "chunk_ms_max": round(cs[-1], 2),
        },
        "realtime": {"seconds": round(wall_rt, 1), "cpu_pct_of_one_core": round(cpu_rt, 1), "late_chunks": late, "chunks": n_chunks},
        "synthetic_set": {
            "note": "合成語音、無麥克風：不是喚醒率",
            "keyword_utterances": sum(1 for m in marks if m["keyword_id"]),
            "reported": detected,
            "reported_per_keyword": {k: f"{v[0]}/{v[1]}" for k, v in sorted(per_kw.items())},
            "other_keyword_reported_instead": wrong,
            "negative_utterances": sum(1 for m in marks if not m["keyword_id"]),
            "triggers_on_negatives": false_triggers,
        },
        "delay_after_keyword_end_ms": None
        if not delays
        else {"n": len(delays), "min": round(min(delays)), "median": round(statistics.median(delays)), "max": round(max(delays)), "note": "音訊時間（100 ms 一塊的粒度）＋該塊的運算時間；不含麥克風與音訊驅動的緩衝"},
        "loadavg_after": [round(v, 2) for v in os.getloadavg()],
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
