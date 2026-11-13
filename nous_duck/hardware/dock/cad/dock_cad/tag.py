"""充電座的 AprilTag（tag36h11）：產生可列印的 SVG（實際尺寸，單位 mm）。

標籤碼表取自 OpenCV 內建的 `DICT_APRILTAG_36h11`（與 AprilRobotics apriltag 函式庫的 tag36h11 相同）。
"""

from __future__ import annotations

import numpy as np

from . import params as P


def tag_bits(tag_id: int = P.TAG_ID) -> np.ndarray:
    """回傳 10×10 的格子（1 = 白、0 = 黑），含最外圈白邊與內圈黑框。"""
    import cv2

    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    # 8×8：黑框＋6×6 資料位元
    img = cv2.aruco.generateImageMarker(dictionary, tag_id, 8, borderBits=1)
    inner = (img > 127).astype(np.uint8)
    full = np.ones((10, 10), dtype=np.uint8)
    full[1:9, 1:9] = inner
    return full


def tag_svg(tag_id: int = P.TAG_ID, black_size_mm: float = P.TAG_BLACK_SIZE) -> str:
    bits = tag_bits(tag_id)
    cell = black_size_mm / 8
    outer = cell * 10
    margin = 10.0  # 裁切線外留白
    page = outer + 2 * margin
    rects = []
    for r in range(10):
        for c in range(10):
            if bits[r, c] == 0:
                x, y = margin + c * cell, margin + r * cell
                rects.append(f'<rect x="{x:.3f}" y="{y:.3f}" width="{cell:.3f}" height="{cell:.3f}"/>')
    label = f"{P.TAG_FAMILY} id {tag_id} - black {black_size_mm:g} mm - print at 100% (no scaling)"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{page:.1f}mm" height="{page + 8:.1f}mm" '
        f'viewBox="0 0 {page:.3f} {page + 8:.3f}">\n'
        f'<rect x="0" y="0" width="{page:.3f}" height="{page + 8:.3f}" fill="white"/>\n'
        f'<rect x="{margin:.3f}" y="{margin:.3f}" width="{outer:.3f}" height="{outer:.3f}" fill="none" '
        f'stroke="#bbb" stroke-width="0.2" stroke-dasharray="2 2"/>\n'
        f'<g fill="black" shape-rendering="crispEdges">\n' + "\n".join(rects) + "\n</g>\n"
        f'<text x="{margin:.3f}" y="{page + 4:.3f}" font-family="sans-serif" font-size="3.2" fill="#555">{label}</text>\n'
        "</svg>\n"
    )


def detect_id(bits: np.ndarray, px_per_cell: int = 20) -> list[int]:
    """把格子放大成影像，用 OpenCV 的 AprilTag 偵測器讀回 ID（自我檢查用）。"""
    import cv2

    img = np.kron(bits, np.ones((px_per_cell, px_per_cell), dtype=np.uint8)) * 255
    img = np.pad(img, px_per_cell * 2, constant_values=255).astype(np.uint8)
    detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11))
    _, ids, _ = detector.detectMarkers(img)
    return [] if ids is None else [int(i) for i in ids.flatten()]
