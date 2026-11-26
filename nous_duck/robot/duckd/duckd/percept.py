"""感知的本機輸入：UDP `127.0.0.1:8793`，一個 datagram 一則 JSON（感知線 D 送過來）。

    {"v":1,"kind":"face"|"sound","bearing_yaw_rad":數字,"bearing_pitch_rad":數字,
     "distance_m":數字或null,"confidence":0到1,"t_ms":整數,"mock":布林}

face 的方位相對頭部鏡頭光軸（左為正、上為正）；sound 的方位相對身體正前方。
只有方位，沒有影像、聲音或身分。格式不對的 datagram 直接丟掉並計數。

`sound` 可以多帶 `"frame":"head"`：麥克風裝在頭上時方位是相對頭部，duckd 會加上當下的頭部 yaw 換成相對身體
（沒帶就是相對身體）。

另外接受「來源還活著」的訊息（2026-11-26 加的，A 線自己的兩個程式之間用）：

    {"v":1,"kind":"status","source":"sound"|"face","ok":布林,"mock":布林,"detail":"..."}

聲音來源只在偵測到語音時才送方位，安靜時 duckd 要靠這個知道麥克風還在不在。
"""
from __future__ import annotations

import json
import math
import socket
import threading
from dataclasses import dataclass

DEFAULT_ADDR = ("127.0.0.1", 8793)


@dataclass(frozen=True)
class Observation:
    kind: str
    yaw: float
    pitch: float
    distance_m: float | None
    confidence: float
    mock: bool
    received: float  # 本機單調時鐘（秒）
    frame: str = "body"  # sound 專用：方位相對 "body"（身體正前方）或 "head"（麥克風裝在頭上）


def parse(data: bytes, now: float) -> Observation | None:
    try:
        m = json.loads(data.decode("utf-8"))
        if m.get("v") != 1 or m.get("kind") not in ("face", "sound") or not isinstance(m.get("mock"), bool):
            return None
        yaw, pitch, conf = float(m["bearing_yaw_rad"]), float(m["bearing_pitch_rad"]), float(m["confidence"])
        dist = m.get("distance_m")
        dist = None if dist is None else float(dist)
        if not (math.isfinite(yaw) and math.isfinite(pitch) and 0.0 <= conf <= 1.0):
            return None
        if abs(yaw) > math.pi or abs(pitch) > math.pi / 2:
            return None
        frame = m.get("frame", "body")
        if frame not in ("body", "head"):
            return None
        return Observation(m["kind"], yaw, pitch, dist, conf, m["mock"], now, frame)
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return None


@dataclass(frozen=True)
class SourceStatus:
    source: str
    ok: bool
    mock: bool
    detail: str
    received: float


def parse_status(data: bytes, now: float) -> SourceStatus | None:
    try:
        m = json.loads(data.decode("utf-8"))
        if m.get("v") != 1 or m.get("kind") != "status" or m.get("source") not in ("face", "sound"):
            return None
        if not isinstance(m.get("ok"), bool) or not isinstance(m.get("mock"), bool):
            return None
        return SourceStatus(m["source"], m["ok"], m["mock"], str(m.get("detail", ""))[:80], now)
    except (ValueError, TypeError, UnicodeDecodeError, AttributeError):
        return None


class PerceptInput:
    def __init__(self, clock, addr: tuple[str, int] = DEFAULT_ADDR):
        self.clock = clock
        self.addr = addr
        self.latest: dict[str, Observation] = {}
        self.status: dict[str, SourceStatus] = {}
        self.dropped = 0
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def feed(self, data: bytes) -> None:
        now = self.clock()
        obs = parse(data, now)
        st = parse_status(data, now) if obs is None else None
        with self._lock:
            if obs is not None:
                self.latest[obs.kind] = obs
            elif st is not None:
                self.status[st.source] = st
            else:
                self.dropped += 1

    def source(self, kind: str, max_age_s: float = 3.0) -> SourceStatus | None:
        """這個來源最近有沒有報到（狀態訊息或方位都算）。"""
        with self._lock:
            st, obs = self.status.get(kind), self.latest.get(kind)
        now = self.clock()
        if st is not None and now - st.received <= max_age_s:
            return st
        if obs is not None and now - obs.received <= max_age_s:
            return SourceStatus(kind, True, obs.mock, "", obs.received)
        return None

    def get(self, kind: str, max_age_s: float) -> Observation | None:
        with self._lock:
            obs = self.latest.get(kind)
        if obs is None or self.clock() - obs.received > max_age_s:
            return None
        return obs

    def start(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(self.addr)  # 只綁 loopback
        sock.settimeout(0.5)
        self._sock = sock

        def loop() -> None:
            while self._sock is not None:
                try:
                    data, _ = sock.recvfrom(2048)
                except socket.timeout:
                    continue
                except OSError:
                    break
                self.feed(data)

        self._thread = threading.Thread(target=loop, name="duckd-percept", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        sock, self._sock = self._sock, None
        if sock:
            sock.close()
