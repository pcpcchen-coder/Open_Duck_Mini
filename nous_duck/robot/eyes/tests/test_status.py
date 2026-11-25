"""狀態環規則（ADR-0006 §4.2、§4.2.1）。"""

import inspect

import pytest

from duck_eyes.status import CAMERA_NIGHT_FLOOR, CYAN, GREEN, RED, WARM_WHITE, YELLOW, DeviceState, ring_spec


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"conversation_active": True},
        {"privacy_switch_off": True},  # 讀值矛盾也照樣顯示青色（寧可多提示）
        {"privacy_switch_off": True, "conversation_active": True},
    ],
)
def test_camera_on_always_cyan(extra):
    for t in (0.0, 0.3, 0.7, 12.4):
        r = ring_spec(DeviceState(camera_streaming=True, **extra), t)
        assert r.color == CYAN and r.level == 1.0


def test_camera_on_with_help_alternates_cyan_yellow():
    s = DeviceState(camera_streaming=True, needs_help=True)
    assert ring_spec(s, 0.2).color == CYAN
    assert ring_spec(s, 0.7).color == YELLOW
    assert ring_spec(s, 1.2).color == CYAN


def test_priority_when_camera_off():
    assert ring_spec(DeviceState(False, privacy_switch_off=True, needs_help=True, conversation_active=True), 5).color == RED
    assert ring_spec(DeviceState(False, needs_help=True, conversation_active=True), 0.2).color == YELLOW
    assert ring_spec(DeviceState(False, conversation_active=True), 1.0).color == GREEN
    assert ring_spec(DeviceState(False), 1.0).color == WARM_WHITE


def test_privacy_switch_short_flash_then_dim():
    s = DeviceState(False, privacy_switch_off=True, privacy_switch_changed_at=10.0)
    assert ring_spec(s, 10.1).level == 1.0
    assert ring_spec(s, 11.0).level == pytest.approx(0.3)


def test_night_dims_but_camera_stays_visible():
    day = ring_spec(DeviceState(True), 0.0)
    night = ring_spec(DeviceState(True, night=True), 0.0)
    assert night.color == CYAN and night.level >= CAMERA_NIGHT_FLOOR and night.level < day.level
    assert ring_spec(DeviceState(False, night=True), 0.0).level < ring_spec(DeviceState(False), 0.0).level


def test_ring_has_no_expression_input():
    """狀態環只吃裝置狀態與時間，沒有任何讓表情或 Nous 改顏色的參數。"""
    assert list(inspect.signature(ring_spec).parameters) == ["s", "t"]
