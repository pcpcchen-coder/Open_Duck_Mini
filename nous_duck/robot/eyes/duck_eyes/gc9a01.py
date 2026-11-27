"""GC9A01 圓形螢幕（240×240，4 線 SPI）的驅動：兩片眼睛共用一條 SPI 匯流排、各自一支 CS。

接線（設計文件 `hardware/expression_mods/gc9a01_eyes.md` §3.2，2026-11-27 使用者確認）：

| 腳 | Pi 4 | 備註 |
|---|---|---|
| SCL／SDA | GPIO 11／10（SPI0） | |
| CS | 左眼 GPIO 8（CE0，`/dev/spidev0.0`）、右眼 GPIO 7（CE1，`/dev/spidev0.1`） | 「左眼」是站在鴨子面前看到的左邊 |
| DC、RES、BLK | GPIO 5、26、6 | 兩片共用 |

- 面板**沒有回讀**：這裡能確認的只有「資料送出去了」，不是「畫面真的出現了」。`last_sent` 是給
  鏡頭服務用的渲染心跳（ADR-0013 §2.3），意思是「最後一次把一幀送進 SPI 的時間」。
- 背光在兩片都送完第一幀之後才打開，避免開機時亮出殘影或雜訊。程式結束、腳位釋放後，
  GPIO 6 回到輸入，Pi 預設上拉，**背光可能又亮起來**；開機到程式啟動前也一樣。要真的關，
  得在 BLK 加下拉電阻（設計文件 §3.2 建議、目前沒加），程式管不到。
- 初始化序列是公開的 GC9A01 序列（Waveshare LCD_1inch28 範例、Adafruit 驅動同一份）；
  2026-11-27 在 777 微電子的模組上實機點亮過（顏色順序、方向經使用者目視確認）。
- SPI 與 GPIO 都可以換成假的（測試用）；真的後端用 `spidev` 與 `gpiod` 2.x，只在用到時才匯入。

命令列（在 Pi 上）：

    python -m duck_eyes.gc9a01 pattern            # 左眼紅→綠→藍→十字、右眼藍：分辨左右與方向
    python -m duck_eyes.gc9a01 demo --cycle       # 輪播全部表情，印出幀率
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from . import panel as _panel

WIDTH = HEIGHT = 240
CHUNK = 4096  # spidev 預設單次傳輸上限（/sys/module/spidev/parameters/bufsiz）

# MADCTL：0x08 是 BGR、不旋轉（2026-11-27 實機確認：顏色正確、畫面沒有旋轉或鏡像）。
# 其他角度是依 MY／MX／MV 位元推出來的，**還沒有在實機上看過**。
MADCTL = {0: 0x08, 90: 0x68, 180: 0xC8, 270: 0xA8}

INIT_SEQUENCE: list[tuple[int, bytes]] = [
    (0xEF, b""), (0xEB, b"\x14"), (0xFE, b""), (0xEF, b""), (0xEB, b"\x14"),
    (0x84, b"\x40"), (0x85, b"\xFF"), (0x86, b"\xFF"), (0x87, b"\xFF"), (0x88, b"\x0A"),
    (0x89, b"\x21"), (0x8A, b"\x00"), (0x8B, b"\x80"), (0x8C, b"\x01"), (0x8D, b"\x01"),
    (0x8E, b"\xFF"), (0x8F, b"\xFF"), (0xB6, b"\x00\x20"),
    (0x3A, b"\x05"),  # 16 bit/pixel（RGB565）
    (0x90, b"\x08\x08\x08\x08"), (0xBD, b"\x06"), (0xBC, b"\x00"), (0xFF, b"\x60\x01\x04"),
    (0xC3, b"\x13"), (0xC4, b"\x13"), (0xC9, b"\x22"), (0xBE, b"\x11"), (0xE1, b"\x10\x0E"),
    (0xDF, b"\x21\x0C\x02"),
    (0xF0, b"\x45\x09\x08\x08\x26\x2A"), (0xF1, b"\x43\x70\x72\x36\x37\x6F"),
    (0xF2, b"\x45\x09\x08\x08\x26\x2A"), (0xF3, b"\x43\x70\x72\x36\x37\x6F"),
    (0xED, b"\x1B\x0B"), (0xAE, b"\x77"), (0xCD, b"\x63"),
    (0x70, b"\x07\x07\x04\x0E\x0F\x09\x07\x08\x03"), (0xE8, b"\x34"),
    (0x62, b"\x18\x0D\x71\xED\x70\x70\x18\x0F\x71\xEF\x70\x70"),
    (0x63, b"\x18\x11\x71\xF1\x70\x70\x18\x13\x71\xF3\x70\x70"),
    (0x64, b"\x28\x29\xF1\x01\xF1\x00\x07"),
    (0x66, b"\x3C\x00\xCD\x67\x45\x45\x10\x00\x00\x00"),
    (0x67, b"\x00\x3C\x00\x00\x00\x01\x54\x10\x32\x98"),
    (0x74, b"\x10\x85\x80\x00\x00\x4E\x00"), (0x98, b"\x3E\x07"),
    (0x35, b""),  # tearing effect line on
    (0x21, b""),  # 顯示反相（標準序列裡就有；實機顏色正確）
]
CASET, RASET, RAMWR, MADCTL_CMD, SLPOUT, DISPON = 0x2A, 0x2B, 0x2C, 0x36, 0x11, 0x29


# ---- 硬體後端 ----
class SpiBus(Protocol):
    def write(self, data: bytes) -> None: ...
    def close(self) -> None: ...


class Gpio(Protocol):
    def set(self, pin: int, value: bool) -> None: ...
    def close(self) -> None: ...


class SpidevBus:
    """`/dev/spidevB.D`；單次最多送 CHUNK bytes，超過就分段。"""

    def __init__(self, bus: int, device: int, hz: int) -> None:
        import spidev  # noqa: PLC0415

        self._spi = spidev.SpiDev()
        self._spi.open(bus, device)
        self._spi.mode = 0
        self._spi.max_speed_hz = hz

    @property
    def hz(self) -> int:
        return self._spi.max_speed_hz

    def write(self, data: bytes) -> None:
        for i in range(0, len(data), CHUNK):
            self._spi.writebytes2(data[i:i + CHUNK])

    def close(self) -> None:
        self._spi.close()


class GpiodLines:
    """用 libgpiod 2.x 要求 DC、RES、BLK 三支腳當輸出。RES 一開始就是高（不重設），背光一開始關。"""

    def __init__(self, dc: int, rst: int | None, blk: int | None, chip: str | None = None) -> None:
        import gpiod  # noqa: PLC0415
        from gpiod.line import Direction, Value  # noqa: PLC0415

        self._Value = Value
        cfg = {dc: gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.INACTIVE)}
        if rst is not None:
            cfg[rst] = gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.ACTIVE)
        if blk is not None:
            cfg[blk] = gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.INACTIVE)
        self._req = gpiod.request_lines(chip or _find_chip(gpiod), consumer="duck-eyes", config=cfg)

    def set(self, pin: int, value: bool) -> None:
        self._req.set_value(pin, self._Value.ACTIVE if value else self._Value.INACTIVE)

    def close(self) -> None:
        self._req.release()


def _find_chip(gpiod) -> str:
    """找出 40 pin 排針那顆 gpiochip（Pi 4 是 gpiochip0；用線名 GPIO5 認，不寫死編號）。"""
    for i in range(16):
        path = f"/dev/gpiochip{i}"
        try:
            with gpiod.Chip(path) as c:
                c.line_offset_from_id("GPIO5")
                return path
        except (OSError, ValueError):
            continue
    raise RuntimeError("找不到 40 pin 排針的 gpiochip")


# ---- 面板 ----
@dataclass(frozen=True)
class Pins:
    dc: int = 5
    rst: int | None = 26
    blk: int | None = 6


class Panel:
    """一片 GC9A01。DC／RES／BLK 可能和另一片共用，所以重設與背光交給 `EyePanels`。"""

    def __init__(self, spi: SpiBus, gpio: Gpio, pins: Pins, rotation: int = 0) -> None:
        if rotation not in MADCTL:
            raise ValueError(f"rotation 只能是 {sorted(MADCTL)}")
        self.spi, self.gpio, self.pins, self.rotation = spi, gpio, pins, rotation

    def command(self, cmd: int, data: bytes = b"") -> None:
        self.gpio.set(self.pins.dc, False)
        self.spi.write(bytes([cmd]))
        if data:
            self.gpio.set(self.pins.dc, True)
            self.spi.write(data)

    def init(self) -> None:
        for cmd, data in INIT_SEQUENCE:
            self.command(cmd, data)
        self.command(MADCTL_CMD, bytes([MADCTL[self.rotation]]))
        self.command(SLPOUT)
        time.sleep(0.12)
        self.command(DISPON)
        time.sleep(0.02)

    def blit(self, rgb: np.ndarray, x0: int = 0, y0: int = 0) -> None:
        """把 uint8 H×W×3 放到 (x0, y0)。"""
        h, w = rgb.shape[:2]
        x1, y1 = x0 + w - 1, y0 + h - 1
        if x0 < 0 or y0 < 0 or x1 >= WIDTH or y1 >= HEIGHT:
            raise ValueError("超出 240×240")
        self.command(CASET, bytes([x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF]))
        self.command(RASET, bytes([y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF]))
        self.command(RAMWR, _panel.to_rgb565(np.ascontiguousarray(rgb)))


class EyePanels:
    """兩片眼睛（畫面左、畫面右）。只送和上一幀不同的部分。

    `band`＞0：每 `band` 列一條、條內只送有變的欄（`panel.dirty_runs`，預設 16 列）；
    `band`＝0：舊做法，24×24 格子（`panel.dirty_spans`，`tile`）。
    """

    def __init__(
        self, left: Panel, right: Panel, gpio: Gpio, pins: Pins, tile: int = 24, band: int = 16, blit_cost_px: int = 400
    ) -> None:
        self.left, self.right, self.gpio, self.pins, self.tile = left, right, gpio, pins, tile
        self.band, self.blit_cost_px = band, blit_cost_px
        self.blits = 0
        self._prev: list[np.ndarray | None] = [None, None]
        self._backlight = False
        self.last_sent: float | None = None  # time.monotonic()，渲染心跳
        self.frames = 0
        self.pixels_sent = 0

    def start(self) -> None:
        """重設（兩片共用 RES，只做一次）→ 兩片各自初始化。背光保持關。"""
        self.backlight(False)
        if self.pins.rst is not None:
            for v, dt in ((True, 0.01), (False, 0.01), (True, 0.12)):
                self.gpio.set(self.pins.rst, v)
                time.sleep(dt)
        self.left.init()
        self.right.init()
        self._prev = [None, None]

    def backlight(self, on: bool) -> None:
        if self.pins.blk is not None:
            self.gpio.set(self.pins.blk, on)
        self._backlight = on

    def spans(self, prev, img):
        if self.band > 0:
            return _panel.dirty_runs(prev, img, self.band, self.blit_cost_px)
        return _panel.dirty_spans(prev, img, self.tile)

    def show(self, left: np.ndarray, right: np.ndarray) -> int:
        """送一幀；回傳這次送出的像素數。兩片第一幀都送完才開背光。"""
        sent = 0
        for k, (p, img) in enumerate(((self.left, left), (self.right, right))):
            for x0, y0, x1, y1 in self.spans(self._prev[k], img):
                p.blit(img[y0:y1, x0:x1], x0, y0)
                sent += (x1 - x0) * (y1 - y0)
                self.blits += 1
            self._prev[k] = img
        if not self._backlight:
            self.backlight(True)
        self.last_sent = time.monotonic()
        self.frames += 1
        self.pixels_sent += sent
        return sent

    def close(self) -> None:
        """釋放 SPI 與 GPIO。面板會停在最後一幀（背光見模組說明）。"""
        for p in (self.left, self.right):
            p.spi.close()
        self.gpio.close()


def open_eyes(hz: int = 20_000_000, pins: Pins = Pins(), rotation: int = 0, swap: bool = False, band: int = 16) -> EyePanels:
    """在 Pi 上打開兩片眼睛（CE0＝畫面左、CE1＝畫面右；swap=True 對調）。

    20 MHz：2026-11-27 桌上實測使用者目視「很順」；裝上頭、和舵機一起時要重新確認。
    """
    gpio = GpiodLines(pins.dc, pins.rst, pins.blk)
    buses: list[SpidevBus] = []
    try:
        for dev in (1, 0) if swap else (0, 1):
            buses.append(SpidevBus(0, dev, hz))
    except Exception:
        for bus in buses:
            bus.close()
        gpio.close()
        raise
    left = Panel(buses[0], gpio, pins, rotation)
    right = Panel(buses[1], gpio, pins, rotation)
    eyes = EyePanels(left, right, gpio, pins, band=band)
    try:
        eyes.start()
    except Exception:
        eyes.close()  # 初始化失敗也要放開 SPI 與腳位
        raise
    return eyes


# ---- 命令列 ----
def _solid(c) -> np.ndarray:
    return np.full((HEIGHT, WIDTH, 3), c, np.uint8)


def cross_pattern() -> np.ndarray:
    """白底黑十字、左上角紅方塊：看方向與是否鏡像。"""
    img = _solid((255, 255, 255))
    img[118:122, :] = 0
    img[:, 118:122] = 0
    img[10:40, 10:40] = (255, 0, 0)
    return img


def _cmd_pattern(eyes: EyePanels, args) -> None:
    blue = _solid((0, 0, 255))
    for c in ((255, 0, 0), (0, 255, 0), (0, 0, 255)):
        eyes.show(_solid(c), blue)
        time.sleep(1.0)
    eyes.show(cross_pattern(), blue)
    print("左眼（CE0）：紅→綠→藍→白底十字、左上角紅方塊；右眼（CE1）：全藍")


def _cmd_demo(eyes: EyePanels, args) -> None:
    import duck_eyes  # noqa: PLC0415

    names = list(duck_eyes.EXPRESSIONS) if args.cycle else [args.expr]
    anim = duck_eyes.EyeAnimator(names[0], seed=0)
    device = duck_eyes.DeviceState(camera_streaming=False)  # 還沒有鏡頭：狀態環一律是待機，不假裝鏡頭開著
    period = 1.0 / args.fps
    t0 = time.monotonic()
    idx, n, render_ms, send_ms = 0, 0, [], []
    while (t := time.monotonic() - t0) < args.seconds:
        k = int(t // args.hold)
        if args.cycle and k != idx and k < len(names):
            idx = k
            anim.set_expression(names[idx], t)
            print(f"{t:5.1f}s → {names[idx]}", flush=True)
        a = time.perf_counter()
        left, right = duck_eyes.render_frame(anim.frame(t, duck_eyes.Inputs()), device, t)
        b = time.perf_counter()
        eyes.show(left, right)
        c = time.perf_counter()
        render_ms.append((b - a) * 1000)
        send_ms.append((c - b) * 1000)
        n += 1
        if (rest := period - (c - a)) > 0:
            time.sleep(rest)
    render_ms.sort()
    send_ms.sort()
    print(
        f"{n} 幀 / {args.seconds:.0f} s = {n / args.seconds:.1f} fps（目標 {args.fps:g}）；"
        f"渲染中位數 {render_ms[n // 2]:.1f} ms、最慢 {render_ms[-1]:.1f}；"
        f"傳送中位數 {send_ms[n // 2]:.1f} ms、最慢 {send_ms[-1]:.1f}；SPI {args.hz / 1e6:g} MHz"
    )


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m duck_eyes.gc9a01", description="GC9A01 眼睛：測試畫面與動畫")
    ap.add_argument("--hz", type=int, default=20_000_000, help="SPI 時脈（預設 20 MHz）")
    ap.add_argument("--rotation", type=int, default=0, choices=sorted(MADCTL))
    ap.add_argument("--swap", action="store_true", help="左右對調（CE0 當畫面右）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pattern", help="純色與十字：分辨左右、看方向")
    d = sub.add_parser("demo", help="跑 duck_eyes 動畫")
    d.add_argument("--expr", default="neutral")
    d.add_argument("--cycle", action="store_true", help="輪播全部表情")
    d.add_argument("--hold", type=float, default=4.0, help="輪播時每個表情幾秒")
    d.add_argument("--seconds", type=float, default=20.0)
    d.add_argument("--fps", type=float, default=20.0)
    args = ap.parse_args(argv)
    eyes = open_eyes(args.hz, rotation=args.rotation, swap=args.swap)
    try:
        {"pattern": _cmd_pattern, "demo": _cmd_demo}[args.cmd](eyes, args)
    except KeyboardInterrupt:
        pass
    finally:
        eyes.close()


if __name__ == "__main__":
    sys.exit(main())
