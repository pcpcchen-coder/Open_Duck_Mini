"""端到端（模擬麥克風，mock）：設定頁存檔 → 執行中的聲源方位服務約 1 秒內換成新值 → 設定頁顯示「已生效」。

真的部分：HTTP 伺服器、設定檔、`duck_audio.doa.run_forever` 的常駐迴圈、UDP 訊息。
假的部分：麥克風（`MockDoaReader`，訊息帶 `mock: true`）。沒有碰任何硬體。
"""
import json
import socket
import threading
import time

from duck_audio import doa


class CountingReader(doa.MockDoaReader):
    """模擬麥克風（mock）：有語音能量可讀，並記下被讀了幾次、被關了幾次。"""

    opened = 0
    closed = 0

    def __init__(self):
        super().__init__(angle_deg=40.0)
        self.energy = 250000.0
        type(self).opened += 1

    def read_energy(self):
        self.reads += 1
        return self.angle_deg, self.energy

    def close(self):
        type(self).closed += 1


def wait_for(cond, timeout=6.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = cond()
        if v:
            return v
        time.sleep(0.05)
    return cond()


def effect(client, key):
    return {s["key"]: s for s in client.call("/api/state")[1]["settings"]}[key]["effect"]


def test_page_save_reaches_running_doa_service_and_privacy_off_stops_reading(served, store):
    client, _ = served()
    assert client.call("/api/save", {"changes": {"calibration.mic.front_angle_deg": 10.0, "calibration.mic.mount": "body"},
                                     "confirm_measurements": True})[0] == 200
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(0.2)
    got: list[dict] = []
    stop = threading.Event()
    CountingReader.opened = CountingReader.closed = 0
    readers: list[CountingReader] = []

    def open_reader():
        readers.append(CountingReader())
        return readers[-1]

    def pump():
        while not stop.is_set():
            try:
                got.append(json.loads(rx.recvfrom(4096)[0]))
            except socket.timeout:
                pass

    threading.Thread(target=pump, daemon=True).start()
    settings = doa.DoaSettings(store.directory)
    th = threading.Thread(target=doa.run_forever, args=(doa.DoaConfig(), rx.getsockname()),
                          kwargs={"open_reader": open_reader, "stop": stop.is_set, "settings": settings}, daemon=True)
    th.start()
    try:
        # 1. 服務用的是設定裡的值（不是 DoaConfig 的內建預設）：正前方 10° → 方位 = −(40−10)° ，frame=body
        sound = wait_for(lambda: next((m for m in got if m["kind"] == "sound"), None))
        assert sound and sound["mock"] is True and sound["frame"] == "body"
        assert abs(sound["bearing_yaw_rad"] - (-0.5236)) < 0.01
        assert wait_for(lambda: effect(client, "hearing.min_speech_energy")["state"] == "applied")

        # 2. 在頁面把能量門檻調到比現在的聲音高 → 一秒左右就不再送方位
        assert client.call("/api/save", {"changes": {"hearing.min_speech_energy": 400000}})[0] == 200
        assert wait_for(lambda: effect(client, "hearing.min_speech_energy") == {"state": "applied", "label": "已生效", "running": 400000.0})
        time.sleep(0.8)  # 視窗（0.5 s）清空
        got.clear()
        time.sleep(1.2)
        assert [m["kind"] for m in got] and all(m["kind"] == "status" and m["ok"] for m in got)

        # 3. 調回來 → 又有方位
        client.call("/api/save", {"changes": {"hearing.min_speech_energy": 100000}})
        got.clear()
        assert wait_for(lambda: any(m["kind"] == "sound" for m in got))

        # 4. 隱私：關掉「讀取聲源方向」→ 服務放開裝置、不再讀，回報自己被關掉；頁面顯示已生效
        client.call("/api/save", {"changes": {"privacy.sound_direction": False}})
        assert wait_for(lambda: CountingReader.closed == 1)
        reads = readers[0].reads
        got.clear()
        time.sleep(1.5)
        assert readers[0].reads == reads and CountingReader.opened == 1  # 一次都沒有再讀
        assert got and all(m == {"v": 1, "kind": "status", "source": "sound", "ok": False, "mock": False, "detail": "disabled in duck settings"} for m in got)
        assert effect(client, "privacy.sound_direction") == {"state": "applied", "label": "已生效", "running": False}

        # 5. 頁面不能再打開；本機指令可以，打開後服務自己恢復
        assert client.call("/api/save", {"changes": {"privacy.sound_direction": True}})[0] == 400
        store.apply({"privacy.sound_direction": True}, "local_cli")
        got.clear()
        assert wait_for(lambda: any(m["kind"] == "sound" for m in got)) and CountingReader.opened == 2
    finally:
        stop.set()
        th.join(timeout=4)
    assert not th.is_alive()
    # 服務停了：頁面不再說「已生效」…這個測試行程還活著（pid 相同），所以這裡只檢查回報檔的內容
    report = json.loads((store.directory / "applied" / "duck-doa.json").read_text())
    assert report["service"] == "duck-doa" and report["values"]["privacy.sound_direction"] is True
    assert report["values"]["calibration.mic.front_angle_deg"] == 10.0
