"""儲存：驗證、整批不寫、只收緊、量測值與偏好分開、上一版、手改壞掉的檔案。"""
import json

import pytest

from duck_settings import schema
from duck_settings.reader import Watcher, load
from duck_settings.store import SaveError, Store


def files(store):
    return {p.name for p in store.directory.iterdir()} if store.directory.exists() else set()


def test_defaults_when_nothing_is_stored(store):
    view = store.load()
    assert view.values == schema.defaults() and view.revision == {"preference": 0, "measurement": 0} and not view.problems


def test_save_validates_and_writes_only_preferences_file(store):
    r = store.apply({"hearing.min_speech_energy": 300000, "features.speaking_bob": False}, "web")
    assert r.changed == {"hearing.min_speech_energy": {"from": 200000.0, "to": 300000.0}, "features.speaking_bob": {"from": True, "to": False}}
    assert r.revision == {"preference": 1, "measurement": 0}
    doc = json.loads((store.directory / "settings.json").read_text())
    assert doc["schema_version"] == schema.SCHEMA_VERSION and doc["revision"] == 1 and doc["updated_by"] == "web"
    assert doc["values"] == {"hearing.min_speech_energy": 300000.0, "features.speaking_bob": False}
    assert "calibration.json" not in files(store)
    assert store.load().values["hearing.min_speech_energy"] == 300000.0


def test_one_bad_value_rejects_the_whole_batch_with_reasons(store):
    with pytest.raises(SaveError) as e:
        store.apply({"features.speaking_bob": False, "head.speed_deg_s": 120, "nope.x": 1, "hearing.recenter_s": "soon"}, "web")
    assert set(e.value.errors) == {"head.speed_deg_s", "nope.x", "hearing.recenter_s"}
    assert "超出範圍" in e.value.errors["head.speed_deg_s"] and e.value.errors["nope.x"] == "沒有這個設定"
    assert files(store) == set() and store.load().values == schema.defaults()  # 什麼都沒寫


def test_unimplemented_settings_cannot_be_written_by_anyone(store):
    for source in ("web", "duck_link", "local_cli"):
        for key, value in (("audio.volume_cap_day", 0.3), ("privacy.camera", False), ("features.wake_word", False), ("eyes.brightness", 0.5)):
            with pytest.raises(SaveError) as e:
                store.apply({key: value}, source)
            assert "還不能設定" in e.value.errors[key]
    assert files(store) == set()


def test_cross_rule_is_checked_against_the_merged_values(store):
    with pytest.raises(SaveError) as e:
        store.apply({"hearing.window_s": 1.0}, "web")  # settle 還是 1.0
    assert "來回擺" in str(e.value)
    store.apply({"hearing.window_s": 1.0, "hearing.settle_s": 1.2}, "web")
    with pytest.raises(SaveError):
        store.apply({"hearing.settle_s": 0.8}, "web")


def test_privacy_can_only_be_tightened_from_web_and_model(store):
    """ADR-0006 §3：收緊誰都可以；放寬不行（設定頁、模型），只有登入本機的人可以。"""
    store.apply({"privacy.sound_direction": False}, "web")  # 收緊：可以
    for source in ("web", "duck_link"):
        with pytest.raises(SaveError) as e:
            store.apply({"privacy.sound_direction": True}, source)
        assert "只能把隱私設定收緊" in e.value.errors["privacy.sound_direction"]
        assert store.load().values["privacy.sound_direction"] is False
    # 夾帶在其他合法變更裡也不行，而且整批不寫
    with pytest.raises(SaveError):
        store.apply({"features.gestures": False, "privacy.sound_direction": True}, "web")
    assert store.load().values["features.gestures"] is True
    r = store.apply({"privacy.sound_direction": True}, "local_cli")
    assert r.changed and store.load().values["privacy.sound_direction"] is True
    assert [c["source"] for c in store.changes()] == ["local_cli", "web"]


def test_reset_and_restore_never_loosen_privacy(store):
    store.apply({"hearing.recenter_s": 20}, "web")
    store.apply({"privacy.sound_direction": False, "hearing.deadzone_deg": 12}, "web")
    r = store.reset(["privacy.sound_direction", "hearing.deadzone_deg", "hearing.recenter_s", "calibration.mic.mount"], "web")
    assert set(r.changed) == {"hearing.deadzone_deg", "hearing.recenter_s"}
    assert "放寬隱私" in r.skipped["privacy.sound_direction"] and "量測值" in r.skipped["calibration.mic.mount"]
    v = store.load().values
    assert v["privacy.sound_direction"] is False and v["hearing.deadzone_deg"] == 8.0
    # 上一版裡隱私是「關」之前的版本嗎？還原也不能把它打開
    store2_prev = store.previous()
    assert store2_prev["values"]["privacy.sound_direction"] is False
    store.apply({"privacy.sound_direction": True}, "local_cli")
    store.apply({"privacy.sound_direction": False, "hearing.recenter_s": 30}, "web")  # 上一版＝隱私開著
    r = store.restore_previous("web")
    assert "privacy.sound_direction" in r.skipped and set(r.changed) == {"hearing.recenter_s"}
    assert store.load().values["privacy.sound_direction"] is False


