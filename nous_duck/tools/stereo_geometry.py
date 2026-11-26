#!/usr/bin/env python3
"""AR0144 雙目鏡頭裝在鴨子頭上時的幾何推算（只用標準函式庫）。

用途：[`docs/stereo_vision_plan.md`](../docs/stereo_vision_plan.md) 裡的數字都由這支腳本算出，
方法與輸出記錄在 `docs/validation/stereo-geometry-2026-11-16.md`。

**全部是名目規格推算，不是量測。** 鏡頭沒有校正、還沒裝上鴨子；實際值以 P2 實機量測為準。

輸入（來源）：
- AR0144 規格（AIOS `docs/11_Stereo_Camera_Interaction_2026-10.md`，main `7b0257d`；
  Waveshare 產品頁）：單眼 1280×720、水平視角 65°、基線 52 mm。
- 鏡頭高度：上游 `robot.xml` 在 Open_Duck_Playground `home` 站姿下，頭殼 `head` 網格離地
  341～401 mm（用 `nous_duck/hardware/dock/cad/dock_cad/duck.py` 的順向運動學算出）。
  鏡頭裝在頭殼正面、位置還沒設計，先取 0.37 m，並列 0.34／0.40 m 當範圍。
- 上游關節範圍（`robot.xml`）：neck_pitch −20°～+65°、head_pitch ±45°、head_yaw ±160°。
  哪個方向是「抬頭」尚未對照實機，表中只算「需要的鏡頭俯仰角」。

用法：

    python3 -I nous_duck/tools/stereo_geometry.py            # 輸出 Markdown 表格
    python3 -I nous_duck/tools/stereo_geometry.py --check    # 只跑內建檢查
"""

from __future__ import annotations

import argparse
import math

# ---- 名目規格 ----
WIDTH_PX = 1280  # 單眼
HEIGHT_PX = 720
HFOV_DEG = 65.0
BASELINE_M = 0.052

# ---- 鴨子 ----
CAM_HEIGHT_M = 0.37
CAM_HEIGHT_RANGE_M = (0.34, 0.40)

# ---- 物體尺寸假設（與 AIOS 文件 11 相同的臉寬；其餘為常見值） ----
FACE_WIDTH_M = 0.15
PERSON_HEIGHT_M = 1.70


def focal_px(width_px: float = WIDTH_PX, hfov_deg: float = HFOV_DEG) -> float:
    """針孔模型焦距（像素）。"""
    return (width_px / 2) / math.tan(math.radians(hfov_deg) / 2)


def vfov_deg(f_px: float, height_px: float = HEIGHT_PX) -> float:
    return math.degrees(2 * math.atan((height_px / 2) / f_px))


def disparity_px(z_m: float, f_px: float, baseline_m: float = BASELINE_M) -> float:
    return f_px * baseline_m / z_m


def depth_step_m(z_m: float, f_px: float, baseline_m: float = BASELINE_M, d_px: float = 1.0) -> float:
    """視差差 d_px 像素時的深度變化（一階近似 ΔZ ≈ Z²·Δd / (f·B)）。"""
    return z_m**2 * d_px / (f_px * baseline_m)


def min_depth_m(max_disp_px: float, f_px: float, baseline_m: float = BASELINE_M) -> float:
    """立體匹配搜尋 max_disp_px 個視差時，能量到的最近距離。"""
    return f_px * baseline_m / max_disp_px


def footprint_width_m(z_m: float, hfov_deg: float = HFOV_DEG) -> float:
    return 2 * z_m * math.tan(math.radians(hfov_deg) / 2)


def size_px(size_m: float, z_m: float, f_px: float) -> float:
    return f_px * size_m / z_m


