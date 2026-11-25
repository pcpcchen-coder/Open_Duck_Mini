"""假的 duck-link hub（**mock**）：只給 duckd 的測試與開發用，不是 Nous，也不是 B 線的 hub。

- WebSocket server，聽 `127.0.0.1:8791/duck-link`；送 `hello`（`role: nous`、`mock: true`）、每 500 ms 一次 heartbeat。
- 用同一份 schema 驗證鴨子送來的每一則訊息；不合格的記在 `schema_errors`。
- `python -m duckd.mock_hub` 會開一個互動用的 hub；`--e2e` 跑一段固定的頭部端到端流程並輸出量測（JSON）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
import uuid

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from .protocol import PROTOCOL_VERSION, Protocol

SOFTWARE = "duckd-mock-hub 0.1.0"


class MockHub:
    mock = True

    def __init__(self, host: str = "127.0.0.1", port: int = 8791, heartbeat_s: float = 0.5, protocol: Protocol | None = None):
        self.host, self.port, self.heartbeat_s = host, port, heartbeat_s
        self.protocol = protocol or Protocol()
        self.received: list[tuple[float, dict]] = []
        self.schema_errors: list[str] = []
        self.rtt_ms: list[float] = []
        self.connections = 0
        self.heartbeat_paused = False
        self.ws = None
        self._server = None
        self._seq = 0
        self._hb_sent: dict[int, float] = {}
        self._waiters: list[tuple[callable, asyncio.Future]] = []
        self.connected = asyncio.Event()

    def _msg(self, type_: str, **fields) -> str:
        m = {"protocol_version": PROTOCOL_VERSION, "type": type_, "sent_at_ms": int(time.time() * 1000), **fields}
        errs = self.protocol.errors(m)
        assert not errs, errs
        return json.dumps(m)

    async def start(self) -> None:
        self._server = await serve(self._handler, self.host, self.port, ping_interval=None, compression=None)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handler(self, ws) -> None:
        if ws.request.path != "/duck-link":
            await ws.close(1008, "wrong path")
            return
        self.ws = ws
        self.connections += 1
        await ws.send(self._msg("hello", role="nous", software=SOFTWARE, mock=True))
        self.connected.set()
        hb = asyncio.create_task(self._heartbeats(ws))
        try:
            async for text in ws:
                now = time.monotonic()
                try:
                    msg = json.loads(text)
                except ValueError:
                    self.schema_errors.append("not json")
                    continue
                errs = self.protocol.errors(msg)
                if errs:
                    self.schema_errors.append(f"{msg.get('type')}: {errs[0]}")
                self.received.append((now, msg))
                if msg.get("type") == "heartbeat" and "echo_of" in msg:
                    sent = self._hb_sent.pop(msg["echo_of"], None)
                    if sent is not None:
                        self.rtt_ms.append((now - sent) * 1000.0)
                for pred, fut in list(self._waiters):
                    if not fut.done() and pred(msg):
                        fut.set_result(msg)
        except ConnectionClosed:
            pass
        finally:
            hb.cancel()
            self.connected.clear()
            if self.ws is ws:
                self.ws = None

    async def _heartbeats(self, ws) -> None:
        try:
            while True:
                if not self.heartbeat_paused:
                    self._seq += 1
                    self._hb_sent[self._seq] = time.monotonic()
                    await ws.send(self._msg("heartbeat", seq=self._seq))
                await asyncio.sleep(self.heartbeat_s)
        except ConnectionClosed:
            pass

    async def wait_for(self, pred, timeout: float = 3.0) -> dict:
        """等一則之後收到、符合條件的訊息。"""
        fut = asyncio.get_running_loop().create_future()
        entry = (pred, fut)
        self._waiters.append(entry)
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._waiters.remove(entry)

    def find(self, pred) -> list[dict]:
        return [m for _, m in self.received if pred(m)]

    async def send_raw(self, text: str) -> None:
        await self.ws.send(text)

    async def command(self, action: str, params: dict | None = None, ttl_ms: int = 3000, timeout: float = 3.0, request_id: str | None = None) -> dict:
        """送一個 command，等它的 ack。回傳 ack，另加 `_latency_ms`（送出到收到 ack）。"""
        rid = request_id or f"req_{uuid.uuid4().hex[:16]}"
        fields = {"request_id": rid, "action": action, "ttl_ms": ttl_ms}
        if params is not None:
            fields["params"] = params
        waiter = asyncio.create_task(self.wait_for(lambda m: m.get("type") == "ack" and m.get("request_id") == rid, timeout))
        await asyncio.sleep(0)
        t0 = time.monotonic()
        await self.ws.send(self._msg("command", **fields))
        ack = dict(await waiter)
        ack["_latency_ms"] = round((time.monotonic() - t0) * 1000.0, 2)
        return ack


# ---------------------------------------------------------------- 端到端流程（頭部）
async def _head_state(hub: MockHub) -> dict:
    ack = await hub.command("status", ttl_ms=2000)
    return ack["data"]


async def _wait_head(hub: MockHub, joint: str, target: float, tol: float = 0.035, timeout: float = 8.0) -> tuple[float, float]:
    """輪詢 status 直到回讀角度到目標附近。回傳（最後角度, 花的秒數）。"""
    t0 = time.monotonic()
    value = float("nan")
    while time.monotonic() - t0 < timeout:
        value = (await _head_state(hub)).get("head", {}).get(joint, float("nan"))
        if abs(value - target) <= tol:
            break
        await asyncio.sleep(0.1)
    return value, time.monotonic() - t0


async def run_e2e(hub: MockHub, amplitude: float = 0.2) -> dict:
    """look → gesture nod → presence，並量延遲。只動頭；幅度預設 0.2 rad（11.5°）。"""
    out: dict = {"mock_hub": True}
    await asyncio.wait_for(hub.connected.wait(), 60)
    hello = await hub.wait_for(lambda m: m.get("type") == "hello", 5) if not hub.find(lambda m: m.get("type") == "hello") else hub.find(lambda m: m.get("type") == "hello")[-1]
    out["hello"] = {k: hello.get(k) for k in ("software", "mock", "gestures", "expressions", "sounds")}
    out["capabilities"] = hello.get("capabilities")
    await asyncio.sleep(1.2)  # 等租約建立
    st = await _head_state(hub)
    out["state_before"] = {k: st.get(k) for k in ("mode", "control_source", "head", "battery", "temperature_c", "loop", "faults")}
    if "head" not in st:
        out["error"] = "head not engaged"
        return out
    home = {k: v for k, v in st["head"].items() if k != "age_ms"}
    steps = []

    async def look(joint: str, value: float, duration: float = 1.5) -> None:
        ack = await hub.command("look", {joint: value, "duration_s": duration}, ttl_ms=5000)
        rec = {"action": "look", "joint": joint, "target": value, "ack": {k: ack.get(k) for k in ("status", "reason", "detail", "applied", "clamped", "_latency_ms")}}
        if ack["status"] == "accepted":
            t0 = time.monotonic()
            start = (await _head_state(hub))["head"][joint]
            # 指令到開始動：輪詢回讀，第一次離開起點超過 0.5°
            onset = None
            while time.monotonic() - t0 < 3.0:
                v = (await _head_state(hub))["head"][joint]
                if abs(v - start) > 0.0087:
                    onset = time.monotonic() - t0
                    break
            applied = ack["applied"][joint]
            final, took = await _wait_head(hub, joint, applied)
            await asyncio.sleep(0.6)
            final = (await _head_state(hub))["head"][joint]
            rec.update(start=start, applied=applied, readback=final, error_rad=round(final - applied, 4), onset_s_upper_bound=None if onset is None else round(onset, 3), reach_s=round(took, 2))
        steps.append(rec)

    await look("head_yaw", home["head_yaw"] + amplitude)
    await look("head_yaw", home["head_yaw"])
    await look("head_pitch", home["head_pitch"] - amplitude * 0.75)
    await look("head_pitch", home["head_pitch"])
    await look("head_yaw", 9.0)  # 故意超出範圍：要被夾限並回報
    await look("head_yaw", home["head_yaw"])

    ack = await hub.command("gesture", {"name": "nod"}, ttl_ms=3000)
    rec = {"action": "gesture nod", "ack": {k: ack.get(k) for k in ("status", "reason", "detail", "applied", "_latency_ms")}}
    if ack["status"] == "accepted":
        rid = ack["request_id"]
        trace = []
        done_task = asyncio.create_task(hub.wait_for(lambda m: m.get("type") == "event" and m.get("event") == "gesture_done" and m.get("request_id") == rid, 10))
        while not done_task.done():
            trace.append((await _head_state(hub))["head"]["head_pitch"])
            await asyncio.sleep(0.05)
        done = await done_task
        rec.update(done=done.get("data"), pitch_min=min(trace), pitch_max=max(trace), samples=len(trace))
    steps.append(rec)

    for state, extra in (("listening", {}), ("thinking", {}), ("speaking", {"speech_level": 0.8}), ("idle", {})):
        ack = await hub.command("presence", {"state": state, **extra}, ttl_ms=3000)
        trace = []
        t0 = time.monotonic()
        while time.monotonic() - t0 < 2.5:
            s = await _head_state(hub)
            trace.append(s["head"])
            if state == "speaking":
                await hub.command("presence", {"state": state, **extra}, ttl_ms=3000)
            await asyncio.sleep(0.1)
        steps.append({
            "action": f"presence {state}", "ack": ack.get("status"), "expression": s.get("expression"),
            "roll_range": [round(min(h["head_roll"] for h in trace), 4), round(max(h["head_roll"] for h in trace), 4)],
            "yaw_range": [round(min(h["head_yaw"] for h in trace), 4), round(max(h["head_yaw"] for h in trace), 4)],
            "pitch_range": [round(min(h["head_pitch"] for h in trace), 4), round(max(h["head_pitch"] for h in trace), 4)],
        })
    await hub.command("look", {**home, "duration_s": 2.0}, ttl_ms=5000)
    await asyncio.sleep(2.5)
    st = await _head_state(hub)
    out["steps"] = steps
    out["state_after"] = {k: st.get(k) for k in ("mode", "head", "battery", "temperature_c", "loop", "faults")}
    out["home"] = home
    acks = [m for _, m in hub.received if m.get("type") == "ack"]
    out["acks"] = len(acks)
    rtt = hub.rtt_ms
    if rtt:
        out["heartbeat_rtt_ms"] = {"n": len(rtt), "median": round(statistics.median(rtt), 2), "max": round(max(rtt), 2), "min": round(min(rtt), 2)}
    out["schema_errors"] = hub.schema_errors
    return out


async def run_lease_test(hub: MockHub) -> dict:
    """租約測試：頭在動的時候把 hub 整個關掉，重開後看有沒有收到 link_lost／link_restored、頭有沒有停在半路。"""
    out: dict = {}
    await asyncio.wait_for(hub.connected.wait(), 60)
    await asyncio.sleep(1.2)
    st = await _head_state(hub)
    home = st["head"]["head_yaw"]
    ack = await hub.command("look", {"head_yaw": home + 0.25, "duration_s": 4.0}, ttl_ms=8000)
    out["look_ack"] = ack.get("status")
    await asyncio.sleep(1.0)
    mid = (await _head_state(hub))["head"]["head_yaw"]
    t_kill = time.monotonic()
    await hub.stop()  # 連線中斷
    if hub.ws is not None:
        await hub.ws.close()
    out["yaw_when_hub_stopped"] = mid
    await asyncio.sleep(3.0)
    hub.received.clear()
    await hub.start()
    await asyncio.wait_for(hub.connected.wait(), 30)
    out["reconnect_s"] = round(time.monotonic() - t_kill, 2)
    await asyncio.sleep(1.5)
    events = [m["event"] for _, m in hub.received if m.get("type") == "event"]
    out["events_after_reconnect"] = events
    st = await _head_state(hub)
    out["yaw_after_reconnect"] = st["head"]["head_yaw"]
    out["yaw_target_was"] = home + 0.25
    out["moved_after_stop_rad"] = round(st["head"]["head_yaw"] - mid, 4)
    out["stopped_short_of_target"] = abs(st["head"]["head_yaw"] - (home + 0.25)) > 0.05
    await hub.command("look", {"head_yaw": home, "duration_s": 2.0}, ttl_ms=5000)
    await asyncio.sleep(2.5)
    out["yaw_home_again"] = (await _head_state(hub))["head"]["head_yaw"]
    out["schema_errors"] = hub.schema_errors
    return out


async def _amain(args) -> int:
    hub = MockHub(args.host, args.port)
    await hub.start()
    print(f"[mock hub] 聽 ws://{hub.host}:{hub.port}/duck-link（這是測試用的假 hub，不是 Nous）", file=sys.stderr)
    if args.e2e:
        result = await run_e2e(hub, args.amplitude)
    elif args.lease:
        result = await run_lease_test(hub)
    else:
        try:
            while True:
                await asyncio.sleep(5)
                print(f"[mock hub] 連線 {hub.connections} 次，收到 {len(hub.received)} 則，schema 錯誤 {len(hub.schema_errors)}", file=sys.stderr)
        except asyncio.CancelledError:
            return 0
    print(json.dumps(result, ensure_ascii=False, indent=1))
    await hub.stop()
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="假的 duck-link hub（mock，測試用）")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8791)
    p.add_argument("--e2e", action="store_true", help="跑頭部端到端流程並輸出量測")
    p.add_argument("--lease", action="store_true", help="跑租約測試（中途關掉 hub 再重開）")
    p.add_argument("--amplitude", type=float, default=0.2, help="look 的幅度（rad）")
    args = p.parse_args()
    try:
        return asyncio.run(_amain(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
