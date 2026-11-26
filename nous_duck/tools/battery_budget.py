#!/usr/bin/env python3
"""低電量回充的名目推算：回家要多少電、四個電量等級的門檻、各等級還能撐多久（只用標準函式庫）。

用途：[`docs/adr/ADR-0009-low-battery-return-interaction.md`](../docs/adr/ADR-0009-low-battery-return-interaction.md)
裡的數字都由這支腳本算出，方法與輸出記錄在 `docs/validation/battery-budget-2026-11-26.md`。

**全部是名目推算，不是量測。** 鴨子還沒走過路，耗電、速度、電池可用容量都沒量過；
下面每個輸入都是假設值，量到實際數字後要換掉再重算。

模型（ADR-0009 §3）：

    E_home  = P_walk × (d / v) + n_dock × P_walk × t_dock     走回家＋對位重試要的電
    E_need  = E_home + E_reserve                               再加固定保留（安全停機、估算誤差以外的餘量）
    E_low   = 剩餘電量估計的下限（估計值減掉不確定度）
    m       = E_low / E_need                                   餘裕倍數

    m < 3.0 → L1 提醒；m < 2.0 → L2 請求回家；m < 1.5 → L3 直接回家；m < 1.2 → L4 走不回去

用法：

    python3 -I nous_duck/tools/battery_budget.py            # 輸出 Markdown 表格
    python3 -I nous_duck/tools/battery_budget.py --check    # 只跑內建檢查
"""

from __future__ import annotations

import argparse

# ---- 電池（假設值；依上游 BOM：2S 18650、每顆約 3000 mAh） ----
CELL_MAH = 3000
SERIES = 2
NOMINAL_V_PER_CELL = 3.7
USABLE_FRACTION = 0.85  # 假設：放到約 3.3 V/顆（負載下）能用到的比例，未量測
CAPACITY_WH = CELL_MAH / 1000 * SERIES * NOMINAL_V_PER_CELL  # 22.2 Wh
USABLE_WH = CAPACITY_WH * USABLE_FRACTION

# ---- 耗電（假設值，未量測） ----
P_WALK_W = 18.0  # 走路：Pi 4（鏡頭＋導航）約 5 W ＋ 14 顆舵機走路
P_STAND_W = 10.0  # 原地站著：舵機維持扭力＋Pi 4

# ---- 回家路徑與對位（假設值） ----
V_EFF_MPS = 0.10  # 含轉彎、停頓的有效速度；上游手把上限是 0.15 m/s，未實測
DOCK_TRIES = 3  # ADR-0004 §3 的重試次數 N（草案）
DOCK_TRY_S = 90.0  # 每次對位（看標籤、轉身、倒退、確認接觸）
RESERVE_WH = 1.5  # 固定保留：安全停機、等人來抱的站立時間

# ---- 剩餘電量估計的不確定度（佔可用容量的比例，假設值） ----
UNCERTAINTY = {
    "只用電壓（目前）": 0.20,
    "加裝電流感測（INA219／INA226）": 0.05,
}

# ---- 等級門檻（ADR-0009 §3.2；餘裕倍數 m） ----
LEVELS = (
    ("L1 提醒", 3.0),
    ("L2 請求回家", 2.0),
    ("L3 直接回家", 1.5),
    ("L4 走不回去", 1.2),
)

DISTANCES_M = (3.0, 10.0, 20.0)


def e_home_wh(d_m: float) -> float:
    """走 d_m 公尺回家、加上對位重試要的電（Wh）。"""
    walk_s = d_m / V_EFF_MPS
    dock_s = DOCK_TRIES * DOCK_TRY_S
    return P_WALK_W * (walk_s + dock_s) / 3600.0


def e_need_wh(d_m: float) -> float:
    return e_home_wh(d_m) + RESERVE_WH


def margin(e_low_wh: float, d_m: float) -> float:
    return e_low_wh / e_need_wh(d_m)


def level_of(m: float) -> str:
    """依餘裕倍數回傳等級名稱；比 L1 門檻寬就回 'L0 正常'。"""
    name = "L0 正常"
    for lv, threshold in LEVELS:
        if m < threshold:
            name = lv
    return name


def threshold_wh(d_m: float, m: float) -> float:
    """要讓餘裕倍數剛好等於 m，剩餘電量下限要多少（Wh）。"""
    return m * e_need_wh(d_m)


