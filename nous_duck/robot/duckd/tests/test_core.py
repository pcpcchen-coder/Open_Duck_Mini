"""duckd 核心：hello、心跳、每個 command 恰好一個 ack、重複 request_id、state、event、租約。

對手是測試自己組的訊息（等於假的 Nous，mock）；身體是 MockBody（mock）。
"""
import inspect
import json

import pytest
from conftest import PROTOCOL, REPO, make_harness

from duckd import core as core_mod
from duckd.body import MockBody


def test_hello_is_valid_and_honest(h):
    hello = h.sent[0]
    assert hello["type"] == "hello" and hello["role"] == "duck" and hello["mock"] is True
    caps = hello["capabilities"]
    assert caps["head"]["status"] == "mock"
    assert caps["walk"]["status"] == "unsupported" and "feet" in caps["walk"]["reason"]
    for missing in ("antennas", "speaker", "microphone", "camera", "navigation", "dock", "imu", "feet", "tracking_face"):
        assert caps[missing]["status"] == "unsupported", missing
    assert caps["eyes"]["status"] == "unsupported"  # 這個測試沒有開眼睛渲染
    assert "available" not in {c["status"] for c in caps.values()}  # mock 身體不能回報 available
    assert hello["gestures"] == ["look_around", "nod", "shake", "tilt"]
    assert hello["sounds"] == [] and hello["expressions"] == []


def test_not_engaged_reports_head_unsupported_and_rejects_motion():
    h = make_harness(engage=False)
    assert h.sent[0]["capabilities"]["head"]["status"] == "unsupported"
    assert h.sent[0]["gestures"] == []
    assert h.last_state()["mode"] == "limp" and "head" not in h.last_state()
    assert h.cmd("look", {"head_yaw": 0.1})["reason"] == "unsupported"
    assert h.cmd("gesture", {"name": "nod"})["reason"] == "unsupported"
    assert h.body.setpoints == []


def test_heartbeat_is_echoed(h):
    out = h.raw({"type": "heartbeat", "seq": 41})
    assert [m for m in out if m["type"] == "heartbeat"] == [{**out[0], "seq": 41, "echo_of": 41}]


def test_every_schema_action_gets_exactly_one_valid_ack(h):
    """schema 裡的每個 action（含還不支援的）都回恰好一個合 schema 的 ack。"""
    params = {
        "walk": {"vx": 0.05, "duration_s": 1.0}, "look": {"head_yaw": 0.1}, "track": {"target": "face"},
        "gesture": {"name": "nod"}, "express": {"expression": "happy"}, "antennas": {"left": 0.5},
        "sound": {"name": "quack_hello"}, "presence": {"state": "listening"}, "go_to": {"place": "brother_room"},
    }
    seen = {}
    for action in sorted(PROTOCOL.actions):
        ack = h.cmd(action, params.get(action))
        seen[action] = (ack["status"], ack.get("reason"))
    assert seen["status"] == ("accepted", None) and seen["stop"] == ("accepted", None)
    assert seen["look"] == ("accepted", None) or seen["look"][1] is None
    for action in ("walk", "antennas", "sound", "express", "track", "go_to", "find_person", "return_home", "follow_me", "wait_here", "where", "places"):
        assert seen[action] == ("rejected", "unsupported"), action
    assert seen["cancel_mission"] == seen["mission_status"] == ("rejected", "no_mission")
    assert len([m for m in h.sent if m["type"] == "ack"]) == len(PROTOCOL.actions)


EXAMPLES = REPO / "nous_duck" / "protocol" / "examples" / "valid.jsonl"


@pytest.mark.skipif(not EXAMPLES.exists(), reason="協定範例不在（Pi 部署目錄）")
def test_valid_examples_from_protocol_all_get_one_ack(h):
    lines = EXAMPLES.read_text(encoding="utf-8").splitlines()
    commands = [json.loads(line) for line in lines if '"type":"command"' in line]
    assert len(commands) >= 8
    for msg in commands:
        out = h._keep(h.core.on_text(json.dumps(msg), h.t))
        assert [m["request_id"] for m in out if m["type"] == "ack"] == [msg["request_id"]]


