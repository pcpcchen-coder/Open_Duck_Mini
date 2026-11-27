"""眼睛輸出：把 `duck_eyes` 的渲染接進 duckd。

- 表情由 `express` 與 `presence` 決定；**狀態環只吃真實裝置狀態**（鏡頭是否串流、對話是否進行、
  是否需要幫忙），表情改不到它。
- 兩種輸出，可以同時開：
  - 實體螢幕：兩片 GC9A01（`duck_eyes.gc9a01`，SPI0）。面板沒有回讀，只能確認「資料送出去了」。
    打不開（沒開 SPI、少套件、腳位被占）就記下原因、退回虛擬面板，不假裝有螢幕。
  - 虛擬面板：把兩眼畫面並排寫成 PNG（給人看的預覽），**不是**實體螢幕。有實體螢幕時每秒最多寫一次。
- 渲染在自己的執行緒，不占控制迴圈的時間。
"""
from __future__ import annotations

import logging
import os
import queue
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
    def __init__(self, panel_path: Path | None = None, fps: float = 5.0, seed: int = 0, hardware=None):
        """`hardware`：已初始化的實體螢幕（`duck_eyes.gc9a01.open_eyes()` 的結果，或同介面：show／close／last_sent）。"""
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
        self.send_ms: list[float] = []
        self.hardware = hardware
        self.hardware_error: str | None = None  # 實體螢幕打不開或送失敗的原因
        self._png_at = -float("inf")
        self.frames = 0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def panel_kind(self) -> str:
        """`gc9a01`＝實體螢幕在用；`virtual_png`＝只有虛擬面板（或實體螢幕打不開）。"""
        return "gc9a01" if self.hardware is not None else "virtual_png"

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
        if self.hardware is not None:  # 有實體螢幕：PNG 只是預覽，每秒最多一次
            now = time.monotonic()
            if now - self._png_at < 1.0:
                return
            self._png_at = now
        img = self._np.concatenate([left, self._np.zeros((left.shape[0], 16, 3), dtype=left.dtype), right], axis=1)
        tmp = self.panel_path.with_name(self.panel_path.name + ".tmp")
        self.panel_path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(encode_png(self._np.ascontiguousarray(img)))
        os.replace(tmp, self.panel_path)

    def show(self, left, right) -> None:
        """送到實體螢幕（有的話）並寫虛擬面板。"""
        if self.hardware is not None:
            t0 = time.perf_counter()
            self.hardware.show(left, right)
            self.send_ms.append((time.perf_counter() - t0) * 1000.0)
            if len(self.send_ms) > 200:
                del self.send_ms[:100]
        self.write_panel(left, right)

    def _drop_hardware(self, why: str) -> None:
        log = logging.getLogger("duckd.eyes")
        log.error("實體眼睛螢幕不能用，退回虛擬面板：%s", why)
        self.hardware_error = why[:150]
        hw, self.hardware = self.hardware, None
        try:
            hw.close()
        except Exception:  # noqa: BLE001
            log.exception("關閉實體螢幕失敗")

    def _send_one(self, left, right) -> None:
        try:
            self.show(left, right)
        except Exception as exc:  # noqa: BLE001 眼睛壞了不能拖垮身體
            if self.hardware is not None:
                self._drop_hardware(f"send failed: {exc}")
            else:
                logging.getLogger("duckd.eyes").exception("虛擬面板寫入失敗")
                self._stop.wait(2.0)

    def start(self) -> None:
        """渲染與傳送分兩個執行緒：送第 N 幀時同時畫第 N+1 幀（中間只放一幀，送不完渲染就等）。

        兩邊加起來的時間變成取較慢的那一邊。numpy 渲染時放開 GIL；spidev 的 ioctl 是否放開 GIL
        以 Pi 上實測為準（驗證紀錄）。
        """
        if self._thread:
            return
        self._stop.clear()
        self._queue: queue.Queue = queue.Queue(maxsize=1)

        def render_loop() -> None:
            period = 1.0 / self.fps
            next_t = time.monotonic()
            while True:
                next_t += period
                wait = next_t - time.monotonic()
                if wait < 0:  # 落後就不追，從現在重新起算
                    next_t, wait = time.monotonic(), 0.0
                if self._stop.wait(wait):
                    break
                try:
                    frame = self.render_once()
                except Exception:  # noqa: BLE001
                    logging.getLogger("duckd.eyes").exception("眼睛渲染失敗")
                    self._stop.wait(2.0)
                    continue
                while not self._stop.is_set():  # 上一幀還沒送走就等（不丟幀、不堆積）
                    try:
                        self._queue.put(frame, timeout=0.2)
                        break
                    except queue.Full:
                        continue

        def send_loop() -> None:
            while not self._stop.is_set():
                try:
                    frame = self._queue.get(timeout=0.2)
                except queue.Empty:
                    continue
                self._send_one(*frame)

        self._sender = threading.Thread(target=send_loop, name="duckd-eyes-send", daemon=True)
        self._sender.start()
        self._thread = threading.Thread(target=render_loop, name="duckd-eyes", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        if getattr(self, "_sender", None):
            self._sender.join(timeout=2.0)  # 送完手上那一幀才關螢幕
            self._sender = None
        if self.hardware is not None:
            try:
                self.hardware.close()  # 只放開 SPI／GPIO；BLK 沒有下拉，背光可能維持亮著（設計文件 §1.2）
            except Exception:  # noqa: BLE001
                logging.getLogger("duckd.eyes").exception("關閉實體螢幕失敗")

    def stats(self) -> dict:
        out: dict = {"panel": self.panel_kind, "frames": self.frames}
        if self.hardware_error:
            out["hardware_error"] = self.hardware_error
        ms = sorted(self.render_ms)
        if ms:
            out.update(render_ms_median=round(ms[len(ms) // 2], 1), render_ms_max=round(ms[-1], 1))
        sm = sorted(self.send_ms)
        if sm:
            out.update(send_ms_median=round(sm[len(sm) // 2], 1), send_ms_max=round(sm[-1], 1))
        hw = self.hardware
        if hw is not None and getattr(hw, "frames", 0):
            out["px_per_frame"] = round(hw.pixels_sent / hw.frames)  # 兩眼合計
            out["blits_per_frame"] = round(getattr(hw, "blits", 0) / hw.frames, 1)
        last = getattr(self.hardware, "last_sent", None)
        if last is not None:
            out["last_sent_age_s"] = round(time.monotonic() - last, 2)  # 渲染心跳（ADR-0013 §2.3）
        return out
