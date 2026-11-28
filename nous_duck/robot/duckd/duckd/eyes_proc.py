"""眼睛放在自己的行程：渲染與 SPI 傳送不和 duckd 的 50 Hz 控制迴圈共用 GIL。

2026-11-28 實測：眼睛執行緒在 duckd 行程裡跑時，對話中控制迴圈 overrun 約 15 次／分鐘（只有虛擬面板時約 1.5），
見 `docs/validation/eyes-duckd-2026-11-28.md` §5。

- 父行程（duckd）：`EyesProcess` 和 `EyesOutput` 介面相同；表情、presence、狀態環的狀態都留在父行程
  （`expression` 讀回的仍是渲染端要畫的表情），每 50 ms 把一份快照送給子行程，不在父行程渲染。
- 子行程：打開 GC9A01（打不開就只寫 PNG）、照快照畫、送螢幕；每秒回報一次狀態。
- 子行程死掉或 3 秒沒有回報：`panel_kind` 變回 `virtual_png`、`hardware_error` 記原因，5 秒後重啟。
  子行程用 spawn 啟動（duckd 有很多執行緒，fork 不安全），父行程結束時子行程跟著結束。
"""
from __future__ import annotations

import logging
import multiprocessing as mp
import os
import threading
import time
from pathlib import Path

from .eyes_out import EyesOutput

log = logging.getLogger("duckd.eyes")

SNAPSHOT_PERIOD_S = 0.05
STATUS_PERIOD_S = 1.0
STALE_S = 3.0
RESTART_S = 5.0
CHILD_NICE = 5  # 和 Pi 上的 chromium 一樣


