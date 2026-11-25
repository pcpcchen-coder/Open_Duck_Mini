"""duck-link 連線層：WebSocket client（鴨子連自己的 loopback，經 SSH 通道到 Nous 端）＋ 50 Hz 控制迴圈。

- 控制迴圈在自己的執行緒：連線斷了、卡住或重連中，迴圈照跑，仲裁器照樣會因為租約失效而停下。
- 斷線自動重連（0.5 s 起、最長 3 s）；socket 一關就通知核心（不用等 1.5 s 的租約）。
- 不用 WebSocket 的 ping：租約由協定的 heartbeat 負責。
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time

from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from .core import Duckd

log = logging.getLogger("duckd.link")

DEFAULT_URL = "ws://127.0.0.1:8791/duck-link"
PERIOD_S = 0.02
RECONNECT_MIN_S = 0.5
RECONNECT_MAX_S = 3.0


class LinkRunner:
    def __init__(self, core: Duckd, url: str = DEFAULT_URL, clock=time.monotonic, period_s: float = PERIOD_S):
        self.core = core
        self.url = url
        self.clock = clock
        self.period_s = period_s
        self.stop_event = threading.Event()  # 停控制迴圈
        self.link_stop = threading.Event()  # 停連線（控制迴圈可以繼續跑，把釋放做完）
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue | None = None
        self._control_thread: threading.Thread | None = None
        self.connects = 0
        self.tick_ms_max = 0.0

    # ------------------------------------------------------------ 控制迴圈（執行緒）
    def _control(self) -> None:
        next_t = self.clock()
        while not self.stop_event.is_set():
            t = self.clock()
            try:
                msgs = self.core.tick(t)
            except Exception:  # noqa: BLE001 迴圈不能死；記下來繼續
                log.exception("控制迴圈這一圈失敗")
                msgs = []
            self.tick_ms_max = max(self.tick_ms_max, (self.clock() - t) * 1000.0)
            if msgs:
                self._post(msgs)
            next_t += self.period_s
            delay = next_t - self.clock()
            if delay < 0:
                self.core.overruns += 1
                if delay < -self.period_s:
                    next_t = self.clock()
            else:
                time.sleep(delay)

    def _post(self, msgs: list[dict]) -> None:
        loop, queue = self._loop, self._queue
        if loop is None or queue is None:
            return
        try:
            loop.call_soon_threadsafe(lambda: [queue.put_nowait(m) for m in msgs])
        except RuntimeError:
            pass  # 事件迴圈已經關了

    def start_control(self) -> None:
        self._control_thread = threading.Thread(target=self._control, name="duckd-control", daemon=True)
        self._control_thread.start()

    # ------------------------------------------------------------ 連線（asyncio）
    async def _session(self) -> None:
        async with connect(self.url, open_timeout=3, ping_interval=None, compression=None, proxy=None, max_size=65536) as ws:
            self.connects += 1
            log.info("已連上 %s", self.url)
            while not self._queue.empty():
                self._queue.get_nowait()
            for m in self.core.on_open(self.clock()):
                self._queue.put_nowait(m)

            async def sender() -> None:
                while True:
                    m = await self._queue.get()
                    await ws.send(json.dumps(m, ensure_ascii=False, separators=(",", ":")))

            async def stopper() -> None:
                while not self.link_stop.is_set():
                    await asyncio.sleep(0.1)
                await ws.close()

            tasks = [asyncio.create_task(sender()), asyncio.create_task(stopper())]
            try:
                async for text in ws:
                    if isinstance(text, str):
                        for m in self.core.on_text(text, self.clock()):
                            self._queue.put_nowait(m)
            finally:
                for t in tasks:
                    t.cancel()

    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        delay = RECONNECT_MIN_S
        while not self.link_stop.is_set():
            t0 = self.clock()
            try:
                await self._session()
            except (OSError, WebSocketException, asyncio.TimeoutError) as exc:
                log.debug("連線結束：%r", exc)
            finally:
                if self.core.connected:
                    log.info("連線中斷")
                self.core.on_close(self.clock())
            delay = RECONNECT_MIN_S if self.clock() - t0 > 5.0 else min(delay * 1.5, RECONNECT_MAX_S)
            end = self.clock() + delay
            while self.clock() < end and not self.link_stop.is_set():
                await asyncio.sleep(0.05)

    def run(self) -> None:
        """阻塞：跑到 `link_stop` 被設定為止。控制迴圈要另外先 `start_control()`。"""
        asyncio.run(self._main())

    def stop(self) -> None:
        self.link_stop.set()
        self.stop_event.set()
        if self._control_thread:
            self._control_thread.join(timeout=2.0)
