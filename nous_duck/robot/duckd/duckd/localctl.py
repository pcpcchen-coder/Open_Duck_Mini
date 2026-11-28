"""本機控制介面：UNIX socket（只有同一個使用者能連），給在鴨子旁邊的人（或部署腳本）用。

這些操作**刻意不在 duck-link 上**：接手／釋放硬體、緊急停止、解除緊急停止，以及腿：
`engage-legs`、`posture`（`{"cmd": "posture", "target": "crouch"|"stand", "duration_s": 3}`）、`posture-stop`
（ADR-0020 草案；只有 `--legs` 啟動時有效）。
一行 JSON 請求、一行 JSON 回覆：`{"cmd": "engage"}` → `{"ok": true, ...}`。
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
from pathlib import Path

from .body import EngageError


SYSTEM_SOCKET = Path("/run/duckd/duckd.sock")  # systemd 服務（RuntimeDirectory=duckd）用的位置


def default_socket_path() -> Path:
    env = os.environ.get("DUCKD_SOCKET")
    if env:
        return Path(env)
    if SYSTEM_SOCKET.exists():
        return SYSTEM_SOCKET
    base = os.environ.get("XDG_RUNTIME_DIR") or str(Path.home() / ".cache" / "nous-duck")
    return Path(base) / "duckd.sock"


def handle(core, link, request: dict) -> dict:
    cmd = request.get("cmd")
    now = time.monotonic()
    if cmd == "status":
        with core.lock:
            s = core.state_fields()
            s.pop("capabilities", None)
            return {
                "ok": True,
                "connected": core.connected,
                "connects": link.connects if link else None,
                "engaged": core.engaged,
                "state": s,
                "stats": dict(core.stats),
                "tick_ms_max": round(link.tick_ms_max, 2) if link else None,
                "motion_latency_ms": list(getattr(core, "motion_latency_ms", [])),
                "eyes": core.eyes.stats() if core.eyes else None,
                "gestures_rejected": core.library.rejected,
                "can_express": core.eyes is not None,
                "settings": getattr(core, "settings_status", None),
                "wake": dict(getattr(core, "wake_stats", {})),
                "voice_relay": core.voice.stats() if getattr(core, "voice", None) else None,
                "posture": core.posture_status() if hasattr(core, "posture_status") else None,
            }
    if cmd == "express":
        # 本機預覽表情（設定頁的「在鴨子上預覽」）：最多 10 秒，之後回到 presence 決定的表情。
        # 這是站在鴨子旁邊的人在看樣子，不是 Nous 的要求，所以不套用「Nous 能叫哪些表情」的限制。
        if core.eyes is None:
            return {"ok": False, "error": "eyes renderer is not running"}
        name = request.get("name")
        if not isinstance(name, str) or not core.eyes.known(name):
            return {"ok": False, "error": f"unknown expression {name!r}"}
        try:
            seconds = min(10.0, max(0.5, float(request.get("duration_s", 5.0))))
        except (TypeError, ValueError):
            return {"ok": False, "error": "duration_s is not a number"}
        core.eyes.express(name, seconds)
        return {"ok": True, "expression": name, "seconds": seconds, "panel": core.eyes.panel_kind}
    try:
        if cmd == "engage":
            actual = core.engage(now)
            return {"ok": True, "head_rad": actual}
        if cmd == "release":
            started = core.begin_release(now)
            end = time.monotonic() + 10.0
            while started and core.engaged and time.monotonic() < end:
                time.sleep(0.05)
            return {"ok": not core.engaged, "released": started}
        if cmd == "engage-legs":
            return {"ok": True, **core.engage_legs(now)}
        if cmd == "posture":
            duration = request.get("duration_s")
            if duration is not None:
                try:
                    duration = float(duration)
                except (TypeError, ValueError):
                    return {"ok": False, "error": "duration_s is not a number"}
            return core.posture_command(str(request.get("target")), duration, now)
        if cmd == "posture-stop":
            return core.posture_stop(now, "local operator")
        if cmd == "estop":
            core.local_estop("local operator", now)
            return {"ok": True}
        if cmd == "clear-estop":
            return {"ok": True, "cleared": core.local_clear_estop()}
        if cmd == "reset-fallen":
            return {"ok": True, "reset": core.arbiter.reset_fallen_local()}
    except EngageError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": False, "error": f"unknown cmd {cmd!r}"}


class LocalControl:
    def __init__(self, core, link, path: Path | None = None):
        self.core, self.link = core, link
        self.path = Path(path) if path else default_socket_path()
        self._sock: socket.socket | None = None

    def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self.path.unlink()
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        old = os.umask(0o177)
        try:
            sock.bind(str(self.path))
        finally:
            os.umask(old)
        sock.listen(4)
        sock.settimeout(0.5)
        self._sock = sock
        threading.Thread(target=self._serve, name="duckd-ctl", daemon=True).start()

    def _serve(self) -> None:
        while self._sock is not None:
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._one, args=(conn,), daemon=True).start()

    def _one(self, conn: socket.socket) -> None:
        with conn:
            try:
                conn.settimeout(15.0)
                line = conn.makefile("r", encoding="utf-8").readline()
                reply = handle(self.core, self.link, json.loads(line))
            except Exception as exc:  # noqa: BLE001
                reply = {"ok": False, "error": repr(exc)}
            try:
                conn.sendall((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))
            except OSError:
                pass

    def stop(self) -> None:
        sock, self._sock = self._sock, None
        if sock:
            sock.close()
        try:
            self.path.unlink()
        except OSError:
            pass


def request(cmd: str, path: Path | None = None, timeout: float = 15.0, **fields) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(str(path or default_socket_path()))
        s.sendall((json.dumps({"cmd": cmd, **fields}) + "\n").encode("utf-8"))
        return json.loads(s.makefile("r", encoding="utf-8").readline())
