#!/usr/bin/env python3
"""GC9A01 1.28 吋圓形螢幕當鴨子眼睛：與上游眼睛零件的尺寸核對、SPI 頻寬推算（只用標準函式庫）。

用途：[`hardware/expression_mods/gc9a01_eyes.md`](../hardware/expression_mods/gc9a01_eyes.md)
裡的數字都由這支腳本算出，方法與輸出記錄在
`docs/validation/gc9a01-eyes-fit-2026-11-17.md`。

- 幾何（§1）：從上游 `print/head.stl`、`left_eye.stl`、`right_eye.stl`、`bulb.stl` **唯讀**量出，
  是 STL 量測，不是實物量測。
- 螢幕（§2）：名目規格（GC9A01 1.28 吋面板 datasheet、Waveshare 產品頁）。777 微電子賣的模組
  外框、腳位還沒拿到實物，**到貨要量**。
- SPI（§3）：理論上限（只算像素資料位元，不含指令、DC 切換、Python 與 DMA 開銷）。
  Pi 4 的 SPI 時脈 = core clock ÷ 偶數除頻，core clock 取預設 500 MHz；實際能跑多快要實測。

用法：

    python3 -I nous_duck/tools/eye_display_fit.py            # 輸出 Markdown 表格
    python3 -I nous_duck/tools/eye_display_fit.py --check    # 只跑內建檢查
"""

from __future__ import annotations

import argparse
import math
import struct
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PRINT = REPO / "print"

# ---- 螢幕名目規格 ----
DISPLAY_PX = 240  # 240×240
ACTIVE_DIA_MM = 32.4  # 有效顯示區直徑（datasheet、Waveshare 一致）
# 模組 PCB 外框依賣家不同：Waveshare 40.4×37.5 mm、JESSINIE 36×39 mm；777 微電子未知
MODULE_OUTLINES_MM = {"Waveshare": (40.4, 37.5), "JESSINIE": (36.0, 39.0)}
BYTES_PER_PX = 2  # RGB565

# ---- Pi 4 SPI ----
CORE_CLOCK_MHZ = 500.0
SPI_DIVIDERS = (8, 10, 12, 16, 20, 24, 32)

# ---- 其他 ----
M25_HEAD_DIA_MM = 4.5  # M2.5 盤頭螺絲頭直徑（常見值）


# ------------------------------------------------------------------ STL


def load_stl(path: Path) -> list[tuple[tuple[float, float, float], ...]]:
    """回傳三角形清單（每個三角形 3 個頂點）。支援 binary 與 ASCII STL。"""
    data = path.read_bytes()
    n = struct.unpack_from("<I", data, 80)[0] if len(data) >= 84 else 0
    if len(data) == 84 + 50 * n:
        tris = []
        for i in range(n):
            v = struct.unpack_from("<9f", data, 84 + 50 * i + 12)
            tris.append(((v[0], v[1], v[2]), (v[3], v[4], v[5]), (v[6], v[7], v[8])))
        return tris
    verts = [
        tuple(float(t) for t in line.split()[1:4])
        for line in data.decode("ascii", "replace").splitlines()
        if line.strip().startswith("vertex")
    ]
    return [tuple(verts[i : i + 3]) for i in range(0, len(verts), 3)]  # type: ignore[misc]


def vertices(tris) -> set[tuple[float, float, float]]:
    return {v for t in tris for v in t}


def bounds(vs) -> tuple[list[float], list[float]]:
    lo = [min(v[i] for v in vs) for i in range(3)]
    hi = [max(v[i] for v in vs) for i in range(3)]
    return lo, hi


def ray_hits_x(tris, y: float, z: float, x0: float, direction: float) -> list[float]:
    """沿 ±x 方向從 (x0, y, z) 射出，回傳所有命中點的 x（Möller–Trumbore）。"""
    hits = []
    d = (direction, 0.0, 0.0)
    o = (x0, y, z)
    for a, b, c in tris:
        # 快速剔除：三角形的 y/z 範圍不含射線
        if not (min(a[1], b[1], c[1]) <= y <= max(a[1], b[1], c[1])):
            continue
        if not (min(a[2], b[2], c[2]) <= z <= max(a[2], b[2], c[2])):
            continue
        e1 = [b[i] - a[i] for i in range(3)]
        e2 = [c[i] - a[i] for i in range(3)]
        p = [d[1] * e2[2] - d[2] * e2[1], d[2] * e2[0] - d[0] * e2[2], d[0] * e2[1] - d[1] * e2[0]]
        det = sum(e1[i] * p[i] for i in range(3))
        if abs(det) < 1e-12:
            continue
        inv = 1.0 / det
        s = [o[i] - a[i] for i in range(3)]
        u = sum(s[i] * p[i] for i in range(3)) * inv
        if u < 0 or u > 1:
            continue
        q = [s[1] * e1[2] - s[2] * e1[1], s[2] * e1[0] - s[0] * e1[2], s[0] * e1[1] - s[1] * e1[0]]
        v = sum(d[i] * q[i] for i in range(3)) * inv
        if v < 0 or u + v > 1:
            continue
        t = sum(e2[i] * q[i] for i in range(3)) * inv
        if t > 1e-6:
            hits.append(x0 + direction * t)
    return hits