def estimate_wh_at(d_m: float, m: float, unc: float) -> float:
    """門檻換算成「估計值」：估計值 − 不確定度 = 下限，所以估計值 = 下限 + 不確定度。"""
    return threshold_wh(d_m, m) + unc * USABLE_WH


def stand_minutes(wh: float) -> float:
    return wh / P_STAND_W * 60.0


def checks() -> None:
    assert abs(CAPACITY_WH - 22.2) < 1e-9
    # 10 m：100 s 走路＋270 s 對位 = 370 s × 18 W = 1.85 Wh
    assert abs(e_home_wh(10.0) - 18.0 * 370 / 3600) < 1e-9
    # 等級單調：門檻倍數嚴格遞減
    ms = [m for _, m in LEVELS]
    assert all(a > b for a, b in zip(ms, ms[1:]))
    assert level_of(3.5) == "L0 正常"
    assert level_of(2.5) == "L1 提醒"
    assert level_of(1.9) == "L2 請求回家"
    assert level_of(1.3) == "L3 直接回家"
    assert level_of(1.0) == "L4 走不回去"
    # 距離越遠，同一等級要的電越多
    for _, m in LEVELS:
        assert threshold_wh(3.0, m) < threshold_wh(10.0, m) < threshold_wh(20.0, m)
    # 不確定度越大，同一門檻對應的估計值越高（越早提醒）
    assert estimate_wh_at(10.0, 2.0, 0.20) > estimate_wh_at(10.0, 2.0, 0.05)
    # L4 門檻在 20 m 時仍低於可用容量（不然模型沒意義）
    assert estimate_wh_at(20.0, 3.0, 0.20) < USABLE_WH * 1.5


def report() -> str:
    out: list[str] = []
    out.append("## 輸入（假設值）\n")
    out.append(f"- 電池名目容量 {CAPACITY_WH:.1f} Wh（{SERIES}S × {CELL_MAH} mAh × {NOMINAL_V_PER_CELL} V），可用比例 {USABLE_FRACTION:.0%} → 可用 {USABLE_WH:.2f} Wh")
    out.append(f"- 走路 {P_WALK_W:.0f} W、站著 {P_STAND_W:.0f} W；有效速度 {V_EFF_MPS:.2f} m/s；對位 {DOCK_TRIES} 次 × {DOCK_TRY_S:.0f} s；固定保留 {RESERVE_WH:.1f} Wh\n")

    out.append("## 回家要的電\n")
    out.append("| 回家路徑 | 走路時間 | E_home (Wh) | E_need (Wh) | 佔可用容量 |")
    out.append("|---|---|---|---|---|")
    for d in DISTANCES_M:
        out.append(f"| {d:.0f} m | {d / V_EFF_MPS / 60:.1f} 分 | {e_home_wh(d):.2f} | {e_need_wh(d):.2f} | {e_need_wh(d) / USABLE_WH:.0%} |")
    out.append("")

    for label, unc in UNCERTAINTY.items():
        out.append(f"## 各等級的門檻：{label}（不確定度 ±{unc:.0%} 可用容量 = {unc * USABLE_WH:.2f} Wh）\n")
        out.append("表內是**剩餘電量估計值**降到多少時進入該等級（Wh／佔可用容量）。")
        out.append("")
        out.append("| 回家路徑 | " + " | ".join(lv for lv, _ in LEVELS) + " |")
        out.append("|---|" + "---|" * len(LEVELS))
        for d in DISTANCES_M:
            cells = []
            for _, m in LEVELS:
                e = estimate_wh_at(d, m, unc)
                cells.append(f"{e:.1f}（{e / USABLE_WH:.0%}）" if e <= USABLE_WH else f"{e:.1f}（>100%，一開機就在這級）")
            out.append(f"| {d:.0f} m | " + " | ".join(cells) + " |")
        out.append("")

    out.append("## 站著不動時，從進入某級到下一級還有多久（只用電壓，10 m）\n")
    out.append("| 從 → 到 | 差距 (Wh) | 站著約幾分鐘 |")
    out.append("|---|---|---|")
    unc = UNCERTAINTY["只用電壓（目前）"]
    for (a, ma), (b, mb) in zip(LEVELS, LEVELS[1:]):
        gap = threshold_wh(10.0, ma) - threshold_wh(10.0, mb)
        out.append(f"| {a} → {b} | {gap:.2f} | {stand_minutes(gap):.0f} |")
    out.append("")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="只跑內建檢查")
    args = ap.parse_args()
    checks()
    if args.check:
        print("battery_budget: checks passed")
        return
    print(report())


if __name__ == "__main__":
    main()
