"""GC9A01 驅動：用假的 SPI／GPIO 記錄送出的位元組與腳位變化（不需要硬體）。"""

import numpy as np
import pytest

from duck_eyes import gc9a01 as G
from duck_eyes.panel import to_rgb565


class Log:
    def __init__(self):
        self.events = []  # ("gpio", pin, value) 或 ("spi", name, dc, bytes)


class FakeGpio:
    def __init__(self, log):
        self.log, self.level, self.closed = log, {}, False

    def set(self, pin, value):
        self.level[pin] = bool(value)
        self.log.events.append(("gpio", pin, bool(value)))

    def close(self):
        self.closed = True


class FakeSpi:
    def __init__(self, log, name, gpio, dc):
        self.log, self.name, self.gpio, self.dc, self.closed = log, name, gpio, dc, False

    def write(self, data):
        assert len(data) > 0
        self.log.events.append(("spi", self.name, self.gpio.level.get(self.dc, False), bytes(data)))

    def close(self):
        self.closed = True


def make(rotation=0, band=16):
    log = Log()
    pins = G.Pins()
    gpio = FakeGpio(log)
    left = G.Panel(FakeSpi(log, "L", gpio, pins.dc), gpio, pins, rotation)
    right = G.Panel(FakeSpi(log, "R", gpio, pins.dc), gpio, pins, rotation)
    return log, gpio, G.EyePanels(left, right, gpio, pins, band=band), pins


def commands(log, name):
    """把某片收到的 SPI 位元組拆成 [(指令, 資料)]：DC 低是指令、DC 高是資料。"""
    out = []
    for e in log.events:
        if e[0] == "spi" and e[1] == name:
            _, _, dc, data = e
            if not dc:
                assert len(data) == 1
                out.append([data[0], b""])
            else:
                out[-1][1] += data
    return [(c, d) for c, d in out]


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(G.time, "sleep", lambda s: None)


def test_start_resets_once_then_inits_both_with_backlight_off():
    log, gpio, eyes, pins = make()
    eyes.start()
    rst = [e[2] for e in log.events if e[0] == "gpio" and e[1] == pins.rst]
    assert rst == [True, False, True]  # 共用的 RES 只脈衝一次
    first_spi = next(i for i, e in enumerate(log.events) if e[0] == "spi")
    last_rst = max(i for i, e in enumerate(log.events) if e[0] == "gpio" and e[1] == pins.rst)
    assert last_rst < first_spi  # 重設完才送指令
    for name in "LR":
        cmds = commands(log, name)
        assert cmds[: len(G.INIT_SEQUENCE)] == G.INIT_SEQUENCE
        assert cmds[len(G.INIT_SEQUENCE):] == [(0x36, b"\x08"), (0x11, b""), (0x29, b"")]
    assert gpio.level[pins.blk] is False


def test_backlight_turns_on_only_after_both_first_frames():
    log, gpio, eyes, pins = make()
    eyes.start()
    log.events.clear()
    img = np.zeros((240, 240, 3), np.uint8)
    eyes.show(img, img)
    blk_on = [i for i, e in enumerate(log.events) if e == ("gpio", pins.blk, True)]
    last_r = max(i for i, e in enumerate(log.events) if e[0] == "spi" and e[1] == "R")
    assert len(blk_on) == 1 and blk_on[0] > last_r
    assert eyes.last_sent is not None


def test_blit_window_and_pixels():
    log, gpio, eyes, pins = make()
    img = np.zeros((10, 20, 3), np.uint8)
    img[..., 0] = 255
    eyes.left.blit(img, 100, 50)
    cmds = commands(log, "L")
    assert cmds[0] == (0x2A, bytes([0, 100, 0, 119]))
    assert cmds[1] == (0x2B, bytes([0, 50, 0, 59]))
    assert cmds[2] == (0x2C, to_rgb565(img))
    with pytest.raises(ValueError):
        eyes.left.blit(img, 230, 0)


def test_full_frame_goes_out_in_chunks_when_real_bus_splits(monkeypatch):
    """SpidevBus 分段：每段 ≤ 4096 bytes，接起來等於原資料。"""
    sent = []

    class S:
        def writebytes2(self, b):
            sent.append(bytes(b))

    bus = G.SpidevBus.__new__(G.SpidevBus)
    bus._spi = S()
    data = bytes(range(256)) * 450  # 115200 bytes＝一張全畫面
    bus.write(data)
    assert max(len(b) for b in sent) <= G.CHUNK and b"".join(sent) == data


def test_only_changed_tiles_are_resent():
    log, gpio, eyes, pins = make(band=0)
    eyes.start()
    a = np.zeros((240, 240, 3), np.uint8)
    eyes.show(a, a)
    log.events.clear()
    assert eyes.show(a, a.copy()) == 0  # 沒變就不送
    assert not [e for e in log.events if e[0] == "spi"]
    b = a.copy()
    b[100, 100] = 255
    assert eyes.show(b, a) == 24 * 24  # 只送那一格
    assert not [e for e in log.events if e[0] == "spi" and e[1] == "R"]


@pytest.mark.parametrize("rot,val", [(0, 0x08), (180, 0xC8)])
def test_rotation_madctl(rot, val):
    log, gpio, eyes, pins = make(rot)
    eyes.left.init()
    assert (0x36, bytes([val])) in commands(log, "L")


def test_bad_rotation():
    with pytest.raises(ValueError):
        make(45)


def test_close_releases_everything():
    log, gpio, eyes, pins = make()
    eyes.close()
    assert gpio.closed and eyes.left.spi.closed and eyes.right.spi.closed


def test_driver_imports_without_hardware_libraries():
    """CI 與 Mac 上沒有 spidev／gpiod：匯入模組不能失敗，只有真的打開硬體時才需要。"""
    import importlib

    importlib.reload(G)


def test_band_mode_sends_only_changed_columns_and_counts_blits():
    log, gpio, eyes, pins = make()
    eyes.start()
    a = np.zeros((240, 240, 3), np.uint8)
    eyes.show(a, a)
    b = a.copy()
    b[100, 100] = 255
    b[100, 200] = 255  # 同一條、隔很遠：分兩段
    blits = eyes.blits
    assert eyes.show(b, a) == 2 * 1 * 16  # 每段 1 欄寬 × 16 列
    assert eyes.blits - blits == 2
