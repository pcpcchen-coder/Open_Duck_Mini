"""唯讀：BNO055（0x28）重複讀固定不變的暫存器，數讀錯的次數並量讀取時間。只寫暫存器位址、不寫值。

用法（Pi）：python3 bno055_i2c_probe.py 2000（紀錄 docs/validation/bno055-i2c-2026-11-28.md）
"""
import fcntl, json, os, struct, sys, time
N = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
fd = os.open("/dev/i2c-1", os.O_RDWR); fcntl.ioctl(fd, 0x0703, 0x28)
def rd(reg, n=1):
    os.write(fd, bytes([reg])); return os.read(fd, n)
from collections import Counter
chip = Counter(); unit = Counter(); amap = Counter(); temp = Counter(); page = Counter(); errs = 0
t0 = time.time()
for _ in range(N):
    try:
        chip[rd(0x00)[0]] += 1; unit[rd(0x3B)[0]] += 1; amap[rd(0x41)[0]] += 1; temp[rd(0x34)[0]] += 1; page[rd(0x07)[0]] += 1
    except OSError:
        errs += 1
dt1 = (time.time() - t0) / (5 * N)
# 8-byte quaternion read timing
t0 = time.time(); qerr = 0
for _ in range(500):
    try: rd(0x20, 8)
    except OSError: qerr += 1
dtq = (time.time() - t0) / 500
print(json.dumps({"n": N, "chip_id_0xA0_expected": dict(chip), "unit_sel": dict(unit), "axis_map": dict(amap), "temp": dict(temp), "page_id_0_expected": dict(page), "oserrors": errs,
                  "ms_per_1byte_read": round(dt1 * 1000, 3), "ms_per_quat_read": round(dtq * 1000, 3), "quat_oserrors": qerr}))
