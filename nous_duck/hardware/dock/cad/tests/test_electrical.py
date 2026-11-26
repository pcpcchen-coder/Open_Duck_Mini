"""充電座電路的設計計算（不是實測）：偵測門檻在最壞元件誤差下仍要分得開。"""

import pytest

from dock_cad import electrical as E

MARGIN = 0.10  # ADC 讀值與門檻之間至少要留的距離（V）


def test_duck_reading_falls_inside_enable_window():
    duck = E.sense_range("duck")
    lo, hi = E.ENABLE_WINDOW_ADC
    assert duck.adc_min - lo >= MARGIN
    assert hi - duck.adc_max >= MARGIN


@pytest.mark.parametrize("case", ["open", "reversed", "short"])
def test_other_cases_stay_outside_enable_window(case):
    """沒有鴨子、鴨子反接、金屬短路都不能送電。"""
    r = E.sense_range(case)
    lo, hi = E.ENABLE_WINDOW_ADC
    assert r.adc_max <= lo - MARGIN or r.adc_min >= hi + MARGIN


def test_adc_never_exceeds_reference():
    assert E.adc_max_when_on() < E.ADC_VREF - 0.1
    assert E.sense_range("open").adc_max < E.ADC_VREF


def test_pins_carry_at_most_1ma_when_off():
    """關閉時頂針只透過偵測上拉帶電：短路電流 ≤ 1.2 mA。"""
    assert E.V_SUPPLY_RANGE[1] / E.R_PULLUP <= 1.2e-3


def test_pfet_fully_on_and_npn_saturated():
    assert E.gate_vgs_on() < E.PFET_VGS_TH_MAX - 1.0  # 比最壞門檻再多 1 V
    # 強迫 β = Ic / Ib < 10 才算確實飽和
    assert E.npn_collector_current() / E.npn_base_current() < 10


def test_ws2812_data_level_reaches_vih():
    assert E.ws2812_vih_worst() < E.V_GPIO


def test_drop_budget_numbers_used_in_docs():
    assert E.drop_at(2.0) == pytest.approx(0.294, abs=0.001)
    assert E.drop_at(3.0) == pytest.approx(0.441, abs=0.001)
