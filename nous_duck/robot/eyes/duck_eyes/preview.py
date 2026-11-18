"""產生預覽：所有表情的總覽圖（PNG）、狀態環總覽、輪播動畫（GIF），以及渲染速度量測。

    python -m duck_eyes.preview --out <資料夾>            # 總覽圖＋狀態環＋輪播 GIF
    python -m duck_eyes.preview --out <資料夾> --bench    # 另外量每幀渲染時間

需要 Pillow（只有預覽用，機上渲染不需要）。找得到中文字型就用中文標籤，否則用英文代號。
預覽一律畫「鏡頭開著」的青色狀態環：2026-11-18 起鏡頭預設常開（ADR-0007）。
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np

from . import render_frame
from .animator import EyeAnimator
from .expressions import EXPRESSIONS, Inputs
from .status import DeviceState

BG = (24, 24, 28)
FACE = (46, 44, 48)
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]


def _font(size: int):
    from PIL import ImageFont

    for f in FONT_CANDIDATES:
        if Path(f).exists():
            return ImageFont.truetype(f, size), True
    return ImageFont.load_default(), False


def _pair_image(left: np.ndarray, right: np.ndarray, gap: int = 40, pad: int = 16):
    from PIL import Image, ImageDraw

    w = 240 * 2 + gap + pad * 2
    h = 240 + pad * 2
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=40, fill=FACE)
    img.paste(Image.fromarray(left), (pad, pad))
    img.paste(Image.fromarray(right), (pad + 240 + gap, pad))
    return img


def snapshot(expr_id: str, t: float | None = None, device: DeviceState | None = None, inputs: Inputs | None = None):
    e = EXPRESSIONS[expr_id]
    tt = e.preview_t if t is None else t
    anim = EyeAnimator(expr_id, seed=1)
    anim._next_blink = float("inf")  # 預覽圖不要剛好拍到眨眼
    if e.action_s is not None:
        anim = EyeAnimator("happy", seed=1)
        anim._next_blink = float("inf")
        anim.set_expression(expr_id, 0.0)
        tt = min(tt, e.action_s * 0.5)
    fr = anim.frame(tt, inputs)
    dev = device or DeviceState(camera_streaming=True)
    return render_frame(fr, dev, tt)


def contact_sheet(path: Path, cols: int = 4, scale: float = 0.5) -> None:
    from PIL import Image, ImageDraw

    font, cjk = _font(22)
    tiles = []
    for eid, e in EXPRESSIONS.items():
        inp = Inputs(audio_level=0.8) if eid == "speaking" else None
        pair = _pair_image(*snapshot(eid, inputs=inp))
        pair = pair.resize((int(pair.width * scale), int(pair.height * scale)), Image.LANCZOS)
        label = f"{e.name_zh}  {eid}" if cjk else eid
        tiles.append((pair, label))
    tw, th = tiles[0][0].size
    lh = 34
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (tw + 20) + 20, rows * (th + lh + 16) + 20), BG)
    d = ImageDraw.Draw(sheet)
    for i, (tile, label) in enumerate(tiles):
        x = 20 + (i % cols) * (tw + 20)
        y = 20 + (i // cols) * (th + lh + 16)
        sheet.paste(tile, (x, y))
        d.text((x + 6, y + th + 6), label, fill=(225, 220, 210), font=font)
    sheet.save(path, optimize=True)


def status_sheet(path: Path, scale: float = 0.5) -> None:
    from PIL import Image, ImageDraw

    font, cjk = _font(20)
    cases = [
        ("鏡頭開著", "camera_on", DeviceState(camera_streaming=True), 0.2),
        ("鏡頭開著＋需要幫忙（青黃交替）", "camera_on+help (cyan/yellow)", DeviceState(camera_streaming=True, needs_help=True), 0.7),
        ("鏡頭關、對話中", "conversation", DeviceState(camera_streaming=False, conversation_active=True), 1.5),
        ("鏡頭關、待機", "standby", DeviceState(camera_streaming=False), 0.2),
        ("實體隱私開關關閉", "privacy_off", DeviceState(camera_streaming=False, privacy_switch_off=True, privacy_switch_changed_at=-5.0), 0.2),
        ("鏡頭關、需要幫忙", "help", DeviceState(camera_streaming=False, needs_help=True), 0.2),
        ("夜間、鏡頭開著", "night camera_on", DeviceState(camera_streaming=True, night=True), 0.2),
    ]
    tiles = []
    for zh, en, dev, t in cases:
        pair = _pair_image(*snapshot("neutral", t=t, device=dev))
        pair = pair.resize((int(pair.width * scale), int(pair.height * scale)), Image.LANCZOS)
        tiles.append((pair, zh if cjk else en))
    tw, th = tiles[0][0].size
    cols = 4
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (tw + 20) + 20, rows * (th + 50) + 20), BG)
    d = ImageDraw.Draw(sheet)
    for i, (tile, label) in enumerate(tiles):
        x = 20 + (i % cols) * (tw + 20)
        y = 20 + (i // cols) * (th + 50)
        sheet.paste(tile, (x, y))
        d.text((x + 6, y + th + 8), label, fill=(225, 220, 210), font=font)
    sheet.save(path, optimize=True)


def showreel(path: Path, fps: int = 10, per_s: float = 1.5, scale: float = 0.5, ids=None) -> int:
    from PIL import Image, ImageDraw

    font, cjk = _font(18)
    ids = list(ids or EXPRESSIONS.keys())
    anim = EyeAnimator("neutral", seed=7)
    dev = DeviceState(camera_streaming=True)
    frames = []
    n = int(len(ids) * per_s * fps)
    for k in range(n):
        t = k / fps
        idx = min(int(t / per_s), len(ids) - 1)
        if anim.expression != ids[idx] and (EXPRESSIONS[ids[idx]].action_s is None or abs(t - idx * per_s) < 1e-6):
            anim.set_expression(ids[idx], t)
        inp = Inputs(audio_level=0.5 + 0.5 * np.sin(t * 9.0) ** 2) if ids[idx] == "speaking" else None
        fr = anim.frame(t, inp)
        pair = _pair_image(*render_frame(fr, dev, t))
        pair = pair.resize((int(pair.width * scale), int(pair.height * scale)), Image.LANCZOS)
        canvas = Image.new("RGB", (pair.width, pair.height + 28), BG)
        canvas.paste(pair, (0, 0))
        e = EXPRESSIONS[ids[idx]]
        ImageDraw.Draw(canvas).text((10, pair.height + 4), f"{e.name_zh} {e.id}" if cjk else e.id, fill=(225, 220, 210), font=font)
        frames.append(canvas.quantize(colors=64, method=Image.Quantize.MEDIANCUT))
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=int(1000 / fps), loop=0, optimize=True)
    return n


def bench(n: int = 60) -> dict:
    anim = EyeAnimator("neutral", seed=3)
    dev = DeviceState(camera_streaming=True)
    times = {}
    for eid in ("neutral", "happy", "love", "sleeping", "dizzy", "low_battery"):
        anim.set_expression(eid, 0.0)
        t0 = time.perf_counter()
        for k in range(n):
            render_frame(anim.frame(1.0 + k / 30), dev, 1.0 + k / 30)
        times[eid] = (time.perf_counter() - t0) / n * 1000
    return times


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--bench", action="store_true")
    ap.add_argument("--no-gif", action="store_true")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    contact_sheet(a.out / "eyes_expressions.png")
    status_sheet(a.out / "eyes_status_ring.png")
    if not a.no_gif:
        n = showreel(a.out / "eyes_showreel.gif")
        print(f"showreel: {n} frames")
    if a.bench:
        for k, v in bench().items():
            print(f"bench {k}: {v:.1f} ms / frame（兩眼）")
    print(f"written to {a.out}")


if __name__ == "__main__":
    main()
