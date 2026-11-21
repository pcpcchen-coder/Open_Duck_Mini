#!/usr/bin/env python3
"""Open Duck Mini v2 舵機工作台：STS3215 逐顆設定 ID／零位、掃描、整機檢查。

只依賴 pyserial（`selftest` 連 pyserial 都不用）。直接講 Feetech STS 協定，
不需要先裝 Open_Duck_Mini_Runtime，Mac 和 Pi 都能跑。

寫入的參數和上游 Runtime v2 的 scripts/configure_motor.py 相同：
mode=0、最大加速度=0、加速度=0、P=32、I=0、D=0、改 ID，然後轉到零位（2048）。
差別只有一處：寫完 EEPROM 後把 lock 設回 1（Feetech 建議的「解鎖→寫入→上鎖」流程；
上游停在 lock=0）。

驗證層級：模擬匯流排的內建檢查（`selftest`）。尚未在實機舵機上驗證。

用法（在這個檔案所在目錄外也可以，路徑換成實際位置）：
    python3 servo_bench.py ports                 # 列出序列埠
    python3 servo_bench.py scan                  # 掃描匯流排上的舵機
    python3 servo_bench.py wizard                # 14 顆逐顆設定（建議）
    python3 servo_bench.py setup 14              # 只設定一顆為 ID 14
    python3 servo_bench.py check                 # 14 顆都接上後一次檢查
    python3 servo_bench.py center 14             # 轉回零位（對舵盤用）
    python3 servo_bench.py relax all             # 全部放鬆（關扭力）
    python3 servo_bench.py monitor               # 即時看位置（手轉關節對零位）
    python3 servo_bench.py selftest              # 不接硬體的內建檢查
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import os
import shutil
import subprocess
import sys
import time

# ---------------------------------------------------------------------------
# 關節表（與上游 docs/configure_motors.md、Runtime rustypot_position_hwi.py 一致）
# 範圍取自 mini_bdx/robots/open_duck_mini_v2/robot.xml（弧度）
# ---------------------------------------------------------------------------

JOINTS = [
    # (id, joint, 中文, 範圍下限 rad, 範圍上限 rad)
    (10, "right_hip_yaw", "右髖偏航", -0.523599, 0.523599),
    (11, "right_hip_roll", "右髖側擺", -0.436332, 0.436332),
    (12, "right_hip_pitch", "右髖俯仰", -0.523599, 1.22173),
    (13, "right_knee", "右膝", -1.5708, 1.5708),
    (14, "right_ankle", "右踝", -1.5708, 1.5708),
    (20, "left_hip_yaw", "左髖偏航", -0.523599, 0.523599),
    (21, "left_hip_roll", "左髖側擺", -0.436332, 0.436332),
    (22, "left_hip_pitch", "左髖俯仰", -1.22173, 0.523599),
    (23, "left_knee", "左膝", -1.5708, 1.5708),
    (24, "left_ankle", "左踝", -1.5708, 1.5708),
    (30, "neck_pitch", "頸俯仰", -0.349066, 1.13446),
    (31, "head_pitch", "頭俯仰", -0.785398, 0.785398),
    (32, "head_yaw", "頭偏航", -2.79253, 2.79253),
    (33, "head_roll", "頭側擺", -0.523599, 0.523599),
]
JOINT_BY_ID = {j[0]: j for j in JOINTS}
ALL_IDS = [j[0] for j in JOINTS]

FACTORY_ID = 1  # 新舵機出廠 ID
DEFAULT_BAUD = 1_000_000
ZERO_RAW = 2048  # 0 rad；pypot degree_to_dxl(0) 與 rustypot 皆對應 2048
STEPS_PER_REV = 4096
MODEL_STS3215 = 777

# STS3215 記憶體表（位址，與 pollen-robotics/pypot@support-feetech-sts3215 sts3215_io.py 相同）
ADDR_MODEL = 3  # 2 bytes
ADDR_ID = 5
ADDR_BAUD = 6
ADDR_P = 21
ADDR_D = 22
ADDR_I = 23
ADDR_MODE = 33
ADDR_TORQUE = 40
ADDR_ACCEL = 41
ADDR_GOAL_POS = 42  # 2 bytes；後面接 goal time(44) 與 goal speed(46)
ADDR_GOAL_SPEED = 46
ADDR_LOCK = 55
ADDR_PRESENT_POS = 56  # 2 bytes
ADDR_PRESENT_LOAD = 60
ADDR_VOLTAGE = 62  # 0.1 V
ADDR_TEMP = 63  # °C
ADDR_STATUS = 65
ADDR_MOVING = 66
ADDR_MAX_ACCEL = 85  # pypot 註明「不在官方記憶體表」，上游 configure_motor.py 會寫它

# 上游 configure_motor.py 寫入的值
UPSTREAM_PARAMS = [
    ("mode", ADDR_MODE, 0),
    ("maximum acceleration", ADDR_MAX_ACCEL, 0),
    ("acceleration", ADDR_ACCEL, 0),
    ("P coefficient", ADDR_P, 32),
    ("I coefficient", ADDR_I, 0),
    ("D coefficient", ADDR_D, 0),
]

INST_PING = 0x01
INST_READ = 0x02
INST_WRITE = 0x03
BROADCAST = 0xFE

# Feetech 狀態位元（依 Feetech 記憶體表；只作提示）
STATUS_BITS = {0: "電壓", 1: "角度感測器", 2: "過熱", 3: "電流", 4: "角度", 5: "過載"}

# C001 型號頁標 6–7.4 V；部分通路標到 8.4 V（見繁中組裝指引第 5 步）
VOLT_WARN_LOW = 6.0
VOLT_WARN_HIGH = 7.4

BAUD_CODES = {0: 1_000_000, 1: 500_000, 2: 250_000, 3: 128_000, 4: 115_200, 5: 76_800, 6: 57_600, 7: 38_400}


# ---------------------------------------------------------------------------
# 協定
# ---------------------------------------------------------------------------


class BusError(Exception):
    pass


class NoReply(BusError):
    pass


class BadReply(BusError):
    pass


def checksum(body: bytes) -> int:
    return (~sum(body)) & 0xFF


def build_packet(sid: int, instr: int, params: bytes = b"") -> bytes:
    body = bytes([sid, len(params) + 2, instr]) + bytes(params)
    return b"\xff\xff" + body + bytes([checksum(body)])


def parse_status(buf: bytearray, want_id: int):
    """從 buf 找出 want_id 的狀態封包。回傳 (error, params, 消耗位元組數) 或 None（還不完整）。

    校驗碼錯誤或 ID 不符時丟 BadReply（常見原因：兩顆同 ID 同時回應、線路干擾）。
    """
    i = 0
    while True:
        i = buf.find(b"\xff\xff", i)
        if i < 0:
            return None
        # 跳過連續的 0xFF（多出來的前導）
        j = i + 2
        while j < len(buf) and buf[j] == 0xFF:
            j += 1
        if len(buf) < j + 2:
            return None
        sid, length = buf[j], buf[j + 1]
        end = j + 2 + length  # 最後一個位元組是校驗碼
        if length < 2:
            raise BadReply(f"長度欄位異常（{length}）")
        if len(buf) < end:
            return None
        body = bytes(buf[j:end - 1])
        if checksum(body) != buf[end - 1]:
            raise BadReply("校驗碼錯誤（可能有兩顆同 ID 同時回應，或線路干擾）")
        if sid != want_id:
            raise BadReply(f"回應的 ID 是 {sid}，不是 {want_id}（可能接了不只一顆）")
        error = buf[j + 2]
        params = bytes(buf[j + 3:end - 1])
        return error, params, end


class Bus:
    """Feetech STS 匯流排。link 需要 write / read / in_waiting / reset_input_buffer。"""

    def __init__(self, link, timeout: float = 0.03):
        self.link = link
        self.timeout = timeout

    def _send(self, sid: int, instr: int, params: bytes = b"", reply: bool = True):
        pkt = build_packet(sid, instr, params)
        try:
            self.link.reset_input_buffer()
        except Exception:
            pass
        self.link.write(pkt)
        if hasattr(self.link, "flush"):
            self.link.flush()
        if not reply or sid == BROADCAST:
            return None
        buf = bytearray()
        echo_checked = False
        deadline = time.monotonic() + self.timeout
        while True:
            n = getattr(self.link, "in_waiting", 0) or 1
            chunk = self.link.read(n)
            if chunk:
                buf += chunk
            # 半雙工板子若會回送自己發出的封包，先丟掉（回送與回應可能同時到）
            if not echo_checked:
                if len(buf) >= len(pkt):
                    if bytes(buf[:len(pkt)]) == pkt:
                        del buf[:len(pkt)]
                    echo_checked = True
                elif pkt.startswith(bytes(buf)) and time.monotonic() < deadline:
                    continue
                else:
                    echo_checked = True
            res = parse_status(buf, sid)
            if res is not None:
                err, params_out, _ = res
                return err, params_out
            if time.monotonic() >= deadline:
                if buf:
                    raise BadReply(f"回應不完整：{bytes(buf).hex(' ')}")
                raise NoReply(f"ID {sid} 沒有回應")

    def ping(self, sid: int) -> bool:
        try:
            self._send(sid, INST_PING)
            return True
        except NoReply:
            return False

    def read(self, sid: int, addr: int, n: int) -> bytes:
        _, data = self._send(sid, INST_READ, bytes([addr, n]))
        if len(data) != n:
            raise BadReply(f"ID {sid} 讀 {addr} 期望 {n} 位元組，收到 {len(data)}")
        return data

    def read_u8(self, sid: int, addr: int) -> int:
        return self.read(sid, addr, 1)[0]

    def read_u16(self, sid: int, addr: int) -> int:
        d = self.read(sid, addr, 2)
        return d[0] | (d[1] << 8)  # STS 為小端序

    def write(self, sid: int, addr: int, data: bytes, reply: bool = True):
        self._send(sid, INST_WRITE, bytes([addr]) + bytes(data), reply=reply)

    def write_u8(self, sid: int, addr: int, value: int, reply: bool = True):
        self.write(sid, addr, bytes([value & 0xFF]), reply=reply)

    def write_u16(self, sid: int, addr: int, value: int):
        self.write(sid, addr, bytes([value & 0xFF, (value >> 8) & 0xFF]))

    # 高階讀取
    def position(self, sid: int) -> int:
        raw = self.read_u16(sid, ADDR_PRESENT_POS)
        if raw & 0x8000:  # 符號位元
            raw = -(raw & 0x7FFF)
        return raw

    def telemetry(self, sid: int) -> dict:
        return {
            "model": self.read_u16(sid, ADDR_MODEL),
            "position": self.position(sid),
            "voltage": self.read_u8(sid, ADDR_VOLTAGE) / 10.0,
            "temperature": self.read_u8(sid, ADDR_TEMP),
            "status": self.read_u8(sid, ADDR_STATUS),
            "torque": self.read_u8(sid, ADDR_TORQUE),
        }

    def scan(self, ids=range(0, 254), progress=None) -> list:
        found = []
        for sid in ids:
            if progress:
                progress(sid)
            try:
                if self.ping(sid):
                    found.append(sid)
            except BadReply:
                found.append(sid)  # 有東西在回應，只是封包壞了
        return found


def raw_to_rad(raw: int) -> float:
    return (raw - ZERO_RAW) * 2 * math.pi / STEPS_PER_REV


def rad_to_raw(rad: float) -> int:
    return int(round(ZERO_RAW + rad * STEPS_PER_REV / (2 * math.pi)))


def status_text(status: int) -> str:
    if not status:
        return "正常"
    bits = [name for b, name in STATUS_BITS.items() if status & (1 << b)]
    return "異常：" + "、".join(bits) + f"（0x{status:02x}）"


# ---------------------------------------------------------------------------
# 終端顯示
# ---------------------------------------------------------------------------

COLORS = {"yellow": "43;30", "green": "42;30", "red": "41;97", "blue": "44;97"}
_QUIET = False
_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def chime(kind: str = "cue"):
    if _QUIET:
        return
    sound = {"cue": "Glass", "ok": "Hero", "fail": "Basso"}.get(kind, "Glass")
    path = f"/System/Library/Sounds/{sound}.aiff"
    if sys.platform == "darwin" and shutil.which("afplay") and os.path.exists(path):
        try:
            subprocess.Popen(["afplay", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            pass
    sys.stdout.write("\a")
    sys.stdout.flush()


def banner(lines, color: str = "blue", clear: bool = False):
    width = max(40, min(shutil.get_terminal_size((80, 24)).columns, 100))
    if clear and _COLOR:
        sys.stdout.write("\033[2J\033[H")

    def disp_len(s):  # 中日韓字元佔兩格
        return sum(2 if ord(c) > 0x2E7F else 1 for c in s)

    out = []
    for line in [""] + list(lines) + [""]:
        pad = max(0, width - 2 - disp_len(line))
        text = "  " + line + " " * pad
        out.append(f"\033[{COLORS[color]}m{text}\033[0m" if _COLOR else "| " + line)
    print("\n".join(out))


def label(sid: int) -> str:
    j = JOINT_BY_ID.get(sid)
    return f"ID {sid}｜{j[2]} {j[1]}" if j else f"ID {sid}｜（不在 14 軸表內）"


# ---------------------------------------------------------------------------
# 序列埠
# ---------------------------------------------------------------------------

# WCH（CH34x，Waveshare Bus Servo Adapter 常見）、Silicon Labs CP210x、FTDI
KNOWN_VIDS = {0x1A86: "WCH CH34x", 0x10C4: "Silicon Labs CP210x", 0x0403: "FTDI"}
SKIP_WORDS = ("bluetooth", "debug-console", "wlan")


def list_ports():
    try:
        from serial.tools import list_ports as lp
    except ImportError:
        die_no_pyserial()
    ports = []
    for p in lp.comports():
        dev = p.device
        if sys.platform == "darwin" and dev.startswith("/dev/tty."):
            continue  # Mac 用 /dev/cu.*
        if any(w in dev.lower() for w in SKIP_WORDS):
            continue
        ports.append(p)
    return ports


def pick_port(explicit: str | None) -> str:
    if explicit:
        return explicit
    ports = list_ports()
    known = [p for p in ports if p.vid in KNOWN_VIDS]
    if len(known) == 1:
        p = known[0]
        print(f"使用序列埠 {p.device}（{KNOWN_VIDS[p.vid]}）")
        return p.device
    cands = known or ports
    if not cands:
        print("找不到序列埠。確認舵機板的 USB 線已接上電腦（要用能傳資料的線）。")
        sys.exit(2)
    print("有多個序列埠，請用 --port 指定舵機板：")
    for p in cands:
        vid = f"{p.vid:04x}:{p.pid:04x}" if p.vid is not None else "—"
        print(f"  {p.device}    {vid}    {p.description}")
    print("（拔掉舵機板 USB 再執行一次 `ports`，消失的那個就是它。）")
    sys.exit(2)


def die_no_pyserial():
    print("需要 pyserial：  python3 -m pip install --user pyserial")
    sys.exit(2)


def open_bus(args) -> Bus:
    try:
        import serial
    except ImportError:
        die_no_pyserial()
    port = pick_port(args.port)
    try:
        ser = serial.Serial(port, args.baud, timeout=0.002, write_timeout=0.5)
    except (serial.SerialException, OSError) as e:
        print(f"打不開 {port}：{e}")
        print("可能被其他程式占用（例如另一個終端機、Arduino IDE），或權限不足（Linux 需在 dialout 群組）。")
        sys.exit(2)
    return Bus(ser, timeout=args.timeout)


# ---------------------------------------------------------------------------
# 指令實作（不直接碰序列埠，方便 selftest）
# ---------------------------------------------------------------------------


def find_single_servo(bus: Bus, log=print):
    """確認匯流排上剛好一顆舵機，回傳它目前的 ID。"""
    log("掃描匯流排（0–253），確認只接了一顆……")
    found = bus.scan()
    if not found:
        raise BusError(
            "找不到舵機。檢查：舵機電源有開、3P 線插對方向（D／V／G）、"
            "--port 是舵機板、鮑率 1M（新舵機出廠值）。可用 `scan --all-baud` 試其他鮑率。"
        )
    if len(found) > 1:
        raise BusError(f"匯流排上找到 {len(found)} 個 ID：{found}。一次只能接一顆，先斷電拔掉其他的。")
    return found[0]


def configure_servo(bus: Bus, target: int, log=print, settle: float = 1.0) -> dict:
    """依上游 configure_motor.py 設定唯一一顆舵機為 target ID 並轉到零位。回傳結果紀錄。"""
    cur = find_single_servo(bus, log)
    model = bus.read_u16(cur, ADDR_MODEL)
    volt = bus.read_u8(cur, ADDR_VOLTAGE) / 10.0
    log(f"找到 ID {cur}（型號代碼 {model}{'，STS3215' if model == MODEL_STS3215 else '，不是 STS3215 的 777，請確認型號'}），電壓 {volt:.1f} V")
    if volt < VOLT_WARN_LOW:
        raise BusError(f"電壓只有 {volt:.1f} V，低於 {VOLT_WARN_LOW} V。先確認舵機電源，再設定。")
    if volt > VOLT_WARN_HIGH + 0.05:
        log(f"⚠ 電壓 {volt:.1f} V 高於 C001 型號頁的 {VOLT_WARN_HIGH} V，請確認這批舵機規格。")

    bus.write_u8(cur, ADDR_LOCK, 0)  # 解鎖 EEPROM
    for _, addr, val in UPSTREAM_PARAMS:
        bus.write_u8(cur, addr, val)
    if cur != target:
        # 改 ID 的回應可能用新或舊 ID，不依賴它，改用 ping 新 ID 確認
        bus.write_u8(cur, ADDR_ID, target, reply=False)
        time.sleep(0.05)
        if not bus.ping(target):
            raise BusError(f"寫入 ID {target} 後 ping 不到。斷電重開再 `scan` 看看它現在是幾號。")
    bus.write_u8(target, ADDR_LOCK, 1)  # 上鎖，寫入的 EEPROM 值斷電後保留

    # 回讀確認
    readback = {"id": bus.read_u8(target, ADDR_ID)}
    for name, addr, val in UPSTREAM_PARAMS:
        readback[name] = bus.read_u8(target, addr)
    bad = [n for n, a, v in UPSTREAM_PARAMS if readback[n] != v]
    if readback["id"] != target or bad:
        raise BusError(f"回讀不符：{readback}")

    # 轉到零位
    bus.write_u8(target, ADDR_TORQUE, 1)
    bus.write_u16(target, ADDR_GOAL_POS, ZERO_RAW)
    time.sleep(settle)
    pos = bus.position(target)
    err = pos - ZERO_RAW
    tel = bus.telemetry(target)
    result = {
        "id": target,
        "joint": JOINT_BY_ID[target][1] if target in JOINT_BY_ID else None,
        "previous_id": cur,
        "model": model,
        "voltage": tel["voltage"],
        "temperature": tel["temperature"],
        "position_raw": pos,
        "zero_error_steps": err,
        "params": readback,
        "time": _dt.datetime.now().isoformat(timespec="seconds"),
    }
    if abs(err) > 20:
        raise BusError(f"轉到零位後位置 {pos}，離 2048 差 {err} 步。檢查舵盤附近是否卡住、電源是否掉壓。")
    return result


def check_all(bus: Bus, ids=ALL_IDS) -> list:
    rows = []
    for sid in ids:
        row = {"id": sid, "ok": False}
        try:
            if not bus.ping(sid):
                row["error"] = "沒有回應"
            else:
                row.update(bus.telemetry(sid))
                row["ok"] = row["model"] == MODEL_STS3215 and row["status"] == 0
                if row["model"] != MODEL_STS3215:
                    row["error"] = f"型號代碼 {row['model']}"
                elif row["status"]:
                    row["error"] = status_text(row["status"])
        except BadReply as e:
            row["error"] = str(e)
        rows.append(row)
    return rows


def move_to(bus: Bus, sid: int, raw: int, speed: int = 400, wait: float = 3.0):
    """限速移動，到位後把速度設回 0（0＝不限速，Runtime 預期的狀態）。"""
    bus.write_u8(sid, ADDR_TORQUE, 1)
    data = bytes([raw & 0xFF, (raw >> 8) & 0xFF, 0, 0, speed & 0xFF, (speed >> 8) & 0xFF])
    try:
        bus.write(sid, ADDR_GOAL_POS, data)
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if bus.read_u8(sid, ADDR_MOVING) == 0 and abs(bus.position(sid) - raw) <= 10:
                break
            time.sleep(0.05)
    finally:
        bus.write_u16(sid, ADDR_GOAL_SPEED, 0)
    return bus.position(sid)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_ids(text: str) -> list:
    if text == "all":
        return list(ALL_IDS)
    ids = []
    for part in text.split(","):
        if "-" in part:
            a, b = part.split("-")
            ids += [i for i in ALL_IDS if int(a) <= i <= int(b)]
        else:
            ids.append(int(part))
    return ids


def cmd_ports(args):
    ports = list_ports()
    if not ports:
        print("沒有序列埠。")
    for p in ports:
        vid = f"{p.vid:04x}:{p.pid:04x}" if p.vid is not None else "—"
        tag = f"  ← 可能是舵機板（{KNOWN_VIDS[p.vid]}）" if p.vid in KNOWN_VIDS else ""
        print(f"{p.device}    {vid}    {p.description}{tag}")


def cmd_scan(args):
    bus = open_bus(args)
    bauds = list(BAUD_CODES.values()) if args.all_baud else [args.baud]
    any_found = False
    for baud in bauds:
        if baud != args.baud or args.all_baud:
            bus.link.baudrate = baud
        print(f"鮑率 {baud}：掃描 0–253 …", flush=True)
        found = bus.scan()
        for sid in found:
            any_found = True
            try:
                t = bus.telemetry(sid)
                print(f"  {label(sid)}  位置 {t['position']}（{raw_to_rad(t['position']):+.3f} rad）"
                      f"  {t['voltage']:.1f} V  {t['temperature']} °C  {status_text(t['status'])}")
            except BusError as e:
                print(f"  ID {sid}：{e}")
        if found and baud != DEFAULT_BAUD:
            print(f"  ⚠ 這些舵機在 {baud} 鮑率，Runtime 需要 1M。")
    if not any_found:
        print("沒有找到舵機。檢查舵機電源、3P 線方向、--port。")
    elif not args.all_baud and FACTORY_ID in bus.scan([FACTORY_ID]):
        print("提示：ID 1 是出廠值，代表還沒設定。")


def cmd_setup(args):
    bus = open_bus(args)
    target = args.id
    if target not in JOINT_BY_ID and not args.force:
        print(f"ID {target} 不在 Open Duck Mini v2 的 14 軸表內（{ALL_IDS}）。真的要用請加 --force。")
        sys.exit(2)
    try:
        r = configure_servo(bus, target)
    except BusError as e:
        chime("fail")
        banner(["❌ 設定失敗", str(e)], "red")
        sys.exit(1)
    chime("ok")
    banner([f"✅ 完成：{label(target)}",
            f"零位 {r['position_raw']}（誤差 {r['zero_error_steps']:+d} 步）  {r['voltage']:.1f} V",
            "舵機正保持在零位。現在依上游照片對齊並裝上舵盤，再貼上 ID 標籤。"], "green")
    append_log(args.log, r)


def load_log(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return {int(k): v for k, v in json.load(f).items()}
    except (OSError, ValueError):
        return {}


def append_log(path: str, record: dict):
    data = load_log(path)
    data[record["id"]] = record
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in sorted(data.items())}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def cmd_wizard(args):
    bus = open_bus(args)
    done = {} if args.redo else load_log(args.log)
    todo = [j for j in JOINTS if j[0] not in done]
    if done:
        print(f"紀錄檔 {args.log} 已有 {len(done)} 顆完成：{sorted(done)}（加 --redo 重做全部）")
    if not todo:
        print("14 顆都設定過了。接上全部舵機後可跑 `check`。")
        return
    total = len(JOINTS)
    for sid, joint, zh, _, _ in todo:
        n = ALL_IDS.index(sid) + 1
        while True:
            chime("cue")
            banner([f"第 {n}/{total} 顆  →  設為 {label(sid)}",
                    "",
                    "1. 關掉舵機電源",
                    "2. 拔掉上一顆，只接上這一顆新的（舵盤周圍淨空）",
                    "3. 打開舵機電源",
                    "4. 按 Enter 開始　（s＝跳過這顆，q＝結束）"], "yellow", clear=True)
            ans = input("> ").strip().lower()
            if ans == "q":
                summarize(args.log)
                return
            if ans == "s":
                break
            try:
                r = configure_servo(bus, sid)
            except BusError as e:
                chime("fail")
                banner([f"❌ {label(sid)} 沒有完成", str(e), "", "按 Enter 重試"], "red")
                input("> ")
                continue
            append_log(args.log, r)
            chime("ok")
            banner([f"✅ 完成：{label(sid)}",
                    f"零位 {r['position_raw']}（誤差 {r['zero_error_steps']:+d} 步）  {r['voltage']:.1f} V",
                    "",
                    "現在：依上游照片對齊並裝上舵盤（舵機正保持零位）",
                    f"貼標籤：「{sid} {zh}」，放進對應的零件盤",
                    "",
                    "按 Enter 換下一顆"], "green")
            input("> ")
            break
    summarize(args.log)


def summarize(path: str):
    done = load_log(path)
    print()
    print("ID   關節               狀態    零位誤差  電壓")
    for sid, joint, zh, _, _ in JOINTS:
        r = done.get(sid)
        if r:
            print(f"{sid:<4} {zh:<6}{joint:<16} ✅    {r['zero_error_steps']:+4d} 步  {r['voltage']:.1f} V")
        else:
            print(f"{sid:<4} {zh:<6}{joint:<16} —")
    print(f"\n完成 {len(done)}/14。紀錄在 {os.path.abspath(path)}")


def cmd_check(args):
    bus = open_bus(args)
    ids = parse_ids(args.ids)
    rows = check_all(bus, ids)
    ok = 0
    print("ID   關節               結果  位置(rad)   電壓    溫度  說明")
    for r in rows:
        j = JOINT_BY_ID.get(r["id"], (r["id"], "?", "?", 0, 0))
        if "position" in r:
            pos = f"{raw_to_rad(r['position']):+.3f}"
            extra = f"{r['voltage']:.1f} V  {r['temperature']:>3} °C"
        else:
            pos, extra = "—", "—"
        mark = "✅" if r["ok"] else "❌"
        ok += r["ok"]
        print(f"{r['id']:<4} {j[2]:<6}{j[1]:<16} {mark}   {pos:>8}   {extra}  {r.get('error', '')}")
    volts = [r["voltage"] for r in rows if "voltage" in r]
    if volts:
        print(f"\n電壓 {min(volts):.1f}–{max(volts):.1f} V")
        if max(volts) > VOLT_WARN_HIGH + 0.05:
            print(f"⚠ 高於 C001 型號頁的 {VOLT_WARN_HIGH} V，請確認這批舵機規格。")
    if args.scan_extra:
        extra_ids = [s for s in bus.scan() if s not in ids]
        if extra_ids:
            print(f"⚠ 另外找到不在清單裡的 ID：{extra_ids}" + ("（ID 1＝還沒設定的新舵機）" if FACTORY_ID in extra_ids else ""))
    print(f"\n{ok}/{len(rows)} 通過")
    sys.exit(0 if ok == len(rows) else 1)


def confirm(msg: str, yes: bool) -> bool:
    if yes:
        return True
    return input(f"{msg}（y/N）> ").strip().lower() == "y"


def cmd_center(args):
    bus = open_bus(args)
    ids = parse_ids(args.ids)
    if not confirm(f"{ids} 會限速轉到零位。已組裝的話，確認機體架空、手邊能切斷舵機電源？", args.yes):
        return
    for sid in ids:
        try:
            pos = move_to(bus, sid, ZERO_RAW, speed=args.speed)
            print(f"{label(sid)}  位置 {pos}（誤差 {pos - ZERO_RAW:+d} 步）")
        except BusError as e:
            print(f"{label(sid)}  ❌ {e}")


def cmd_relax(args):
    bus = open_bus(args)
    for sid in parse_ids(args.ids):
        try:
            bus.write_u8(sid, ADDR_TORQUE, 0)
            print(f"{label(sid)}  已放鬆")
        except BusError as e:
            print(f"{label(sid)}  ❌ {e}")


def cmd_monitor(args):
    bus = open_bus(args)
    ids = parse_ids(args.ids)
    if args.relax:
        for sid in ids:
            try:
                bus.write_u8(sid, ADDR_TORQUE, 0)
            except BusError:
                pass
    print("Ctrl+C 結束。數值是弧度，0＝零位；超出 robot.xml 範圍標 !")
    try:
        while True:
            parts = []
            for sid in ids:
                try:
                    rad = raw_to_rad(bus.position(sid))
                    lo, hi = JOINT_BY_ID[sid][3:5] if sid in JOINT_BY_ID else (-9, 9)
                    flag = "!" if not lo <= rad <= hi else " "
                    parts.append(f"{sid}:{rad:+.2f}{flag}")
                except BusError:
                    parts.append(f"{sid}:  —  ")
            sys.stdout.write("\r" + " ".join(parts))
            sys.stdout.flush()
            time.sleep(0.2)
    except KeyboardInterrupt:
        print()


# ---------------------------------------------------------------------------
# selftest：模擬匯流排，不需要硬體與 pyserial
# ---------------------------------------------------------------------------


class FakeServo:
    def __init__(self, sid: int, pos: int = 1500, volt: int = 74):
        self.mem = bytearray(128)
        self.mem[ADDR_MODEL:ADDR_MODEL + 2] = bytes([MODEL_STS3215 & 0xFF, MODEL_STS3215 >> 8])
        self.mem[ADDR_ID] = sid
        self.mem[ADDR_P] = 16
        self.mem[ADDR_ACCEL] = 254
        self.mem[ADDR_MAX_ACCEL] = 254
        self.mem[ADDR_LOCK] = 1
        self.mem[ADDR_VOLTAGE] = volt
        self.mem[ADDR_TEMP] = 28
        self.set_pos(pos)

    @property
    def sid(self):
        return self.mem[ADDR_ID]

    def set_pos(self, pos):
        self.mem[ADDR_PRESENT_POS:ADDR_PRESENT_POS + 2] = bytes([pos & 0xFF, pos >> 8])


class FakeLink:
    def __init__(self, servos, echo: bool = False):
        self.servos = servos
        self.echo = echo
        self.rx = bytearray()
        self.writes = []

    @property
    def in_waiting(self):
        return len(self.rx)

    def reset_input_buffer(self):
        self.rx.clear()

    def read(self, n):
        out = bytes(self.rx[:n])
        del self.rx[:n]
        return out

    def write(self, pkt):
        self.writes.append(bytes(pkt))
        if self.echo:
            self.rx += pkt
        sid, length, instr = pkt[2], pkt[3], pkt[4]
        params = pkt[5:5 + length - 2]
        assert checksum(pkt[2:-1]) == pkt[-1]
        for s in [s for s in self.servos if s.sid == sid]:
            reply_id = s.sid
            out = b""
            if instr == INST_READ:
                addr, n = params[0], params[1]
                out = bytes(s.mem[addr:addr + n])
            elif instr == INST_WRITE:
                addr, data = params[0], params[1:]
                s.mem[addr:addr + len(data)] = data
                if s.mem[ADDR_TORQUE] and addr <= ADDR_GOAL_POS < addr + len(data):
                    s.set_pos(s.mem[ADDR_GOAL_POS] | (s.mem[ADDR_GOAL_POS + 1] << 8))
            body = bytes([reply_id, len(out) + 2, 0]) + out
            self.rx += b"\xff\xff" + body + bytes([checksum(body)])


def selftest():
    failures = 0

    def check(name, cond):
        nonlocal failures
        print(("  ok   " if cond else "  FAIL ") + name)
        failures += not cond

    quiet = lambda *a, **k: None  # noqa: E731

    print("協定")
    check("PING ID 1 封包＝ff ff 01 02 01 fb", build_packet(1, INST_PING) == bytes.fromhex("ffff010201fb"))
    check("READ 位置封包校驗碼", build_packet(14, INST_READ, bytes([56, 2]))[-1] == checksum(bytes([14, 4, 2, 56, 2])))
    try:
        parse_status(bytearray.fromhex("ffff0e0200ee"), 14)  # 正確應為 ef
        check("校驗碼錯誤會被擋下", False)
    except BadReply:
        check("校驗碼錯誤會被擋下", True)
    check("不完整封包回傳 None", parse_status(bytearray.fromhex("ffff0e"), 14) is None)
    check("位置換算 2048＝0 rad、rad_to_raw 可逆", raw_to_rad(2048) == 0 and rad_to_raw(raw_to_rad(3000)) == 3000)

    print("單顆設定（新舵機 ID 1 → 14）")
    s = FakeServo(1)
    bus = Bus(FakeLink([s]), timeout=0.001)
    r = configure_servo(bus, 14, log=quiet, settle=0)
    check("ID 改成 14", s.sid == 14 and r["previous_id"] == 1)
    check("上游參數 mode/maxacc/acc/P/I/D＝0/0/0/32/0/0",
          [s.mem[a] for _, a, _ in UPSTREAM_PARAMS] == [0, 0, 0, 32, 0, 0])
    check("EEPROM 已上鎖", s.mem[ADDR_LOCK] == 1)
    check("扭力開啟並停在零位 2048", s.mem[ADDR_TORQUE] == 1 and r["position_raw"] == 2048)

    print("回送（echo）的板子")
    s = FakeServo(1)
    bus = Bus(FakeLink([s], echo=True), timeout=0.001)
    r = configure_servo(bus, 23, log=quiet, settle=0)
    check("有回送時仍能設定", s.sid == 23 and r["position_raw"] == 2048)

    print("安全檢查")
    bus = Bus(FakeLink([FakeServo(1), FakeServo(5)]), timeout=0.001)
    try:
        configure_servo(bus, 10, log=quiet, settle=0)
        check("接兩顆時拒絕設定", False)
    except BusError as e:
        check("接兩顆時拒絕設定", "一次只能接一顆" in str(e))
    bus = Bus(FakeLink([]), timeout=0.001)
    try:
        configure_servo(bus, 10, log=quiet, settle=0)
        check("沒接舵機時回報找不到", False)
    except BusError as e:
        check("沒接舵機時回報找不到", "找不到舵機" in str(e))
    bus = Bus(FakeLink([FakeServo(1, volt=48)]), timeout=0.001)
    try:
        configure_servo(bus, 10, log=quiet, settle=0)
        check("電壓過低時拒絕設定", False)
    except BusError as e:
        check("電壓過低時拒絕設定", "低於" in str(e))

    print("整機檢查")
    servos = [FakeServo(i, pos=2048) for i in ALL_IDS if i != 31]
    rows = check_all(Bus(FakeLink(servos), timeout=0.001))
    bad = [r["id"] for r in rows if not r["ok"]]
    check("缺 ID 31 時只有 31 不通過", bad == [31])

    print("限速移動")
    s = FakeServo(12, pos=2600)
    s.mem[ADDR_TORQUE] = 1
    link = FakeLink([s])
    pos = move_to(Bus(link, timeout=0.001), 12, ZERO_RAW, wait=0.01)
    check("轉到零位", pos == 2048)
    check("結束後速度設回 0（不影響 Runtime）", s.mem[ADDR_GOAL_SPEED] == 0 and s.mem[ADDR_GOAL_SPEED + 1] == 0)

    print("\n全部通過" if not failures else f"\n{failures} 項失敗")
    return 0 if not failures else 1


def main(argv=None):
    global _QUIET
    ap = argparse.ArgumentParser(description="Open Duck Mini v2 舵機工作台（STS3215）")
    ap.add_argument("--port", help="舵機板序列埠，例如 /dev/cu.usbmodem1234 或 /dev/ttyACM0；省略時自動找")
    ap.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    ap.add_argument("--timeout", type=float, default=0.03, help="每次通訊等待秒數（預設 0.03）")
    ap.add_argument("--quiet", action="store_true", help="不要提示音")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("ports", help="列出序列埠")
    p = sub.add_parser("scan", help="掃描匯流排上的舵機")
    p.add_argument("--all-baud", action="store_true", help="所有 Feetech 鮑率都掃")
    p = sub.add_parser("setup", help="把唯一接著的一顆設成指定 ID 並轉到零位")
    p.add_argument("id", type=int)
    p.add_argument("--force", action="store_true", help="允許 14 軸表以外的 ID")
    p.add_argument("--log", default="servo_setup_log.json")
    p = sub.add_parser("wizard", help="14 顆逐顆設定精靈（可中斷、可續做）")
    p.add_argument("--log", default="servo_setup_log.json")
    p.add_argument("--redo", action="store_true", help="忽略紀錄檔，從第一顆重做")
    p = sub.add_parser("check", help="檢查 14 顆是否都在線")
    p.add_argument("ids", nargs="?", default="all", help="all、14、10-14、30,31")
    p.add_argument("--scan-extra", action="store_true", help="另外掃描是否有清單外的 ID（例如未設定的 ID 1）")
    p = sub.add_parser("center", help="限速轉到零位")
    p.add_argument("ids", help="all、14、10-14、30,31")
    p.add_argument("--speed", type=int, default=400, help="步／秒，預設 400（約 35°/s）")
    p.add_argument("--yes", action="store_true")
    p = sub.add_parser("relax", help="關扭力（可以用手轉）")
    p.add_argument("ids", help="all、14、10-14、30,31")
    p = sub.add_parser("monitor", help="即時顯示位置")
    p.add_argument("ids", nargs="?", default="all")
    p.add_argument("--relax", action="store_true", help="先關扭力，方便用手轉")
    sub.add_parser("selftest", help="不接硬體的內建檢查")

    args = ap.parse_args(argv)
    _QUIET = args.quiet
    handlers = {
        "ports": cmd_ports, "scan": cmd_scan, "setup": cmd_setup, "wizard": cmd_wizard,
        "check": cmd_check, "center": cmd_center, "relax": cmd_relax, "monitor": cmd_monitor,
    }
    if args.cmd == "selftest":
        sys.exit(selftest())
    try:
        handlers[args.cmd](args)
    except KeyboardInterrupt:
        print("\n已中斷。")
        sys.exit(130)


if __name__ == "__main__":
    main()
