"""送進 GC9A01 之前的資料處理（硬體驅動在 `gc9a01.py`）。

GC9A01 吃 RGB565、高位元組在前。局部更新只送有變動的矩形，SPI 頻寬才夠（設計文件 §3.4）。
"""

from __future__ import annotations

import numpy as np


def to_rgb565(img: np.ndarray) -> bytes:
    """uint8 H×W×3 → RGB565 big-endian bytes。"""
    if img.dtype != np.uint8 or img.ndim != 3 or img.shape[2] != 3:
        raise ValueError("expect uint8 HxWx3")
    r = img[..., 0].astype(np.uint16) >> 3
    g = img[..., 1].astype(np.uint16) >> 2
    b = img[..., 2].astype(np.uint16) >> 3
    v = (r << 11) | (g << 5) | b
    return v.astype(">u2").tobytes()


def dirty_rect(prev: np.ndarray | None, cur: np.ndarray) -> tuple[int, int, int, int] | None:
    """回傳有變動的最小矩形 (x0, y0, x1, y1)，含頭不含尾；沒變動回傳 None；沒有上一幀回傳整個畫面。"""
    h, w = cur.shape[:2]
    if prev is None:
        return (0, 0, w, h)
    diff = np.any(prev != cur, axis=2)
    if not diff.any():
        return None
    ys = np.flatnonzero(diff.any(axis=1))
    xs = np.flatnonzero(diff.any(axis=0))
    return (int(xs[0]), int(ys[0]), int(xs[-1]) + 1, int(ys[-1]) + 1)


def dirty_spans(prev: np.ndarray | None, cur: np.ndarray, tile: int = 24) -> list[tuple[int, int, int, int]]:
    """把畫面切成 tile×tile 的格子，回傳有變動的區塊清單 (x0, y0, x1, y1)。

    同一列裡相鄰的變動格子合併成一塊。和 `dirty_rect` 的單一外接矩形比，眨眼（上下眼皮）或
    狀態環（一圈細環）這類分散的變化送的像素少很多；代價是每塊多幾個指令。沒有上一幀回傳整個畫面。
    """
    h, w = cur.shape[:2]
    if prev is None:
        return [(0, 0, w, h)]
    diff = np.any(prev != cur, axis=2)
    ny, nx = -(-h // tile), -(-w // tile)
    pad = np.zeros((ny * tile, nx * tile), bool)
    pad[:h, :w] = diff
    cells = pad.reshape(ny, tile, nx, tile).any(axis=(1, 3))
    spans = []
    for j in range(ny):
        row = cells[j]
        i = 0
        while i < nx:
            if not row[i]:
                i += 1
                continue
            k = i
            while k < nx and row[k]:
                k += 1
            spans.append((i * tile, j * tile, min(w, k * tile), min(h, (j + 1) * tile)))
            i = k
    return spans


def dirty_runs(
    prev: np.ndarray | None, cur: np.ndarray, band: int = 8, blit_cost_px: int = 400
) -> list[tuple[int, int, int, int]]:
    """比 `dirty_spans` 更貼的局部更新：每 `band` 列一條，條內只取真的有變的欄，回傳 (x0, y0, x1, y1)。

    同一條裡兩段變動中間的空隙，如果「多送空隙的像素」比「多一次 blit 的指令開銷」便宜就合併。
    `blit_cost_px`＝一次 blit（CASET＋RASET＋RAMWR，DC 切換 6 次）的開銷換算成像素；預設值是估計，
    要在 Pi 上量。狀態環這種細環，每條只送左右兩小段，不會像 24×24 格子那樣整格重送。
    沒有上一幀回傳整個畫面。
    """
    h, w = cur.shape[:2]
    if prev is None:
        return [(0, 0, w, h)]
    diff = np.any(prev != cur, axis=2)
    rows_any = diff.any(axis=1)
    out = []
    for y0 in range(0, h, band):
        y1 = min(h, y0 + band)
        if not rows_any[y0:y1].any():
            continue
        cols = np.flatnonzero(diff[y0:y1].any(axis=0))
        bh = y1 - y0
        # 找連續段：相鄰欄號差 > 1 的地方就是斷點
        breaks = np.flatnonzero(np.diff(cols) > 1)
        starts = np.concatenate(([cols[0]], cols[breaks + 1]))
        ends = np.concatenate((cols[breaks], [cols[-1]])) + 1
        sx, ex = int(starts[0]), int(ends[0])
        for s, e in zip(starts[1:], ends[1:]):
            if (int(s) - ex) * bh <= blit_cost_px:
                ex = int(e)
            else:
                out.append((sx, y0, ex, y1))
                sx, ex = int(s), int(e)
        out.append((sx, y0, ex, y1))
    return out
