#!/usr/bin/env python3
"""D2：量人臉偵測與整條處理（偵測＋雙目估距＋選人）在這台機器上的時間、CPU 與記憶體。

輸入是**合成畫面（mock）**：量的是運算量，不是偵測率。輸出一行 JSON（方便貼進驗證紀錄）。

    python tools/bench_detector.py [--frames 60] [--threads 0]

`--threads`：OpenCV 執行緒數（0＝OpenCV 預設）。CPU 用「行程 CPU 時間 ÷ 牆上時間」表示，
100%＝一顆核心滿載（Pi 4 有 4 顆）。
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402

from duck_perception.camera import StereoRig  # noqa: E402
from duck_perception.face_detect import YuNetDetector  # noqa: E402
from duck_perception.pipeline import FacePipeline  # noqa: E402
from duck_perception.synthetic import SyntheticPerson, SyntheticStereoSource  # noqa: E402


def rss_mb() -> float:
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return r / (1024 * 1024) if platform.system() == "Darwin" else r / 1024


def bench(width: int, height: int, frames: int, people: int) -> dict:
    rig = StereoRig.ar0144_nominal(width, height)
    ppl = [SyntheticPerson(0.15 * (i - (people - 1) / 2), 0.03 * i, 1.0 + 0.5 * i, seed=i) for i in range(people)]
    src = SyntheticStereoSource(rig=rig, people=ppl)
    det = YuNetDetector((width, height))
    pipe = FacePipeline(src, det)
    imgs = []
    for k in range(8):  # 先產生畫面，不把合成繪圖算進去
        src.set_pose(k * 0.1, 0.02 * k, 0.01 * k)
        imgs.append(src.read())
    for f in imgs[:3]:
        det.detect(f.left)  # 暖機
    t_det, n_det = [], 0
    c0, w0 = time.process_time(), time.perf_counter()
    for i in range(frames):
        f = imgs[i % len(imgs)]
        t = time.perf_counter()
        n_det += len(det.detect(f.left))
        t_det.append((time.perf_counter() - t) * 1000)
    cpu_det = (time.process_time() - c0) / (time.perf_counter() - w0) * 100
    t_pipe = []
    c0, w0 = time.process_time(), time.perf_counter()
    for i in range(frames):
        f = imgs[i % len(imgs)]
        t = time.perf_counter()
        pipe.process(f)
        t_pipe.append((time.perf_counter() - t) * 1000)
    cpu_pipe = (time.process_time() - c0) / (time.perf_counter() - w0) * 100

    def stats(xs):
        xs = sorted(xs)
        return {"mean_ms": round(statistics.fmean(xs), 1), "p50_ms": round(xs[len(xs) // 2], 1), "p95_ms": round(xs[int(len(xs) * 0.95) - 1], 1), "max_ms": round(xs[-1], 1)}

    return {
        "size": f"{width}x{height}",
        "people": people,
        "faces_per_frame": round(n_det / frames, 2),
        "detect": stats(t_det),
        "detect_cpu_pct_while_running": round(cpu_det),
        "pipeline_stereo": stats(t_pipe),
        "pipeline_cpu_pct_while_running": round(cpu_pipe),
        "max_fps_detect": round(1000 / statistics.fmean(t_det), 1),
        "cpu_pct_at_10hz": round(cpu_pipe * statistics.fmean(t_pipe) / 100.0, 1),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--threads", type=int, default=0)
    a = ap.parse_args()
    if a.threads > 0:
        cv2.setNumThreads(a.threads)
    out = {
        "mock_input": True,
        "machine": platform.machine(),
        "python": platform.python_version(),
        "opencv": cv2.__version__,
        "opencv_threads": cv2.getNumThreads(),
        "loadavg_before": [round(x, 2) for x in os.getloadavg()],
        "results": [bench(w, h, a.frames, p) for (w, h, p) in ((320, 180, 1), (640, 360, 1), (640, 360, 3), (1280, 720, 1))],
    }
    out["rss_max_mb"] = round(rss_mb(), 1)
    out["loadavg_after"] = [round(x, 2) for x in os.getloadavg()]
    print(json.dumps(out, ensure_ascii=False))
