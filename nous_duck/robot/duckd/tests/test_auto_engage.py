"""「對話時讓頭出力」（ADR-0014 補充 §A）：全部用 mock（舵機控制台的模擬匯流排、假 hub），**不是實機驗證**。

最重要的一項：開關**預設關**，關著的時候不管 Nous 送什麼 presence，duckd 都**不會打開匯流排**。
"""
import json

import pytest
from conftest import make_harness

from duckd import core as core_mod
from duckd.head_real import HEAD_IDS, HeadBody
from duckd.limits import LEG_SERVO_IDS, Limits

from servo_console.bus import MockBus

ALL_IDS = sorted(LEG_SERVO_IDS | HEAD_IDS)


class Opens:
    """包住匯流排工廠：數有幾次打開匯流排。"""

    def __init__(self, head_torque=True, legs_torque=True):
        self.n = 0
        self.bus = MockBus(ALL_IDS)
        for i in HEAD_IDS:
            self.bus.torque[i] = head_torque
        for i in LEG_SERVO_IDS:
            self.bus.torque[i] = legs_torque
        orig = self.bus.open

        def counted_open():
            self.n += 1
            orig()

        self.bus.open = counted_open

    def __call__(self):
        return self.bus


def head_body(tmp_path, opens, port_users=lambda: []):
    cfg = tmp_path / "duck_config.json"
    cfg.write_text(json.dumps({"joints_offsets": {}}))
    return HeadBody(Limits(), opens, cfg, port_users=port_users, mock=True)


def harness(tmp_path, *, auto=None, opens=None, port_users=lambda: []):
    opens = opens or Opens()
    body = head_body(tmp_path, opens, port_users)
    h = make_harness(body=body, engage=False)
    if auto is not None:
        h.core.apply_settings({"features.head_auto_engage": auto})
    return h, body, opens


def conversation(h, seconds_each=1.0):
    for state in ("wake", "listening", "thinking", "speaking"):
        ack = h.cmd("presence", {"state": state})
        assert ack["status"] == "accepted"
        h.run(seconds_each)


def test_default_off_never_opens_the_bus(tmp_path):
    h, body, opens = harness(tmp_path)  # 不套用設定＝內建預設
    assert h.core.features["head_auto_engage"] is False
    conversation(h)
    h.cmd("presence", {"state": "idle"})
    h.run(3.0)
    assert opens.n == 0  # 匯流排一次都沒打開
    assert not h.core.engaged
    assert h.core.auto_engage["state"] == "off"
    # 沒接手時，Nous 要求 look／gesture 一律明確拒絕（不是假成功）
    look = h.cmd("look", {"head_yaw": 0.1})
    assert look["status"] == "rejected" and look["reason"] == "unsupported" and "not engaged" in look["detail"]
    gesture = h.cmd("gesture", {"name": "nod"})
    assert gesture["status"] == "rejected" and gesture["reason"] == "unsupported"
    assert opens.n == 0


def test_explicit_off_setting_also_never_opens(tmp_path):
    h, body, opens = harness(tmp_path, auto=False)
    conversation(h)
    assert opens.n == 0 and not h.core.engaged


def test_on_engages_at_conversation_start_and_releases_after_idle(tmp_path):
    h, body, opens = harness(tmp_path, auto=True)
    h.run(1.0)
    assert opens.n == 0  # 開著但還沒有對話：不接手
    assert h.core.auto_engage["state"] == "waiting"
    h.cmd("presence", {"state": "listening"})
    h.run(0.2)
    assert opens.n == 1 and h.core.engaged
    assert h.core.auto_engage["state"] == "engaged"
    h.run(1.5)
    # listening：微微歪頭（presence 的頭部小動作）。模擬匯流排用真實時鐘限速，這裡只看目標與方向
    assert h.core.arbiter.head_goal["head_roll"] == pytest.approx(0.12, abs=0.01)
    assert h.core.reading.head["head_roll"] > 0.0
    h.cmd("presence", {"state": "idle"})
    h.run(core_mod.AUTO_RELEASE_IDLE_S - 5.0)
    assert h.core.engaged  # 對話結束後先留著（可能馬上又講話）
    h.run(15.0)
    assert not h.core.engaged
    assert h.core.auto_engage["releases"] == 1
    # 放開時恢復接手前的扭力狀態（這裡接手前頭部有出力，所以還是出力；不會突然垂下）
    assert all(opens.bus.torque[i] for i in HEAD_IDS)
    # 腿從頭到尾沒被寫過
    assert all(opens.bus.torque[i] for i in LEG_SERVO_IDS)


