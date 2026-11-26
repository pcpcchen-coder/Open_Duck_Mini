"""HTTP：頁面、狀態、儲存與錯誤回報、存取限制、表情預覽、在鴨子上預覽。"""
import json
import os
import socket
import threading

import pytest

from duck_settings import schema
from duck_settings.reader import Watcher
from duck_settings.server import host_allowed, is_lan_address


def test_page_is_one_self_contained_file(served):
    c, _ = served()
    status, html = c.call("/", raw=True)
    text = html.decode("utf-8")
    assert status == 200 and "<title>鴨子設定</title>" in text
    # 資源全部內嵌：沒有外部的 script、樣式、圖片、字型
    import re

    assert not re.findall(r'(?:src|href)\s*=\s*["\'](?!#|data:)[^"\']+', text)
    assert "http://" not in text and "https://" not in text and "@import" not in text
    assert c.call("/healthz", raw=True) == (200, b"ok\n")


def test_state_lists_every_setting_with_value_default_range_and_effect(served):
    c, _ = served()
    status, st = c.call("/api/state")
    assert status == 200 and st["ok"] and st["revision"] == {"preference": 0, "measurement": 0}
    assert [s["id"] for s in st["sections"]] == ["features", "audio", "hearing", "head", "eyes", "privacy", "calibration"]
    by = {s["key"]: s for s in st["settings"]}
    assert set(by) == set(schema.BY_KEY)
    e = by["hearing.min_speech_energy"]
    assert (e["value"], e["default"], e["min"], e["max"], e["apply"], e["consumer"]) == (200000.0, 200000.0, 0.0, 5000000.0, "live", "duck-doa")
    assert e["effect"]["state"] == "service_down"  # 沒有服務在跑：照實說，不寫「已生效」
    blocked = by["audio.night_start"]
    assert blocked["writable"] is False and blocked["effect"]["state"] == "none" and blocked["blocked_by"]
    assert st["duckd"] == {"reachable": False} and st["access"] == {"token_required": False, "lan_only": True}
    assert any("緊急停止" in t for t in st["never_here"])


def test_save_roundtrip_and_real_reasons_on_failure(served, store):
    c, _ = served()
    rev = c.call("/api/state")[1]["revision"]
    status, r = c.call("/api/save", {"changes": {"hearing.min_speech_energy": 350000, "features.speaking_bob": False}, "base_revision": rev})
    assert status == 200 and set(r["changed"]) == {"hearing.min_speech_energy", "features.speaking_bob"}
    assert store.load().values["hearing.min_speech_energy"] == 350000.0
    status, r = c.call("/api/save", {"changes": {"head.speed_deg_s": 200, "audio.night_start": "23:00"}})
    assert status == 400 and set(r["errors"]) == {"head.speed_deg_s", "audio.night_start"} and "超出範圍" in r["errors"]["head.speed_deg_s"]
    status, r = c.call("/api/save", {"changes": {"hearing.recenter_s": 9}, "base_revision": rev})
    assert status == 409 and r["code"] == "conflict"
    status, r = c.call("/api/save", {"changes": {"privacy.sound_direction": False}})
    assert status == 200
    status, r = c.call("/api/save", {"changes": {"privacy.sound_direction": True}})
    assert status == 400 and "只能把隱私設定收緊" in r["error"]
    status, r = c.call("/api/save", {"changes": {"calibration.mic.front_angle_deg": 10}})
    assert status == 400
    assert c.call("/api/save", {"changes": {"calibration.mic.front_angle_deg": 10}, "confirm_measurements": True})[0] == 200
    status, r = c.call("/api/reset", {"keys": ["hearing.min_speech_energy", "privacy.sound_direction"]})
    assert status == 200 and set(r["changed"]) == {"hearing.min_speech_energy"} and "privacy.sound_direction" in r["skipped"]
    status, r = c.call("/api/restore_previous", {})
    assert status == 200 and store.load().values["hearing.min_speech_energy"] == 350000.0
    st = c.call("/api/state")[1]
    assert st["has_previous"] and st["changes"][0]["source"] == "web" and len(st["changes"]) >= 4
    assert c.call("/api/nope", {})[0] == 404


def test_write_failure_reports_the_real_reason(served, store):
    c, _ = served()
    store.directory.mkdir(parents=True, exist_ok=True)
    os.chmod(store.directory, 0o500)
    try:
        status, r = c.call("/api/save", {"changes": {"hearing.recenter_s": 9}})
    finally:
        os.chmod(store.directory, 0o700)
    if os.geteuid() != 0:  # root 不受權限限制
        assert status == 500 and r["code"] == "io" and "寫不進設定檔" in r["error"]
        assert store.load().values["hearing.recenter_s"] == 8.0


