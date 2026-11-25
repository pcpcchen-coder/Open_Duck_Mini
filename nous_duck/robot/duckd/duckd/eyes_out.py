"""眼睛輸出：把 `duck_eyes` 的渲染接進 duckd。

- 表情由 `express` 與 `presence` 決定；**狀態環只吃真實裝置狀態**（鏡頭是否串流、對話是否進行、
  是否需要幫忙），表情改不到它。
- 螢幕還沒到貨：只有「虛擬面板」——把兩眼畫面並排寫成 PNG（給人看的預覽），**不是**實體螢幕。
  GC9A01 的 SPI 驅動等螢幕到貨後再寫，這裡沒有假的驅動。
- 渲染在自己的執行緒，不占控制迴圈的時間。
"""
from __future__ import annotations

import os
import struct
import threading
import time
import zlib
from pathlib import Path

from ._paths import ensure_sibling_packages


def encode_png(rgb) -> bytes:
    """uint8 H×W×3 → PNG（只用標準函式庫）。"""
    h, w = rgb.shape[:2]
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 1)) + chunk(b"IEND", b"")


class EyesOutput:
    def __init__(self, panel_path: Path | None = None, fps: float = 5.0, seed: int = 0):
        ensure_sibling_packages()
        import duck_eyes  # 需要 numpy
        import numpy as np

        self._np = np
        self._de = duck_eyes
        self.panel_path = Path(panel_path) if panel_path else None
        self.fps = fps
        self._lock = threading.Lock()
        self._anim = duck_eyes.EyeAnimator("neutral", seed=seed, t0=0.0)
        self._t0 = time.monotonic()
        self._base = "neutral"  # presence 決定的表情
        self._override: tuple[str, float] | None = None  # express 指定的（表情, 到期時間）
        self._device = duck_eyes.DeviceState(camera_streaming=False)
        self._audio_level: float | None = None
        self._gaze: tuple[float, float] | None = None
        self.render_ms: list[float] = []
        self.frames = 0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # 面板種類：目前只有虛擬面板
    panel_kind = "virtual_png"

    @property
    def expressions(self) -> list[str]:
        return sorted(self._de.NOUS_ALLOWED)

    def can_request(self, name: str) -> bool:
        return self._de.nous_can_request(name)

    def known(self, name: str) -> bool:
        return name in self._de.EXPRESSIONS

    def set_base(self, name: str, camera_streaming: bool = False, night: bool = False) -> None:
        if name == "sleeping":
            name = self._de.resting_expression(self._de.DeviceState(camera_streaming=camera_streaming, night=True), charging=False)
        with self._lock:
            self._base = name

    def express(self, name: str, duration_s: float | None) -> None:
        with self._lock:
            until = float("inf") if duration_s is None else self._t() + duration_s
            self._override = (name, until)

    def clear_express(self) -> None:
        with self._lock:
            self._override = None

    def set_device(self, *, camera_streaming: bool, conversation_active: bool, needs_help: bool, night: bool = False) -> None:
        with self._lock:
            self._device = self._de.DeviceState(
                camera_streaming=camera_streaming, conversation_active=conversation_active, needs_help=needs_help, night=night
            )

    def set_inputs(self, audio_level: float | None, gaze: tuple[float, float] | None) -> None:
        with self._lock:
            self._audio_level, self._gaze = audio_level, gaze

    @property
    def expression(self) -> str:
        with self._lock:
            return self._current()

    def _t(self) -> float:
        return time.monotonic() - self._t0

    def _current(self) -> str:
        if self._override and self._t() >= self._override[1]:
            self._override = None
        return self._override[0] if self._override else self._base

    def render_once(self):
        """畫一幀，回傳（左眼, 右眼）兩張 240×240 RGB。"""
        with self._lock:
            t = self._t()
            self._anim.set_expression(self._current(), t)
            frame = self._anim.frame(t, self._de.Inputs(gaze=self._gaze, audio_level=self._audio_level))
            device = self._device
        t0 = time.perf_counter()
        left, right = self._de.render_frame(frame, device, t)
        self.render_ms.append((time.perf_counter() - t0) * 1000.0)
        if len(self.render_ms) > 200:
            del self.render_ms[:100]
        self.frames += 1
        return left, right

    def write_panel(self, left, right) -> None:
        if self.panel_path is None:
            return
        img = self._np.concatenate([left, self._np.zeros((left.shape[0], 16, 3), dtype=left.dtype), right], axis=1)
        tmp = self.panel_path.with_name(self.panel_path.name + ".tmp")
        self.panel_path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(encode_png(self._np.ascontiguousarray(img)))
        os.replace(tmp, self.panel_path)

    def start(self) -> None:
        if self._thread:
            return
        self._stop.clear()

        def loop() -> None:
            period = 1.0 / self.fps
            while not self._stop.wait(period):
                try:
                    self.write_panel(*self.render_once())
                except Exception:  # noqa: BLE001 眼睛壞了不能拖垮身體
                    import logging

                    logging.getLogger("duckd.eyes").exception("眼睛渲染失敗")
                    self._stop.wait(2.0)

        self._thread = threading.Thread(target=loop, name="duckd-eyes", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def stats(self) -> dict:
        ms = sorted(self.render_ms)
        if not ms:
            return {"frames": 0}
        return {"frames": self.frames, "render_ms_median": round(ms[len(ms) // 2], 1), "render_ms_max": round(ms[-1], 1)}
