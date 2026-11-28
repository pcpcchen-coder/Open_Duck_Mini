"""唯讀探測（2026-11-28 duckd-posture 驗證紀錄 §5.1）：每輪讀 14 顆的電壓、溫度、電流（同步讀），印出 JSON。

不寫任何暫存器、不開扭力。匯流排要空著（舵機控制台與 duckd 都沒接手）。
用法（Pi）：~/duck/duckd-venv/bin/python status_noise_probe.py 1500 > probe.json
"""
import json, statistics, sys, time
from pypot.feetech import FeetechSTS3215IO
IDS = [10, 11, 12, 13, 14, 20, 21, 22, 23, 24, 30, 31, 32, 33]
N = int(sys.argv[1])
io = FeetechSTS3215IO("/dev/ttyACM0", baudrate=1000000, timeout=0.02, use_sync_read=True)
rows = []
t0 = time.time()
for k in range(N):
    try:
        v = io.get_present_voltage(IDS); t = io.get_present_temperature(IDS); c = io.get_present_current(IDS)
        rows.append((time.time() - t0, list(v), list(t), [int(x) & 0x7FFF for x in c]))
    except Exception as exc:
        rows.append((time.time() - t0, None, None, repr(exc)[:80]))
        try: io.flush()
        except Exception: pass
io.close()
print(json.dumps({"ids": IDS, "rows": rows}))
