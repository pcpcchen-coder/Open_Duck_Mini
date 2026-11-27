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


def test_dirty_spans_cover_every_change_and_merge_neighbours():
    from duck_eyes.panel import dirty_spans

    a = np.zeros((240, 240, 3), np.uint8)
    assert dirty_spans(None, a) == [(0, 0, 240, 240)]
    assert dirty_spans(a, a.copy()) == []
    b = a.copy()
    b[5, 5] = 1  # 左上角一點
    b[230, 200:239] = 9  # 右下一條橫線（跨兩格）
    spans = dirty_spans(a, b, tile=24)
    assert spans == [(0, 0, 24, 24), (192, 216, 240, 240)]
    # 每個有變動的像素都在某一塊裡
    covered = np.zeros((240, 240), bool)
    for x0, y0, x1, y1 in spans:
        covered[y0:y1, x0:x1] = True
    assert covered[np.any(a != b, axis=2)].all()


def test_dirty_spans_ring_sends_far_less_than_bounding_rect():
    """狀態環改顏色：只動一圈細環，格子版送的像素應遠少於整張外接矩形。"""
    from duck_eyes import DeviceState, EyeAnimator, render_frame
    from duck_eyes.panel import dirty_spans

    fr = EyeAnimator("neutral", seed=1).frame(0.5)
    a, _ = render_frame(fr, DeviceState(False), 0.5)
    b, _ = render_frame(fr, DeviceState(True), 0.5)
    x0, y0, x1, y1 = dirty_rect(a, b)
    rect_px = (x1 - x0) * (y1 - y0)
    span_px = sum((s[2] - s[0]) * (s[3] - s[1]) for s in dirty_spans(a, b))
    assert span_px < 0.6 * rect_px
