#!/usr/bin/env python3
"""下載感知用的第三方模型到 `robot/perception/models/`（不進版控），並核對 SHA-256。

只用標準函式庫。雜湊不符就刪檔並以非 0 結束，不留下未驗證的模型。

模型清單（來源與雜湊沿用 AIOS `prototype/ambient-shell/scripts/face-setup.mjs`，main `8eb53b2` 唯讀查閱）：

- YuNet 人臉偵測 `face_detection_yunet_2023mar.onnx`：OpenCV Zoo，**MIT**
  （OpenCV Zoo `models/face_detection_yunet/LICENSE`）。網址釘在 Hugging Face revision。

用法：

    python3 nous_duck/robot/perception/tools/fetch_models.py [--dest 資料夾]
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

MODELS = [
    {
        "name": "face_detection_yunet_2023mar.onnx",
        "url": "https://huggingface.co/opencv/face_detection_yunet/resolve/"
        "3cc26e7f1014a5ee5d74a42acee58bafc9d0a310/face_detection_yunet_2023mar.onnx",
        "sha256": "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
        "license": "MIT（OpenCV Zoo face_detection_yunet/LICENSE）",
    },
]

DEFAULT_DEST = Path(__file__).resolve().parents[1] / "models"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(dest: Path) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    for m in MODELS:
        out = dest / m["name"]
        if out.exists() and sha256_of(out) == m["sha256"]:
            print(f"已存在且雜湊相符：{out.name}")
            continue
        print(f"下載 {m['name']}（{m['license']}）")
        req = urllib.request.Request(m["url"], headers={"User-Agent": "fetch-models"})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
        got = hashlib.sha256(data).hexdigest()
        if got != m["sha256"]:
            print(f"SHA-256 不符：{m['name']} 期望 {m['sha256']}，得到 {got}", file=sys.stderr)
            return 1
        out.write_bytes(data)
        print(f"完成：{out}（{len(data)} bytes）")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    sys.exit(fetch(ap.parse_args().dest))
