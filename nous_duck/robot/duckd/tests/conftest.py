"""duckd 測試共用工具。全部不需要硬體：身體用 MockBody／模擬匯流排，對手用假 hub（都是 mock）。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from duckd.arbiter import SafetyArbiter  # noqa: E402
from duckd.body import MockBody  # noqa: E402
from duckd.core import Duckd  # noqa: E402
from duckd.gestures import GestureLibrary  # noqa: E402
from duckd.limits import Limits  # noqa: E402
from duckd.protocol import Protocol  # noqa: E402

PROTOCOL = Protocol()
REPO = ROOT.parents[2]  # repo 根目錄


class Harness:
    """核心＋假時鐘。`run(秒)` 以 20 ms 一圈推進，期間每 0.5 s 自動送 heartbeat（可關）。"""

    def __init__(self, core: Duckd, body):
        self.core, self.body, self.arbiter = core, body, core.arbiter
        self.t = 100.0
        self.sent: list[dict] = []
        self.heartbeats = True
        self._seq = 0
        self._next_hb = self.t
        self._rid = 0

    def _keep(self, msgs):
        for m in msgs:
            assert not PROTOCOL.errors(m), (m, PROTOCOL.errors(m))
        self.sent.extend(msgs)
        return msgs

    def open(self):
        return self._keep(self.core.on_open(self.t))

    def heartbeat(self):
        self._seq += 1
        return self.raw({"type": "heartbeat", "seq": self._seq})

    def raw(self, fields: dict, **over):
        msg = {"protocol_version": "0.1", "sent_at_ms": 1795600000000, **fields, **over}
        return self._keep(self.core.on_text(json.dumps(msg), self.t))

    def cmd(self, action: str, params: dict | None = None, ttl_ms: int = 3000, rid: str | None = None) -> dict:
        self._rid += 1
        rid = rid or f"req_{self._rid:08d}"
        fields = {"type": "command", "request_id": rid, "action": action, "ttl_ms": ttl_ms}
        if params is not None:
            fields["params"] = params
        out = self.raw(fields)
        acks = [m for m in out if m["type"] == "ack" and m["request_id"] == rid]
        assert len(acks) == 1, out
        return acks[0]

    def tick(self):
        return self._keep(self.core.tick(self.t))

    def run(self, seconds: float):
        out = []
        for _ in range(round(seconds / 0.02)):
            if self.heartbeats and self.t >= self._next_hb:
                out += self.heartbeat()
                self._next_hb = self.t + 0.5
            out += self.tick()
            self.t += 0.02
        return out

    def events(self, name: str | None = None):
        return [m for m in self.sent if m["type"] == "event" and (name is None or m["event"] == name)]

    def last_state(self):
        return [m for m in self.sent if m["type"] == "state"][-1]


def make_harness(*, limits: Limits | None = None, body=None, engage: bool = True, connect: bool = True, **core_kw) -> Harness:
    limits = limits or Limits()
    body = body or MockBody()
    arbiter = SafetyArbiter(limits, walk_supported=False, walk_unsupported_reason="feet switches not wired")
    core_kw.setdefault("allow_unverified_gestures", True)
    core = Duckd(PROTOCOL, body, arbiter, GestureLibrary(limits), **core_kw)
    h = Harness(core, body)
    if engage:
        core.engage(h.t)
    if connect:
        h.open()
        h.run(0.1)
    return h


@pytest.fixture
def h():
    return make_harness()
