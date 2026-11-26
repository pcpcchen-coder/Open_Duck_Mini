"""聲源方位服務讀鴨子設定（ADR-0019）：值的對應、執行中換設定、關掉時不讀裝置、校正結果寫進設定。

麥克風是模擬的（`MockDoaReader`，mock）；設定檔用真的 `duck_settings.store.Store` 寫。
"""
import json
import sys
from pathlib import Path

import pytest

ROBOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROBOT / "settings"))

from duck_audio import doa  # noqa: E402
from duck_audio.doa import DoaConfig, DoaService, DoaSettings, MockDoaReader, config_from_settings  # noqa: E402
from duck_settings import schema  # noqa: E402
from duck_settings.store import Store  # noqa: E402


def test_defaults_from_settings_equal_the_shipped_doa_json():
    cfg, enabled = config_from_settings(schema.defaults())
    shipped = DoaConfig.load(ROBOT / "audio" / "config" / "doa.json")
    assert cfg == shipped and enabled is True


def test_every_mapped_value_reaches_the_config(tmp_path):
    Store(tmp_path).apply({
        "hearing.min_speech_energy": 350000, "hearing.speech_source": "flag", "hearing.window_s": 0.8, "hearing.settle_s": 1.5,
        "hearing.min_speech_samples": 6, "hearing.cluster_tolerance_deg": 30, "calibration.mic.mount": "desk",
        "calibration.mic.front_angle_deg": 176.9, "calibration.mic.counterclockwise": True, "calibration.mic.calibrated": True,
        "privacy.sound_direction": False,
    }, "local_cli")
    s = DoaSettings(tmp_path)
    cfg, enabled = s.current()
    assert enabled is False
    assert (cfg.min_speech_energy, cfg.speech_source, cfg.window_s, cfg.min_speech_samples, cfg.cluster_tolerance_deg) == (350000.0, "flag", 0.8, 6, 30.0)
    assert (cfg.mount, cfg.front_angle_deg, cfg.counterclockwise, cfg.calibrated) == ("desk", 176.9, True, True)
    assert (cfg.sample_hz, cfg.publish_hz) == (20.0, 10.0)  # 不在設定裡的維持內建值
    s.report(cfg, enabled)
    report = json.loads((tmp_path / "applied" / "duck-doa.json").read_text())
    assert set(report["values"]) == {k.key for k in schema.SETTINGS if k.consumer == "duck-doa"}
    assert s.poll() is None  # 沒變就不重讀


def test_set_config_changes_a_running_service():
    class Clock:
        t = 0.0

        def __call__(self):
            return self.t

    clock, sent = Clock(), []
    reader = MockDoaReader(angle_deg=30, speech=True)
    svc = DoaService(reader, DoaConfig(front_angle_deg=0, counterclockwise=True, mount="body"), sent.append, clock=clock)
    for _ in range(20):
        svc.step()
        clock.t += 0.05
    first = [json.loads(m) for m in sent if b'"kind": "sound"' in m][-1]
    assert first["frame"] == "body" and first["bearing_yaw_rad"] == pytest.approx(0.5236, abs=1e-3)
    svc.set_config(DoaConfig(front_angle_deg=10, counterclockwise=False, mount="head"))
    sent.clear()
    for _ in range(20):
        svc.step()
        clock.t += 0.05
    after = [json.loads(m) for m in sent if b'"kind": "sound"' in m][-1]
    assert after["frame"] == "head" and after["bearing_yaw_rad"] == pytest.approx(-0.3491, abs=1e-3)


def test_calibrate_writes_into_settings_not_doa_json(tmp_path, monkeypatch, capsys):
    legacy = tmp_path / "doa.json"
    legacy.write_text(json.dumps({"front_angle_deg": 5.0, "mount": "desk"}))
    sdir = tmp_path / "settings"
    monkeypatch.setattr(doa, "MockDoaReader", lambda angle: MockDoaReader(angle_deg=angle, speech=True))
    monkeypatch.setattr(sys, "argv", ["doa", "--calibrate", "0.3", "--write-config", "--mock-angle", "123", "--config", str(legacy), "--settings-dir", str(sdir)])
    assert doa.main() == 0
    v = Store(sdir).load().values
    assert v["calibration.mic.front_angle_deg"] == 123.0 and v["calibration.mic.calibrated"] is True
    assert json.loads(legacy.read_text()) == {"front_angle_deg": 5.0, "mount": "desk"}  # 舊檔不動
    assert Store(sdir).changes()[0]["source"] == "local_cli"


def test_missing_settings_package_falls_back_to_doa_json(tmp_path, monkeypatch, capsys):
    legacy = tmp_path / "doa.json"
    legacy.write_text(json.dumps({"front_angle_deg": 77.0, "mount": "desk", "calibrated": True}))

    def boom(*a, **k):
        raise ImportError("No module named 'duck_settings'")

    monkeypatch.setattr(doa, "DoaSettings", boom)
    monkeypatch.setattr(sys, "argv", ["doa", "--probe", "--mock-angle", "5", "--config", str(legacy), "--settings-dir", str(tmp_path / "s")])
    assert doa.main() == 0
    out = capsys.readouterr()
    assert json.loads(out.out)["config"]["front_angle_deg"] == 77.0 and "讀不到鴨子設定" in out.err
