"""**模擬的 Nous 端（mock）**：只用來測鴨子端的 duck-voice 服務，不是真的 Nous，也不會理解任何話。

行為：收到 `turn_start` 後數上行的框數與能量；「有聲音之後安靜 0.8 秒」或收滿 `max_listen_s` 就送 `listen_stop`，
然後把一段**合成語音 fixture**（`fixtures/speech_zh_synthetic_fixture.wav`）當回話串流回去。
上行音訊只算 RMS，不存、不轉送。`hello_ack` 會帶 `mock: true`。

    python -m duck_audio.mock_nous --port 8791
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging

import numpy as np

from .kws import AUDIO_ROOT
from .wavio import read_wav, resample

log = logging.getLogger("mock-nous")
PATH = "/duck-voice"


class MockNous:
    def __init__(self, reply_rate: int = 24000, end_silence_s: float = 0.8, max_listen_s: float = 6.0, speech_rms: float = 0.01,
                 reply: np.ndarray | None = None, realtime: bool = True, fixed_listen_s: float | None = None) -> None:
        #: 固定聽這麼久就當作說完了（實機用：XVF3800 有自動增益，固定的能量門檻分不出有沒有人說話）。
        self.fixed_listen_s = fixed_listen_s
        if reply is None:
            x, rate = read_wav(AUDIO_ROOT / "fixtures" / "speech_zh_synthetic_fixture.wav")
            reply = resample(x, rate, reply_rate)
        self.reply = (np.clip(reply, -1, 1) * 32767).astype("<i2")
        self.reply_rate = reply_rate
        self.end_silence_s, self.max_listen_s, self.speech_rms = end_silence_s, max_listen_s, speech_rms
        self.realtime = realtime
        #: 紀錄（給測試看）：每一輪收到幾框、控制訊息的順序。
        self.turns: list[dict] = []
        self.messages: list[dict] = []
        self.hello: dict | None = None

    async def handler(self, ws) -> None:
        turn: dict | None = None
        stopper: asyncio.Task | None = None
        async for m in ws:
            if isinstance(m, bytes):
                if turn is None or turn.get("stopped"):
                    continue
                x = np.frombuffer(m, dtype="<i2").astype(np.float32) / 32768.0
                turn["frames"] += 1
                turn["t"] += len(x) / 16000
                if float(np.sqrt(np.mean(x * x))) > self.speech_rms:
                    turn["heard"] = True
                    turn["quiet"] = 0.0
                else:
                    turn["quiet"] += len(x) / 16000
                if self.fixed_listen_s is not None:
                    done = turn["t"] >= self.fixed_listen_s
                else:
                    done = (turn["heard"] and turn["quiet"] >= self.end_silence_s) or turn["t"] >= self.max_listen_s
                if done:
                    turn["stopped"] = True
                    stopper = asyncio.ensure_future(self._reply(ws, turn["turn_id"]))
                continue
            msg = json.loads(m)
            self.messages.append(msg)
            kind = msg.get("type")
            if kind == "hello":
                self.hello = msg
                await ws.send(json.dumps({"type": "hello_ack", "v": 0, "mock": True}))
            elif kind == "turn_start":
                turn = {"turn_id": msg["turn_id"], "frames": 0, "t": 0.0, "heard": False, "quiet": 0.0, "trigger": msg.get("trigger")}
                self.turns.append(turn)
            elif kind == "turn_end" and turn is not None and not turn.get("stopped") and msg.get("reason") in ("silence", "max_duration"):
                turn["stopped"] = True
                stopper = asyncio.ensure_future(self._reply(ws, turn["turn_id"]))
        if stopper is not None:
            stopper.cancel()

    async def _reply(self, ws, turn_id: int) -> None:
        try:
            await ws.send(json.dumps({"type": "listen_stop", "turn_id": turn_id}))
            await asyncio.sleep(0.2 if self.realtime else 0)
            await ws.send(json.dumps({"type": "speak_start", "turn_id": turn_id}))
            hop = self.reply_rate // 50
            for i in range(0, len(self.reply), hop):
                await ws.send(self.reply[i : i + hop].tobytes())
                if self.realtime:
                    await asyncio.sleep(0.018)
            await ws.send(json.dumps({"type": "speak_end", "turn_id": turn_id}))
        except Exception:  # noqa: BLE001  對方斷線
            pass

    async def serve(self, port: int, host: str = "127.0.0.1"):
        import websockets  # noqa: PLC0415

        async def route(ws):
            path = getattr(getattr(ws, "request", None), "path", PATH)
            if path != PATH:
                await ws.close(code=1008)
                return
            await self.handler(ws)

        return await websockets.serve(route, host, port, max_size=1 << 20)


async def _main(port: int, fixed_listen_s: float | None) -> None:
    server = await MockNous(fixed_listen_s=fixed_listen_s).serve(port)
    log.info("模擬的 Nous（mock）在 ws://127.0.0.1:%d%s", port, PATH)
    await server.wait_closed()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="模擬的 Nous 端（mock），測 duck-voice 用")
    ap.add_argument("--port", type=int, default=8791)
    ap.add_argument("--listen-s", type=float, default=None, help="固定聽幾秒就回話（實機建議 4）；不給就用能量判斷")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s mock-nous %(message)s")
    a = ap.parse_args()
    asyncio.run(_main(a.port, a.listen_s))
