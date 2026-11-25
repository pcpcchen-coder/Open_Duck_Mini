#!/usr/bin/env python3
"""D4：用**合成雙目影像**（已知真值）量臉部估距誤差，輸出 Markdown 表。

這是合成資料上的演算法檢查：臉是平面示意圖、影像已校正、內參與基線就是產生影像用的那一組。
真的鏡頭會多出校正殘差、焦距與基線誤差、臉的立體形狀、動態模糊；**表中數字不是實機精度**。

    python tools/stereo_error_table.py [--trials 30]
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from duck_perception.camera import StereoRig  # noqa: E402
from duck_perception.stereo_depth import depth_sigma_m, face_stereo_depth  # noqa: E402
from duck_perception.synthetic import SyntheticPerson, SyntheticStereoSource, TruthDetector  # noqa: E402


def run(width: int, height: int, trials: int, noise_sigma: float, det_noise_px: float) -> list[str]:
    rig = StereoRig.ar0144_nominal(width, height)
    rows = [
        f"#### {width}×{height}（f = {rig.left.fx:.1f} px，B = {rig.baseline_m * 1000:.0f} mm；影像雜訊 σ={noise_sigma}、偵測框雜訊 σ={det_noise_px} px；每個距離 {trials} 次）\n",
        "| 真實距離 Z | 真實視差 | 量到的次數 | 平均誤差 | 誤差標準差 | 最大絕對誤差 | 相對誤差（RMS） | 理論：1 px 視差的深度變化 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    rng = np.random.default_rng(0)
    for z in (0.4, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0):
        errs, fails = [], {}
        for k in range(trials):
            yaw, pitch = rng.uniform(-0.2, 0.2), rng.uniform(-0.08, 0.08)
            # 讓光軸深度剛好是 z
            rng_m = z / (math.cos(yaw) * math.cos(pitch))
            src = SyntheticStereoSource(rig=rig, people=[SyntheticPerson(yaw, pitch, rng_m, seed=k)], noise_sigma=noise_sigma, seed=k)
            f = src.read()
            dets = TruthDetector(src, noise_px=det_noise_px, seed=k).detect()
            if not dets:
                fails["out_of_view"] = fails.get("out_of_view", 0) + 1
                continue
            sd = face_stereo_depth(f.left, f.right, dets[0], rig)
            if sd.depth_m is None:
                fails[sd.reason] = fails.get(sd.reason, 0) + 1
                continue
            errs.append(sd.depth_m - f.truth[0].distance_m)
        step = depth_sigma_m(z, rig, 1.0) * 1000
        if errs:
            e = np.array(errs) * 1000
            rows.append(
                f"| {z} m | {rig.disparity_px(z):.1f} px | {len(errs)}/{trials} | {e.mean():+.0f} mm | {e.std():.0f} mm | {np.abs(e).max():.0f} mm"
                f" | {math.sqrt(float((e**2).mean())) / (z * 1000) * 100:.1f}% | {step:.0f} mm |"
            )
        else:
            rows.append(f"| {z} m | {rig.disparity_px(z):.1f} px | 0/{trials} | — | — | — | — | {step:.0f} mm |")
        if fails:
            rows[-1] += "  <!-- 量不到：" + "、".join(f"{k}×{v}" for k, v in fails.items()) + " -->"
    rows.append("")
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--trials", type=int, default=30)
    a = ap.parse_args()
    print("（合成雙目影像，mock；不是實機量測）\n")
    for w, h in ((640, 360), (1280, 720)):
        print("\n".join(run(w, h, a.trials, noise_sigma=3.0, det_noise_px=1.5)))
