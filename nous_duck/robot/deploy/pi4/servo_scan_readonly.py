#!/usr/bin/env python3
"""唯讀掃描 Feetech STS3215 舵機匯流排（ADR-0008，Pi 4 單板）。

只送 PING 與 READ 指令，**不寫任何暫存器、不開扭力、不會讓舵機動**。
用來在第一次通電後確認：14 顆舵機的 ID 都在、沒有重複或沒設定的 ID（出廠預設是 1）、
電壓與溫度正常、目前角度。

用法（在 Pi 上，runtime-venv）：
    ~/duck/runtime-venv/bin/python servo_scan_readonly.py [--port /dev/ttyACM0] [--max-id 60]

ID 對照取自上游 Open_Duck_Mini_Runtime（commit 376de65）的
mini_bdx_runtime/rustypot_position_hwi.py 與 scripts/check_voltage.py。
"""

import argparse
import sys

from pypot.feetech import FeetechSTS3215IO

# 上游的關節名稱與舵機 ID（右腿 10–14、左腿 20–24、頭頸 30–33）
EXPECTED = {
    10: "right_hip_yaw",
    11: "right_hip_roll",
    12: "right_hip_pitch",
    13: "right_knee",
    14: "right_ankle",
    20: "left_hip_yaw",
    21: "left_hip_roll",
    22: "left_hip_pitch",
    23: "left_knee",
    24: "left_ankle",
    30: "neck_pitch",
    31: "head_pitch",
    32: "head_yaw",
    33: "head_roll",
}


def read_one(io, motor_id, getter):
    """讀一個值；讀不到回傳錯誤說明字串（不中斷整個掃描）。"""
    try:
        return getter([motor_id])[0]
    except Exception as exc:  # pypot 對逾時或錯誤封包會丟例外
        return f"錯誤：{type(exc).__name__}"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", default="/dev/ttyACM0")
    parser.add_argument("--max-id", type=int, default=60, help="掃描 ID 0 到這個值（預設 60）")
    args = parser.parse_args()

    io = FeetechSTS3215IO(args.port, baudrate=1000000, timeout=0.02)
    try:
        found = [i for i in range(0, args.max_id + 1) if io.ping(i)]

        print(f"掃描 ID 0–{args.max_id}，回應的 ID：{found if found else '沒有'}")
        if not found:
            print("沒有任何舵機回應。舵機電源有開嗎？（驅動板的 DC 輸入）")
            return 1

        print()
        print(f"{'ID':>3}  {'關節':<16} {'電壓(V)':>7} {'溫度(°C)':>8} {'角度(°)':>8}  {'原始位置':>8}")
        for motor_id in found:
            name = EXPECTED.get(motor_id, "（不在上游清單）")
            volt_raw = read_one(io, motor_id, io.get_present_voltage)
            temp = read_one(io, motor_id, io.get_present_temperature)
            pos = read_one(io, motor_id, io.get_present_position)
            raw = read_one(io, motor_id, io.get_present_position_raw)
            volt = round(volt_raw * 0.1, 1) if isinstance(volt_raw, (int, float)) else volt_raw
            pos = round(pos, 1) if isinstance(pos, float) else pos
            print(f"{motor_id:>3}  {name:<16} {volt!s:>7} {temp!s:>8} {pos!s:>8}  {raw!s:>8}")

        missing = sorted(set(EXPECTED) - set(found))
        extra = sorted(set(found) - set(EXPECTED))
        print()
        print(f"上游清單 14 顆，找到 {len(set(found) & set(EXPECTED))} 顆")
        if missing:
            print("缺少：" + "、".join(f"{i}（{EXPECTED[i]}）" for i in missing))
        if extra:
            print("多出（可能沒設定 ID，出廠預設是 1）：" + "、".join(str(i) for i in extra))
        return 0 if not missing and not extra else 2
    finally:
        io.close()


if __name__ == "__main__":
    sys.exit(main())