def ground_visible(cam_h_m: float, pitch_down_deg: float, vfov: float) -> tuple[float, float | None]:
    """鏡頭往下俯 pitch_down_deg 度時，畫面裡看得到的地面範圍（水平距離）。

    回傳（最近，最遠）；最遠為 None 表示畫面上緣在地平線以上（看得到遠處）。
    """
    low = math.radians(pitch_down_deg + vfov / 2)
    high = math.radians(pitch_down_deg - vfov / 2)
    if low <= 0:
        raise ValueError("畫面下緣沒有往下，看不到地面")
    near = cam_h_m / math.tan(low)
    far = cam_h_m / math.tan(high) if high > 0 else None
    return near, far


def elevation_deg(target_h_m: float, dist_m: float, cam_h_m: float = CAM_HEIGHT_M) -> float:
    """從鏡頭看目標的仰角（正＝往上）。"""
    return math.degrees(math.atan2(target_h_m - cam_h_m, dist_m))


def person_fits_vertically_m(person_h_m: float, cam_h_m: float, vfov: float) -> float:
    """鏡頭水平、不轉頭時，要離多遠才能把整個人（腳到頭頂）放進畫面。"""
    half = math.radians(vfov / 2)
    need_up = (person_h_m - cam_h_m) / math.tan(half)
    need_down = cam_h_m / math.tan(half)
    return max(need_up, need_down)


# ---------------------------------------------------------------- 輸出


def _fmt(x: float, nd: int = 0) -> str:
    return f"{x:.{nd}f}"


def tables() -> str:
    f = focal_px()
    f_half = focal_px(WIDTH_PX / 2)
    vf = vfov_deg(f)
    out: list[str] = []
    out.append("### 基本量\n")
    out.append("| 量 | 值 |\n|---|---|")
    out.append(f"| 焦距 f（單眼 1280 px） | {_fmt(f, 1)} px |")
    out.append(f"| 焦距 f（縮成 640×360） | {_fmt(f_half, 1)} px |")
    out.append(f"| 垂直視角 | {_fmt(vf, 1)}° |")
    out.append(f"| 鏡頭高度（假設） | {CAM_HEIGHT_M} m（範圍 {CAM_HEIGHT_RANGE_M[0]}～{CAM_HEIGHT_RANGE_M[1]} m） |")
    out.append("")

    out.append("### 深度解析度（1 px 視差對應的深度變化）\n")
    out.append("| 距離 | 視差（1280） | 每 1 px 深度變化（1280） | 每 1 px 深度變化（640） | 畫面寬度 |")
    out.append("|---:|---:|---:|---:|---:|")
    for z in (0.3, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0):
        out.append(
            f"| {z} m | {_fmt(disparity_px(z, f))} px | {_fmt(depth_step_m(z, f) * 1000)} mm"
            f" | {_fmt(depth_step_m(z, f_half) * 1000)} mm | {_fmt(footprint_width_m(z), 2)} m |"
        )
    out.append("")

    out.append("### 立體匹配能量到的最近距離\n")
    out.append("| 解析度 | 搜尋 64 個視差 | 搜尋 128 個視差 | 搜尋 256 個視差 |\n|---|---:|---:|---:|")
    for label, ff in (("1280×720", f), ("640×360", f_half)):
        cells = " | ".join(f"{_fmt(min_depth_m(d, ff), 2)} m" for d in (64, 128, 256))
        out.append(f"| {label} | {cells} |")
    out.append("")

    out.append("### 頭往下俯時看得到的地面（鏡頭高度 0.37 m）\n")
    out.append("| 鏡頭俯角 | 最近看得到的地面 | 最遠看得到的地面 |\n|---:|---:|---:|")
    for pitch in (0, 10, 20, 30, 40):
        near, far = ground_visible(CAM_HEIGHT_M, pitch, vf)
        far_s = "地平線以上（看得到遠處）" if far is None else f"{_fmt(far, 2)} m"
        out.append(f"| {pitch}° | {_fmt(near, 2)} m | {far_s} |")
    lo, hi = CAM_HEIGHT_RANGE_M
    out.append("")
    out.append(
        f"平視時腳前看不到的範圍：鏡頭高 {lo} m 時 {_fmt(ground_visible(lo, 0, vf)[0], 2)} m、"
        f"{hi} m 時 {_fmt(ground_visible(hi, 0, vf)[0], 2)} m。"
    )
    out.append("")

    out.append("### 看人臉要抬頭多少（臉在畫面正中央所需的鏡頭仰角）\n")
    targets = (
        ("大人站著（臉約 1.6 m）", 1.6),
        ("大人坐著（臉約 1.2 m）", 1.2),
        ("小孩站著（臉約 1.0 m）", 1.0),
        ("躺在床上（臉約 0.6 m）", 0.6),
    )
    out.append("| 對象 | 距離 0.5 m | 1.0 m | 1.5 m | 2.0 m |\n|---|---:|---:|---:|---:|")
    for label, h in targets:
        cells = " | ".join(f"{_fmt(elevation_deg(h, d))}°" for d in (0.5, 1.0, 1.5, 2.0))
        out.append(f"| {label} | {cells} |")
    out.append("")
    out.append(
        f"只要臉在畫面內（不必置中），所需仰角可再少半個垂直視角（{_fmt(vf / 2, 1)}°）。"
        f"鏡頭平視、不轉頭時，要離 {_fmt(person_fits_vertically_m(PERSON_HEIGHT_M, CAM_HEIGHT_M, vf), 1)} m"
        f" 以上才能把 {PERSON_HEIGHT_M} m 高的人整個放進畫面。"
    )
    out.append("")

    out.append("### 物體在畫面中的大小（像素）\n")
    out.append("| 距離 | 臉寬 15 cm（1280） | 臉寬 15 cm（640） | 標籤邊長 10 cm（1280） | 標籤 10 cm（640） | 標籤 15 cm（1280） |")
    out.append("|---:|---:|---:|---:|---:|---:|")
    for z in (0.5, 1.0, 2.0, 3.0, 4.0):
        out.append(
            f"| {z} m | {_fmt(size_px(FACE_WIDTH_M, z, f))} | {_fmt(size_px(FACE_WIDTH_M, z, f_half))}"
            f" | {_fmt(size_px(0.10, z, f))} | {_fmt(size_px(0.10, z, f_half))} | {_fmt(size_px(0.15, z, f))} |"
        )
    out.append("")
    return "\n".join(out)


