"""XVF3800 麥克風陣列的聲源方向（DOA）：USB 控制介面讀角度與語音旗標 → 聲音方位 → 送給 duckd。

讀法沿用使用者的 FamilyRecorder 專案（`pcpcchen-coder/FamilyRecorder`，MIT License，
`src/family_recorder/direction.py`，commit `ff76063`；唯讀參考後在這裡重寫，沒有整段複製）：

- USB vendor control IN（bmRequestType `0xC0`、bRequest 0、wValue `0x80 | command`、wIndex `resource`）。
- DOA：resource 20、command 18，回 5 bytes：狀態（0＝成功、64＝重試）＋兩個 little-endian uint16（角度 0–359°、語音旗標）。
- 角度用**環狀分群**（358° 與 2° 是同一個方向），取筆數最多的那一群。
- 出廠 0° 是麥克風的機構方向，要校準「正前方」。

FamilyRecorder 只在 macOS 上對標準版 XVF3800（VID `0x2886`、PID `0x001A`）驗證過。
**Pi 4（Linux）上的行為、其他 PID（例如 Flex 版）、韌體版本的相容性，都要以實機紀錄為準**
（`docs/validation/`）；這個檔案的測試用的是模擬裝置（mock）。

只用 USB 的控制端點（endpoint 0）：不 claim 介面、不 detach 核心的 snd-usb-audio，**不占用音訊串流**。
只送方位，不碰也不保存任何聲音。

    python -m duck_audio.doa --probe                 # 找裝置、印 USB ID 與一筆讀值
    python -m duck_audio.doa --calibrate 5           # 你站在鴨子正前方說話 5 秒 → 印出該填的 front_angle_deg
    python -m duck_audio.doa --run                   # 讀 DOA 並送給 duckd（UDP 127.0.0.1:8793）
    python -m duck_audio.doa --run --mock-angle 30   # 沒有裝置時用模擬資料（訊息帶 mock: true）
"""
from __future__ import annotations

import argparse
import json
import math
import socket
import struct
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

XVF3800_VENDOR_ID = 0x2886  # Seeed
#: 看過的 PID。0x001A＝FamilyRecorder 驗證過的標準版（USB）。其他 PID 會被接受但標成「未驗證」。
KNOWN_PRODUCT_IDS = {0x001A: "reSpeaker XVF3800 (USB firmware)"}
USB_VENDOR_DEVICE_IN = 0xC0
DOA_RESOURCE_ID = 20
DOA_COMMAND_ID = 18
CONTROL_SUCCESS = 0
CONTROL_RETRY = 64
DEFAULT_ADDR = ("127.0.0.1", 8793)
DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "doa.json"


class DoaError(RuntimeError):
    pass


def decode_doa(response: bytes) -> tuple[float, bool]:
    """5 bytes → （原始角度 0–359°, 有沒有偵測到語音）。"""
    if len(response) != 5:
        raise DoaError(f"DOA 回應長度不對：{len(response)}")
    if response[0] != CONTROL_SUCCESS:
        raise DoaError(f"DOA 回應狀態異常：{response[0]}")
    angle, speech = struct.unpack("<2H", response[1:])
    return float(angle % 360), bool(speech)


class XVF3800Reader:
    """真的裝置（需要 pyusb 與 libusb；Pi 上的權限由 udev 規則給，見 deploy/pi4/setup_doa.sh）。"""

    mock = False

    def __init__(self, timeout_ms: int = 1000, usb_core=None, product_id: int | None = None):
        if usb_core is None:
            import usb.core as usb_core  # noqa: PLC0415
        kwargs = {"idVendor": XVF3800_VENDOR_ID}
        if product_id is not None:
            kwargs["idProduct"] = product_id
        self._dev = usb_core.find(**kwargs)
        if self._dev is None:
            raise DoaError("找不到 XVF3800（USB VID 2886）。麥克風接上了嗎？`lsusb` 看得到嗎？")
        self._timeout_ms = timeout_ms
        self.vendor_id = int(self._dev.idVendor)
        self.product_id = int(self._dev.idProduct)
        self.bcd_device = int(getattr(self._dev, "bcdDevice", 0))
        self.verified_product = self.product_id in KNOWN_PRODUCT_IDS

    def describe(self) -> dict:
        def text(attr: str) -> str | None:
            try:
                return str(getattr(self._dev, attr))
            except Exception:  # noqa: BLE001 沒權限讀字串描述元也不影響 DOA
                return None

        return {
            "vid": f"{self.vendor_id:04x}",
            "pid": f"{self.product_id:04x}",
            "bcdDevice": f"{self.bcd_device >> 8:x}.{self.bcd_device & 0xFF:02x}",
            "manufacturer": text("manufacturer"),
            "product": text("product"),
            "known_pid": KNOWN_PRODUCT_IDS.get(self.product_id),
        }

    def read(self) -> tuple[float, bool]:
        response = b""
        for attempt in range(4):
            raw = self._dev.ctrl_transfer(USB_VENDOR_DEVICE_IN, 0, 0x80 | DOA_COMMAND_ID, DOA_RESOURCE_ID, 5, self._timeout_ms)
            response = bytes(raw)
            if response and response[0] == CONTROL_RETRY and attempt < 3:
                time.sleep(0.01)
                continue
            break
        return decode_doa(response)

    def close(self) -> None:
        try:
            import usb.util  # noqa: PLC0415

            usb.util.dispose_resources(self._dev)
        except Exception:  # noqa: BLE001
            pass