def test_head_was_limp_before_auto_engage_is_restored_to_limp(tmp_path):
    """接手前頭沒出力：自動接手時才開扭力，放開時先回到接手時的位置再關扭力（和本機 engage 一樣）。"""
    opens = Opens(head_torque=False)
    h, body, _ = harness(tmp_path, auto=True, opens=opens)
    h.cmd("presence", {"state": "wake"})
    h.run(0.5)
    assert all(opens.bus.torque[i] for i in HEAD_IDS)
    h.cmd("presence", {"state": "idle"})
    h.run(core_mod.AUTO_RELEASE_IDLE_S + 10.0)
    assert not h.core.engaged
    assert not any(opens.bus.torque[i] for i in HEAD_IDS)


def test_bus_busy_blocks_and_retries(tmp_path):
    users = [[(1070, "python -m servo_console")]]
    h, body, opens = harness(tmp_path, auto=True, port_users=lambda: users[0])
    h.cmd("presence", {"state": "listening"})
    h.run(0.5)
    assert not h.core.engaged and opens.n == 0
    st = h.core.auto_engage
    assert st["state"] == "blocked" and "servo_console" in st["reason"]
    inactive = h.core.settings_inactive()
    assert "自動接手失敗" in inactive["features.presence_head_motion"]
    users[0] = []  # 控制台放開了
    h.run(5.0)
    assert not h.core.engaged  # 還在等 AUTO_RETRY_S
    h.run(core_mod.AUTO_RETRY_S)
    assert h.core.engaged


def test_manual_engage_is_never_auto_released(tmp_path):
    h, body, opens = harness(tmp_path, auto=True)
    h.core.engage(h.t)
    h.cmd("presence", {"state": "idle"})
    h.run(core_mod.AUTO_RELEASE_IDLE_S + 10.0)
    assert h.core.engaged
    assert h.core.auto_engage["state"] == "manual"


def test_switching_off_releases_auto_engaged_head(tmp_path):
    h, body, opens = harness(tmp_path, auto=True)
    h.cmd("presence", {"state": "speaking"})
    h.run(0.5)
    assert h.core.engaged
    h.core.apply_settings({"features.head_auto_engage": False})
    h.run(3.0)
    assert not h.core.engaged


def test_inactive_reasons_for_settings_page(tmp_path):
    h, body, opens = harness(tmp_path, auto=False)
    out = h.core.settings_inactive()
    for k in ("features.presence_head_motion", "features.speaking_bob", "features.gestures", "features.track_sound"):
        assert "頭部沒有出力" in out[k]
    h.core.apply_settings({"features.head_auto_engage": True})
    h.cmd("presence", {"state": "speaking"})
    h.run(0.5)
    out = h.core.settings_inactive()
    assert "features.presence_head_motion" not in out
    assert "speech_level" in out["features.speaking_bob"]  # Nous 沒送音量
    assert "duck-doa" in out["features.track_sound"]  # 沒有聲音來源
    h.cmd("presence", {"state": "speaking", "speech_level": 0.5})
    h.run(0.2)
    assert "features.speaking_bob" not in h.core.settings_inactive()


def test_status_has_diagnostics(tmp_path):
    from duckd.localctl import handle

    h, body, opens = harness(tmp_path, auto=False)
    h.cmd("presence", {"state": "listening"})
    st = handle(h.core, None, {"cmd": "status"})
    assert st["commands_by_action"]["presence"] == 1
    assert st["presence_log"][-1]["state"] == "listening"
    assert st["auto_engage"]["state"] == "off"
    assert st["speech_level_seen"] == 0
