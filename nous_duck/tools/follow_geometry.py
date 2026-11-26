#!/usr/bin/env python3
"""「跟著我來」的名目推算：速度落差、跟隨時鏡頭看得到人的哪一段、看不到的腳前地面（只用標準函式庫）。

用途：[`docs/adr/ADR-0007-follow-me-and-wait-here.md`](../docs/adr/ADR-0007-follow-me-and-wait-here.md)
裡的數字都由這支腳本算出，方法與輸出記錄在 `docs/validation/follow-geometry-2026-11-19.md`。

**全部是名目推算，不是量測。** 鴨子還沒組裝，鏡頭沒裝上、沒校正；步態實際速度沒量過。

輸入（來源）：
- 鏡頭幾何（焦距、垂直視角、鏡頭高度 0.37 m）沿用 `stereo_geometry.py`，來源寫在那支腳本。
- 鴨子最高前進速度 0.15 m/s：上游 `xbox_controller.py` 的手把映射上限（architecture.md §4），
  **不是實測速度**；另列 0.10 m/s 當保守情況。
- 人走路速度 0.3～1.2 m/s：假設值（刻意放慢到一般步行），不是量測。
- 跟隨距離 1.5 m、追蹤上限 3.0 m：本 ADR 的草案值，待實測。
- 人體高度：腰約 1.0 m、肩約 1.4 m、臉約 1.6 m（成人站姿常見值）。

用法：

    python3 -I nous_duck/tools/follow_geometry.py            # 輸出 Markdown 表格
    python3 -I nous_duck/tools/follow_geometry.py --check    # 只跑內建檢查
"""

from __future__ import annotations

import argparse
import importlib.util
import math
from pathlib import Path

# `python3 -I` 不會把腳本目錄放進 sys.path，所以用檔案路徑載入同目錄的 stereo_geometry.py。
_spec = importlib.util.spec_from_file_location("stereo_geometry", Path(__file__).with_name("stereo_geometry.py"))
assert _spec is not None and _spec.loader is not None
sg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sg)

# ---- 鴨子 ----
DUCK_SPEED_NOMINAL = 0.15  # m/s，上游手把映射上限，未實測
DUCK_SPEED_SLOW = 0.10  # m/s，保守情況

# ---- 跟隨參數（草案） ----
FOLLOW_DIST_M = 1.5
TRACK_MAX_M = 3.0

# ---- 人 ----
PERSON_SPEEDS = (0.3, 0.5, 0.8, 1.0, 1.2)
BODY_MARKS = (("腳踝", 0.1), ("膝", 0.5), ("腰", 1.0), ("肩", 1.4), ("臉", 1.6))


def gap_growth(person_v: float, duck_v: float) -> float:
    """人比鴨子快時，每秒距離拉開多少（m/s）。人比較慢時回傳 0（鴨子追得上）。"""
    return max(0.0, person_v - duck_v)


def time_to_lose(person_v: float, duck_v: float, start_m: float = FOLLOW_DIST_M, max_m: float = TRACK_MAX_M) -> float | None:
    """從跟隨距離開始，人持續往前走，多久會超出追蹤上限；追得上回傳 None。"""
    g = gap_growth(person_v, duck_v)
    if g == 0:
        return None
    return (max_m - start_m) / g


def travel_time(dist_m: float, v: float) -> float:
    return dist_m / v


def visible_band(dist_m: float, pitch_up_deg: float, vfov: float, cam_h: float = sg.CAM_HEIGHT_M) -> tuple[float, float]:
    """鏡頭往上仰 pitch_up_deg 度時，在水平距離 dist_m 的垂直平面上看得到的高度範圍（m，離地）。

    下限小於 0 時截成 0（看得到腳底的地面）。
    """
    low = cam_h + dist_m * math.tan(math.radians(pitch_up_deg - vfov / 2))
    high = cam_h + dist_m * math.tan(math.radians(pitch_up_deg + vfov / 2))
    return max(0.0, low), high


def blind_ground_m(pitch_up_deg: float, vfov: float, cam_h: float = sg.CAM_HEIGHT_M) -> float | None:
    """鏡頭往上仰時，腳前看不到的地面距離；畫面下緣不再往下時回傳 None（完全看不到地面）。"""
    down = math.radians(vfov / 2 - pitch_up_deg)
    if down <= 0:
        return None
    return cam_h / math.tan(down)


# ---------------------------------------------------------------- 輸出


def _f(x: float, nd: int = 1) -> str:
    return f"{x:.{nd}f}"


