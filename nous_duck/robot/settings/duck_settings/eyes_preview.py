"""表情預覽圖：用 `duck_eyes` 真的渲染每個表情（和鴨子上畫的是同一份程式），縮小後轉成 PNG。

需要 numpy 與 `duck_eyes`。沒有的話回報原因，**不放假圖**。
預覽畫的是「鏡頭沒在串流」的狀態（現在鴨子上沒有鏡頭），所以沒有青色的鏡頭狀態環。
"""
from __future__ import annotations

import base64
import struct
import sys
import threading
import zlib
from pathlib import Path

from . import schema

PREVIEW_PX = 96  # 每隻眼睛縮成這個大小


def _ensure_duck_eyes() -> None:
    here = Path(__file__).resolve()
    for candidate in (here.parents[2] / "eyes", here.parents[1]):  # repo：robot/eyes；Pi：和 duck_settings 放一起
        if (candidate / "duck_eyes").is_dir() and str(candidate) not in sys.path:
            sys.path.append(str(candidate))


def encode_png(rgb) -> bytes:
    """uint8 H×W×3 → PNG（只用標準函式庫）。"""
    h, w = rgb.shape[:2]
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


def _shrink(img, np, size: int):
    """240×240 → size×size（區塊平均；240 要能被 size 整除，否則取最近鄰）。"""
    h = img.shape[0]
    if h % size == 0:
        k = h // size
        return img.reshape(size, k, size, k, 3).mean(axis=(1, 3)).round().astype(np.uint8)
    idx = (np.arange(size) * h / size).astype(int)
    return img[idx][:, idx]


class ExpressionPreviews:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict | None = None

    def get(self) -> dict:
        with self._lock:
            if self._cache is None:
                self._cache = self._render()
            return self._cache

    def _render(self) -> dict:
        try:
            _ensure_duck_eyes()
            import numpy as np  # noqa: PLC0415
            import duck_eyes  # noqa: PLC0415
            from duck_eyes.preview import snapshot  # noqa: PLC0415
        except ImportError as exc:
            return {"available": False, "reason": f"不能產生預覽圖：{exc}（需要 numpy 與 duck_eyes）", "expressions": []}
        device = duck_eyes.DeviceState(camera_streaming=False)
        gap = np.zeros((PREVIEW_PX, 8, 3), dtype=np.uint8)
        items = []
        for name, exp in duck_eyes.EXPRESSIONS.items():
            left, right = snapshot(name, device=device)
            pair = np.concatenate([_shrink(left, np, PREVIEW_PX), gap, _shrink(right, np, PREVIEW_PX)], axis=1)
            items.append({
                "id": name, "name": exp.name_zh, "sound": exp.sound,
                "sound_name": duck_eyes.SOUND_CUES.get(exp.sound) if exp.sound else None,
                "social": name in duck_eyes.NOUS_ALLOWED,
                "png": "data:image/png;base64," + base64.b64encode(encode_png(np.ascontiguousarray(pair))).decode("ascii"),
            })
        missing = sorted(set(schema.EXPRESSIONS) ^ set(duck_eyes.EXPRESSIONS))
        return {"available": True, "reason": "", "expressions": items, "mismatch": missing}
