"""語音對話狀態機（純邏輯）。重點是紅線：什麼時候音訊可以離開鴨子。"""

import pytest

from duck_audio.session import SessionConfig, State, VoiceSession


def kinds(actions):
    return [(a.kind, a.data.get("type") or a.data.get("name") or a.data.get("state") or a.data.get("on")) for a in actions]


def sends(actions):
    return [a.data for a in actions if a.kind == "send"]


def connected(**cfg):
    s = VoiceSession(SessionConfig(**cfg))
    s.on_link(True, 0.0)
    return s


def test_idle_never_uplinks():
    s = connected()
    assert not any(s.on_mic_frame(i * 0.02, True) for i in range(500))
    assert s.frames_up == 0 and s.frames_blocked == 500


def test_wake_starts_turn_after_cue_and_uplinks_only_while_listening():
    s = connected()
    acts = s.on_wake(1.0, "HEY_YAZI", None)
    assert kinds(acts)[0] == ("sfx", "listen_on")
    assert sends(acts) == [{"type": "turn_start", "turn_id": 1, "trigger": "wake_word", "keyword_id": "HEY_YAZI", "doa_deg": None}]
    assert ("uplink", True) in kinds(acts) and ("kws", False) in kinds(acts)
    assert s.state is State.LISTENING and s.on_mic_frame(1.1, True)
    acts = s.on_remote({"type": "listen_stop", "turn_id": 1}, 3.0)
    assert sends(acts) == [{"type": "turn_end", "turn_id": 1, "reason": "remote"}] and s.state is State.WAITING
    assert not s.on_mic_frame(3.1, True)  # 等回話時不上行


def test_wake_without_link_does_not_listen():
    s = VoiceSession()
    acts = s.on_wake(1.0, "HEY_YAZI")
    assert s.state is State.IDLE and sends(acts) == [] and ("sfx", "confused_hm") in kinds(acts)
    assert not s.on_mic_frame(1.1, True)


def test_second_wake_during_turn_is_ignored():
    s = connected()
    s.on_wake(1.0, "HEY_YAZI")
    assert s.on_wake(1.5, "HEY_YAZI") == [] and s.turn_id == 1


@pytest.mark.parametrize(
    "speech_until,expect_reason,expect_state,t_end",
    [(None, "no_speech", State.IDLE, 8.0), (3.0, "silence", State.WAITING, 4.5)],
)
def test_local_timeouts_close_uplink(speech_until, expect_reason, expect_state, t_end):
    s = connected()
    s.on_wake(0.0, "HEY_YAZI")
    t, ended = 0.0, None
    while t < 40 and ended is None:
        t = round(t + 0.02, 2)
        s.on_mic_frame(t, speech_until is not None and t <= speech_until)
        acts = s.tick(t)
        if sends(acts):
            ended = (sends(acts)[0], t)
    assert ended[0] == {"type": "turn_end", "turn_id": 1, "reason": expect_reason}
    assert ended[1] == pytest.approx(t_end, abs=0.05) and s.state is expect_state
    assert not s.on_mic_frame(t + 0.02, True)


def test_max_duration_even_if_speech_never_stops():
    s = connected(max_listen_s=5.0)
    s.on_wake(0.0, "HEY_YAZI")
    t = 0.0
    while s.state is State.LISTENING and t < 20:
        t = round(t + 0.02, 2)
        s.on_mic_frame(t, True)
        acts = s.tick(t)
    assert t == pytest.approx(5.0, abs=0.05) and sends(acts)[0]["reason"] == "max_duration"


def test_reply_playback_and_return_to_idle():
    s = connected()
    s.on_wake(0.0, "HEY_YAZI")
    s.on_remote({"type": "listen_stop", "turn_id": 1}, 2.0)
    assert not s.accepts_downlink()
    acts = s.on_remote({"type": "speak_start", "turn_id": 1}, 2.5)
    assert s.state is State.SPEAKING and s.accepts_downlink() and ("kws", False) in kinds(acts)
    assert sends(s.on_playback_started()) == [{"type": "playback", "turn_id": 1, "state": "started"}]
    s.on_remote({"type": "speak_end", "turn_id": 1}, 5.0)
    assert not s.accepts_downlink()
    assert s.tick(6.0) == [] and s.state is State.SPEAKING  # 還沒真的播完
    assert sends(s.on_playback_done(6.5)) == [{"type": "playback", "turn_id": 1, "state": "finished"}]
    assert s.tick(7.0) == []
    acts = s.tick(7.6)
    assert s.state is State.IDLE and ("kws", True) in kinds(acts)