def tables() -> str:
    f = sg.focal_px()
    vf = sg.vfov_deg(f)
    out: list[str] = []

    out.append("### 速度落差：多久會跟丟\n")
    out.append(
        f"從跟隨距離 {FOLLOW_DIST_M} m 開始，人一直往前走，距離拉到追蹤上限 {TRACK_MAX_M} m 所需的時間。"
        "「—」表示鴨子追得上。\n"
    )
    out.append(
        f"| 人的速度 | 每秒拉開（鴨子 {DUCK_SPEED_NOMINAL} m/s） | 超出追蹤上限（{DUCK_SPEED_NOMINAL} m/s） "
        f"| 每秒拉開（鴨子 {DUCK_SPEED_SLOW} m/s） | 超出追蹤上限（{DUCK_SPEED_SLOW} m/s） |"
    )
    out.append("|---:|---:|---:|---:|---:|")
    for v in PERSON_SPEEDS:
        cells = []
        for dv in (DUCK_SPEED_NOMINAL, DUCK_SPEED_SLOW):
            t = time_to_lose(v, dv)
            cells.append(f"{_f(gap_growth(v, dv), 2)} m/s")
            cells.append("—" if t is None else f"{_f(t)} s")
        out.append(f"| {v} m/s | " + " | ".join(cells) + " |")
    out.append("")

    out.append("### 走一段路要多久\n")
    out.append(f"| 距離 | 人 1.0 m/s | 鴨子 {DUCK_SPEED_NOMINAL} m/s | 鴨子 {DUCK_SPEED_SLOW} m/s |\n|---:|---:|---:|---:|")
    for d in (3, 5, 10, 15):
        out.append(
            f"| {d} m | {_f(travel_time(d, 1.0))} s | {_f(travel_time(d, DUCK_SPEED_NOMINAL))} s"
            f" | {_f(travel_time(d, DUCK_SPEED_SLOW))} s |"
        )
    out.append("")

    out.append(f"### 跟隨時看得到人的哪一段（鏡頭高 {sg.CAM_HEIGHT_M} m、垂直視角 {_f(vf)}°）\n")
    out.append("表中是在該距離的垂直平面上，畫面看得到的離地高度範圍。\n")
    out.append("| 鏡頭仰角 | 1.0 m | 1.5 m | 2.0 m | 3.0 m |\n|---:|---:|---:|---:|---:|")
    for p in (0, 10, 20):
        cells = []
        for d in (1.0, 1.5, 2.0, 3.0):
            lo, hi = visible_band(d, p, vf)
            cells.append(f"{_f(lo, 2)}～{_f(hi, 2)} m")
        out.append(f"| {p}° | " + " | ".join(cells) + " |")
    out.append("")
    out.append(f"在跟隨距離 {FOLLOW_DIST_M} m，各身體部位是否在畫面內：\n")
    out.append("| 鏡頭仰角 | " + " | ".join(n for n, _ in BODY_MARKS) + " |")
    out.append("|---:|" + ":---:|" * len(BODY_MARKS))
    for p in (0, 10, 20):
        lo, hi = visible_band(FOLLOW_DIST_M, p, vf)
        out.append(f"| {p}° | " + " | ".join("✓" if lo <= h <= hi else "✗" for _, h in BODY_MARKS) + " |")
    out.append("")

    out.append("### 抬頭看人時，腳前看不到的地面\n")
    out.append("| 鏡頭仰角 | 腳前看不到的地面 |\n|---:|---:|")
    for p in (0, 5, 10, 15, 20):
        b = blind_ground_m(p, vf)
        out.append(f"| {p}° | {'完全看不到地面' if b is None else _f(b, 2) + ' m'} |")
    out.append("")
    return "\n".join(out)


def check() -> None:
    f = sg.focal_px()
    vf = sg.vfov_deg(f)
    # 人比鴨子慢就追得上
    assert time_to_lose(0.1, DUCK_SPEED_NOMINAL) is None
    # 1.0 m/s 對 0.15 m/s：每秒拉開 0.85 m，1.5→3.0 m 約 1.8 s
    t = time_to_lose(1.0, DUCK_SPEED_NOMINAL)
    assert t is not None and abs(t - 1.5 / 0.85) < 1e-9
    # 10 m 鴨子要約 67 s
    assert abs(travel_time(10, DUCK_SPEED_NOMINAL) - 66.67) < 0.01
    # 仰角 0 的盲區要和 stereo_geometry 平視的「最近看得到的地面」一致
    near0, _ = sg.ground_visible(sg.CAM_HEIGHT_M, 0, vf)
    b0 = blind_ground_m(0, vf)
    assert b0 is not None and abs(b0 - near0) < 1e-9
    # 仰角超過半個垂直視角就完全看不到地面
    assert blind_ground_m(vf / 2 + 0.1, vf) is None
    # 平視時，1.5 m 處看得到腳踝、看不到臉
    lo, hi = visible_band(1.5, 0, vf)
    assert lo <= 0.1 <= hi and not (lo <= 1.6 <= hi)
    # 仰角越大，看得到的上緣越高
    assert visible_band(1.5, 10, vf)[1] > visible_band(1.5, 0, vf)[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="只跑內建檢查")
    args = parser.parse_args()
    check()
    if args.check:
        print("follow_geometry: checks passed")
        return
    print(tables())


if __name__ == "__main__":
    main()