def test_measurements_live_in_their_own_file_and_need_confirmation(store):
    with pytest.raises(SaveError) as e:
        store.apply({"calibration.mic.front_angle_deg": 176.9}, "web")
    assert "量測值" in e.value.errors["calibration.mic.front_angle_deg"]
    with pytest.raises(SaveError):
        store.apply({"calibration.mic.front_angle_deg": 176.9}, "duck_link", confirm_measurements=True)  # 模型不能改量測值
    store.apply({"calibration.mic.front_angle_deg": 176.9, "calibration.mic.calibrated": True}, "web", confirm_measurements=True)
    store.apply({"hearing.recenter_s": 12}, "web")
    cal = json.loads((store.directory / "calibration.json").read_text())
    pref = json.loads((store.directory / "settings.json").read_text())
    assert cal["values"] == {"calibration.mic.front_angle_deg": 176.9, "calibration.mic.calibrated": True}
    assert pref["values"] == {"hearing.recenter_s": 12.0}
    # 「回復預設」與「還原上一版」都不動量測值
    store.reset([s.key for s in schema.SETTINGS], "web")
    store.restore_previous("web")
    assert store.load().values["calibration.mic.front_angle_deg"] == 176.9
    assert json.loads((store.directory / "calibration.json").read_text()) == cal


def test_previous_version_is_kept_and_restorable(store):
    with pytest.raises(SaveError):
        store.restore_previous("web")
    store.apply({"hearing.recenter_s": 12}, "web")
    store.apply({"hearing.recenter_s": 20, "features.gestures": False}, "web")
    assert store.previous()["values"] == {"hearing.recenter_s": 12.0}
    r = store.restore_previous("web")
    assert r.changed == {"hearing.recenter_s": {"from": 20.0, "to": 12.0}, "features.gestures": {"from": False, "to": True}}
    assert store.load().values["hearing.recenter_s"] == 12.0
    # 第一次儲存的上一版是「全部預設」
    for i in range(30):
        store.apply({"hearing.recenter_s": 10 + i}, "web")
    assert len(list((store.directory / "history").glob("settings-*.json"))) == 20


def test_conflicting_edit_is_refused(store):
    base = store.load().revision
    store.apply({"hearing.recenter_s": 12}, "web", base_revision=base)
    with pytest.raises(SaveError) as e:
        store.apply({"hearing.recenter_s": 15}, "web", base_revision=base)
    assert e.value.code == "conflict" and store.load().values["hearing.recenter_s"] == 12.0


def test_hand_edited_or_corrupt_files_fall_back_to_defaults_and_say_so(store):
    store.directory.mkdir(parents=True)
    (store.directory / "settings.json").write_text(json.dumps({"schema_version": 1, "revision": 7, "values": {
        "head.speed_deg_s": 500, "hearing.recenter_s": 15, "features.track_sound": "yes", "from.the.future": 1,
        "calibration.mic.front_angle_deg": 90,  # 放錯檔案：不採用
    }}))
    view = load(store.directory)
    assert view.values["head.speed_deg_s"] == 30.0 and view.values["features.track_sound"] is True  # 不合格 → 預設，不夾限、不採用
    assert view.values["hearing.recenter_s"] == 15.0 and view.values["calibration.mic.front_angle_deg"] == 0.0
    assert len(view.problems) == 2 and view.revision["preference"] == 7
    (store.directory / "settings.json").write_text("{not json")
    view = load(store.directory)
    assert view.values == schema.defaults() and "不是合法的 JSON" in view.problems[0]
    (store.directory / "settings.json").write_text(json.dumps({"values": {"hearing.settle_s": 0.6, "hearing.window_s": 2.0}}))
    view = load(store.directory)
    assert (view.values["hearing.settle_s"], view.values["hearing.window_s"]) == (1.0, 0.5) and view.problems


def test_watcher_rereads_only_when_a_file_changes_and_reports_what_it_uses(store):
    w = Watcher(store.directory, "duck-doa")
    assert w.poll() is not None and w.poll() is None
    store.apply({"hearing.min_speech_energy": 123000}, "web")
    view = w.poll()
    assert view is not None and view["hearing.min_speech_energy"] == 123000.0 and w.poll() is None
    assert "hearing.min_speech_energy" in w.keys() and "head.speed_deg_s" not in w.keys()
    w.report({"hearing.min_speech_energy": 123000.0})
    path = store.directory / "applied" / "duck-doa.json"
    doc = json.loads(path.read_text())
    assert doc["values"] == {"hearing.min_speech_energy": 123000.0} and doc["revision"]["preference"] == 1
    mtime = path.stat().st_mtime_ns
    w.report({"hearing.min_speech_energy": 123000.0})  # 沒變就不重寫
    assert path.stat().st_mtime_ns == mtime


def test_cli_set_get_import(store, tmp_path, capsys):
    from duck_settings import cli

    d = ["--dir", str(store.directory)]
    assert cli.main(d + ["set", "hearing.recenter_s", "11"]) == 0
    assert cli.main(d + ["get", "hearing.recenter_s"]) == 0 and capsys.readouterr().out.strip().endswith("11.0")
    assert cli.main(d + ["set", "head.speed_deg_s", "999"]) == 1
    assert cli.main(d + ["set", "calibration.mic.mount", "desk"]) == 0  # 沒加引號的字串
    old = tmp_path / "doa.json"
    old.write_text(json.dumps({"front_angle_deg": 176.9, "counterclockwise": False, "mount": "head", "sample_hz": 20.0, "calibrated": True,
                               "speech_source": "energy", "min_speech_energy": 200000.0, "window_s": 0.5}))
    assert cli.main(d + ["import-doa", str(old)]) == 0
    v = store.load().values
    assert (v["calibration.mic.front_angle_deg"], v["calibration.mic.calibrated"], v["calibration.mic.mount"]) == (176.9, True, "head")
    assert "sample_hz" in capsys.readouterr().out  # 沒有對應設定的欄位照實列出
