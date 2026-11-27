"""眼睛輸出：duck_eyes 接進 duckd、虛擬面板出 PNG、capabilities.eyes 的誠實回報。"""
import struct
import zlib

import numpy as np
import pytest
from conftest import make_harness

from duckd.eyes_out import EyesOutput, encode_png


def test_png_encoder_roundtrip():
    img = (np.arange(4 * 6 * 3) % 251).astype(np.uint8).reshape(4, 6, 3)
    data = encode_png(img)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    w, h, depth, ctype = struct.unpack(">IIBB", data[16:26])
    assert (w, h, depth, ctype) == (6, 4, 8, 2)
    idat_len = struct.unpack(">I", data[33:37])[0]
    raw = zlib.decompress(data[41 : 41 + idat_len])
    rows = [raw[i * 19 + 1 : (i + 1) * 19] for i in range(4)]
    assert b"".join(rows) == img.tobytes()


def test_virtual_panel_writes_both_eyes(tmp_path):
    eyes = EyesOutput(tmp_path / "eyes.png")
    left, right = eyes.render_once()
    assert left.shape == right.shape == (240, 240, 3) and left.dtype == np.uint8
    eyes.write_panel(left, right)
    data = (tmp_path / "eyes.png").read_bytes()
    assert struct.unpack(">II", data[16:24]) == (240 * 2 + 16, 240)
    assert eyes.stats()["frames"] == 1 and eyes.stats()["render_ms_median"] > 0
    assert eyes.panel_kind == "virtual_png"


def test_eyes_capability_is_never_available_without_real_panels(tmp_path):
    h = make_harness(eyes=EyesOutput(tmp_path / "eyes.png"))
    cap = h.sent[0]["capabilities"]["eyes"]
    assert cap["status"] == "mock" and "virtual" in cap["reason"]
    assert "happy" in h.sent[0]["expressions"] and "low_battery" not in h.sent[0]["expressions"]
    assert make_harness().sent[0]["capabilities"]["eyes"]["status"] == "unsupported"


def test_express_policy_and_duration(tmp_path):
    eyes = EyesOutput(None)
    h = make_harness(eyes=eyes)
    assert h.cmd("express", {"expression": "happy", "duration_s": 0.2})["status"] == "accepted"
    assert h.cmd("status")["data"]["expression"] == "happy"
    # 代表鴨子實際狀態的表情，Nous 叫不出來
    assert h.cmd("express", {"expression": "low_battery"})["reason"] == "unsupported"
    assert h.cmd("express", {"expression": "charging"})["reason"] == "unsupported"
    assert h.cmd("express", {"expression": "no_such_face"})["reason"] == "unknown_name"
    import time

    time.sleep(0.25)
    assert eyes.expression == "neutral"  # 到期回到 presence 的表情


def test_presence_drives_expression_and_status_ring_uses_real_state(tmp_path):
    eyes = EyesOutput(None)
    h = make_harness(eyes=eyes)
    h.cmd("presence", {"state": "listening"})
    h.tick()
    assert eyes.expression == "listening" and eyes._device.conversation_active is True
    assert eyes._device.camera_streaming is False  # 沒有鏡頭：狀態環不會是青色
    h.cmd("presence", {"state": "speaking", "speech_level": 0.7})
    h.tick()
    assert eyes.expression == "speaking" and eyes._audio_level == pytest.approx(0.7)
    h.cmd("presence", {"state": "sleeping"})
    h.tick()
    assert eyes.expression == "sleeping" and eyes._device.conversation_active is False
    h.core.local_estop("test", h.t)
    h.tick()
    assert eyes._device.needs_help is True
    # 斷線：對話狀態環熄掉
    h.core.local_clear_estop()
    h.cmd("presence", {"state": "listening"})
    h.heartbeats = False
    h.run(2.0)
    assert eyes._device.conversation_active is False and eyes.expression == "neutral"
    left, right = eyes.render_once()
    assert left.any()


class FakePanels:
    """假的實體螢幕（同 duck_eyes.gc9a01.EyePanels 的 show／close／last_sent）。"""

    def __init__(self, fail_on_show=False):
        self.shown, self.closed, self.last_sent, self.fail = [], False, None, fail_on_show

    def show(self, left, right):
        if self.fail:
            raise OSError("spi gone")
        import time

        self.shown.append((left.copy(), right.copy()))
        self.last_sent = time.monotonic()
        return 0

    def close(self):
        self.closed = True


def test_hardware_panels_get_frames_and_capability_is_degraded_not_available(tmp_path):
    hw = FakePanels()
    eyes = EyesOutput(tmp_path / "eyes.png", hardware=hw)
    assert eyes.panel_kind == "gc9a01"
    eyes.show(*eyes.render_once())
    assert len(hw.shown) == 1 and hw.shown[0][0].shape == (240, 240, 3)
    assert (tmp_path / "eyes.png").exists()  # 預覽照寫
    st = eyes.stats()
    assert st["panel"] == "gc9a01" and "send_ms_median" in st and st["last_sent_age_s"] >= 0
    cap = make_harness(eyes=eyes).sent[0]["capabilities"]["eyes"]
    assert cap["status"] == "degraded" and "no pixel readback" in cap["reason"]  # 沒有回讀，不說 available
    eyes.stop()
    assert hw.closed


def test_png_preview_is_throttled_when_hardware_present(tmp_path):
    eyes = EyesOutput(tmp_path / "eyes.png", hardware=FakePanels())
    l, r = eyes.render_once()
    eyes.show(l, r)
    (tmp_path / "eyes.png").unlink()
    eyes.show(l, r)  # 同一秒內：不再寫 PNG
    assert not (tmp_path / "eyes.png").exists()


def test_send_failure_drops_to_virtual_panel_and_reports_why(tmp_path):
    hw = FakePanels(fail_on_show=True)
    eyes = EyesOutput(tmp_path / "eyes.png", fps=50, hardware=hw)
    eyes.start()
    import time

    end = time.monotonic() + 3
    while eyes.hardware is not None and time.monotonic() < end:
        time.sleep(0.02)
    eyes.stop()
    assert eyes.panel_kind == "virtual_png" and hw.closed
    assert "spi gone" in eyes.hardware_error and "spi gone" in eyes.stats()["hardware_error"]
    cap = make_harness(eyes=eyes).sent[0]["capabilities"]["eyes"]
    assert cap["status"] == "mock" and "failed" in cap["reason"]


def test_expression_change_reaches_hardware_panels(tmp_path):
    """presence（語音工作階段）改變時，下一幀送到實體螢幕的畫面跟著變。"""
    hw = FakePanels()
    eyes = EyesOutput(None, hardware=hw)
    h = make_harness(eyes=eyes)
    eyes.show(*eyes.render_once())
    h.cmd("presence", {"state": "thinking"})
    assert eyes.expression == "thinking"
    eyes.show(*eyes.render_once())
    assert not np.array_equal(hw.shown[0][0], hw.shown[1][0])
