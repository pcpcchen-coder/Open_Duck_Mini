"""充電座電路的數字：鴨子偵測電壓、ADC 門檻、閘極驅動、狀態燈邏輯準位、壓降預算。

接線圖（`../../wiring/`）上的元件值都從這裡來；測試 `tests/test_electrical.py` 檢查
門檻在元件誤差下仍分得開。這些是**設計計算**，還沒有實際電路量測。

單位：伏特、歐姆、安培。
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

# ---------------------------------------------------------------------------
# 元件值（與接線圖一致）
# ---------------------------------------------------------------------------
V_SUPPLY_NOM = 5.0
V_SUPPLY_RANGE = (4.75, 5.25)  # USB 5 V 規格範圍

R_PULLUP = 4_700.0  # R1：5 V → 頂針＋的偵測上拉（平常唯一連到頂針的電源，最大 1 mA）
R_DIV_TOP = 15_000.0  # R2：頂針＋ → ADC
R_DIV_BOT = 22_000.0  # R3：ADC → GND
R_TOL = 0.01  # 1% 電阻

R_ID = 10_000.0  # 鴨子側識別電阻
VF_ID_DIODE = (0.50, 0.70)  # 鴨子側 1N4148 在約 0.2 mA 時的順向壓降範圍
VF_TVS_FWD = (0.60, 0.85)  # 反接時鴨子側 TVS 順向導通
I_CHARGER_LEAK = (0.0, 200e-6)  # 偵測時鴨子充電板（低於 UVLO）可能吃掉的電流，未知，先假設 0～200 µA

ADC_VREF = 3.3  # XIAO RP2040 的 ADC 參考電壓
ADC_BITS = 12

#: 韌體門檻：ADC 讀值（伏特，已經過分壓）落在這個區間、穩定 300 ms 才送電。
ENABLE_WINDOW_ADC = (1.20, 2.30)

# 高側開關
R_GATE_PULLUP = 10_000.0  # R4：閘極 → 源極（5 V），平常關
R_GATE_SERIES = 220.0  # R5：NPN 集極 → 閘極
R_BASE = 1_000.0  # R6：GPIO → NPN 基極
R_BASE_PULLDOWN = 10_000.0  # R7：基極 → GND（開機時 GPIO 浮接也保持關）
VCE_SAT = 0.2
VBE = 0.7
V_GPIO = 3.3
PFET_VGS_TH_MAX = -3.0  # AO4407A 規格書 Vgs(th) 最壞值（以實際買到的規格書為準）

# 狀態燈 WS2812B：VDD 經 1N4148 降壓，讓 3.3 V 資料線達到 VIH = 0.7 × VDD
VF_LED_DIODE = (0.65, 1.0)  # 1N4148 在 1～60 mA
WS2812_VIH_RATIO = 0.7

# 韌體電流門檻
I_TRIP = 3.3  # 超過就立刻關
I_DONE = 0.05  # 低於這個值持續 10 秒＝充飽或鴨子離開 → 關、回到偵測
I_MIN_AFTER_ENABLE = 0.02  # 送電 5 秒後電流仍低於這個值＝不是在充電的東西 → 關


def adc_from_pin(v_pin: float, r_top: float = R_DIV_TOP, r_bot: float = R_DIV_BOT) -> float:
    return v_pin * r_bot / (r_top + r_bot)


def _pin_voltage(case: str, vsup: float, rp: float, rt: float, rb: float, vf: float, rid: float, ileak: float) -> float:
    """頂針＋的電壓（開關關閉、只有偵測上拉時）。節點方程式，單位 mA／kΩ 也一樣成立。"""
    rd = rt + rb
    g_p, g_d = 1 / rp, 1 / rd
    if case == "open":  # 沒有鴨子
        return vsup * g_p / (g_p + g_d)
    if case == "short":  # 金屬短路兩極
        return 0.0
    if case == "reversed":  # 鴨子反接：鴨子側 TVS 順向導通，把頂針＋鉗在約一個二極體壓降
        return vf
    if case == "duck":  # 鴨子正確坐好：1N4148＋R_ID 到 GND，另有充電板漏電
        g_id = 1 / rid
        v = (vsup * g_p + vf * g_id - ileak) / (g_p + g_d + g_id)
        return v
    raise ValueError(case)


@dataclass
class SenseRange:
    case: str
    adc_min: float
    adc_max: float
    pin_min: float
    pin_max: float


def sense_range(case: str) -> SenseRange:
    """在電源、1% 電阻、二極體壓降、充電板漏電的最壞組合下，ADC 讀值的範圍。"""
    vals = []
    tol = (1 - R_TOL, 1 + R_TOL)
    vfs = VF_TVS_FWD if case == "reversed" else VF_ID_DIODE
    for vsup, kp, kt, kb, vf, kid, ileak in product(V_SUPPLY_RANGE, tol, tol, tol, vfs, tol, I_CHARGER_LEAK):
        rt, rb = R_DIV_TOP * kt, R_DIV_BOT * kb
        v = _pin_voltage(case, vsup, R_PULLUP * kp, rt, rb, vf, R_ID * kid, ileak)
        vals.append((adc_from_pin(v, rt, rb), v))
    adcs, pins = zip(*vals)
    return SenseRange(case, min(adcs), max(adcs), min(pins), max(pins))


def adc_max_when_on() -> float:
    """送電中（頂針＋≈ 電源）ADC 的最高值，不能超過 ADC 參考電壓。"""
    return max(adc_from_pin(V_SUPPLY_RANGE[1], R_DIV_TOP * (1 - R_TOL), R_DIV_BOT * (1 + R_TOL)), 0)


def gate_vgs_on(vsup: float = V_SUPPLY_RANGE[0]) -> float:
    """NPN 導通時 P-MOSFET 的 Vgs（負值）。"""
    v_gate = VCE_SAT + (vsup - VCE_SAT) * R_GATE_SERIES / (R_GATE_PULLUP + R_GATE_SERIES)
    return v_gate - vsup


def npn_base_current() -> float:
    i_rb = (V_GPIO - VBE) / R_BASE
    return i_rb - VBE / R_BASE_PULLDOWN


def npn_collector_current(vsup: float = V_SUPPLY_RANGE[1]) -> float:
    return (vsup - VCE_SAT) / (R_GATE_PULLUP + R_GATE_SERIES)


def ws2812_vih_worst() -> float:
    """WS2812B 的 VDD 經 1N4148 降壓後，資料線要的 VIH 最壞值（VDD 最高時）。"""
    vdd_max = V_SUPPLY_RANGE[1] - VF_LED_DIODE[0]
    return WS2812_VIH_RATIO * vdd_max


#: 3 A 時的壓降預算（Ω）。數字取規格書典型或最壞值的保守估計，**要實測**。
DROP_BUDGET_OHM = {
    "USB-C 母座板＋接頭": 0.020,
    "PTC 自恢復保險絲": 0.030,
    "P-MOSFET AO4407A（Vgs −4.5 V）": 0.020,
    "INA219 分流電阻（換成 0.01 Ω）": 0.010,
    "20 AWG 線，來回約 0.5 m": 0.017,
    "彈簧頂針＋黃銅片（每極 2 支並聯，兩極）": 0.050,
}


def drop_at(current: float, budget: dict[str, float] = DROP_BUDGET_OHM) -> float:
    return current * sum(budget.values())


def summary() -> dict:
    out = {c: sense_range(c) for c in ("open", "duck", "reversed", "short")}
    return {
        "sense": out,
        "adc_max_when_on": adc_max_when_on(),
        "gate_vgs_on": gate_vgs_on(),
        "npn_ib": npn_base_current(),
        "npn_ic": npn_collector_current(),
        "ws2812_vih_worst": ws2812_vih_worst(),
        "drop_2a": drop_at(2.0),
        "drop_3a": drop_at(3.0),
    }


if __name__ == "__main__":
    s = summary()
    for c, r in s["sense"].items():
        print(f"{c:9s} 頂針＋ {r.pin_min:5.2f}～{r.pin_max:5.2f} V  → ADC {r.adc_min:5.3f}～{r.adc_max:5.3f} V")
    print(f"送電窗 ADC {ENABLE_WINDOW_ADC}")
    for k in ("adc_max_when_on", "gate_vgs_on", "npn_ib", "npn_ic", "ws2812_vih_worst", "drop_2a", "drop_3a"):
        print(k, round(s[k], 4))
