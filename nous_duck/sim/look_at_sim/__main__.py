"""跑全部情境，輸出 Markdown 表格（驗證紀錄用）。"""

from __future__ import annotations

import argparse
import math

from .sim import SCENARIOS, SimOptions, run_scenario


def _deg(x):
    s = _f(x)
    return s if s == "—" else s + "°"


def _f(x, nd=1):
    if x is None:
        return "—"
    if isinstance(x, float) and math.isnan(x):
        return "—"
    return f"{x:.{nd}f}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seeds", type=int, default=3, help="每個情境跑幾個亂數種子（預設 3）")
    ap.add_argument("--no-readback", action="store_true", help="偵測結果不附舵機回讀")
    args = ap.parse_args()

    print("| 情境 | 種子 | 看準所需時間 | 最後 2 s 誤差（中位／最大） | 人在畫面內（最後 2 s） | 頭頸最大角速度 | 身體轉角 | 換人次數 | 仰角不夠 | 最後狀態 |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---|---|")
    for name, sc in SCENARIOS.items():
        for seed in range(args.seeds):
            r = run_scenario(sc, SimOptions(seed=seed, use_joint_readback=not args.no_readback))
            T = sc.duration
            med, mx = r.error_stats(T - 2, T)
            settle = r.settle_time(t_from=5.0) if name == "two_people_switch" else r.settle_time()
            print(
                f"| `{name}` | {seed} | {_f(settle)} s | {_deg(med)} ／ {_deg(mx)} | {r.in_view_ratio(T - 2, T):.0%} "
                f"| {_f(r.head_qvel_max, 2)} rad/s | {_f(math.degrees(r.body_yaw_final), 0)}° | {r.switch_count} "
                f"| {'是' if r.pitch_saturated_any else '否'} | {r.states[-1]} |"
            )
    print()
    print("情境說明：")
    print()
    for name, sc in SCENARIOS.items():
        print(f"- `{name}`（{sc.duration:.0f} s）：{sc.description}")


if __name__ == "__main__":
    main()
