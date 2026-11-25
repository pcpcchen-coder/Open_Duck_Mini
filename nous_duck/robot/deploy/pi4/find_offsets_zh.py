#!/usr/bin/env python3
"""中文版零點偏移校正（照上游 scripts/find_soft_offsets.py 的流程，不改上游）。

和上游的差別：
- 提示改成中文，每一步都顯示舵機 ID。
- 依 ID 順序（10–14 右腿、20–24 左腿、30–33 頭頸），可用 --ids 只校正指定的幾顆。
- 每顆量完印出偏移的弧度與角度；做完後可以直接寫進 ~/duck_config.json（先備份）。
- 結束或 Ctrl-C 時關掉全部扭力。

流程（每顆）：全部舵機回零點 → 只放鬆這一顆 → 你用手把它扳到正確的零點 →
偏移 = 扳完的位置 − 指令零點的位置 → 帶著偏移回零點、重新出力 → 你確認。

上游來源：Open_Duck_Mini_Runtime commit 376de65 的 scripts/find_soft_offsets.py、
mini_bdx_runtime/rustypot_position_hwi.py。

用法（在 Pi 上）：
    source ~/duck/runtime-venv/bin/activate
    cd ~/duck/Open_Duck_Mini_Runtime/scripts
    python ~/duck/find_offsets_zh.py            # 全部 14 顆
    python ~/duck/find_offsets_zh.py --ids 23 24  # 只校正 ID 23、24
"""

import argparse
import json
import math
import os
import shutil
import sys
import time

from mini_bdx_runtime.duck_config import DuckConfig
from mini_bdx_runtime.rustypot_position_hwi import HWI

CONFIG_PATH = os.path.expanduser("~/duck_config.json")

ZH_NAMES = {
    "right_hip_yaw": "右髖・左右轉",
    "right_hip_roll": "右髖・側擺",
    "right_hip_pitch": "右髖・前後擺",
    "right_knee": "右膝",
    "right_ankle": "右踝",
    "left_hip_yaw": "左髖・左右轉",
    "left_hip_roll": "左髖・側擺",
    "left_hip_pitch": "左髖・前後擺",
    "left_knee": "左膝",
    "left_ankle": "左踝",
    "neck_pitch": "脖子・俯仰",
    "head_pitch": "頭・俯仰",
    "head_yaw": "頭・左右轉",
    "head_roll": "頭・側傾",
}


def ask(prompt):
    return input(prompt).strip().lower()


def label(hwi, name):
    return f"ID {hwi.joints[name]}（{ZH_NAMES[name]}，{name}）"


def fmt(rad):
    return f"{rad:+.3f} rad（{math.degrees(rad):+.1f}°）"


def save_offsets(measured):
    """把量到的偏移寫進 ~/duck_config.json；先備份，只改有量的關節。"""
    if os.path.exists(CONFIG_PATH):
        backup = f"{CONFIG_PATH}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(CONFIG_PATH, backup)
        print(f"已備份原設定：{backup}")
        with open(CONFIG_PATH, encoding="utf-8") as f:
            config = json.load(f)
    else:
        config = {}
    offsets = config.setdefault("joints_offsets", {})
    for name, value in measured.items():
        offsets[name] = round(float(value), 4)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
        f.write("\n")
    print(f"已寫入 {CONFIG_PATH}")


