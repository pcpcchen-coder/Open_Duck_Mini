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
