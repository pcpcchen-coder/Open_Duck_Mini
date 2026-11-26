#!/usr/bin/env python3
"""低電量回充的名目推算：回家要多少電、四個電量等級的門檻、各等級還能撐多久（只用標準函式庫）。

用途：[`docs/adr/ADR-0012-low-battery-return-interaction.md`](../docs/adr/ADR-0012-low-battery-return-interaction.md)
裡的數字都由這支腳本算出，方法與輸出記錄在 `docs/validation/battery-budget-2026-11-26.md`。

**全部是名目推算，不是量測。** 鴨子還沒走過路，耗電、速度、電池可用容量都沒量過；
下面每個輸入都是假設值，量到實際數字後要換掉再重算。

模型（ADR-0012 §3）：

    E_home  = P_walk × (d / v) + n_dock × P_walk × t_dock     走回家＋對位重試要的電
    E_need  = E_home + E_reserve                               再加固定保留（安全停機、估算誤差以外的餘量）
    E_low   = 剩餘電量估計的下限（估計值減掉不確定度）
    m       = E_low / E_need                                   餘裕倍數

    m < 3.0 → L1 提醒；m < 2.0 → L2 請求回家；m < 1.5 → L3 直接回家；m < 1.2 → L4 走不回去

電量估算（2026-11-26 使用者決定：只用電壓，三元電池建表）：

    剩餘可用電量 = USABLE_WH × (SOC(每顆電壓) − SOC(3.3 V)) ÷ (1 − SOC(3.3 V))

SOC 用 NMC_OCV_TABLE 線性內插。表是常見三元（NMC）18650 靜置開路電壓的**代表值**，
不是這批電芯的量測；鴨子是在暫停、舵機仍出力時讀電壓，讀值會比開路電壓低，
要照 ADR-0012 §3.5 的站立放電實測重建這張表。

用法：

    python3 -I nous_duck/tools/battery_budget.py            # 輸出 Markdown 表格
    python3 -I nous_duck/tools/battery_budget.py --check    # 只跑內建檢查
"""

from __future__ import annotations

import argparse
import math

# ---- 電池（假設值；依上游 BOM：2S 18650、每顆約 3000 mAh） ----
CELL_MAH = 3000
SERIES = 2
NOMINAL_V_PER_CELL = 3.7
USABLE_FRACTION = 0.85  # 假設：放到約 3.3 V/顆能用到的比例（≈ 1 − SOC(3.3 V) 再打老化與溫度折扣），未量測
CAPACITY_WH = CELL_MAH / 1000 * SERIES * NOMINAL_V_PER_CELL  # 22.2 Wh
USABLE_WH = CAPACITY_WH * USABLE_FRACTION

# ---- 三元（NMC）18650 電壓對照表（每顆，靜置開路電壓，25 °C；代表值，未量測） ----
# (SOC, 每顆電壓 V)，SOC 由低到高。
NMC_OCV_TABLE = (
    (0.00, 3.00), (0.05, 3.40), (0.10, 3.50), (0.15, 3.57), (0.20, 3.61),
    (0.25, 3.64), (0.30, 3.67), (0.35, 3.70), (0.40, 3.73), (0.45, 3.76),
    (0.50, 3.79), (0.55, 3.82), (0.60, 3.85), (0.65, 3.88), (0.70, 3.92),
    (0.75, 3.96), (0.80, 4.00), (0.85, 4.05), (0.90, 4.10), (0.95, 4.15),
    (1.00, 4.20),
)
CUTOFF_V_PER_CELL = 3.3  # = VOLT_WARN_V 6.6 V ÷ 2（L4 硬底線）
SERVO_VOLT_STEP_V = 0.1  # STS3215 回報電壓的解析度（整組電池；上游 check_voltage.py 乘 0.1）