def test_speak_start_while_listening_closes_uplink_first():
    s = connected()
    s.on_wake(0.0, "HEY_YAZI")
    acts = s.on_remote({"type": "speak_start", "turn_id": 1}, 2.0)
    assert sends(acts)[0] == {"type": "turn_end", "turn_id": 1, "reason": "remote"} and s.state is State.SPEAKING


def test_remote_cannot_open_mic_from_idle_and_stale_turn_ids_ignored():
    s = connected()
    assert s.on_remote({"type": "listen", "turn_id": 9}, 1.0) == [] and s.state is State.IDLE
    assert s.on_remote({"type": "speak_start", "turn_id": 1}, 1.0) == [] and s.state is State.IDLE
    s.on_wake(2.0, "HEY_YAZI")
    assert s.on_remote({"type": "listen_stop", "turn_id": 7}, 3.0) == [] and s.state is State.LISTENING
    assert s.on_remote({"type": "nonsense"}, 3.0) == [] and s.on_remote({}, 3.0) == []


def test_follow_up_listen_only_right_after_reply():
    s = connected()
    s.on_wake(0.0, "HEY_YAZI")
    s.on_remote({"type": "speak_start", "turn_id": 1}, 2.0)
    assert s.on_remote({"type": "listen"}, 2.5) == []  # 還在播：不接受
    s.on_remote({"type": "speak_end", "turn_id": 1}, 4.0)
    s.on_playback_done(4.5)
    acts = s.on_remote({"type": "listen"}, 4.8)
    assert s.state is State.LISTENING and s.turn_id == 2
    assert sends(acts)[0]["trigger"] == "follow_up" and sends(acts)[0]["keyword_id"] is None


def test_reply_timeout_and_link_loss():
    s = connected(reply_timeout_s=5.0)
    s.on_wake(0.0, "HEY_YAZI")
    s.on_remote({"type": "listen_stop", "turn_id": 1}, 1.0)
    assert s.tick(5.9) == []
    acts = s.tick(6.1)
    assert s.state is State.IDLE and ("sfx", "confused_hm") in kinds(acts)
    s.on_wake(10.0, "HEY_YAZI")
    acts = s.on_link(False, 11.0)
    assert s.state is State.IDLE and ("uplink", False) in kinds(acts) and ("flush_playback", None) in kinds(acts)
    assert not s.on_mic_frame(11.1, True)


def test_flush_and_session_end():
    s = connected()
    s.on_wake(0.0, "HEY_YAZI")
    s.on_remote({"type": "speak_start", "turn_id": 1}, 1.0)
    acts = s.on_remote({"type": "flush"}, 2.0)
    assert ("flush_playback", None) in kinds(acts) and not s.accepts_downlink()
    acts = s.on_remote({"type": "session_end"}, 2.1)
    assert s.state is State.IDLE


def test_disable_stops_everything_and_blocks_wake():
    s = connected()
    s.on_wake(0.0, "HEY_YAZI")
    acts = s.set_enabled(False, 1.0)
    assert s.state is State.DISABLED and sends(acts)[0]["reason"] == "cancelled" and ("kws", False) in kinds(acts)
    assert s.on_wake(2.0, "HEY_YAZI") == [] and not s.on_mic_frame(2.0, True)
    assert ("kws", True) in kinds(s.set_enabled(True, 3.0)) and s.state is State.IDLE


def test_barge_in_only_when_enabled():
    s = connected()
    s.on_wake(0.0, "HEY_YAZI")
    s.on_remote({"type": "speak_start", "turn_id": 1}, 1.0)
    assert s.on_wake(2.0, "HEY_YAZI") == []  # 預設半雙工
    b = connected(barge_in=True)
    b.on_wake(0.0, "HEY_YAZI")
    acts = b.on_remote({"type": "speak_start", "turn_id": 1}, 1.0)
    assert ("kws", True) in kinds(acts)
    acts = b.on_wake(2.0, "HEY_YAZI")
    assert ("flush_playback", None) in kinds(acts) and b.state is State.LISTENING and b.turn_id == 2
