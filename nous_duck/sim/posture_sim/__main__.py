"""蹲低／起立的量測：跑一組情境，印出表格並（可選）寫 JSON。數字是**模擬值**。

    cd nous_duck/sim
    .venv/bin/python -m posture_sim                                   # 印表格（約 1 分鐘）
    .venv/bin/python -m posture_sim --out ../docs/validation/data/posture-crouch-sim-2026-11-28.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from walk_sim.mass import budget_items, load_budget
from walk_sim.model import ModelOptions

from .poses import CROUCH, CROUCH_HEAD_DOWN, SIT3, STAND
from .sim import PostureSim, Segment, crouch_cycle, head_level_offset, partial

KP = 13.37


def scenarios():
    budget = load_budget("p2_single_pi4.json")
    yield "nominal", "標準：3 秒蹲下、停 5 秒、3 秒起立", ModelOptions(), crouch_cycle(), {}
    yield "head_down", "頭不抬（對照）", ModelOptions(), crouch_cycle(crouch=CROUCH_HEAD_DOWN), {}
    yield "fast", "快：1.5 秒蹲下、1.5 秒起立", ModelOptions(), crouch_cycle(duration=1.5), {}
    yield "slow", "慢：6 秒蹲下、6 秒起立", ModelOptions(), crouch_cycle(duration=6.0), {}
    yield "kp70", "舵機 kp −30%", ModelOptions(kp=KP * 0.7), crouch_cycle(), {}
    yield "kp70_f2", "kp −30%、力矩上限 2.0 N·m", ModelOptions(kp=KP * 0.7, force_limit=2.0), crouch_cycle(), {}
    yield "mu04", "地板摩擦 0.4（比較滑）", ModelOptions(floor_friction=0.4), crouch_cycle(), {}
    yield "playground_solver", "Playground 的求解器設定", ModelOptions(solver="playground"), crouch_cycle(), {}
    yield (
        "mass_high",
        "加裝件取上限（單板 Pi 4，質量預算 p2_single_pi4）",
        ModelOptions(mass_items=tuple(budget_items(budget, "high"))),
        crouch_cycle(),
        {},
    )
    yield (
        "mass_high_kp70",
        "加裝件取上限＋kp −30%",
        ModelOptions(kp=KP * 0.7, mass_items=tuple(budget_items(budget, "high"))),
        crouch_cycle(),
        {},
    )
    # 控制迴圈卡住：蹲到一半（第 1.5 秒）卡 0.2 秒／1 秒。
    yield "stall_200ms", "蹲到一半控制迴圈卡 0.2 秒", ModelOptions(), crouch_cycle(), {"stall": (1.5, 0.2)}
    yield "stall_1s", "蹲到一半控制迴圈卡 1 秒，恢復後目標直接跳到該到的位置", ModelOptions(), crouch_cycle(), {"stall": (1.5, 1.0)}
    yield (
        "stall_1s_pause",
        "蹲到一半控制迴圈卡 1 秒，時間軸跟著暫停",
        ModelOptions(),
        crouch_cycle(),
        {"stall": (1.5, 1.0), "stall_mode": "pause"},
    )
    # 中途停住（收手方案一：停在目前目標）：在 25／50／75 % 的位置停 10 秒，再起立。
    for f in (0.25, 0.5, 0.75):
        yield (
            f"freeze_{int(f * 100)}",
            f"蹲到 {int(f * 100)}% 停住 10 秒再起立",
            ModelOptions(),
            [Segment(partial(f), 3.0 * f, "down"), Segment(None, 10.0, "hold"), Segment(STAND, 3.0, "up"), Segment(None, 2.0, "settle")],
            {},
        )
    # 收手方案二：放鬆（kp 降到 0.5）。在蹲到一半、蹲好時各試一次。
    yield "limp_mid", "蹲到一半時放鬆（kp 0.5）", ModelOptions(), crouch_cycle(), {"limp_at": 1.5}
    yield "limp_crouched", "蹲好後放鬆（kp 0.5）", ModelOptions(), crouch_cycle(), {"limp_at": 5.0}
    yield "limp_standing", "站著時放鬆（kp 0.5），對照", ModelOptions(), [Segment(None, 1.0, "stand"), Segment(None, 5.0, "limp")], {"limp_at": 1.0}
    # 對照：使用者的「坐下3」，從站姿直接過去。
    yield "sit3_direct", "對照：從站姿直接換到「坐下3」", ModelOptions(), [Segment(SIT3, 3.0, "down"), Segment(None, 3.0, "hold")], {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, help="寫 JSON 結果")
    args = ap.parse_args(argv)
    rows = []
    for key, label, opts, segs, kw in scenarios():
        r = PostureSim(opts).run(segs, **kw).to_dict()
        r.update(key=key, label=label)
        rows.append(r)
        lowest = min(s["base_z"] for s in r["segments"])
        pitch_max = max(s["pitch_range_deg"][1] for s in r["segments"])
        pitch_min = min(s["pitch_range_deg"][0] for s in r["segments"])
        end = r["segments"][-1]
        print(
            f"{key:18s} 下降 {r['base_drop_cm']:5.2f} cm  最低 {lowest:.3f} m  俯仰 {pitch_min:6.1f}～{pitch_max:5.1f}°  "
            f"結束 {end['base_z']:.3f} m／{end['trunk_pitch_deg']:6.1f}°  重心餘裕最小 {r['min_support_margin_cm']:5.2f} cm  "
            f"腳滑 {r['foot_slip_cm']:4.2f} cm  力矩 {r['max_torque_nm']:.2f} N·m  {'倒' if r['fell'] else '站'}  {label}"
        )
    offset = head_level_offset()
    print(f"head_level_offset（頭不抬的蹲姿要加多少 head_pitch 才回到站姿的頭部俯仰）：{offset:.3f} rad")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "level": "simulation (MuJoCo)",
            "poses": {"stand": STAND, "crouch": CROUCH, "crouch_head_down": CROUCH_HEAD_DOWN, "sit3": SIT3},
            "head_level_offset_rad": round(offset, 4),
            "results": rows,
        }
        args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"寫入 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