def test_duplicate_request_id_returns_original_ack_without_re_executing(h):
    first = h.cmd("look", {"head_yaw": 0.3}, rid="req_dup_0001")
    assert first["status"] == "accepted"
    n = h.core.stats["commands"]
    h.run(0.2)
    # 同一個 request_id、不同內容：不執行，回原本的 ack
    again = h.cmd("look", {"head_yaw": -0.3}, rid="req_dup_0001")
    assert again == first
    assert h.core.stats["commands"] == n
    assert h.arbiter.head_goal["head_yaw"] == pytest.approx(0.3)


def test_schema_invalid_command_is_rejected_invalid(h):
    out = h.core.on_text(json.dumps({"protocol_version": "0.1", "type": "command", "sent_at_ms": 1, "request_id": "req_bad_0001", "action": "torque_off", "ttl_ms": 1000}), h.t)
    assert out[0]["status"] == "rejected" and out[0]["reason"] == "invalid"
    out = h.core.on_text(json.dumps({"protocol_version": "9.0", "type": "command", "sent_at_ms": 1, "request_id": "req_bad_0002", "action": "stop", "ttl_ms": 1000}), h.t)
    assert out[0]["reason"] == "invalid" and "protocol_version" in out[0]["detail"]
    assert h.core.on_text("not json", h.t) == [] and h.core.on_text('{"type":"heartbeat"}', h.t) == []
    assert h.core.invalid_messages == 4
    # look 的參數多了不認得的關節
    assert h.cmd("look", {"left_knee": 0.3})["reason"] == "invalid"
    assert h.body.setpoints[-1]["head_yaw"] == 0.0


def test_expired_command_is_dropped(h):
    msg = {"protocol_version": "0.1", "type": "command", "sent_at_ms": 1, "request_id": "req_old_0001", "action": "look", "ttl_ms": 500, "params": {"head_yaw": 0.3}}
    out = h.core.on_text(json.dumps(msg), h.t, received_at=h.t - 0.6)
    assert out[0]["status"] == "rejected" and out[0]["reason"] == "expired"
    assert h.arbiter.head_goal["head_yaw"] == 0.0


def test_look_moves_mock_head_and_state_reads_back(h):
    ack = h.cmd("look", {"head_yaw": 0.3, "head_pitch": -0.1, "duration_s": 1.0})
    assert ack["status"] == "accepted" and ack["applied"] == {"head_yaw": 0.3, "head_pitch": -0.1, "duration_s": 1.0}
    h.run(1.5)
    st = h.last_state()
    assert st["mock"] is True and st["mode"] == "holding" and st["control_source"] == "duck_link"
    assert st["head"]["head_yaw"] == pytest.approx(0.3, abs=0.01) and st["head"]["head_pitch"] == pytest.approx(-0.1, abs=0.01)
    assert st["link"] == {"lease_ok": True, "rtt_ms": None}
    assert h.core.motion_latency_ms and h.core.motion_latency_ms[0] <= 40.0


def test_look_out_of_range_reports_clamped(h):
    ack = h.cmd("look", {"head_yaw": 3.0})
    assert ack["clamped"] is True and ack["applied"]["head_yaw"] == 0.5


def test_state_at_least_once_per_second_and_after_accepted_command(h):
    h.sent.clear()
    h.run(3.0)
    states = [m for m in h.sent if m["type"] == "state"]
    assert 3 <= len(states) <= 4
    h.sent.clear()
    h.cmd("look", {"head_yaw": 0.1})
    h.tick()
    assert [m["type"] for m in h.sent].count("state") == 1


def test_lease_expiry_stops_motion_and_reports_after_reconnect(h):
    h.cmd("look", {"head_yaw": 0.5, "duration_s": 5.0}, ttl_ms=60000)
    h.run(0.5)
    h.heartbeats = False
    h.sent.clear()
    h.run(2.0)
    assert [e["event"] for e in h.events()] == ["link_lost"]
    assert h.last_state()["link"]["lease_ok"] is False and h.last_state()["control_source"] == "none"
    frozen = h.arbiter.head_cmd["head_yaw"]
    assert 0.05 < frozen < 0.25
    assert h.cmd("look", {"head_yaw": 0.0})["reason"] == "link_degraded"
    assert h.cmd("gesture", {"name": "nod"})["reason"] == "link_degraded"
    assert h.cmd("presence", {"state": "speaking"})["reason"] == "link_degraded"
    assert h.cmd("stop")["status"] == "accepted"  # stop 永遠接受
    h.heartbeats = True
    h.run(1.0)
    assert [e["event"] for e in h.events()] == ["link_lost", "link_restored"]
    assert h.arbiter.head_cmd["head_yaw"] == pytest.approx(frozen)  # 沒有自動繼續


