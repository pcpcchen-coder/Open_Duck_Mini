"""聽聲辨位轉頭（T5）：死區、平滑、自噪音迴避、回正、轉到極限。聲音方位是測試合成的（mock）。"""
import json
import math

import pytest
from conftest import make_harness

from duckd.percept import Observation, PerceptInput
from duckd.track import SoundTrackConfig, SoundTracker

D = math.radians


def ob(t, deg, conf=0.9):
    return Observation("sound", D(deg), 0.0, None, conf, True, t)


def feed(tr, t0, deg, n=3, dt=0.1, moving=False):
    out, t = [], t0
    for _ in range(n):
        t += dt
        out.append(tr.update(ob(t, deg), t, moving))
    return t, out


def test_needs_two_consistent_bearings_then_turns():
    tr = SoundTracker()
    tr.reset(0.0)
    assert tr.update(ob(0.1, 20), 0.1, False) == (0.0, None)  # 一筆不夠
    yaw, what = tr.update(ob(0.2, 22), 0.2, False)
    assert what == "turn" and yaw == pytest.approx(D(21), abs=1e-6) and not tr.at_limit


def test_scattered_bearings_are_not_adopted():
    tr = SoundTracker()
    tr.reset(0.0)
    assert tr.update(ob(0.1, -25), 0.1, False)[1] is None
    assert tr.update(ob(0.2, 25), 0.2, False) == (0.0, None)  # 相差 50°：不採用


def test_deadzone_and_low_confidence():
    tr = SoundTracker()
    tr.reset(0.0)
    t, out = feed(tr, 0.0, 5)  # 5° < 死區 8°
    assert all(o == (0.0, None) for o in out)
    assert tr.update(ob(1.0, 20, conf=0.1), 1.0, False)[1] is None
    assert tr.update(ob(1.1, 20, conf=0.1), 1.1, False)[1] is None


def test_wraparound_uses_circular_mean():
    tr = SoundTracker(SoundTrackConfig(yaw_limit=math.pi))
    tr.reset(0.0)
    tr.update(ob(0.1, 178), 0.1, False)
    yaw, what = tr.update(ob(0.2, -178), 0.2, False)
    assert what == "turn" and abs(abs(yaw) - math.pi) < D(1)


def test_beyond_head_range_goes_to_limit_and_flags_it():
    tr = SoundTracker()
    tr.reset(0.0)
    t, out = feed(tr, 0.0, 120, n=2)
    assert out[-1] == (0.5, "turn") and tr.at_limit and tr.bearing == pytest.approx(D(120))
    t, out = feed(tr, t + 1.0, -150, n=2)
    assert out[-1] == (-0.5, "turn") and tr.at_limit


def test_bearings_heard_while_head_moves_are_ignored():
    tr = SoundTracker()
    tr.reset(0.0)
    t, out = feed(tr, 0.0, -40, n=4, moving=True)  # 頭在動：可能是舵機的聲音
    assert all(o == (0.0, None) for o in out) and tr.ignored_self_noise == 4
    t, out = feed(tr, t, -40, n=4)  # 剛停下 settle_s（1.0 s）內也不算
    assert out[3] == (0.0, None)
    t, out = feed(tr, t + 0.9, -40, n=3)
    assert ("turn" in [w for _, w in out]) and tr.target == -0.5  # 夾在頭部範圍


def test_recenters_after_quiet_period():
    tr = SoundTracker()
    tr.reset(0.0)
    t, _ = feed(tr, 0.0, 25, n=2)
    assert tr.target == pytest.approx(D(25))
    assert tr.update(None, t + 7.9, False) == (pytest.approx(D(25)), None)
    assert tr.update(None, t + 8.2, False) == (0.0, "recenter")
    assert tr.update(None, t + 9.0, False) == (0.0, None)  # 只回報一次


def test_same_observation_is_used_once():
    tr = SoundTracker()
    tr.reset(0.0)
    o = ob(0.1, 30)
    assert tr.update(o, 0.1, False)[1] is None
    assert tr.update(o, 0.12, False)[1] is None and tr.update(o, 0.14, False)[1] is None


# ---------------------------------------------------------------- 經過 duckd 核心
def datagram(deg, mock=True, frame="body"):
    return json.dumps({"v": 1, "kind": "sound", "frame": frame, "bearing_yaw_rad": D(deg), "bearing_pitch_rad": 0.0, "distance_m": None, "confidence": 0.8, "t_ms": 0, "mock": mock}).encode()


def status(ok=True, mock=True, detail=""):
    return json.dumps({"v": 1, "kind": "status", "source": "sound", "ok": ok, "mock": mock, "detail": detail}).encode()


class Rig:
    def __init__(self):
        self.t = [100.0]
        self.p = PerceptInput(lambda: self.t[0])
        self.h = make_harness(percept=self.p)
        # 聽聲轉頭只在對話中動（ADR-0014 補充 §B）：這些測試都在「在聽」的時候
        self.h.cmd("presence", {"state": "listening"})

    def run(self, seconds, speak_deg=None, alive=True):
        for i in range(round(seconds / 0.02)):
            self.t[0] = self.h.t
            if alive and i % 25 == 0:
                self.p.feed(status())
            if speak_deg is not None and i % 5 == 0:
                self.p.feed(datagram(speak_deg))
            self.h.run(0.02)


