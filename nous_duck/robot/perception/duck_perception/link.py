"""感知 → duckd 的本機介面（與 A 線約定）：UDP `127.0.0.1:8793`，一個 datagram 一則 JSON。

    {"v":1,"kind":"face"|"sound","bearing_yaw_rad":數字,"bearing_pitch_rad":數字,
     "distance_m":數字或null,"confidence":0到1,"t_ms":整數,"mock":布林}

- `face`：方位相對**頭部鏡頭光軸**，左為正、上為正。
- `sound`：方位相對**身體正前方**。
- 只送方位與距離，**不送影像、特徵或身分**。
- 只送到 loopback；其他位址直接拒絕（原始感知結果不離開這片板子）。
- UDP 不保證送達：這是「最新觀測」串流，掉了就等下一則；接收端要自己看 `t_ms` 判斷新舊。
"""

from __future__ import annotations

import ipaddress
import json
import math
import socket
from typing import Any

PROTOCOL_VERSION = 1
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8793
KINDS = ("face", "sound")
_KEYS = {"v", "kind", "bearing_yaw_rad", "bearing_pitch_rad", "distance_m", "confidence", "t_ms", "mock"}


def encode_target(
    kind: str,
    bearing_yaw_rad: float,
    bearing_pitch_rad: float,
    distance_m: float | None,
    confidence: float,
    t_ms: int,
    mock: bool,
) -> bytes:
    if kind not in KINDS:
        raise ValueError(f"kind 必須是 {KINDS}")
    for name, x in (("bearing_yaw_rad", bearing_yaw_rad), ("bearing_pitch_rad", bearing_pitch_rad), ("confidence", confidence)):
        if not isinstance(x, (int, float)) or not math.isfinite(x):
            raise ValueError(f"{name} 必須是有限數字")
    if distance_m is not None and not (isinstance(distance_m, (int, float)) and math.isfinite(distance_m) and distance_m > 0):
        raise ValueError("distance_m 必須是正數或 None")
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence 必須在 0～1")
    if not isinstance(mock, bool):
        raise ValueError("mock 必須是布林")
    msg = {
        "v": PROTOCOL_VERSION,
        "kind": kind,
        "bearing_yaw_rad": round(float(bearing_yaw_rad), 5),
        "bearing_pitch_rad": round(float(bearing_pitch_rad), 5),
        "distance_m": None if distance_m is None else round(float(distance_m), 3),
        "confidence": round(float(confidence), 3),
        "t_ms": int(t_ms),
        "mock": mock,
    }
    return json.dumps(msg, separators=(",", ":")).encode("utf-8")


def decode_target(data: bytes) -> dict[str, Any]:
    """解析並檢查一則訊息（給測試與接收端用）；格式不對丟 ValueError。"""
    msg = json.loads(data.decode("utf-8"))
    if not isinstance(msg, dict) or set(msg) != _KEYS:
        raise ValueError("欄位不符")
    if msg["v"] != PROTOCOL_VERSION:
        raise ValueError("版本不符")
    # 用 encode 的檢查再跑一次
    encode_target(msg["kind"], msg["bearing_yaw_rad"], msg["bearing_pitch_rad"], msg["distance_m"], msg["confidence"], msg["t_ms"], msg["mock"])
    return msg


class UdpTargetSender:
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        if not ipaddress.ip_address(host).is_loopback:
            raise ValueError("感知結果只能送到 loopback")
        self.addr = (host, port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sent = 0
        self.errors = 0

    def send(self, kind: str, yaw: float, pitch: float, distance_m: float | None, confidence: float, t_ms: int, mock: bool) -> bool:
        """送出一則；沒有人在聽（ICMP 拒絕）等錯誤回傳 False，不丟例外、不重送。"""
        data = encode_target(kind, yaw, pitch, distance_m, confidence, t_ms, mock)
        try:
            self._sock.sendto(data, self.addr)
        except OSError:
            self.errors += 1
            return False
        self.sent += 1
        return True

    def close(self) -> None:
        self._sock.close()