def ray_hits_z(tris, x: float, y: float, z0: float, direction: float) -> list[float]:
    """沿 ±z 方向射出；把座標換成 (z, y, x) 後重用 ray_hits_x。"""
    swapped = [tuple((v[2], v[1], v[0]) for v in t) for t in tris]
    return ray_hits_x(swapped, y, x, z0, direction)


# ------------------------------------------------------------------ 幾何量測


def measure() -> dict:
    head = load_stl(PRINT / "head.stl")
    hv = vertices(head)
    bot = load_stl(PRINT / "head_bot_sheet.stl")
    out: dict = {"head_bounds": bounds(hv), "eyes": {}}
    for name in ("left_eye", "right_eye"):
        bez = vertices(load_stl(PRINT / f"{name}.stl"))
        lo, hi = bounds(bez)
        cy, cz = (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2
        r = lambda v: math.hypot(v[1] - cy, v[2] - cz)  # noqa: E731
        # 頭殼眼孔：眼睛軸線附近（r<20）、正面牆範圍（x≥110）的頂點中，離軸線最近的距離
        near = [v for v in hv if v[0] >= 110 and r(v) < 20]
        hole_r = min(r(v) for v in near)
        wall = [v[0] for v in near if abs(r(v) - hole_r) < 0.2]
        # 4 個螺絲孔：取頭殼最前面（x 最大）那一面、r 在 14～20 之間的頂點，依象限分群，
        # 取包圍盒中心與寬度（牆內面有其他凹槽，所以只看正面）
        front_x = max(v[0] for v in near)
        screws = []
        for sy in (-1, 1):
            for sz in (-1, 1):
                pts = [
                    v for v in near
                    if v[0] > front_x - 0.05 and 14 < r(v) < 20 and (v[1] - cy) * sy > 0 and (v[2] - cz) * sz > 0
                ]
                # 正面網格還有少數不屬於孔的頂點：以中位數為中心，只留 2 mm 內的點
                my = sorted(p[1] for p in pts)[len(pts) // 2]
                mz = sorted(p[2] for p in pts)[len(pts) // 2]
                pts = [p for p in pts if math.hypot(p[1] - my, p[2] - mz) < 2.0]
                ys, zs = [p[1] for p in pts], [p[2] for p in pts]
                screws.append(
                    (
                        (max(ys) + min(ys)) / 2 - cy,
                        (max(zs) + min(zs)) / 2 - cz,
                        max(max(ys) - min(ys), max(zs) - min(zs)),
                    )
                )
        # 眼蓋（left_eye／right_eye）本身的開孔：貼頭殼那面與最外面
        def bezel_hole(at_x: float) -> float:
            pts = [v for v in bez if abs(v[0] - at_x) < 0.05 and r(v) < 16]
            return 2 * min(r(v) for v in pts)

        wall_inner = min(wall)
        # 牆後方空間：從牆內面往 −x 射線，看頭殼本身多深才擋到（不含頭內的舵機、支架）
        behind = []
        for dy, dz in ((0, 0), (15, 0), (-15, 0), (0, 15), (0, -15)):
            hits = ray_hits_x(head, cy + dy, cz + dz, wall_inner - 0.1, -1.0)
            behind.append(wall_inner - max(hits) if hits else float("inf"))
        # 上下內部高度：在牆後 5 mm 處，從眼睛中心往 ±z 射線
        up = ray_hits_z(head, wall_inner - 5, cy, cz, +1.0)
        # 頭殼底部是開口，由 head_bot_sheet 封住，所以往下量到 head_bot_sheet
        down = ray_hits_z(bot, wall_inner - 5, cy, cz, -1.0)
        out["eyes"][name] = {
            "center_yz": (cy, cz),
            "head_hole_dia": 2 * hole_r,
            "wall_x": (min(wall), max(wall)),
            "screws": screws,
            "bezel_hole_inner": bezel_hole(lo[0]),
            "bezel_hole_outer": bezel_hole(hi[0]),
            "bezel_outer_dia": hi[1] - lo[1],
            "free_depth_behind_wall": min(behind),
            "inner_up": (min(up) - cz) if up else None,
            "inner_down": (cz - max(down)) if down else None,
        }
    bulb = vertices(load_stl(PRINT / "bulb.stl"))
    out["bulb_bounds"] = bounds(bulb)
    return out


# ------------------------------------------------------------------ 推算


def pitch_mm() -> float:
    return ACTIVE_DIA_MM / DISPLAY_PX


def visible_px(aperture_mm: float) -> float:
    return min(aperture_mm, ACTIVE_DIA_MM) / pitch_mm()


def frame_ms(spi_mhz: float, w: int = DISPLAY_PX, h: int = DISPLAY_PX) -> float:
    return w * h * BYTES_PER_PX * 8 / (spi_mhz * 1e6) * 1e3


def spi_rows():
    for div in SPI_DIVIDERS:
        mhz = CORE_CLOCK_MHZ / div
        full = frame_ms(mhz)
        part = frame_ms(mhz, 120, 120)
        yield div, mhz, full, 1000 / full, 1000 / (2 * full), 1000 / (2 * part)


def _f(x: float, nd: int = 1) -> str:
    return f"{x:.{nd}f}"


def tables() -> str:
    m = measure()
    lines = ["## 1. 上游眼睛零件（STL 量測）", ""]
    lines.append("| 項目 | left_eye 那側 | right_eye 那側 |")
    lines.append("|---|---|---|")
    L, R = m["eyes"]["left_eye"], m["eyes"]["right_eye"]

    def row(label, f):
        lines.append(f"| {label} | {f(L)} | {f(R)} |")

    row("眼睛中心 (y, z) mm", lambda e: f"({_f(e['center_yz'][0])}, {_f(e['center_yz'][1])})")
    row("頭殼眼孔直徑 mm", lambda e: _f(e["head_hole_dia"]))
    row("頭殼正面牆 x 範圍 mm（厚度）", lambda e: f"{_f(e['wall_x'][0])}～{_f(e['wall_x'][1])}（{_f(e['wall_x'][1] - e['wall_x'][0])}）")
    row("眼蓋外徑 mm", lambda e: _f(e["bezel_outer_dia"]))
    row("眼蓋開孔：貼頭殼面／最外面 mm", lambda e: f"{_f(e['bezel_hole_inner'])}／{_f(e['bezel_hole_outer'])}")
    row(
        "4 個螺絲孔相對中心 (dy, dz)、孔徑 mm",
        lambda e: "、".join(f"({_f(s[0])}, {_f(s[1])}) Ø{_f(s[2])}" for s in e["screws"]),
    )
    row("螺絲孔中心離眼睛中心 mm", lambda e: _f(math.hypot(e["screws"][0][0], e["screws"][0][1]), 2))
    row("牆後頭殼本身的淨深 mm（不含頭內舵機、支架）", lambda e: _f(e["free_depth_behind_wall"]))
    row("牆後 5 mm 處，中心往上到頭殼內面／往下到 head_bot_sheet mm", lambda e: f"{_f(e['inner_up'])}／{_f(e['inner_down'])}")
    spacing = L["center_yz"][0] - R["center_yz"][0]
    lines += ["", f"兩眼中心距：{_f(spacing)} mm。bulb（燈件）厚 {_f(m['bulb_bounds'][1][0] - m['bulb_bounds'][0][0])} mm、外徑 {_f(m['bulb_bounds'][1][1] - m['bulb_bounds'][0][1])} mm。", ""]

    ap = min(L["head_hole_dia"], L["bezel_hole_inner"])
    screw_r = math.hypot(L["screws"][0][0], L["screws"][0][1])
    screw_hole = L["screws"][0][2]
    lines += ["## 2. GC9A01 放進原版眼眶", ""]
    lines.append("| 項目 | 值 | 算法 |")
    lines.append("|---|---|---|")
    lines.append(f"| 像素間距 | {pitch_mm():.3f} mm | {ACTIVE_DIA_MM} ÷ {DISPLAY_PX} |")
    lines.append(f"| 原版眼孔看得到的直徑 | {_f(ap)} mm | 頭殼孔與眼蓋貼頭殼面的孔取小 |")
    lines.append(f"| 看得到的像素直徑 | {_f(visible_px(ap), 0)} px（全畫面 {DISPLAY_PX} px） | {_f(ap)} ÷ {pitch_mm():.3f} |")
    lines.append(f"| 看得到的面積比例 | {_f(100 * (ap / ACTIVE_DIA_MM) ** 2, 0)} % | ({_f(ap)} ÷ {ACTIVE_DIA_MM})² |")
    lines.append(f"| 有效顯示區全露出要的開孔 | ≥ {ACTIVE_DIA_MM} mm | — |")
    lines.append(f"| 螺絲孔內緣離中心 | {_f(screw_r - screw_hole / 2, 2)} mm | {_f(screw_r, 2)} − {_f(screw_hole)}/2 |")
    lines.append(f"| M2.5 螺絲頭（Ø{M25_HEAD_DIA_MM}）內緣離中心 | {_f(screw_r - M25_HEAD_DIA_MM / 2, 2)} mm | {_f(screw_r, 2)} − {M25_HEAD_DIA_MM}/2 |")
    lines.append(f"| 有效顯示區半徑 | {_f(ACTIVE_DIA_MM / 2, 2)} mm | 玻璃與 PCB 只會更大 |")
    for k, (w, h) in MODULE_OUTLINES_MM.items():
        lines.append(f"| {k} 模組外框半寬 | {_f(min(w, h) / 2, 2)}～{_f(max(w, h) / 2, 2)} mm | {w}×{h} ÷ 2 |")
    lines.append(f"| 兩個模組並排時中間剩下 | {_f(spacing - max(max(v) for v in MODULE_OUTLINES_MM.values()))}～{_f(spacing - min(min(v) for v in MODULE_OUTLINES_MM.values()))} mm | 中心距 − 模組寬 |")
    lines.append("")

    lines += ["## 3. Pi 4 SPI 頻寬（理論上限）", ""]
    lines.append(f"一幀 {DISPLAY_PX}×{DISPLAY_PX}×16 bit = {DISPLAY_PX * DISPLAY_PX * BYTES_PER_PX} bytes。只算像素資料，不含指令與軟體開銷。")
    lines.append("")
    lines.append("| 除頻 | SPI 時脈 MHz | 全畫面一幀 ms | 單眼全畫面 fps | 兩眼共用匯流排、各自全畫面 fps | 兩眼只更新 120×120 區塊 fps |")
    lines.append("|---|---|---|---|---|---|")
    for div, mhz, full, f1, f2, fp in spi_rows():
        lines.append(f"| {div} | {_f(mhz, 2)} | {_f(full)} | {_f(f1, 0)} | {_f(f2, 0)} | {_f(fp, 0)} |")
    lines.append("")
    return "\n".join(lines)


def check() -> None:
    m = measure()
    L, R = m["eyes"]["left_eye"], m["eyes"]["right_eye"]
    for e in (L, R):
        assert abs(e["head_hole_dia"] - 25.0) < 0.2, e["head_hole_dia"]
        assert abs(e["bezel_hole_inner"] - 25.0) < 0.2, e["bezel_hole_inner"]
        assert abs(e["center_yz"][1] - 139.4) < 0.3, e["center_yz"]
        for dy, dz, d in e["screws"]:
            assert abs(abs(dy) - 12.5) < 0.2 and abs(abs(dz) - 12.5) < 0.2, (dy, dz)
            assert abs(d - 2.7) < 0.2, d
        assert abs((e["wall_x"][1] - e["wall_x"][0]) - 3.0) < 0.1, e["wall_x"]
        assert e["inner_up"] is not None and e["inner_down"] is not None
    assert abs((L["center_yz"][0] - R["center_yz"][0]) - 80.0) < 0.2
    # 原版眼孔比有效顯示區小 → 只看得到中間約 185 px
    assert 184 < visible_px(25.0) < 186
    # 有效顯示區半徑已經大於螺絲頭內緣 → 模組不能直接貼在原版牆內面
    screw_r = math.hypot(L["screws"][0][0], L["screws"][0][1])
    assert ACTIVE_DIA_MM / 2 > screw_r - M25_HEAD_DIA_MM / 2
    # 頻寬：62.5 MHz 全畫面約 14.7 ms
    assert abs(frame_ms(62.5) - 14.7456) < 1e-3
    assert abs(frame_ms(31.25) - 29.4912) < 1e-3
    print("eye_display_fit: checks passed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="只跑內建檢查")
    args = parser.parse_args()
    if args.check:
        check()
    else:
        print(tables())


if __name__ == "__main__":
    main()