def test_capability_follows_source_liveness():
    r = Rig()
    assert r.h.core.capabilities()["tracking_sound"]["status"] == "unsupported"
    assert r.h.cmd("track", {"target": "sound"})["reason"] == "unsupported"
    r.p.feed(status())  # 安靜、但來源在
    assert r.h.core.capabilities()["tracking_sound"]["status"] == "mock"
    assert r.h.cmd("track", {"target": "sound"})["status"] == "accepted"
    r.p.feed(status(ok=False, detail="usb unplugged"))
    cap = r.h.core.capabilities()["tracking_sound"]
    assert cap["status"] == "unsupported" and "usb unplugged" in cap["reason"]
    r.p.feed(status(mock=False))
    assert r.h.core.capabilities()["tracking_sound"]["status"] == "degraded"  # 真的來源：未驗證前不是 available


def test_track_sound_turns_head_reports_limit_and_recenters():
    r = Rig()
    r.p.feed(status())
    ack = r.h.cmd("track", {"target": "sound", "body": True})
    assert ack["applied"] == {"target": "sound", "body": False} and ack["clamped"] is True  # 坐著不轉身
    r.run(2.0, speak_deg=20)
    assert r.h.body.head["head_yaw"] == pytest.approx(D(20), abs=0.02)
    ev = r.h.events("tracking_acquired")[0]["data"]
    assert ev["target"] == "sound" and ev["at_limit"] is False and ev["mock"] is True
    r.run(3.0, speak_deg=-100)  # 在頭轉不到的地方
    assert r.h.body.head["head_yaw"] == pytest.approx(-0.5, abs=0.02)
    last = r.h.events("tracking_acquired")[-1]["data"]
    assert last["at_limit"] is True and last["head_yaw_rad"] == -0.5 and last["bearing_rad"] == pytest.approx(D(-100), abs=0.01)
    assert r.h.core.sound.ignored_self_noise > 0  # 轉頭途中的方位被丟掉
    assert r.h.core.tracking == "sound"
    r.run(10.5)  # 安靜：不算追丟，8 s 後回正
    assert r.h.core.tracking == "sound"
    assert abs(r.h.body.head["head_yaw"]) < 0.02
    quiet = r.h.events("tracking_lost")[-1]
    assert quiet["reason"] == "quiet" and quiet["data"]["recentered"] is True


def test_source_disappearing_ends_tracking():
    r = Rig()
    r.p.feed(status())
    r.h.cmd("track", {"target": "sound"})
    r.run(1.0, speak_deg=20)
    r.run(6.0, alive=False)
    assert r.h.core.tracking == "none" and r.h.events("tracking_lost")


def test_head_does_not_chase_while_speaker_stays_put():
    r = Rig()
    r.p.feed(status())
    r.h.cmd("track", {"target": "sound"})
    r.run(6.0, speak_deg=25)
    assert len(r.h.events("tracking_acquired")) == 1  # 只轉一次，之後落在死區內
    yaws = [s["head_yaw"] for s in r.h.body.setpoints[-150:]]
    assert max(yaws) - min(yaws) < 1e-6


def test_stop_and_link_loss_end_sound_tracking():
    r = Rig()
    r.p.feed(status())
    r.h.cmd("track", {"target": "sound"})
    r.run(1.5, speak_deg=25)
    r.h.cmd("stop")
    assert r.h.core.tracking == "none"
    before = dict(r.h.arbiter.head_cmd)
    r.run(1.0, speak_deg=-25)
    assert r.h.arbiter.head_cmd == before


def test_head_mounted_mic_bearing_is_converted_with_current_head_yaw():
    """麥克風裝在頭上：人固定在身體左前方 30°，頭轉過去之後麥克風看到的方位變成 0，頭不應該再轉或轉回來。"""
    r = Rig()
    r.p.feed(status())
    r.h.cmd("track", {"target": "sound"})
    person = D(30)
    for i in range(300):
        r.t[0] = r.h.t
        if i % 25 == 0:
            r.p.feed(status())
        if i % 5 == 0:
            rel = person - r.h.body.head["head_yaw"]  # 麥克風（頭）看到的方位
            r.p.feed(datagram(math.degrees(rel), frame="head"))
        r.h.run(0.02)
    assert r.h.body.head["head_yaw"] == pytest.approx(D(30) if D(30) <= 0.5 else 0.5, abs=0.03)
    assert len(r.h.events("tracking_acquired")) == 1


def test_sound_tracking_pauses_outside_conversation():
    """對話外（idle）頭不跟著聲音轉，回到對話才繼續（電視開著也不會被帶走）。"""
    r = Rig()
    r.run(0.5)  # 聲音來源先回報存活
    assert r.h.cmd("track", {"target": "sound"})["status"] == "accepted"
    r.h.cmd("presence", {"state": "idle"})
    r.run(3.0, speak_deg=20.0)
    assert r.h.core.tracking == "sound" and r.h.core.tracking_paused
    assert abs(r.h.arbiter.head_goal["head_yaw"]) < 0.01
    r.h.cmd("presence", {"state": "listening"})
    r.run(3.0, speak_deg=20.0)
    assert not r.h.core.tracking_paused
    assert r.h.arbiter.head_goal["head_yaw"] > 0.1
