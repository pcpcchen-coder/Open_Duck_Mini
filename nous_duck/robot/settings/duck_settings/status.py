"""系統狀態（唯讀）：服務有沒有在跑、各服務實際套用的值、duckd 的狀態、Pi 的溫度與負載。

這裡**只讀**：不啟動、不停止、不重啟任何服務，不碰舵機匯流排。讀不到就照實回報讀不到。
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any

from . import schema
from .reader import View, read_applied

SERVICES = (
    ("duckd", "duckd（頭部、動作、眼睛、duck-link）"),
    ("duck-doa", "duck-doa（聲源方位）"),
    ("duck-voice", "duck-voice（喚醒詞、收音、喇叭回話）"),
    ("duck-console", "duck-console（舵機控制台）"),
    ("duck-settings", "duck-settings（這個設定頁）"),
)
DUCKD_SOCKETS = (Path("/run/duckd/duckd.sock"),)

#: 不在設定頁上的東西（ADR-0019 §2.6）。頁面的「系統狀態」會列出來，讓人知道去哪裡看。
NEVER_HERE = (
    "緊急停止與解除：只在鴨子本機（duckd-ctl estop／clear-estop）或舵機控制台",
    "過熱、低電壓、跌倒、通訊中斷的門檻與保護：寫在程式裡（duckd/limits.py、舵機控制台），不能關、不能放寬",
    "頭部角度的機構上限、角速度硬上限（90°/s）：寫在 duckd/limits.py",
    "腿的任何設定、扭力、kp、零點偏移：舵機控制台（要人在場）",
    "接手／釋放舵機匯流排：duckd-ctl engage／release",
    "隱私的固定規則（原始影像與未喚醒音訊不寫檔、不外傳；鏡頭開著一定有提示）：沒有開關",
)


def pid_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def service_states(runner=None) -> dict[str, dict]:
    """systemd 服務狀態。不是 systemd 的環境（例如 Mac 上開發）回 `unknown`。"""
    out: dict[str, dict] = {}
    have = shutil.which("systemctl") is not None
    for unit, label in SERVICES:
        state = "unknown"
        if runner is not None:
            state = runner(unit)
        elif have:
            try:
                r = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True, timeout=2)
                state = (r.stdout.strip() or "unknown").splitlines()[0]
            except (OSError, subprocess.SubprocessError):
                state = "unknown"
        out[unit] = {"label": label, "state": state}
    return out


def duckd_request(request: dict, sockets=None, timeout: float = 2.0) -> dict | None:
    """問 duckd 的本機控制介面（UNIX socket）。連不上回 None。"""
    env = os.environ.get("DUCKD_SOCKET")
    candidates = [Path(env)] if env else []
    candidates += list(sockets if sockets is not None else DUCKD_SOCKETS)
    candidates.append(Path(os.environ.get("XDG_RUNTIME_DIR") or str(Path.home() / ".cache" / "nous-duck")) / "duckd.sock")
    for path in candidates:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.connect(str(path))
                s.sendall((json.dumps(request) + "\n").encode("utf-8"))
                line = s.makefile("r", encoding="utf-8").readline()
            reply = json.loads(line)
            return reply if isinstance(reply, dict) else None
        except (OSError, ValueError):
            continue
    return None


def duckd_summary(sockets=None) -> dict:
    reply = duckd_request({"cmd": "status"}, sockets)
    if not reply or not reply.get("ok"):
        return {"reachable": False}
    st = reply.get("state") or {}
    return {
        "reachable": True, "engaged": bool(reply.get("engaged")), "hub_connected": bool(reply.get("connected")),
        "mode": st.get("mode"), "mock": bool(st.get("mock")), "presence": st.get("presence"), "tracking": st.get("tracking"),
        "expression": st.get("expression"), "faults": st.get("faults") or [], "has_eyes": reply.get("eyes") is not None,
        "can_preview_expression": bool(reply.get("can_express")), "settings": reply.get("settings"),
    }


def pi_summary() -> dict:
    out: dict = {"hostname": socket.gethostname()}
    try:
        out["cpu_temp_c"] = round(int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000.0, 1)
    except (OSError, ValueError):
        out["cpu_temp_c"] = None
    try:
        out["load1"] = round(os.getloadavg()[0], 2)
    except OSError:
        out["load1"] = None
    return out


def effects(view: View, directory: Path, services: dict[str, dict]) -> dict[str, dict]:
    """每一項設定「生效了沒」。依各服務自己回報的值判斷，不是用猜的。"""
    reports: dict[str, tuple[dict | None, bool]] = {}
    for unit in {s.consumer for s in schema.SETTINGS if s.consumer}:
        rep = read_applied(directory, unit)
        reports[unit] = (rep, bool(rep) and pid_alive(rep.get("pid")))
    out: dict[str, dict] = {}
    for s in schema.SETTINGS:
        if not s.consumer:
            out[s.key] = {"state": "none", "label": schema.STATUS_LABEL[s.status]}
            continue
        rep, alive = reports[s.consumer]
        active = services.get(s.consumer, {}).get("state") == "active"
        if not alive:
            if active:
                out[s.key] = {"state": "not_reading", "label": f"{s.consumer} 在跑，但沒有回報它用的設定（還是舊版程式）"}
            else:
                out[s.key] = {"state": "service_down", "label": f"{s.consumer} 沒在跑；下次啟動時會用這個值"}
            continue
        if s.key not in rep["values"]:
            out[s.key] = {"state": "not_reading", "label": f"{s.consumer} 沒有回報這一項（程式版本比較舊）"}
            continue
        running = rep["values"][s.key]
        if running is None:
            # 服務在跑、有回報這一項，但套用失敗（例如找不到喇叭）：照實說原因，不寫「已生效」
            why = str(rep.get("note") or "沒有說明原因")
            out[s.key] = {"state": "failed", "label": f"{s.consumer} 套用失敗：{why}"[:200]}
            continue
        shown = f"{running:g}" if isinstance(running, float) else ("開" if running is True else "關" if running is False else str(running))
        why_idle = (rep.get("inactive") or {}).get(s.key) if isinstance(rep.get("inactive"), dict) else None
        if running == view.values[s.key] and why_idle:
            # 值讀到了，但現在不會有效果（例如頭部沒有出力）：不寫「已生效」，照實說原因
            out[s.key] = {"state": "inactive", "label": f"已讀到，但現在不會動：{why_idle}"[:200], "running": running}
        elif running == view.values[s.key]:
            out[s.key] = {"state": "applied", "label": "已生效", "running": running}
        elif s.apply == "restart":
            out[s.key] = {"state": "restart_needed", "label": f"要重啟 {s.consumer} 才生效（現在用的是 {shown}）", "running": running}
        else:
            out[s.key] = {"state": "pending", "label": f"等 {s.consumer} 套用（現在用的是 {shown}）", "running": running}
    return out