def check() -> None:
    """內建檢查：和 AIOS 文件 11 的數字對得上，且幾何關係合理。"""
    f = focal_px()
    assert abs(f - 1005) < 1, f  # AIOS 11：f ≈ 1005 px
    assert round(disparity_px(2.0, f)) == 26  # AIOS 11：2 m 視差 26 px
    assert round(depth_step_m(2.0, f) * 1000) == 77  # AIOS 11：2 m 每 px 約 77 mm
    assert round(size_px(FACE_WIDTH_M, 2.0, f)) == 75  # AIOS 11：2 m 臉寬約 75 px
    vf = vfov_deg(f)
    assert 39 < vf < 40, vf
    near0, far0 = ground_visible(CAM_HEIGHT_M, 0, vf)
    assert far0 is None and 0.9 < near0 < 1.1, near0
    near20, far20 = ground_visible(CAM_HEIGHT_M, 20, vf)
    assert near20 < near0 and far20 is not None and far20 > 10  # 上緣接近水平
    assert elevation_deg(CAM_HEIGHT_M, 1.0) == 0
    # 深度步距隨距離平方成長
    assert abs(depth_step_m(2.0, f) / depth_step_m(1.0, f) - 4) < 1e-9
    # 解析度減半，最近距離也減半
    assert abs(min_depth_m(128, focal_px(640)) * 2 - min_depth_m(128, f)) < 1e-9


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="只跑內建檢查")
    args = parser.parse_args()
    check()
    if args.check:
        print("stereo_geometry: checks passed")
        return
    print(tables())


if __name__ == "__main__":
    main()
