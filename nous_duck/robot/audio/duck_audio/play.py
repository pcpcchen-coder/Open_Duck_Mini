"""播放檢查用的小工具（開發用）。

    python -m duck_audio.play --device null --sfx listen_on          # 送到 ALSA null 裝置
    python -m duck_audio.play --device speaker --sfx listen_on --silent-check     # speaker＝自動找喇叭

`--silent-check`：夜間驗證用。送出的是**全零的取樣**（長度與格式和真的音效相同），確認裝置開得起來、
格式被接受、寫入沒有錯誤；喇叭不會有內容可播。真的要聽，白天拿掉這個旗標（音量受本機上限限制）。
"""

from __future__ import annotations

import argparse
import json
import sys

import numpy as np

from .playback import AplaySink, DuckAudioOut, GateConfig, PlaybackGate
from .wavio import read_wav

SPEAKER = "speaker"  # 特別值：用 speaker.find_speaker() 自動找


def main() -> int:
    ap = argparse.ArgumentParser(description="鴨子播放路徑檢查")
    ap.add_argument("--device", default="null", help="ALSA 裝置；speaker＝自動找鴨子的喇叭；預設 null（不出聲）")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--sfx", help="音效名稱，或 all")
    g.add_argument("--wav", help="16-bit wav 檔（當成 duck_raw 播）")
    ap.add_argument("--volume", type=float, default=1.0, help="要求的音量 0～1（會被夾到本機上限）")
    ap.add_argument("--silent-check", action="store_true", help="送全零取樣（不出聲的路徑檢查）")
    a = ap.parse_args()
    if a.device == SPEAKER:
        from .speaker import find_speaker  # noqa: PLC0415

        a.device = find_speaker()

    gate = PlaybackGate(GateConfig())
    gate.request_volume(a.volume)
    out = DuckAudioOut(lambda: AplaySink(a.device), gate)
    results = []
    if a.wav:
        x, rate = read_wav(a.wav)
        if a.silent_check:
            x = np.zeros_like(x)
        results.append(("wav", out.play_raw(x, rate)))
    else:
        names = [e["name"] for e in out._load_manifest()["sounds"]] if a.sfx == "all" else [a.sfx]
        for n in names:
            if a.silent_check:
                entry = next(e for e in out._load_manifest()["sounds"] if e["name"] == n)
                x, rate = read_wav(out.sounds_dir / entry["file"])
                results.append((n, out.play_raw(np.zeros_like(x), rate)))
            else:
                results.append((n, out.play_sfx(n)))
    ok = True
    for name, r in results:
        ok &= r.status == "played"
        print(json.dumps({"name": name, "device": a.device, "silent_check": a.silent_check, "status": r.status, "reason": r.reason,
                          "frames": r.frames, "duration_s": round(r.duration_s, 3), "gain": r.gain, "peak": r.peak}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