def main():
    parser = argparse.ArgumentParser(description="中文版零點偏移校正")
    parser.add_argument("--ids", type=int, nargs="*", help="只校正這些 ID（預設全部 14 顆）")
    args = parser.parse_args()

    # 跟上游一樣：量測時所有偏移從 0 開始，量的是相對舵機原始零點的偏移
    dummy = DuckConfig(config_json_path=None, ignore_default=True)
    hwi = HWI(dummy)
    for name in hwi.joints_offsets:
        hwi.joints_offsets[name] = 0.0

    by_id = {joint_id: name for name, joint_id in hwi.joints.items()}
    order = sorted(by_id) if not args.ids else args.ids
    unknown = [i for i in order if i not in by_id]
    if unknown:
        print(f"沒有這些 ID：{unknown}。可用的 ID：{sorted(by_id)}")
        return 1
    names = list(hwi.joints.keys())

    print("======")
    print("注意：按 Enter 後，14 顆舵機會用正常扭力（kp=32）很快轉到零點。")
    print("請把鴨子懸空拿好或仰躺、腳朝上，腿和脖子擺動時不要撞到東西或夾到手。")
    print("要校正的舵機：" + "、".join(str(i) for i in order))
    print("隨時可以按 Ctrl-C 停止，全部舵機會關掉扭力。")
    print("======")
    if ask("準備好了按 Enter 開始（輸入 q 離開）：") == "q":
        return 0

    measured = {}
    try:
        hwi.init_pos = hwi.zero_pos
        hwi.set_kds([0] * len(hwi.joints))
        hwi.turn_on()
        hwi.set_position_all(hwi.zero_pos)
        time.sleep(1)

        for n, joint_id in enumerate(order, 1):
            name = by_id[joint_id]
            i = names.index(name)
            while True:
                print()
                print(f"=== [{n}/{len(order)}] {label(hwi, name)} ===")
                res = ask("Enter 開始校正這顆，s 跳過，q 結束：")
                if res == "q":
                    raise StopIteration
                if res == "s":
                    print(f"跳過 ID {joint_id}")
                    break

                hwi.joints_offsets[name] = 0.0
                hwi.set_position_all(hwi.zero_pos)
                time.sleep(0.5)
                positions = hwi.get_present_positions()
                if positions is None:
                    print("讀不到位置，再試一次")
                    continue
                current = positions[i]

                hwi.io.disable_torque([joint_id])
                input(f"ID {joint_id} 已經放鬆。用手把它扳到正確的零點，扶住不動，按 Enter 記錄：")
                positions = hwi.get_present_positions()
                if positions is None:
                    print("讀不到位置，再試一次")
                    hwi.io.enable_torque([joint_id])
                    continue
                offset = float(positions[i] - current)
                print(f"ID {joint_id} 的偏移：{fmt(offset)}")
                if abs(offset) > math.radians(15):
                    print("偏移超過 15°，可能舵盤裝錯一齒或扳錯方向，請再確認一次。")

                hwi.joints_offsets[name] = offset
                input("按 Enter，讓它帶著這個偏移回到零點並重新出力：")
                hwi.set_position_all(hwi.zero_pos)
                time.sleep(0.5)
                hwi.io.enable_torque([joint_id])

                res = ask(f"ID {joint_id} 現在的位置對嗎？（Enter／y 對，n 重來）：")
                if res in ("", "y"):
                    measured[name] = offset
                    print(f"✓ ID {joint_id} 偏移設為 {fmt(offset)}")
                    break
                print("好，重來一次")
                hwi.joints_offsets[name] = 0.0
    except StopIteration:
        print("提前結束")
    except KeyboardInterrupt:
        print("\n中斷，關掉全部扭力（偏移沒有寫入設定檔）")
        hwi.turn_off()
        report(hwi, measured)
        return 130

    try:
        report(hwi, measured)
        if measured and ask("要寫進 ~/duck_config.json 嗎？（Enter／y 寫入，n 不寫）：") in ("", "y"):
            save_offsets(measured)
        input("按 Enter 關掉全部扭力（鴨子會變軟，請扶好）：")
    except KeyboardInterrupt:
        print()
    finally:
        hwi.turn_off()
        print("扭力已關。")
    return 0


def report(hwi, measured):
    print()
    print("------ 這次量到的偏移 ------")
    if not measured:
        print("（沒有）")
    for name, joint_id in sorted(hwi.joints.items(), key=lambda kv: kv[1]):
        if name in measured:
            print(f"ID {joint_id:>2}  {ZH_NAMES[name]:<8} {name:<16} {fmt(measured[name])}")
    print("----------------------------")


if __name__ == "__main__":
    sys.exit(main())
