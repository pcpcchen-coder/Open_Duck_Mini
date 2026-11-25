#!/usr/bin/env python3
"""通道探測（在 Pi 上執行，只用 Python 標準函式庫，不寫檔、不碰任何硬體）。

用途：確認 SSH 通道通了、Pi 上的程式連得到 Mac 的 duck-link hub，並量經過 Wi-Fi＋SSH 通道的心跳往返時間。
它會以「探測程式」的身分完成 duck-link 的 hello（mock: true，software 註明不是鴨子），回應 hub 的心跳幾秒後離開。
它不是鴨子：不送 state、不接受任何指令（收到指令一律回 rejected: unsupported）。

用法（在 Mac 上，hub 與通道都開著時）：
    ssh duck-pi4 python3 - < scripts/tunnel-probe.py
輸出一行 JSON：hub 的 hello、收到幾次心跳、探測程式量到的心跳間隔。
往返時間要看 Mac 這邊的 `duckctl link`（hub 用鴨子的回聲量）。
"""
import base64, json, os, socket, struct, sys, time

HOST, PORT, PATH = "127.0.0.1", int(os.environ.get("DUCK_HUB_PORT", "8791")), "/duck-link"
SECONDS = float(os.environ.get("PROBE_SECONDS", "6"))


def send_text(sock, text):
    data = text.encode()
    mask = os.urandom(4)
    head = bytes([0x81])
    n = len(data)
    head += bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n)
    sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))


def read_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("closed")
        buf += chunk
    return buf


def read_frame(sock):
    b0, b1 = read_exact(sock, 2)
    n = b1 & 0x7F
    if n == 126:
        n = struct.unpack(">H", read_exact(sock, 2))[0]
    elif n == 127:
        n = struct.unpack(">Q", read_exact(sock, 8))[0]
    return b0 & 0x0F, read_exact(sock, n)


def msg(**body):
    return json.dumps({"protocol_version": "0.1", "sent_at_ms": int(time.time() * 1000), **body})


result = {"probe": "tunnel-probe (not a duck)", "connected": False}
try:
    sock = socket.create_connection((HOST, PORT), timeout=5)
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall((f"GET {PATH} HTTP/1.1\r\nHost: {HOST}:{PORT}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                  f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    head = b""
    while b"\r\n\r\n" not in head:
        head += sock.recv(1)
    result["http_status"] = head.split(b"\r\n")[0].decode()
    if b" 101 " not in head.split(b"\r\n")[0]:
        raise ConnectionError("upgrade refused")
    result["connected"] = True
    send_text(sock, msg(type="hello", role="duck", software="tunnel-probe (not a duck)", duck_id="tunnel_probe", mock=True, capabilities={}))
    sock.settimeout(2)
    beats, arrivals, end = 0, [], time.monotonic() + SECONDS
    while time.monotonic() < end:
        try:
            opcode, payload = read_frame(sock)
        except socket.timeout:
            continue
        if opcode == 8:
            result["closed_by_hub"] = struct.unpack(">H", payload[:2])[0] if len(payload) >= 2 else None
            break
        if opcode != 1:
            continue
        m = json.loads(payload)
        if m["type"] == "hello":
            result["hub_hello"] = {"role": m.get("role"), "software": m.get("software")}
        elif m["type"] == "heartbeat":
            beats += 1
            arrivals.append(time.monotonic())
            send_text(sock, msg(type="heartbeat", seq=m["seq"], echo_of=m["seq"]))
        elif m["type"] == "command":
            send_text(sock, msg(type="ack", request_id=m["request_id"], status="rejected", reason="unsupported", detail="tunnel probe, not a duck"))
    gaps = [round((b - a) * 1000) for a, b in zip(arrivals, arrivals[1:])]
    result.update(heartbeats=beats, heartbeat_gap_ms={"min": min(gaps), "max": max(gaps), "mean": round(sum(gaps) / len(gaps))} if gaps else None)
    sock.close()
except Exception as exc:  # noqa: BLE001
    result["error"] = f"{type(exc).__name__}: {exc}"
print(json.dumps(result, ensure_ascii=False))
sys.exit(0 if result.get("heartbeats") else 1)