def soc_from_cell_v(v: float) -> float:
    """每顆電壓 → SOC（0～1），表外夾到端點。"""
    t = NMC_OCV_TABLE
    if v <= t[0][1]:
        return t[0][0]
    if v >= t[-1][1]:
        return t[-1][0]
    for (s0, v0), (s1, v1) in zip(t, t[1:]):
        if v0 <= v <= v1:
            return s0 + (s1 - s0) * (v - v0) / (v1 - v0)
    raise AssertionError("unreachable")


def cell_v_from_soc(soc: float) -> float:
    """SOC → 每顆電壓（表的反查）。"""
    t = NMC_OCV_TABLE
    soc = min(max(soc, 0.0), 1.0)
    for (s0, v0), (s1, v1) in zip(t, t[1:]):
        if s0 <= soc <= s1:
            return v0 + (v1 - v0) * (soc - s0) / (s1 - s0)
    raise AssertionError("unreachable")


SOC_CUTOFF = soc_from_cell_v(CUTOFF_V_PER_CELL)


def usable_fraction_from_pack_v(pack_v: float) -> float:
    """整組電壓 → 剩餘可用電量佔 USABLE_WH 的比例（0～1）。"""
    soc = soc_from_cell_v(pack_v / SERIES)
    return max(0.0, (soc - SOC_CUTOFF) / (1.0 - SOC_CUTOFF))


def pack_v_from_usable_fraction(f: float) -> float:
    """剩餘可用電量比例 → 整組電壓。"""
    soc = SOC_CUTOFF + min(max(f, 0.0), 1.0) * (1.0 - SOC_CUTOFF)
    return cell_v_from_soc(soc) * SERIES


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
    "只用電壓（2026-11-26 決定採用）": 0.20,
    "只用電壓、電壓表已用站立放電實測校正（假設）": 0.10,
    "加裝電流感測（INA219／INA226；未採用，留作比較）": 0.05,
}

# ---- 等級門檻（ADR-0012 §3.2；餘裕倍數 m） ----
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


