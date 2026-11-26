"""把目前的 presence 告訴喚醒服務（`duck-voice`，`robot/audio`）：UDP `127.0.0.1:8794`。

    {"v":1,"kind":"presence","state":"listening"}

喚醒服務在 presence 不是 `idle` 時不偵測喚醒詞（對話中不重複喚醒）；它 30 秒沒收到更新就當作對話結束，
所以這裡除了狀態改變時送，也固定每幾秒重送一次。只送狀態名稱，沒有音訊、沒有對話內容。

UDP 送到沒有人在聽的 loopback 埠不會出錯：喚醒服務沒在跑時這裡等於沒做事，不影響 duckd。
"""
from __future__ import annotations

import json
import socket

DEFAULT_ADDR = ("127.0.0.1", 8794)
RESEND_S = 5.0  # 喚醒服務的逾時是 30 秒；掉幾個封包也還在範圍內


class PresenceRelay:
    def __init__(self, addr: tuple[str, int] = DEFAULT_ADDR, resend_s: float = RESEND_S, sock=None):
        if addr[0] not in ("127.0.0.1", "::1", "localhost"):
            raise ValueError("presence 只送本機 loopback")
        self.addr = addr
        self.resend_s = resend_s
        self._sock = sock or socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setblocking(False)
        self._state: str | None = None
        self._sent_at = float("-inf")
        self.sent = 0
        self.errors = 0

    def presence(self, state: str, now: float) -> bool:
        """每圈呼叫；只有狀態改變或該重送時才真的送。回傳這次有沒有送。"""
        if state == self._state and now - self._sent_at < self.resend_s:
            return False
        self._state, self._sent_at = state, now
        try:
            self._sock.sendto(json.dumps({"v": 1, "kind": "presence", "state": state}, separators=(",", ":")).encode(), self.addr)
        except OSError:
            self.errors += 1
            return False
        self.sent += 1
        return True

    def stats(self) -> dict:
        return {"addr": f"{self.addr[0]}:{self.addr[1]}", "state": self._state, "sent": self.sent, "errors": self.errors}

    def close(self) -> None:
        self._sock.close()
