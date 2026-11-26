"""畫充電座電路圖（開發工具，CI 不跑）。

    pip install schemdraw==0.23 matplotlib
    python nous_duck/hardware/dock/wiring/draw_wiring.py

輸出到同目錄：
- dock_schematic.svg / .png：原理圖（充電座側＋鴨子側）
- dock_wiring.svg / .png：實體接線圖（模組、線色、線徑、裝在哪一段椅背）

元件值來自 `../cad/dock_cad/electrical.py`（測試在 `../cad/tests/test_electrical.py`）。
中文字型用文泉驛正黑（沒有就退回系統字型，中文可能變方塊）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "cad"))
from dock_cad import electrical as E  # noqa: E402

for name in ("WenQuanYi Zen Hei", "Noto Sans CJK TC", "Noto Sans TC", "Microsoft JhengHei", "PingFang TC"):
    if any(name == f.name for f in font_manager.fontManager.ttflist):
        FONT = name
        break
else:
    FONT = "DejaVu Sans"
plt.rcParams["font.family"] = FONT
plt.rcParams["svg.fonttype"] = "none"

RED, BLACK, YEL, BLUE, GRN, ORG, GRAY = "#d62728", "#222222", "#c9a000", "#1f77b4", "#2ca02c", "#ff7f0e", "#888888"


def k(r: float) -> str:
    return f"{r / 1000:g} kΩ" if r >= 1000 else f"{r:g} Ω"


# ---------------------------------------------------------------------------
# 1. 原理圖
# ---------------------------------------------------------------------------
def draw_schematic(out: Path) -> None:
    """座標都手動指定（schemdraw 自動排版會疊在一起）。Y_RAIL＝電源、0＝地線。"""
    import schemdraw
    import schemdraw.elements as elm

    schemdraw.config(font=FONT, fontsize=11, lw=1.4)
    d = schemdraw.Drawing(show=False)
    YT, YR, YG = 9.4, 6.0, 0.0  # 偵測上拉、電源、地線

    def line(a, b, c=BLACK, ls="-"):
        d.add(elm.Line().at(a).to(b).color(c).linestyle(ls))

    def dot(p, c=BLACK, open_=False):
        d.add(elm.Dot(open=open_).at(p).color(c))

    def text(p, s, loc="center", c=BLACK, size=12.0):
        """loc＝文字在點的哪一側：left／right／top／bottom／center。"""
        ha = {"left": "right", "right": "left"}.get(loc, "center")
        va = {"top": "bottom", "bottom": "top"}.get(loc, "center")
        d.add(elm.Label().at(p).label(s, loc="center", color=c, fontsize=size, halign=ha, valign=va))

    # ---------------- 電源入口
    dot((0, YR), RED, True)
    dot((0, YG), BLACK, True)
    text((-0.3, YR), "J1 USB-C 母座板 VBUS\n（5 V／3 A 電源）", "left", RED)
    text((-0.3, YG), "J1 GND", "left")
    line((0, YR), (0.8, YR), RED)
    d.add(elm.Fuse().at((0.8, YR)).to((2.6, YR)).color(RED))
    text((1.7, YR + 0.8), "F1 PTC 自恢復\n保持 ≥ 3.5 A", "center", RED, 11)
    line((2.6, YR), (6.5, YR), RED)
    dot((3.2, YR), RED)
    text((3.2, YR - 0.45), "5V_RAIL", "right", RED, 11)
    # C1
    d.add(elm.Capacitor(polar=True).at((3.2, YR)).to((3.2, YG)))
    text((2.95, 2.2), "C1\n100 µF\n10 V", "left", BLACK, 11)
    dot((3.2, YG))

    # ---------------- 高側開關 Q1＋閘極驅動
    q1 = d.add(elm.PFet().theta(90).reverse().at((6.5, YR)))
    text((7.25, YR + 1.25), "Q1 P-MOSFET\nAO4407A", "center", BLACK, 11.5)
    dot((5.8, YR))
    d.add(elm.Resistor().at((5.8, YR)).to((5.8, 3.6)))
    text((5.45, 4.8), f"R4\n{k(E.R_GATE_PULLUP)}", "left", BLACK, 11)
    line((5.8, 3.6), (q1.gate[0], 3.6))
    line(q1.gate, (q1.gate[0], 3.6))
    dot((q1.gate[0], 3.6))
    d.add(elm.Resistor().at((q1.gate[0], 3.6)).to((q1.gate[0], 2.1)))
    text((q1.gate[0] + 0.25, 2.85), f"R5 {k(E.R_GATE_SERIES)}", "right", BLACK, 11)
    q2 = d.add(elm.BjtNpn(circle=True).anchor("collector").at((q1.gate[0], 2.1)))
    text((q2.emitter[0] + 0.3, 1.4), "Q2 NPN\nS8050／2N3904", "right", BLACK, 11)
    line(q2.emitter, (q2.emitter[0], YG))
    dot((q2.emitter[0], YG))
    bx = 5.0
    d.add(elm.Resistor().at(q2.base).to((bx, q2.base[1])))
    text((bx + 0.55, q2.base[1] - 0.45), f"R6 {k(E.R_BASE)}", "top", BLACK, 11)
    dot((bx, q2.base[1]), BLUE)
    text((bx, q2.base[1] + 0.35), "EN ← XIAO D7", "top", BLUE, 11.5)
    d.add(elm.Resistor().at((bx, q2.base[1])).to((bx, YG)))
    text((bx - 0.3, 0.7), f"R7\n{k(E.R_BASE_PULLDOWN)}", "left", BLACK, 11)
    dot((bx, YG))

    # ---------------- 電流量測（INA219 的分流電阻）
    line(q1.drain, (8.6, YR), RED)
    d.add(elm.Rshunt().at((8.6, YR)).to((10.8, YR)).color(RED))
    text((9.7, YR + 1.0), "INA219 分流 0.01 Ω\n（VIN+ → VIN-）", "center", RED, 10.5)
    line((10.8, YR), (17.0, YR), RED)
    dot((11.4, YR), RED)
    text((11.5, YR - 0.45), "PIN+", "right", RED, 11)

    # ---------------- 偵測上拉 R1（跨過開關）
    line((3.2, YR), (3.2, YT), RED)
    d.add(elm.Resistor().at((3.2, YT)).to((11.4, YT)))
    text((7.3, YT + 0.75), f"R1 偵測上拉 {k(E.R_PULLUP)}：開關關閉時，頂針只經過它帶電（最多約 1 mA）", "center", BLACK, 11.5)
    line((11.4, YT), (11.4, YR), RED)

    # ---------------- 分壓 → ADC
    dot((12.6, YR), RED)
    d.add(elm.Resistor().at((12.6, YR)).to((12.6, 3.4)))
    text((12.85, 4.7), f"R2\n{k(E.R_DIV_TOP)}", "right", BLACK, 11)
    dot((12.6, 3.4), BLUE)
    text((12.4, 3.4), "SENSE → XIAO A0", "left", BLUE, 11.5)
    d.add(elm.Resistor().at((12.6, 3.4)).to((12.6, YG)))
    text((12.85, 1.7), f"R3\n{k(E.R_DIV_BOT)}", "right", BLACK, 11)
    dot((12.6, YG))
    line((12.6, 3.4), (14.0, 3.4))
    d.add(elm.Capacitor().at((14.0, 3.4)).to((14.0, YG)))
    text((14.25, 1.7), "C2\n100 nF", "right", BLACK, 11)
    dot((14.0, YG))

    # ---------------- 輸出 TVS
    dot((15.6, YR), RED)
    d.add(elm.Zener().at((15.6, YG)).to((15.6, YR)))  # 單向 TVS：陰極接 PIN+
    text((16.1, 3.0), "D3 單向 TVS\nSMAJ6.5A", "right", BLACK, 11)
    dot((15.6, YG))

    # ---------------- 地線
    line((0, YG), (17.0, YG))

    # ---------------- 接觸面
    xc = 17.0
    dot((xc, YR), RED, True)
    dot((xc, YG), BLACK, True)
    text((xc - 0.25, YR + 1.0), "頂針+ ×2\n（面對椅子的右邊）", "left", RED, 11)
    text((xc - 0.25, YG - 1.0), "頂針- ×2\n（面對椅子的左邊）", "left", BLACK, 11)
    line((xc + 0.6, YT + 1.0), (xc + 0.6, YG - 1.9), GRAY, "--")
    text((xc + 0.6, YT + 1.0), "接觸面（V 形導引座）", "top", GRAY, 11)
    text((xc - 4.0, YT + 1.6), "◀ 充電座（底座電子艙）", "center", BLACK, 12)
    text((xc + 5.0, YT + 1.6), "鴨子（背殼內）▶", "center", BLACK, 12)
    xd = 18.2
    line((xc, YR), (xd, YR), RED, ":")
    line((xc, YG), (xd, YG), BLACK, ":")
    dot((xd, YR), RED, True)
    dot((xd, YG), BLACK, True)
    text((xd + 0.25, YR + 1.0), "觸片+\n（鴨子左手邊）", "right", RED, 11)
    text((xd + 0.25, YG - 1.0), "觸片-\n（鴨子右手邊）", "right", BLACK, 11)

    # ---------------- 鴨子側
    line((xd, YR), (24.0, YR), RED)
    dot((19.6, YR), RED)
    d.add(elm.Zener().at((19.6, YG)).to((19.6, YR)))  # 單向：反接時順向導通
    text((20.1, 3.0), "單向 TVS\nSMAJ6.5A", "right", BLACK, 11)
    dot((19.6, YG))
    dot((21.4, YR), RED)
    d.add(elm.Diode().at((21.4, YR)).to((21.4, 3.6)))
    text((21.65, 4.8), "1N4148", "right", BLACK, 11)
    d.add(elm.Resistor().at((21.4, 3.6)).to((21.4, YG)))
    text((21.65, 1.8), f"R_ID\n{k(E.R_ID)}", "right", BLACK, 11)
    dot((21.4, YG))
    d.add(elm.Diode().at((22.4, YR)).to((24.0, YR)).color(RED))
    text((23.2, YR + 0.9), "理想二極體\n（或 SS54）", "center", RED, 11)
    line((24.0, YR), (24.6, YR), RED)
    line((xd, YG), (24.6, YG))
    # 充電板（方框）
    for a, b in (((24.6, YG - 0.6), (27.8, YG - 0.6)), ((27.8, YG - 0.6), (27.8, YR + 0.6)),
                 ((27.8, YR + 0.6), (24.6, YR + 0.6)), ((24.6, YR + 0.6), (24.6, YG - 0.6))):
        line(a, b)
    text((26.1, 3.0), "鴨子的\n2S 充電板\n（5 V 輸入，\n規格待確認）", "center", BLACK, 11.5)
    text((24.8, YR), "IN+", "right", RED, 11)
    text((24.8, YG), "IN-", "right", BLACK, 11)
    text((24.6, YR - 1.0), "INA219（選配）\n→ Pi 4 I²C", "right", GRAY, 11)

    # ---------------- 說明
    text((-6.5, YT + 3.0), "鴨子的家 充電座電路 原理圖（設計 v0：未實作、未實測）", "right", BLACK, 18)
    notes = (
        "· 平常 Q1 關閉，頂針只經 R1 帶微小電壓；XIAO 讀 A0，看到「有鴨子」的電壓區間"
        f"（ADC {E.ENABLE_WINDOW_ADC[0]:.2f}–{E.ENABLE_WINDOW_ADC[1]:.2f} V）穩定 300 ms 才把 D7 拉高送電。\n"
        "· 送電中 XIAO 用 INA219 監控：電流 > 3.3 A 立刻關；< 50 mA 持續 10 秒（充飽或鴨子離開）就關，回到偵測。\n"
        "· 鴨子反接（鴨子側 TVS 順向導通）或金屬短路，A0 都只有 0–0.5 V，不會送電。"
    )
    text((-6.5, YG - 3.2), notes, "right", BLACK, 12)
    d.save(str(out.with_suffix(".svg")))
    d.save(str(out.with_suffix(".png")), dpi=150)


# ---------------------------------------------------------------------------
# 2. 實體接線圖
# ---------------------------------------------------------------------------
def draw_wiring(out: Path) -> None:
    from matplotlib.patches import FancyBboxPatch, Rectangle

    fig, ax = plt.subplots(figsize=(17, 11.5))
    ax.set_xlim(0, 17)
    ax.set_ylim(0, 11.5)
    ax.axis("off")

    def box(x0, y0, x1, y1, title, fc="#f7f7f7", ec=BLACK, size=12, lw=1.4, tloc="top"):
        ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0, boxstyle="round,pad=0.02,rounding_size=0.08", fc=fc, ec=ec, lw=lw))
        if tloc == "top":
            ax.text((x0 + x1) / 2, y1 - 0.12, title, ha="center", va="top", fontsize=size, weight="bold")
        elif tloc == "bottom":
            ax.text((x0 + x1) / 2, y0 + 0.12, title, ha="center", va="bottom", fontsize=size, weight="bold")
        else:
            ax.text((x0 + x1) / 2, (y0 + y1) / 2, title, ha="center", va="center", fontsize=size)

    def pin(x, y, name, side):
        ax.plot([x], [y], "o", ms=6, mfc="white", mec=BLACK, zorder=5)
        dx, dy, ha, va = {"left": (-0.1, 0, "right", "center"), "right": (0.1, 0, "left", "center"),
                          "top": (0, 0.12, "center", "bottom"), "bottom": (0, -0.12, "center", "top")}[side]
        ax.text(x + dx, y + dy, name, ha=ha, va=va, fontsize=9.5, zorder=6)

    def wire(pts, color, lw=2.6, ls="-"):
        xs, ys = zip(*pts)
        ax.plot(xs, ys, color=color, lw=lw, ls=ls, solid_capstyle="round", zorder=3)

    def note(x, y, s, color=BLACK, ha="center", size=9.5):
        ax.text(x, y, s, fontsize=size, color=color, ha=ha, va="center", bbox=dict(fc="white", ec="none", pad=0.8), zorder=4)

    # 區域底色：裝在家的哪一段
    ax.add_patch(Rectangle((0.2, 0.3), 10.6, 9.9, fc="#eef4fa", ec="none"))
    ax.text(0.35, 10.05, "底座（電子艙）dock_plinth", fontsize=12.5, va="top", color="#3c6e91", weight="bold")
    ax.add_patch(Rectangle((11.3, 5.4), 5.5, 4.8, fc="#fbf3e2", ec="none"))
    ax.text(11.45, 10.05, "中椅背 → V 形導引座", fontsize=12.5, va="top", color="#9a6a00", weight="bold")
    ax.add_patch(Rectangle((11.3, 0.3), 5.5, 4.6, fc="#f8e9e9", ec="none"))
    ax.text(11.45, 4.75, "屋頂山牆（圓窗後面）", fontsize=12.5, va="top", color="#a03a3a", weight="bold")

    # USB-C 母座板
    box(0.5, 5.3, 2.3, 7.4, "J1 USB-C\n母座板")
    pin(2.3, 6.8, "VBUS", "left")
    pin(2.3, 5.9, "GND", "left")
    ax.text(1.4, 5.0, "從後蓋下緣缺口\n接 5 V／3 A 電源", fontsize=9.5, ha="center", va="top")

    # INA219（在主板上方，同樣在底座裡）
    box(4.6, 8.3, 8.8, 9.6, "INA219 模組\n（分流電阻換成 0.01 Ω）", fc="#eef0ff", size=10.5)
    # 腳位順序依接線好畫排列（實際模組的排針順序以絲印為準）
    ina = {"SCL": 5.0, "SDA": 5.6, "GND": 6.2, "VCC": 6.8}
    for n, x in ina.items():
        pin(x, 8.3, n, "bottom")
    pin(8.8, 9.25, "VIN+", "left")
    pin(8.8, 8.7, "VIN-", "left")

    # 主板（洞洞板）
    box(3.2, 0.7, 10.4, 7.7, "主板：40 × 90 mm 洞洞板（平放，用雙面泡棉膠黏在底座中間）", fc="#ffffff", size=11, tloc="bottom")
    box(4.4, 1.6, 6.4, 5.6, "XIAO\nRP2040\n（插排母）", fc="#e8f5e9", size=11)
    left = {"3V3": 5.0, "GND ": 4.5, "D4/SDA": 4.0, "D5/SCL": 3.5}
    right = {"5V": 5.0, "GND": 4.6, "D7": 4.2, "A0": 3.8, "D6": 2.2}
    for n, y in left.items():
        pin(4.4, y, n.strip(), "right")
    for n, y in right.items():
        pin(6.4, y, n, "left")
    box(7.4, 3.4, 10.0, 7.2, "電源開關＋偵測\n（原理圖的 F1、C1、\nQ1、Q2、R1–R7、\nC2、D3，\n加上 D1 1N5819\n給 XIAO 5V）", fc="#fff8e6", size=10, tloc="center")
    box(7.4, 1.35, 10.0, 2.9, "狀態燈零件\nD2 1N4148 → 燈 VDD\nR8 330 Ω → 燈 DIN", fc="#fff8e6", size=10, tloc="center")

    # ---- 主電流（20 AWG）
    wire([(2.3, 6.8), (7.4, 6.8)], RED)
    wire([(2.3, 5.9), (7.4, 5.9)], BLACK)
    note(2.85, 7.12, "20 AWG 紅", RED)
    note(2.85, 5.6, "20 AWG 黑")
    wire([(9.2, 7.2), (9.2, 9.25), (8.8, 9.25)], RED)
    wire([(8.8, 8.7), (9.6, 8.7), (9.6, 7.2)], RED)
    note(9.75, 9.7, "Q1 汲極 → VIN+；VIN- → PIN+（20 AWG）", RED)
    wire([(10.0, 6.8), (11.0, 6.8), (11.0, 7.6), (12.4, 7.6)], RED)
    wire([(10.0, 5.9), (11.6, 5.9), (11.6, 6.5), (12.4, 6.5)], BLACK)
    note(11.75, 7.95, "PIN+ 20 AWG 紅", RED)
    note(11.45, 5.6, "GND 20 AWG 黑")

    # ---- XIAO 右側 → 開關電路（板上短線）
    wire([(6.4, 5.0), (7.4, 5.0)], RED, 1.6)
    wire([(6.4, 4.6), (7.4, 4.6)], BLACK, 1.6)
    wire([(6.4, 4.2), (7.4, 4.2)], YEL, 1.6)
    wire([(6.4, 3.8), (7.4, 3.8)], BLUE, 1.6, "--")
    ax.text(6.9, 5.13, "5V", fontsize=8.5, ha="center", va="bottom", color=RED)
    ax.text(6.9, 4.33, "EN", fontsize=8.5, ha="center", va="bottom", color="#8a6d00")
    ax.text(6.9, 3.93, "SENSE", fontsize=8.5, ha="center", va="bottom", color=BLUE)
    wire([(6.4, 2.2), (7.4, 2.2)], GRAY, 1.6, "--")
    ax.text(6.9, 2.33, "DIN", fontsize=8.5, ha="center", va="bottom", color=GRAY)

    # ---- XIAO 左側 → INA219（I²C 與 3V3）
    # 欄位、目標腳位、顏色、水平線高度：排成互不交叉
    cols = {"SCL": (3.55, 5.0, GRN, 8.2), "SDA": (3.7, 5.6, BLUE, 8.05), "GND": (3.85, 6.2, BLACK, 7.9), "3V3": (4.0, 6.8, ORG, 7.75)}
    ys = {"3V3": 5.0, "GND": 4.5, "SDA": 4.0, "SCL": 3.5}
    for n, (cx, px, c, hy) in cols.items():
        wire([(4.4, ys[n]), (cx, ys[n]), (cx, hy), (px, hy), (px, 8.3)], c, 1.6)
    note(1.75, 3.6, "I²C 與電源（26 AWG）：\n橘＝3V3 → VCC\n黑＝GND\n藍＝SDA，綠＝SCL", ha="center", size=9.5)

    # 頂針
    box(12.4, 5.8, 14.6, 8.5, "頂針 ×4\n（V 形導引座背面）", fc="#ffffff", size=10.5)
    pin(12.4, 7.6, "+ ×2（右邊）", "right")
    pin(12.4, 6.5, "- ×2（左邊）", "right")
    ax.text(14.75, 7.15, "穿過：底座頂板孔 →\n中椅背底板孔 →\n中椅背正面的頂針窗\n約 30 cm\n兩支 + 並聯、兩支 - 並聯", fontsize=9.5, va="center")
    # LED
    box(12.4, 0.8, 14.6, 3.4, "WS2812B ×1\n＋C3 100 nF", fc="#ffffff", size=10.5)
    pin(12.4, 2.7, "VDD", "right")
    pin(12.4, 2.1, "DIN", "right")
    pin(12.4, 1.5, "GND", "right")
    wire([(10.0, 2.5), (11.4, 2.5), (11.4, 2.7), (12.4, 2.7)], RED, 1.8)
    wire([(10.0, 2.1), (12.4, 2.1)], YEL, 1.8)
    wire([(10.0, 1.5), (12.4, 1.5)], BLACK, 1.8)
    note(11.9, 0.55, "26 AWG 三芯：紅 VDD／黃 DIN／黑 GND", size=9)
    ax.text(14.75, 2.1, "穿過：底座頂板孔 →\n中椅背 → 上椅背 →\n屋頂的中央走線孔\n約 60 cm", fontsize=9.5, va="center")

    ax.text(0.2, 11.4, "鴨子的家 充電座 實體接線圖（設計 v0：未實作、未實測）", fontsize=17, va="top", weight="bold")
    ax.text(0.2, 10.8, "主電流路徑（≥ 2 A）用 20 AWG；控制與燈用 26 AWG。電路細節看原理圖 dock_schematic。", fontsize=11, va="top")
    fig.savefig(out.with_suffix(".png"), dpi=150, bbox_inches="tight", facecolor="white")
    fig.savefig(out.with_suffix(".svg"), bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    draw_schematic(HERE / "dock_schematic")
    draw_wiring(HERE / "dock_wiring")
    print("ok")