def voltage_mode_thresholds(unc: float, d_m: float) -> list[float]:
    """電壓模式的固定門檻（ADR-0012 §3.5）：用最遠回家路徑 d_m 算，往上取到 0.1 V，
    相鄰兩級至少差一格（0.1 V）；差不到就把較高的那級往上推。回傳 L1～L4 的整組電壓。"""
    step = SERVO_VOLT_STEP_V
    raw = [pack_v_from_usable_fraction(estimate_wh_at(d_m, m, unc) / USABLE_WH) for _, m in LEVELS]
    out = [math.ceil(round(v / step, 6)) * step for v in raw]
    for i in range(len(out) - 2, -1, -1):  # 從 L3 往 L1 推
        if out[i] < out[i + 1] + step - 1e-9:
            out[i] = out[i + 1] + step
    return [round(v, 1) for v in out]


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
    # 電壓表：單調、端點、內插、反查
    vs = [v for _, v in NMC_OCV_TABLE]
    assert all(a < b for a, b in zip(vs, vs[1:]))
    assert soc_from_cell_v(4.2) == 1.0 and soc_from_cell_v(2.9) == 0.0
    assert abs(soc_from_cell_v(3.79) - 0.50) < 1e-9
    assert abs(SOC_CUTOFF - 0.0375) < 1e-9  # 3.30 V 在 3.00（0%）與 3.40（5%）之間的 3/4
    for soc in (0.1, 0.33, 0.5, 0.77):
        assert abs(soc_from_cell_v(cell_v_from_soc(soc)) - soc) < 1e-9
    assert abs(usable_fraction_from_pack_v(6.6)) < 1e-9 and usable_fraction_from_pack_v(8.4) == 1.0
    # 電壓模式門檻：0.1 V 對齊、相鄰至少差 0.1 V、L4 高於硬底線
    for unc in (0.20, 0.10):
        th = voltage_mode_thresholds(unc, max(DISTANCES_M))
        assert all(abs(v * 10 - round(v * 10)) < 1e-9 for v in th)
        assert all(a - b >= SERVO_VOLT_STEP_V - 1e-9 for a, b in zip(th, th[1:]))
        assert th[-1] > CUTOFF_V_PER_CELL * SERIES
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

    out.append("## 三元電池電壓對照表（代表值，每顆靜置開路電壓；整組 = ×2）\n")
    out.append("| SOC | 每顆 (V) | 整組 2S (V) | 剩餘可用電量（以 6.6 V 為 0%） |")
    out.append("|---|---|---|---|")
    for soc, v in reversed(NMC_OCV_TABLE):
        if soc * 100 % 10 == 0 or soc <= 0.05:
            out.append(f"| {soc:.0%} | {v:.2f} | {v * SERIES:.2f} | {usable_fraction_from_pack_v(v * SERIES):.0%} |")
    out.append("")
    out.append(f"硬底線 {CUTOFF_V_PER_CELL:.2f} V/顆（整組 {CUTOFF_V_PER_CELL * SERIES:.1f} V）在表上是 SOC {SOC_CUTOFF:.2%}。\n")

    out.append("## 舵機電壓解析度 0.1 V 對應多少電量\n")
    out.append("| 整組電壓區間 | 每 0.1 V 約等於剩餘可用電量 |")
    out.append("|---|---|")
    for lo, hi in ((8.0, 8.4), (7.6, 8.0), (7.3, 7.6), (7.0, 7.3), (6.6, 7.0)):
        df = usable_fraction_from_pack_v(hi) - usable_fraction_from_pack_v(lo)
        out.append(f"| {lo:.1f}～{hi:.1f} V | {df / ((hi - lo) / SERVO_VOLT_STEP_V):.1%} |")
    out.append("")

    for label in ("只用電壓（2026-11-26 決定採用）", "只用電壓、電壓表已用站立放電實測校正（假設）"):
        unc_v = UNCERTAINTY[label]
        out.append(f"## 各等級的電壓門檻：{label}（±{unc_v:.0%}；整組 2S，暫停時讀值）\n")
        out.append("剩餘可用電量估計值降到該級門檻時的整組電壓；括號內是和下一級差多少（舵機解析度 0.1 V）。")
        out.append("")
        out.append("| 回家路徑 | " + " | ".join(lv for lv, _ in LEVELS) + " |")
        out.append("|---|" + "---|" * len(LEVELS))
        for d in DISTANCES_M:
            vs = [pack_v_from_usable_fraction(estimate_wh_at(d, m, unc_v) / USABLE_WH) for _, m in LEVELS]
            cells = [f"{v:.2f} V（差 {v - vs[i + 1]:.2f}）" if i + 1 < len(vs) else f"{v:.2f} V" for i, v in enumerate(vs)]
            out.append(f"| {d:.0f} m | " + " | ".join(cells) + " |")
        out.append("")

    out.append(f"## 電壓模式的固定門檻（最遠 {max(DISTANCES_M):.0f} m、往上取到 0.1 V、相鄰至少差 0.1 V）\n")
    out.append("| 情況 | " + " | ".join(lv for lv, _ in LEVELS) + " | L1 時約剩可用電量 |")
    out.append("|---|" + "---|" * (len(LEVELS) + 1))
    for label in ("只用電壓（2026-11-26 決定採用）", "只用電壓、電壓表已用站立放電實測校正（假設）"):
        th = voltage_mode_thresholds(UNCERTAINTY[label], max(DISTANCES_M))
        out.append(f"| {label} | " + " | ".join(f"{v:.1f} V" for v in th) + f" | {usable_fraction_from_pack_v(th[0]):.0%} |")
    out.append("")

    out.append("## 站著不動時，從進入某級到下一級還有多久（只用電壓，10 m）\n")
    out.append("| 從 → 到 | 差距 (Wh) | 站著約幾分鐘 |")
    out.append("|---|---|---|")
    unc = UNCERTAINTY["只用電壓（2026-11-26 決定採用）"]
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
