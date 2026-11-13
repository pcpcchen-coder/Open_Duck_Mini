"""產生 README 用的示意圖（無頭 Chromium＋three.js 軟體算圖）。

    python -m dock_cad.render --three /path/to/three.module.js   # three@0.170.0
    # three.module.js 可從 https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js 下載

輸出到 ../images/。這是開發工具：repo 不內嵌 three.js，CI 不跑這一步。
圖裡的鴨子是上游 CAD（home 站姿）；背殼換成改裝件；觸片、頂針、AprilTag 是示意。
"""

from __future__ import annotations

import argparse
import os
import json
import shutil
import tempfile
from pathlib import Path

import numpy as np

from . import params as P
from .build import build
from .dock_parts import pin_positions, tag_outer_size
from .duck import load_duck
from .geom import box, cyl, to_trimesh
from .tag import tag_bits

IMG_DIR = Path(__file__).resolve().parents[2] / "images"

#: AR0144 水平視角 65°、16:9 → 垂直視角（度）
DUCK_EYE_VFOV = float(np.degrees(2 * np.arctan(np.tan(np.radians(65 / 2)) * 720 / 1280)))


def _mesh_entry(name, verts, faces, color, opacity=1.0, offset=(0, 0, 0)):
    v = np.asarray(verts, dtype=np.float32) + np.asarray(offset, dtype=np.float32)
    return {
        "name": name,
        "color": color,
        "opacity": opacity,
        "pos": np.round(v, 2).flatten().tolist(),
        "idx": np.asarray(faces, dtype=np.int32).flatten().tolist(),
    }


def scene_data(explode: bool = False, with_duck: bool = True, duck_dx: float = 0.0, only: tuple[str, ...] = ()) -> list[dict]:
    res = build()
    duck = load_duck()
    entries = []
    for p in res.parts:
        tm = to_trimesh(p.solid)
        off = p.explode if explode else (0, 0, 0)
        entries.append(_mesh_entry(p.key, tm.vertices, tm.faces, p.color, offset=off))
    # 示意：頂針（金色小圓柱）
    for pin in pin_positions(res.contact_z):
        c = to_trimesh(cyl("x", (0, pin["y"], pin["z"]), 1.0, -16, P.CRADLE_BASE_X + P.PIN_PROTRUDE))
        off = (60, 0, 0) if explode else (0, 0, 0)
        entries.append(_mesh_entry("pogo_pin_mock", c.vertices, c.faces, "#d4a017", offset=off))
    # 示意：AprilTag 紙
    bits = tag_bits()
    cell = P.TAG_BLACK_SIZE / 8
    s = tag_outer_size()
    paper = to_trimesh(box(P.BACK_FRONT_X - 0.2, P.BACK_FRONT_X + 0.1, -s / 2, s / 2, P.TAG_CENTER_Z - s / 2, P.TAG_CENTER_Z + s / 2))
    toff = (0, 0, 60) if explode else (0, 0, 0)
    entries.append(_mesh_entry("tag_paper_mock", paper.vertices, paper.faces, "#ffffff", offset=toff))
    blacks = []
    for r in range(10):
        for c in range(10):
            if bits[r, c] == 0:
                # 從房間這側（+X）看過去，觀看者的左手邊是 -Y
                y0 = -s / 2 + c * cell
                z0 = P.TAG_CENTER_Z + s / 2 - r * cell
                blacks.append(box(P.BACK_FRONT_X + 0.05, P.BACK_FRONT_X + 0.3, y0, y0 + cell, z0 - cell, z0))
    from .geom import union_all

    bt = to_trimesh(union_all(blacks))
    entries.append(_mesh_entry("tag_black_mock", bt.vertices, bt.faces, "#111111", offset=toff))
    # 示意：狀態燈（窗內暖色）
    led = to_trimesh(cyl("x", (0, 0, P.WINDOW_Z), P.WINDOW_D / 2 - 0.5, P.BACK_FRONT_X - P.WALL - 2, P.BACK_FRONT_X - P.WALL - 1))
    entries.append(_mesh_entry("led_glow_mock", led.vertices, led.faces, "#ffd27a", offset=(0, 0, 120) if explode else (0, 0, 0)))

    if with_duck:
        dx = duck_dx + (160 if explode else 0)
        # 建議做法：原版背殼（已印好）＋外掛觸點板
        orig_tm = to_trimesh(res.body_back_orig)
        entries.append(_mesh_entry("body_back_orig", duck.print_to_dock(orig_tm.vertices), orig_tm.faces, "#f4f1ea", offset=(dx, 0, 0)))
        plate_tm = to_trimesh(res.contact_plate)
        entries.append(_mesh_entry("contact_plate", duck.print_to_dock(plate_tm.vertices), plate_tm.faces, "#f08a24", offset=(dx, 0, 0)))
        # 示意：黃銅觸片
        from .body_back_mod import strip_rects_print

        for srect in strip_rects_print():
            b = to_trimesh(box(P.BOSS_FACE_X - 0.2, P.BOSS_FACE_X + 0.6, srect["y0"], srect["y1"], srect["z0"], srect["z1"]))
            entries.append(_mesh_entry("brass_strip_mock", duck.print_to_dock(b.vertices), b.faces, "#c9a227", offset=(dx, 0, 0)))
        for part in duck.parts:
            if part.name == "body_back":
                continue
            col = "#eeeeee"
            if part.name.startswith(("wj-", "drive_", "passive_")):
                col = "#333333"
            elif part.name.startswith("foot_bottom_tpu"):
                col = "#444444"
            elif part.name in ("head", "body_front", "body_middle_top", "body_middle_bottom", "left_cache", "right_cache"):
                col = "#f4f1ea"
            entries.append(_mesh_entry("duck:" + part.name, part.vertices, part.faces, col, offset=(dx, 0, 0)))
    if only:
        entries = [e for e in entries if any(e["name"].startswith(o) for o in only)]
    return entries