class MockDoaReader:
    """模擬裝置（mock）：固定回一個角度。**不代表真實麥克風的行為。**"""

    mock = True

    def __init__(self, angle_deg: float = 0.0, speech: bool = True):
        self.angle_deg, self.speech = angle_deg, speech
        self.reads = 0
        self.fail: str | None = None

    def describe(self) -> dict:
        return {"mock": True}

    def read(self) -> tuple[float, bool]:
        self.reads += 1
        if self.fail:
            raise DoaError(self.fail)
        return float(self.angle_deg % 360), self.speech

    def close(self) -> None:
        pass


# ---------------------------------------------------------------- 角度處理
def angular_distance_deg(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def circular_mean_deg(angles: list[float]) -> float:
    s = sum(math.sin(math.radians(a)) for a in angles)
    c = sum(math.cos(math.radians(a)) for a in angles)
    if abs(s) < 1e-12 and abs(c) < 1e-12:
        return angles[0] % 360.0
    return math.degrees(math.atan2(s, c)) % 360.0


def cluster_angles(angles: list[float], tolerance_deg: float) -> list[list[float]]:
    """環狀分群：一個角度離某一群的平均不超過 tolerance 就併進去；最後把靠得夠近的群合併。大群在前。"""
    clusters: list[list[float]] = []
    for a in angles:
        best = min(clusters, key=lambda c: angular_distance_deg(a, circular_mean_deg(c)), default=None)
        if best is not None and angular_distance_deg(a, circular_mean_deg(best)) <= tolerance_deg:
            best.append(a)
        else:
            clusters.append([a])
    merged = True
    while merged and len(clusters) > 1:
        merged = False
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                if angular_distance_deg(circular_mean_deg(clusters[i]), circular_mean_deg(clusters[j])) <= tolerance_deg:
                    clusters[i].extend(clusters.pop(j))
                    merged = True
                    break
            if merged:
                break
    return sorted(clusters, key=len, reverse=True)


@dataclass(frozen=True)
class DoaConfig:
    #: 麥克風回報的哪個原始角度（度）對應到**鴨子身體的正前方**。麥克風不管裝在鴨子身上還是放在桌上，
    #: 都用 `--calibrate` 量這個值（人站在鴨子正前方說話）。預設 0＝沒校準。
    front_angle_deg: float = 0.0
    #: 原始角度增加的方向。True＝從上面看逆時針（往左為正，FamilyRecorder 的標示方式）；實機確認後再改。
    counterclockwise: bool = True
    #: 麥克風裝在哪：`head`（裝在頭上，會跟著頭轉；ADR-0005 的規劃）、`body`（裝在身體上）、`desk`（放在桌上、不在鴨子身上）。
    #: `head` 時送出的方位是**相對頭部**（訊息帶 `"frame":"head"`），由 duckd 加上當下的頭部 yaw 換成相對身體；
    #: `body`／`desk` 時是相對身體正前方（`"frame":"body"`）。`desk` 只在聲源夠遠、麥克風離鴨子很近時才近似正確。
    mount: str = "body"
    sample_hz: float = 20.0
    window_s: float = 0.5
    min_speech_samples: int = 4
    cluster_tolerance_deg: float = 25.0
    publish_hz: float = 10.0
    calibrated: bool = False

    @classmethod
    def load(cls, path: Path | None) -> "DoaConfig":
        if path is None or not Path(path).exists():
            return cls()
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        cfg = cls(**known)
        if cfg.mount not in ("head", "body", "desk"):
            raise DoaError(f"mount 只能是 head／body／desk，不是 {cfg.mount!r}")
        return cfg


def to_bearing_rad(raw_deg: float, cfg: DoaConfig) -> float:
    """原始角度 → 相對身體正前方的方位（rad，左為正，−π～π）。"""
    rel = (raw_deg - cfg.front_angle_deg) % 360.0
    if not cfg.counterclockwise:
        rel = (-rel) % 360.0
    if rel > 180.0:
        rel -= 360.0
    return math.radians(rel)


@dataclass
class DoaEstimator:
    """滑動視窗內「有語音」的樣本做環狀分群，回傳主要方向。沒有語音就沒有輸出。"""

    cfg: DoaConfig = field(default_factory=DoaConfig)
    _samples: list[tuple[float, float]] = field(default_factory=list)  # (時間, 原始角度)，只留有語音的

    def add(self, now: float, raw_deg: float, speech: bool) -> None:
        if speech:
            self._samples.append((now, raw_deg % 360.0))
        self._samples = [(t, a) for t, a in self._samples if now - t <= self.cfg.window_s]

    def estimate(self, now: float) -> tuple[float, float, float] | None:
        """回傳（原始角度, 方位 rad, 信心 0–1）；語音樣本不夠就 None。信心＝主要方向那一群占的比例。"""
        live = [a for t, a in self._samples if now - t <= self.cfg.window_s]
        if len(live) < self.cfg.min_speech_samples:
            return None
        clusters = cluster_angles(live, self.cfg.cluster_tolerance_deg)
        raw = circular_mean_deg(clusters[0])
        return raw, to_bearing_rad(raw, self.cfg), len(clusters[0]) / len(live)


# ---------------------------------------------------------------- 送給 duckd
def sound_message(bearing_rad: float, confidence: float, mock: bool, frame: str = "body") -> bytes:
    return json.dumps({
        "v": 1, "kind": "sound", "frame": frame, "bearing_yaw_rad": round(bearing_rad, 4), "bearing_pitch_rad": 0.0,
        "distance_m": None, "confidence": round(max(0.0, min(1.0, confidence)), 3),
        "t_ms": int(time.time() * 1000), "mock": bool(mock),
    }).encode("utf-8")


def status_message(ok: bool, mock: bool, detail: str = "") -> bytes:
    return json.dumps({"v": 1, "kind": "status", "source": "sound", "ok": bool(ok), "mock": bool(mock), "detail": detail[:80]}).encode("utf-8")


class DoaService:
    """讀裝置 → 估方向 → 只在有語音時送 `sound`；每秒送一次 `status`（讓 duckd 知道來源還在）。"""

    def __init__(self, reader, cfg: DoaConfig, send, clock=time.monotonic):
        self.reader, self.cfg, self.send, self.clock = reader, cfg, send, clock
        self.estimator = DoaEstimator(cfg)
        self.sent_sound = 0
        self.read_errors = 0
        self.last_error = ""
        self._last_publish = -math.inf
        self._last_status = -math.inf
        self.last_raw: float | None = None

    def step(self) -> None:
        now = self.clock()
        ok = True
        try:
            raw, speech = self.reader.read()
            self.last_raw = raw
            self.estimator.add(now, raw, speech)
            self.last_error = ""
        except Exception as exc:  # noqa: BLE001 讀取失敗照實回報，不送假方位
            ok = False
            self.read_errors += 1
            self.last_error = str(exc)[-80:]
        if ok and now - self._last_publish >= 1.0 / self.cfg.publish_hz:
            est = self.estimator.estimate(now)
            if est is not None:
                self._last_publish = now
                self.send(sound_message(est[1], est[2], self.reader.mock, "head" if self.cfg.mount == "head" else "body"))
                self.sent_sound += 1
        if now - self._last_status >= 1.0:
            self._last_status = now
            detail = self.last_error or ("" if self.cfg.calibrated or self.reader.mock else "front angle not calibrated")
            self.send(status_message(ok, self.reader.mock, detail))

    def run(self, stop=lambda: False) -> None:
        period = 1.0 / self.cfg.sample_hz
        while not stop():
            t0 = self.clock()
            self.step()
            time.sleep(max(0.0, period - (self.clock() - t0)))


def calibrate(reader, seconds: float, cfg: DoaConfig, clock=time.monotonic, sleep=time.sleep) -> dict:
    """人站在鴨子正前方說話；回傳這段時間語音樣本的主要原始角度。"""
    angles, total, end = [], 0, clock() + seconds
    while clock() < end:
        raw, speech = reader.read()
        total += 1
        if speech:
            angles.append(raw)
        sleep(1.0 / cfg.sample_hz)
    if len(angles) < cfg.min_speech_samples:
        return {"ok": False, "speech_samples": len(angles), "total_samples": total, "error": "語音樣本太少（有對著麥克風說話嗎？）"}
    clusters = cluster_angles(angles, cfg.cluster_tolerance_deg)
    main = clusters[0]
    front = circular_mean_deg(main)
    spread = sum(angular_distance_deg(a, front) for a in main) / len(main)
    return {"ok": True, "front_angle_deg": round(front, 1), "share": round(len(main) / len(angles), 2), "spread_deg": round(spread, 1), "speech_samples": len(angles), "total_samples": total}


def run_forever(cfg: DoaConfig, addr: tuple[str, int], open_reader=None, retry_s: float = 3.0, max_errors: int = 40, stop=lambda: False) -> int:
    """常駐模式：裝置沒接就每秒回報「不在」，接上後自動開始；連續讀取失敗就重開裝置。不送任何假方位。"""
    open_reader = open_reader or XVF3800Reader
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    send = lambda data: sock.sendto(data, addr)  # noqa: E731
    announced = None
    while not stop():
        try:
            reader = open_reader()
        except (DoaError, ImportError, OSError) as exc:
            if announced != "missing":
                print(f"等麥克風：{exc}", file=sys.stderr, flush=True)
                announced = "missing"
            end = time.monotonic() + retry_s
            while time.monotonic() < end and not stop():
                send(status_message(False, False, "XVF3800 not found"))
                time.sleep(1.0)
            continue
        print(f"DOA 開始：{reader.describe()} → udp://{addr[0]}:{addr[1]}（mount={cfg.mount}，front={cfg.front_angle_deg}°，calibrated={cfg.calibrated}）", file=sys.stderr, flush=True)
        announced = "ok"
        svc = DoaService(reader, cfg, send)
        base = 0
        try:
            period = 1.0 / cfg.sample_hz
            while not stop():
                t0 = time.monotonic()
                before = svc.read_errors
                svc.step()
                base = base + 1 if svc.read_errors > before else 0
                if base >= max_errors:
                    print(f"連續 {base} 次讀取失敗（{svc.last_error}），重開裝置", file=sys.stderr, flush=True)
                    break
                time.sleep(max(0.0, period - (time.monotonic() - t0)))
        except KeyboardInterrupt:
            reader.close()
            return 0
        reader.close()
        time.sleep(1.0)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="XVF3800 聲源方向 → duckd")
    p.add_argument("--probe", action="store_true")
    p.add_argument("--calibrate", type=float, metavar="秒")
    p.add_argument("--run", action="store_true")
    p.add_argument("--watch", type=float, metavar="秒", help="只印讀值（不送給 duckd），驗證用")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--write-config", action="store_true", help="--calibrate 成功後把結果寫進 --config")
    p.add_argument("--mock-angle", type=float, default=None, help="用模擬裝置（訊息帶 mock: true）")
    p.add_argument("--host", default=DEFAULT_ADDR[0])
    p.add_argument("--port", type=int, default=DEFAULT_ADDR[1])
    args = p.parse_args()
    cfg = DoaConfig.load(args.config)
    if args.run and args.mock_angle is None:
        return run_forever(cfg, (args.host, args.port))
    try:
        reader = MockDoaReader(args.mock_angle) if args.mock_angle is not None else XVF3800Reader()
    except (DoaError, ImportError) as exc:
        print(f"不能讀 DOA：{exc}", file=sys.stderr)
        return 2
    try:
        if args.probe:
            raw, speech = reader.read()
            print(json.dumps({"device": reader.describe(), "raw_angle_deg": raw, "speech_detected": speech, "config": cfg.__dict__}, ensure_ascii=False, indent=1))
        elif args.calibrate:
            result = calibrate(reader, args.calibrate, cfg)
            print(json.dumps(result, ensure_ascii=False, indent=1))
            if result["ok"] and args.write_config:
                data = {**cfg.__dict__, "front_angle_deg": result["front_angle_deg"], "calibrated": True}
                args.config.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
                print(f"已寫入 {args.config}", file=sys.stderr)
            return 0 if result["ok"] else 1
        elif args.watch:
            est, end = DoaEstimator(cfg), time.monotonic() + args.watch
            while time.monotonic() < end:
                now = time.monotonic()
                raw, speech = reader.read()
                est.add(now, raw, speech)
                e = est.estimate(now)
                print(json.dumps({"raw": raw, "speech": speech, "bearing_deg": None if e is None else round(math.degrees(e[1]), 1), "confidence": None if e is None else round(e[2], 2)}), flush=True)
                time.sleep(1.0 / cfg.sample_hz)
        elif args.run:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            addr = (args.host, args.port)
            print(f"DOA → udp://{addr[0]}:{addr[1]}（{'模擬裝置 mock' if reader.mock else reader.describe()}）", file=sys.stderr)
            DoaService(reader, cfg, lambda data: sock.sendto(data, addr)).run()
        else:
            p.print_help()
    except KeyboardInterrupt:
        pass
    finally:
        reader.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