def test_socket_close_events_are_delivered_after_reconnect(h):
    h.cmd("gesture", {"name": "nod"})
    h.run(0.4)
    h.core.on_close(h.t)
    h.heartbeats = False
    h.sent.clear()
    assert h.run(1.0) == []  # 斷線中不送任何東西
    frozen = dict(h.arbiter.head_cmd)
    h.run(1.0)
    assert h.arbiter.head_cmd == frozen and not h.core.player.active
    h.open()
    assert [m["type"] for m in h.sent[:1]] == ["hello"]
    assert [e["event"] for e in h.events()] == ["gesture_done", "link_lost"]
    assert h.events("gesture_done")[0]["reason"] == "link_lost" and h.events("gesture_done")[0]["data"]["completed"] is False
    h.heartbeats = True
    h.run(0.6)
    assert [e["event"] for e in h.events()][-1] == "link_restored"


def test_stop_cancels_everything(h):
    h.cmd("gesture", {"name": "shake"})
    h.run(0.5)
    assert h.cmd("stop")["status"] == "accepted"
    assert h.events("gesture_done")[-1]["reason"] == "stop"
    before = dict(h.arbiter.head_cmd)
    h.run(1.0)
    assert h.arbiter.head_cmd == before
    assert h.cmd("look", {"head_yaw": 0.0})["status"] == "accepted"  # stop 之後新的明確指令可以做


def test_estop_latches_and_protocol_cannot_clear_it(h):
    h.cmd("look", {"head_yaw": 0.4}, ttl_ms=60000)
    h.run(0.3)
    h.core.local_estop("test operator", h.t)
    h.run(0.2)
    assert h.events("estop") and h.last_state()["mode"] == "estop" and "estop_latched" in h.last_state()["faults"]
    for action, params in (("look", {"head_yaw": 0.0}), ("gesture", {"name": "nod"}), ("resume", None)):
        assert h.cmd(action, params)["reason"] == "estop_latched", action
    assert h.cmd("stop")["status"] == "accepted"
    assert h.cmd("status")["data"]["mode"] == "estop"
    # 協定裡沒有任何 action 能解除；程式裡處理指令的函式也不碰解除、扭力、接手／釋放
    src = "".join(inspect.getsource(getattr(core_mod.Duckd, n)) for n in dir(core_mod.Duckd) if n.startswith("_do_") or n in ("_command", "on_text"))
    for forbidden in ("clear_estop", "reset_estop", "reset_fallen", "engage(", "release(", "set_torque"):
        assert forbidden not in src, forbidden
    assert not {a for a in PROTOCOL.actions if "estop" in a or "torque" in a or "clear" in a}
    # 本機解除之後才行
    assert h.core.local_clear_estop()
    h.run(0.1)
    assert h.events("estop_cleared")
    assert h.cmd("look", {"head_yaw": 0.0})["status"] == "accepted"


def test_body_fault_estop_propagates():
    body = MockBody()
    h = make_harness(body=body)
    body.fault_estop = "自動：ID 31 溫度 66 °C"
    h.run(0.1)
    assert h.events("estop") and h.cmd("look", {"head_yaw": 0.1})["reason"] == "estop_latched"


def test_release_returns_head_to_engage_pose_without_link():
    body = MockBody(start={"head_yaw": 0.1})
    h = make_harness(body=body)
    h.cmd("look", {"head_yaw": 0.4}, ttl_ms=60000)
    h.run(1.5)
    h.core.on_close(h.t)  # 沒有連線也要能收尾
    h.heartbeats = False
    assert h.core.begin_release(h.t)
    assert h.cmd("look", {"head_yaw": 0.0})["reason"] in ("unsupported", "link_degraded")
    h.run(3.0)
    assert not h.core.engaged and not body.engaged
    assert body.head["head_yaw"] == pytest.approx(0.1, abs=0.03)
    assert h.core.capabilities()["head"]["status"] == "unsupported"