HTML = """<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0;background:#f6f4ef}canvas{display:block}</style>
<script type="importmap">{"imports":{"three":"./three.module.js"}}</script></head><body>
<script type="module">
import * as THREE from 'three';
const qs=new URLSearchParams(location.search); const W=+qs.get('w'), H=+qs.get('h');
const renderer=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});
renderer.setSize(W,H); renderer.setPixelRatio(1); document.body.appendChild(renderer.domElement);
renderer.shadowMap.enabled=false;
const scene=new THREE.Scene(); scene.background=new THREE.Color('#f6f4ef');
scene.add(new THREE.HemisphereLight(0xffffff,0x998877,1.6));
const dl=new THREE.DirectionalLight(0xffffff,1.6); dl.position.set(600,500,900); scene.add(dl);
const dl2=new THREE.DirectionalLight(0xffffff,0.5); dl2.position.set(-500,-300,300); scene.add(dl2);
const data=await (await fetch('./scene.json')).json();
for(const m of data.meshes){
  const g=new THREE.BufferGeometry();
  g.setAttribute('position',new THREE.Float32BufferAttribute(m.pos,3));
  g.setIndex(m.idx); g.computeVertexNormals();
  const mat=new THREE.MeshStandardMaterial({color:m.color,roughness:0.75,metalness:m.name.includes('brass')||m.name.includes('pogo')?0.6:0.0,
    transparent:m.opacity<1,opacity:m.opacity,flatShading:!m.name.startsWith('duck:'), emissive:m.name.includes('led')?0xffb030:0x000000, emissiveIntensity:m.name.includes('led')?0.9:0});
  const mesh=new THREE.Mesh(g,mat); scene.add(mesh);
  const edges=new THREE.LineSegments(new THREE.EdgesGeometry(g,35),new THREE.LineBasicMaterial({color:0x000000,transparent:true,opacity:0.18}));
  if(!m.name.startsWith('duck:')) scene.add(edges);
}
// 地板格線
const grid=new THREE.GridHelper(1200,24,0xcccccc,0xe2ded5); grid.rotation.x=Math.PI/2; scene.add(grid);
const cam=new THREE.PerspectiveCamera(data.fov,W/H,1,5000);
cam.up.set(0,0,1); cam.position.set(...data.eye); cam.lookAt(...data.target);
renderer.render(scene,cam);
window.__done=true;
</script></body></html>"""


def render_views(three_js: Path, out_dir: Path = IMG_DIR) -> list[Path]:
    from playwright.sync_api import sync_playwright

    views = [
        ("dock_docked_front.png", dict(explode=False, with_duck=True), (900, 520, 520), (40, 0, 230), 30),
        ("dock_empty_front.png", dict(explode=False, with_duck=False), (860, 450, 560), (30, 0, 270), 32),
        ("dock_backing_in_side.png", dict(explode=False, with_duck=True, duck_dx=70.0), (300, 980, 330), (80, 0, 220), 28),
        ("dock_exploded.png", dict(explode=True, with_duck=False), (900, 700, 700), (40, 0, 260), 32),
        ("contact_plate_closeup.png", dict(with_duck=True, duck_dx=0.0, only=("body_back_orig", "contact_plate", "brass_strip")), (-300, -210, 330), (5, 0, 205), 30),
        ("cradle_closeup.png", dict(with_duck=False, only=("dock_cradle", "pogo_pin")), (260, 170, 300), (5, 0, 205), 30),
        # 鴨子在預備點（充電座前方 50 cm）面向充電座時，頭上鏡頭看到的畫面（示意）：
        # 鏡頭高度約 370 mm、水平視角 65°（AR0144 規格）、1280×720 → 垂直視角約 39.4°
        ("duck_eye_view_50cm.png", dict(with_duck=False), (500, 0, 370), (0, 0, 370), DUCK_EYE_VFOV, (1280, 720)),
    ]
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        shutil.copy(three_js, tmp / "three.module.js")
        (tmp / "index.html").write_text(HTML, encoding="utf-8")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=os.environ.get("DOCK_RENDER_CHROME") or None, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
            for fname, kw, eye, target, fov, *size in views:
                W, H = size[0] if size else (1000, 700)
                meshes = scene_data(**kw)
                (tmp / "scene.json").write_text(json.dumps({"meshes": meshes, "eye": eye, "target": target, "fov": fov}))
                page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
                # file:// 不能 fetch，改用本機 HTTP
                page.goto(f"http://127.0.0.1:{_serve(tmp)}/index.html?w={W}&h={H}")
                page.wait_for_function("window.__done === true", timeout=120000)
                path = out_dir / fname
                page.screenshot(path=str(path))
                page.close()
                written.append(path)
            browser.close()
    return written


_SERVERS: dict[str, int] = {}


def _serve(directory: Path) -> int:
    key = str(directory)
    if key in _SERVERS:
        return _SERVERS[key]
    import functools
    import http.server
    import threading

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=key)
    handler.log_message = lambda *a, **k: None  # type: ignore[attr-defined]
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _SERVERS[key] = srv.server_address[1]
    return _SERVERS[key]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--three", required=True, type=Path, help="three@0.170.0 的 three.module.js")
    args = ap.parse_args()
    for p in render_views(args.three):
        print(p)


if __name__ == "__main__":
    main()
