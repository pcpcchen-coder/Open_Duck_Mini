#!/usr/bin/env python3
"""產生**合成語音 fixture**（不是真人錄音）：變聲試聽（D6）與喚醒詞運算量測（D7）用。

語音由 MeloTTS zh_en（MIT，經 sherpa-onnx 執行）在開發機上合成，只有一個合成聲音。
句子不含任何人名、房間名或家裡的資訊。產生的 wav 進版控，檔名與 `fixtures/manifest.json` 都標明是合成的。

因為只有一個合成聲音、沒有麥克風、沒有房間聲學，這些檔案**不能**用來宣稱喚醒率或誤喚醒率。

    python tools/fetch_models.py tts-melo
    python tools/make_speech_fixture.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from duck_audio.wavio import resample, write_wav  # noqa: E402

MELO = ROOT / "models" / "vits-melo-tts-zh_en"
OUT = ROOT / "fixtures"

#: 變聲試聽用的句子（24 kHz：與即時語音模型常見的輸出取樣率相同）
VOICE = {"speech_zh": "你好，我是鴨子。今天天氣很好，我們一起去客廳看看吧。"}

#: 喚醒詞候選（**使用者還沒決定喚醒詞**；這些只是拿來量運算量的例子）
KEYWORDS = {
    "hei_yazi": "嘿鴨子",
    "hey_duck": "Hey Duck",
    "xiaoya_xiaoya": "小鴨小鴨",
}
#: 不含喚醒詞的句子（含幾句發音接近的，用來看會不會亂觸發；樣本太少，不能算誤喚醒率）
NEGATIVES = {
    "neg_weather": "今天天氣很好，我們去散步吧。",
    "neg_black_shoes": "黑色的鞋子放在架子上。",
    "neg_duck_pond": "鴨子在池塘裡游泳。",
    "neg_hey_doug": "Hey Doug, the dock is over there.",
    "neg_time": "現在幾點了？",
}
SPEEDS = (0.9, 1.0, 1.15)


def trim(x: np.ndarray, rate: int, pad_s: float = 0.05) -> np.ndarray:
    """去掉頭尾的靜音（留 pad_s），讓「關鍵詞結束時間」＝檔案結尾前 pad_s。"""
    thr = 0.02 * float(np.max(np.abs(x)))
    idx = np.nonzero(np.abs(x) > thr)[0]
    pad = int(pad_s * rate)
    return x[max(0, idx[0] - pad) : idx[-1] + pad]


def main() -> int:
    import sherpa_onnx

    if not (MELO / "model.onnx").exists():
        print("找不到 MeloTTS；先執行 tools/fetch_models.py tts-melo", file=sys.stderr)
        return 1
    cfg = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(model=str(MELO / "model.onnx"), lexicon=str(MELO / "lexicon.txt"), tokens=str(MELO / "tokens.txt")),
            num_threads=4,
        ),
        rule_fsts=f"{MELO / 'date.fst'},{MELO / 'number.fst'}",
    )
    tts = sherpa_onnx.OfflineTts(cfg)
    OUT.mkdir(exist_ok=True)
    (OUT / "kws").mkdir(exist_ok=True)
    entries = []

    def synth(text: str, speed: float, rate_out: int, path: Path, role: str, key: str) -> None:
        a = tts.generate(text, sid=0, speed=speed)
        x = trim(np.asarray(a.samples, dtype=np.float32), a.sample_rate)
        x = resample(x, a.sample_rate, rate_out)
        x = 0.5 * x / float(np.max(np.abs(x)))
        write_wav(path, x, rate_out)
        entries.append(
            {
                "file": str(path.relative_to(OUT)),
                "role": role,
                "key": key,
                "text": text,
                "speed": speed,
                "rate_hz": rate_out,
                "duration_s": round(len(x) / rate_out, 3),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )

    for key, text in VOICE.items():
        synth(text, 1.0, 24000, OUT / f"{key}_synthetic_fixture.wav", "voice", key)
    for key, text in KEYWORDS.items():
        for sp in SPEEDS:
            synth(text, sp, 16000, OUT / "kws" / f"{key}_x{sp:.2f}_synthetic.wav", "keyword", key)
    for key, text in NEGATIVES.items():
        synth(text, 1.0, 16000, OUT / "kws" / f"{key}_synthetic.wav", "negative", key)
    manifest = {
        "comment": "合成語音 fixture（MeloTTS zh_en，MIT；經 sherpa-onnx 合成）。不是真人錄音，不含任何人名或家裡的資訊。只有一個合成聲音：不能用來宣稱喚醒率。",
        "synthetic": True,
        "generator": "python tools/make_speech_fixture.py",
        "tts_model": "vits-melo-tts-zh_en（sherpa-onnx tts-models；MeloTTS，MIT）",
        "files": entries,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    total = sum((OUT / e["file"]).stat().st_size for e in entries)
    print(f"產生 {len(entries)} 個檔案，共 {total / 1024:.0f} KB → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
