import numpy as np

from duck_eyes.panel import dirty_rect, to_rgb565


def test_rgb565_known_values():
    img = np.array([[[255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 255, 255], [0, 0, 0]]], np.uint8)
    assert to_rgb565(img) == bytes([0xF8, 0x00, 0x07, 0xE0, 0x00, 0x1F, 0xFF, 0xFF, 0x00, 0x00])


def test_full_frame_size():
    assert len(to_rgb565(np.zeros((240, 240, 3), np.uint8))) == 240 * 240 * 2


def test_dirty_rect():
    a = np.zeros((240, 240, 3), np.uint8)
    b = a.copy()
    assert dirty_rect(None, a) == (0, 0, 240, 240)
    assert dirty_rect(a, b) is None
    b[10:20, 30:45] = 7
    assert dirty_rect(a, b) == (30, 10, 45, 20)