def _child_main(conn, panel_path, fps, hw_kwargs) -> None:  # pragma: no cover - 在子行程跑；測試從父行程觀察
    """子行程：只有渲染、傳送、回報。父行程那端關掉（duckd 結束）就跟著結束。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s duckd.eyes-proc %(message)s")
    import signal

    # systemd 停服務時整個 cgroup 都收到 SIGTERM：子行程不自己結束，等 duckd 叫它收尾（或管線斷了再走）
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    # 眼睛的優先權比 duckd 的控制迴圈低：CPU 搶不過來時先慢的是眼睛（11-28 實測：子行程 nice 0 時對話中仍約 10 次 overrun／分鐘）
    try:
        os.nice(CHILD_NICE)
    except OSError:
        pass
    hardware, error = None, None
    if hw_kwargs is not None:
        try:
            from ._paths import ensure_sibling_packages

            ensure_sibling_packages()
            from duck_eyes.gc9a01 import open_eyes

            hardware = open_eyes(**hw_kwargs)
        except Exception as exc:  # noqa: BLE001
            error = f"open failed: {exc}"[:150]
            logging.error("實體眼睛螢幕打不開（%s）；只寫虛擬面板", exc)
    eyes = EyesOutput(Path(panel_path) if panel_path else None, fps=fps, hardware=hardware)
    eyes.hardware_error = error
    eyes.start()
    next_status = 0.0
    try:
        while True:
            if conn.poll(0.1):
                try:
                    msg = conn.recv()
                except EOFError:
                    break
                if msg is None:
                    break
                eyes.apply_snapshot(msg)
            now = time.monotonic()
            if now >= next_status:
                next_status = now + STATUS_PERIOD_S
                try:
                    conn.send(("stats", eyes.stats()))
                except (BrokenPipeError, OSError):
                    break
    finally:
        eyes.stop()


class EyesProcess(EyesOutput):
    """`EyesOutput` 的狀態介面，渲染與螢幕在子行程。"""

    def __init__(self, panel_path: Path | None = None, fps: float = 15.0, seed: int = 0, hw_kwargs: dict | None = None, ctx=None):
        super().__init__(None, fps=fps, seed=seed)  # 父行程不寫 PNG、不開螢幕
        self._child_panel_path = str(panel_path) if panel_path else None
        self._hw_kwargs = hw_kwargs
        self._ctx = ctx or mp.get_context("spawn")
        self._proc = None
        self._conn = None
        self._child_stats: dict | None = None
        self._child_stats_at = -float("inf")
        self.restarts = 0
        self._proc_error: str | None = None
        self._mgr: threading.Thread | None = None
        self._mgr_stop = threading.Event()

    # ---- 父行程對外的狀態 ----
    @property
    def panel_kind(self) -> str:
        st = self._fresh_stats()
        return st.get("panel", "virtual_png") if st else "virtual_png"

    @property
    def hardware_error(self) -> str | None:  # type: ignore[override]
        if self._proc_error and not self._fresh_stats():
            return self._proc_error
        st = self._fresh_stats()
        return st.get("hardware_error") if st else self._proc_error

    @hardware_error.setter
    def hardware_error(self, value) -> None:  # EyesOutput.__init__ 會設 None
        self._proc_error = value

    def _fresh_stats(self) -> dict | None:
        if self._child_stats is not None and time.monotonic() - self._child_stats_at <= STALE_S:
            return self._child_stats
        return None

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "expression": self._current(),
                "device": self._device,
                "audio_level": self._audio_level,
                "gaze": self._gaze,
                "brightness": self.brightness,
                "fps": self.fps,
            }

    # ---- 子行程管理 ----
    def _spawn(self) -> None:
        parent, child = self._ctx.Pipe()
        proc = self._ctx.Process(
            target=_child_main, args=(child, self._child_panel_path, self.fps, self._hw_kwargs), name="duckd-eyes-proc", daemon=True
        )
        proc.start()
        child.close()
        self._proc, self._conn = proc, parent
        log.info("眼睛子行程啟動（pid %s）", proc.pid)

    def _reap(self, why: str) -> None:
        log.error("眼睛子行程%s；%s 秒後重啟", why, RESTART_S)
        self._proc_error = f"eyes process {why}"[:150]
        self._child_stats = None
        try:
            if self._conn is not None:
                self._conn.close()
        except OSError:
            pass
        if self._proc is not None and self._proc.is_alive():
            self._proc.terminate()
            self._proc.join(timeout=2.0)
        self._proc, self._conn = None, None

    def _manage(self) -> None:
        started = time.monotonic()
        dead_at = None
        while not self._mgr_stop.wait(SNAPSHOT_PERIOD_S):
            now = time.monotonic()
            if self._proc is None:
                if dead_at is not None and now - dead_at >= RESTART_S:
                    self.restarts += 1
                    self._spawn()
                    started, dead_at = now, None
                continue
            try:
                self._conn.send(self.snapshot())
                while self._conn.poll():
                    kind, payload = self._conn.recv()
                    if kind == "stats":
                        self._child_stats, self._child_stats_at = payload, now
            except (BrokenPipeError, EOFError, OSError) as exc:
                self._reap(f"pipe closed ({exc.__class__.__name__})")
                dead_at = now
                continue
            if not self._proc.is_alive():
                self._reap(f"exited (code {self._proc.exitcode})")
                dead_at = now
            elif now - max(started, self._child_stats_at) > STALE_S + 10.0:  # 開機要 import numpy，給寬一點
                self._reap("not reporting")
                dead_at = now

    def start(self) -> None:
        if self._mgr:
            return
        self._mgr_stop.clear()
        self._spawn()
        self._mgr = threading.Thread(target=self._manage, name="duckd-eyes-mgr", daemon=True)
        self._mgr.start()

    def stop(self) -> None:
        self._mgr_stop.set()
        if self._mgr:
            self._mgr.join(timeout=2.0)
            self._mgr = None
        if self._conn is not None:
            try:
                self._conn.send(None)  # 請子行程自己收尾（放開 SPI／GPIO）
            except OSError:
                pass
        if self._proc is not None:
            self._proc.join(timeout=5.0)
            if self._proc.is_alive():
                self._proc.terminate()
                self._proc.join(timeout=2.0)
        self._proc, self._conn = None, None

    def stats(self) -> dict:
        st = dict(self._fresh_stats() or {"panel": "virtual_png", "frames": 0})
        st["process"] = {
            "pid": self._proc.pid if self._proc is not None else None,
            "alive": bool(self._proc is not None and self._proc.is_alive()),
            "restarts": self.restarts,
            "stats_age_s": None if self._child_stats is None else round(time.monotonic() - self._child_stats_at, 2),
        }
        if self.hardware_error:
            st["hardware_error"] = self.hardware_error
        return st

    def render_once(self):  # 父行程不渲染
        raise RuntimeError("EyesProcess renders in the child process")
