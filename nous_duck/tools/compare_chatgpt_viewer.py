"""比對 ChatGPT 版組裝檢視器（docs/handoff/chatgpt_viewer_html/）與本 repo pipeline 的零件擺放。

作法：兩邊都用上游 STL 的本地座標（毫米）加上每個實例的位置與四元數擺放。
1. 用 trunk_bottom 求兩邊座標系之間的剛體變換。
2. 每個 ChatGPT 實例取 STL 頂點（抽樣約 400 點）擺到世界座標，和本 repo 同一種網格的每個實例比對，
   取最小的最大頂點誤差。CAD 沒有擺放位置的 7 件改用上游 print/ 的 STL（單位已是毫米）。
3. 比對對上的實例，舵機 ID 是否相同。
4. 列出膝、踝、髖俯仰舵機主動舵盤的 x 座標（+X 是鴨子的左邊），看左右腿是否 180° 而不是鏡像。

用法（先執行 pipeline 產生 dist/build/scene.json）：
    python3 -I nous_duck/tools/compare_chatgpt_viewer.py
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
CHATGPT_HTML = REPO / "nous_duck/docs/handoff/chatgpt_viewer_html/Open_Duck_Mini_v2_Assembly_Viewer.html"
SCENE = REPO / "nous_duck/assembly_viewer/dist/build/scene.json"
CAD_DIR = REPO / "mini_bdx/robots/open_duck_mini_v2"
PRINT_DIR = REPO / "print"
TOLERANCE_MM = 0.01


def quat_matrix(q) -> np.ndarray:  # xyzw
    x, y, z, w = np.asarray(q, dtype=float) / np.linalg.norm(q)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def stl_vertices(path: Path, units: float) -> np.ndarray:
    data = path.read_bytes()
    (n,) = struct.unpack("<I", data[80:84])
    rec = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("f", "<u2")])
    v = np.frombuffer(data, dtype=rec, offset=84, count=n)["v"].reshape(-1, 3).astype(float) * units
    return v[:: max(1, len(v) // 400)]


def read_chatgpt_data(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    start = text.index("const DATA=") + len("const DATA=")
    data, _ = json.JSONDecoder().raw_decode(text[start:])
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scene", type=Path, default=SCENE)
    ap.add_argument("--html", type=Path, default=CHATGPT_HTML)
    args = ap.parse_args()

    ours = json.loads(args.scene.read_text(encoding="utf-8"))
    cg = read_chatgpt_data(args.html)

    our_inst = [
        dict(id=p["id"], mesh=p["mesh"].removeprefix("print:"), R=quat_matrix(p["quaternion_xyzw"]),
             t=np.array(p["position_mm"]), servo=p["servo_id"])
        for p in ours["parts"]
    ]
    cg_inst = [
        dict(id=p["id"], mesh=s["m"], R=quat_matrix(s["q"]), t=np.array(s["p"]), servo=p.get("motor"), name=p["name"])
        for p in cg["parts"]
        for s in p["sh"]
        if "m" in s and "q" in s
    ]
    proxies = sorted({p["k"] for p in cg["parts"] if not any("m" in s for s in p["sh"])})

    a = next(x for x in our_inst if x["mesh"] == "trunk_bottom")
    b = next(x for x in cg_inst if x["mesh"] == "trunk_bottom")
    G_R = b["R"] @ a["R"].T
    G_t = b["t"] - G_R @ a["t"]

    verts: dict[str, np.ndarray] = {}
    def local(mesh: str) -> np.ndarray:
        if mesh not in verts:
            cad = CAD_DIR / f"{mesh}.stl"
            verts[mesh] = stl_vertices(cad, 1000.0) if cad.exists() else stl_vertices(PRINT_DIR / f"{mesh}.stl", 1.0)
        return verts[mesh]

    worst = 0.0
    bad, id_diff, matched = [], [], {}
    for x in cg_inst:
        v = local(x["mesh"])
        wx = v @ x["R"].T + x["t"]
        best = None
        for y in our_inst:
            if y["mesh"] != x["mesh"]:
                continue
            wy = (v @ y["R"].T + y["t"]) @ G_R.T + G_t
            err = float(np.abs(wy - wx).max())
            if best is None or err < best[0]:
                best = (err, y)
        if best is None:
            bad.append((x["id"], x["mesh"], "本 repo 沒有這種網格"))
            continue
        err, y = best
        worst = max(worst, err)
        if err > TOLERANCE_MM:
            bad.append((x["id"], x["mesh"], f"最近的實例 {y['id']} 差 {err:.2f} mm"))
        else:
            matched[y["id"]] = x["id"]
            if (x["servo"] or None) != (y["servo"] or None):
                id_diff.append((x["id"], x["servo"], y["id"], y["servo"]))

    print(f"座標系差異：旋轉\n{np.round(G_R, 6)}\n平移 {np.round(G_t, 3).tolist()} mm（ChatGPT 版 = 本 repo × 旋轉 + 平移）")
    print(f"ChatGPT 版網格實例 {len(cg_inst)}，本 repo {len(our_inst)}；一對一對上 {len(set(matched))}")
    print(f"最大頂點誤差 {worst:.4f} mm（容許 {TOLERANCE_MM} mm）")
    print(f"ChatGPT 版另有 {len(proxies)} 類沒有 CAD 網格的示意零件：{', '.join(proxies)}")
    for row in bad:
        print("位置不符：", *row)
    for row in id_diff:
        print("舵機 ID 不同：", *row)

    print("\n主動舵盤 x 座標（本 repo 座標，+X 是鴨子的左邊；兩腿中心約 ±91 mm）")
    horn_local = (local("drive_palonier").min(0) + local("drive_palonier").max(0)) / 2
    for sid in (12, 13, 14, 22, 23, 24):
        s = next(s for s in ours["servos"] if s["id"] == sid)
        x = next(x for x in cg_inst if x["servo"] == sid and x["mesh"] == "drive_palonier")
        cg_horn = G_R.T @ (x["R"] @ horn_local + x["t"] - G_t)
        side = "內側" if abs(s["horn_center_mm"][0]) < 91 else "外側"
        print(f"  ID {sid} {s['joint']:<16} 本 repo {s['horn_center_mm'][0]:7.1f}  ChatGPT 版 {cg_horn[0]:7.1f}  → {side}")

    ok = not bad and not id_diff and len(set(matched)) == len(our_inst)
    print("\n結論：" + ("擺放與舵機 ID 完全一致" if ok else "有差異，見上方"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