def test_posts_need_the_page_header_json_and_a_sane_host(served, store):
    c, _ = served()
    body = {"changes": {"hearing.recenter_s": 9}}
    assert c.call("/api/save", body, headers={"X-Duck-Settings": "0"})[0] == 403  # 別的網站的表單送不出這個標頭
    assert c.call("/api/save", body, headers={"Content-Type": "text/plain"})[0] == 403
    assert c.call("/api/save", body, headers={"Host": "evil.example.com"})[0] == 403  # DNS rebinding
    assert c.call("/api/state", headers={"Host": "evil.example.com"})[0] == 403
    assert c.call("/api/save", b"[1]")[0] == 400 and c.call("/api/save", b"{oops")[0] == 400
    assert c.call("/api/save", b"x" * 70000)[0] == 413
    assert store.load().values["hearing.recenter_s"] == 8.0
    # Origin：瀏覽器跨站送出時會帶別人的 Origin；沙箱或本機檔案是 null
    for origin in ("http://evil.example.com", "null", "https://127.0.0.1", "http://duck-pi4.local:9999"):
        assert c.call("/api/save", body, headers={"Origin": origin})[0] == 403, origin
    assert store.load().values["hearing.recenter_s"] == 8.0
    host = c.base.split("//", 1)[1]
    assert c.call("/api/save", body, headers={"Origin": "http://" + host})[0] == 200
    assert c.call("/api/save", {"changes": {"hearing.recenter_s": 10}}, headers={"Host": "duck-pi4.local:8081", "Origin": "http://duck-pi4.local:8081"})[0] == 200


def test_change_log_records_time_source_address_key_and_values(served, store):
    c, _ = served()
    c.call("/api/save", {"changes": {"hearing.recenter_s": 9, "features.gestures": False}})
    store.apply({"hearing.recenter_s": 11}, "local_cli")
    line = (store.directory / "changes.jsonl").read_text().splitlines()[0]
    entry = json.loads(line)
    assert entry["source"] == "web" and entry["from"] == "127.0.0.1" and entry["at"] > 1.7e9
    assert entry["changes"] == {"hearing.recenter_s": {"from": 8.0, "to": 9.0}, "features.gestures": {"from": True, "to": False}}
    shown = c.call("/api/state")[1]["changes"]
    assert [(e["source"], e["from"]) for e in shown] == [("local_cli", ""), ("web", "127.0.0.1")]
    # 被拒絕的請求不會留下「改了」的紀錄
    c.call("/api/save", {"changes": {"head.speed_deg_s": 999}})
    assert len((store.directory / "changes.jsonl").read_text().splitlines()) == 2


def test_no_credentials_are_ever_served(served, store, tmp_path):
    """頁面與 API 不顯示金鑰、權杖、Wi-Fi 密碼；開了 token 模式也不會把 token 送回來。"""
    c, _ = served(token="s3cret-token-value")
    c.call("/api/save", {"changes": {"hearing.recenter_s": 9}})
    blobs = [c.call(p, raw=True)[1].decode("utf-8") for p in ("/", "/api/state", "/api/expressions")]
    import re

    for blob in blobs:
        assert "s3cret-token-value" not in blob
        blob = re.sub(r"data:image/png;base64,[A-Za-z0-9+/=]+", "", blob)  # 預覽圖的 base64 會碰巧拼出任何字
        for word in ("password", "passwd", "psk", "ssid", "api_key", "apikey", "secret", "private_key"):
            assert word not in blob.lower(), word
    keys = " ".join(s["key"] for s in json.loads(blobs[1])["settings"])
    assert "token" not in keys and "wifi" not in keys


def test_only_lan_addresses_and_known_hosts():
    for ok in ("127.0.0.1", "192.168.1.20", "10.0.0.5", "172.16.3.4", "169.254.10.1", "::1", "fe80::1%wlan0", "fd00::5", "::ffff:192.168.1.9"):
        assert is_lan_address(ok), ok
    for bad in ("8.8.8.8", "1.1.1.1", "2001:4860:4860::8888", "::ffff:8.8.8.8", "garbage", ""):
        assert not is_lan_address(bad), bad
    for ok in ("192.168.1.20:8081", "duck-pi4.local:8081", "localhost:8765", "[fe80::1]:8081", socket.gethostname()):
        assert host_allowed(ok), ok
    for bad in ("evil.example.com", "duck-pi4.local.evil.com:8081", ""):
        assert not host_allowed(bad), bad
    assert host_allowed("duck.home.arpa", ("duck.home.arpa",))


def test_token_mode(served):
    c, _ = served(token="s3cret-token")
    assert c.call("/", raw=True)[0] == 200  # 頁面本身不含資料
    c.token = None
    assert c.call("/api/state")[0] == 401 and c.call("/api/save", {"changes": {"hearing.recenter_s": 9}})[0] == 401
    c.token = "s3cret-token"
    st = c.call("/api/state")[1]
    assert st["ok"] and st["access"]["token_required"] is True


