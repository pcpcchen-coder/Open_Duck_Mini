"""表情使用規則。"""

import itertools

from duck_eyes import EXPRESSIONS, DeviceState
from duck_eyes.policy import LOCAL_ONLY, NOUS_ALLOWED, nous_can_request, resting_expression


def test_sets_cover_all_and_disjoint():
    assert NOUS_ALLOWED | LOCAL_ONLY == set(EXPRESSIONS)
    assert not (NOUS_ALLOWED & LOCAL_ONLY)


def test_state_expressions_are_local_only():
    for eid in ("worried", "low_battery", "charging", "listening", "speaking", "dizzy", "focused", "sleeping", "waking", "scared"):
        assert not nous_can_request(eid), eid


def test_never_closed_eyes_while_camera_streaming():
    for night, charging in itertools.product((False, True), repeat=2):
        e = resting_expression(DeviceState(camera_streaming=True, night=night), charging)
        assert EXPRESSIONS[e].left.shape not in ("arc_down", "arc_up"), (night, charging, e)


def test_sleeping_only_when_camera_off_at_night():
    assert resting_expression(DeviceState(camera_streaming=False, night=True), True) == "sleeping"
    assert resting_expression(DeviceState(camera_streaming=True, night=True), True) == "sleepy"