def test_effects_follow_what_services_report(served, store):
    c, _ = served(services={"duckd": "active", "duck-doa": "active"})
    by = lambda: {s["key"]: s["effect"] for s in c.call("/api/state")[1]["settings"]}  # noqa: E731
    assert by()["head.speed_deg_s"]["state"] == "not_reading"  # 服務在跑但沒有回報：舊版程式
    w = Watcher(store.directory, "duckd")  # 這個測試行程假裝是 duckd（pid 活著）
    w.report({"head.speed_deg_s": 30.0, "hearing.settle_s": 1.0})
    e = by()
    assert e["head.speed_deg_s"]["state"] == "applied" and e["hearing.settle_s"]["state"] == "applied"
    assert e["hearing.recenter_s"]["state"] == "not_reading"  # 這個服務沒回報這一項
    c.call("/api/save", {"changes": {"head.speed_deg_s": 45, "hearing.settle_s": 1.5}})
    e = by()
    assert e["head.speed_deg_s"]["state"] == "restart_needed" and e["head.speed_deg_s"]["running"] == 30.0
    assert e["hearing.settle_s"]["state"] == "pending"
    # 回報的行程已經不在：不能算生效
    path = store.directory / "applied" / "duckd.json"
    doc = json.loads(path.read_text())
    doc["pid"] = 2 ** 22 + 12345
    path.write_text(json.dumps(doc))
    assert by()["head.speed_deg_s"]["state"] == "not_reading"


def test_expression_previews_are_rendered_by_duck_eyes(served):
    import duck_eyes

    c, _ = served()
    status, r = c.call("/api/expressions")
    assert status == 200 and r["available"] and r["mismatch"] == []
    assert [e["id"] for e in r["expressions"]] == list(duck_eyes.EXPRESSIONS) and len(r["expressions"]) == 25
    import base64

    seen = set()
    for e in r["expressions"]:
        png = base64.b64decode(e["png"].split(",", 1)[1])
        assert png[:8] == b"\x89PNG\r\n\x1a\n" and int.from_bytes(png[16:20], "big") == 200 and int.from_bytes(png[20:24], "big") == 96
        seen.add(png)
        assert e["social"] == (e["id"] in duck_eyes.NOUS_ALLOWED) and e["name"]
    assert len(seen) >= 23  # 圖是真的畫出來的，不是同一張


class FakeDuckd:
    """假的 duckd 本機控制介面（mock）：只回答 status 與 express。"""

    def __init__(self, path, can_express=True):
        self.path, self.can_express, self.requests = path, can_express, []
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(str(path))
        self.sock.listen(4)
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                req = json.loads(conn.makefile("r").readline())
                self.requests.append(req)
                if req["cmd"] == "status":
                    reply = {"ok": True, "engaged": False, "connected": False, "eyes": {"frames": 3} if self.can_express else None,
                             "can_express": self.can_express, "state": {"mode": "limp", "mock": True, "presence": "idle", "tracking": "none", "faults": []}}
                elif req["cmd"] == "express" and self.can_express:
                    reply = {"ok": True, "expression": req["name"], "panel": "virtual_png"}
                else:
                    reply = {"ok": False, "error": "eyes renderer is not running"}
                conn.sendall((json.dumps(reply) + "\n").encode())


def test_preview_on_duck_only_when_duckd_can(served, tmp_path):
    import tempfile

    c, _ = served()
    status, r = c.call("/api/preview_expression", {"name": "happy"})
    assert status == 503 and "duckd 沒在跑" in r["error"]  # 沒有 duckd：照實說不能
    with tempfile.TemporaryDirectory(dir="/tmp") as d:  # UNIX socket 路徑有長度上限
        fake = FakeDuckd(os.path.join(d, "duckd.sock"))
        c2, _ = served(duckd_sockets=(fake.path,))
        st = c2.call("/api/state")[1]["duckd"]
        assert st["reachable"] and st["can_preview_expression"] and st["mock"] and st["engaged"] is False
        status, r = c2.call("/api/preview_expression", {"name": "happy"})
        assert status == 200 and r == {"ok": True, "shown": "happy", "seconds": 5.0, "panel": "virtual_png"}
        assert fake.requests[-1] == {"cmd": "express", "name": "happy", "duration_s": 5.0}
        assert c2.call("/api/preview_expression", {"name": "../etc"})[0] == 400
        fake.sock.close()
        fake2 = FakeDuckd(os.path.join(d, "duckd2.sock"), can_express=False)
        c3, _ = served(duckd_sockets=(fake2.path,))
        assert c3.call("/api/state")[1]["duckd"]["can_preview_expression"] is False
        status, r = c3.call("/api/preview_expression", {"name": "happy"})
        assert status == 503 and "duckd 拒絕" in r["error"]
        fake2.sock.close()
