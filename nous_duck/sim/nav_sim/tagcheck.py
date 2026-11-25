"""用 MuJoCo 的相機算圖＋OpenCV 的 AprilTag 36h11 偵測器，檢查「幾何合成的標籤觀測（mock）」合不合理。

    cd nous_duck/sim
    python -m nav_sim.tagcheck --out ../docs/validation/data/tagcheck-2026-11-25.json

做法：把鴨子（站姿、不走路）放在幾個位置，頭上的相機（AR0144 名目值：1280×720、垂直視角 39.4°）算一張圖，
用 `cv2.aruco`（`DICT_APRILTAG_36h11`）偵測，再用 `solvePnP` 由四個角點算出標籤相對相機的位姿，
換成機身座標後跟地圖上的真實值比。同一個位置也產生 mock 觀測，比較兩邊「看得到哪些標籤」。

限制：算圖沒有鏡頭畸變、動態模糊、曝光與雜訊；相機位置是假設值。這只能說明 mock 的幾何與量級合理，
**不代表實機的偵測率或精度**。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import mujoco
import numpy as np

from duck_nav.geometry import Pose2D, to_body, wrap
from duck_nav.mock_sensors import FOCAL_PX, MockCameraConfig, MockTagCamera

from .loop import synthetic_home
from .scene import MujocoBody

W, H = 1280, 720

POSES = [
    ("dock_staging_0.5m", Pose2D(0.732, 1.5, math.pi)),
    ("dock_far_1.25m", Pose2D(1.32, 1.5, math.pi)),
    ("living_facing_east", Pose2D(2.0, 1.3, 0.0)),
    ("living_facing_south", Pose2D(1.8, 1.4, -math.pi / 2)),
    ("hallway_facing_east", Pose2D(3.2, 3.5, 0.0)),
    ("hallway_facing_west", Pose2D(2.6, 3.5, math.pi)),
    ("brother_room_facing_north", Pose2D(2.6, 5.0, math.pi / 2)),
    ("study_facing_east", Pose2D(5.2, 5.4, 0.0)),
    ("living_oblique_to_tag1", Pose2D(2.6, 0.5 + 0.9, 0.35)),
]


def detect(img: np.ndarray):
    import cv2

    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    det = cv2.aruco.ArucoDetector(d, cv2.aruco.DetectorParameters())
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    corners, ids, _ = det.detectMarkers(gray)
    return ([] if ids is None else [int(i) for i in ids.flatten()]), corners


def run(seed: int = 0) -> dict:
    import cv2

    m = synthetic_home()
    rows = []
    cam = MockTagCamera(m, MockCameraConfig(dropout=0.0), seed=seed)
    f = (H / 2) / math.tan(math.radians(39.4) / 2)
    K = np.array([[f, 0, W / 2], [0, f, H / 2], [0, 0, 1]], dtype=float)
    for name, pose in POSES:
        body = MujocoBody(m, start=pose, seed=seed, with_tag_textures=True, obs_noise=False)
        sim = body.sim
        r = mujoco.Renderer(sim.m, height=H, width=W)
        r.update_scene(sim.d, camera="head_cam")
        img = r.render().copy()
        r.close()
        ids, corners = detect(img)
        tp = body.true_pose
        cam_id = sim.m.camera("head_cam").id
        cpos = sim.d.cam_xpos[cam_id].copy()
        cmat = sim.d.cam_xmat[cam_id].reshape(3, 3).copy()  # 相機座標（x 右、y 上、看 −z）→ 世界
        found = []
        for tid, c in zip(ids, corners):
            tag = m.tags.get(tid)
            if tag is None:
                continue
            s = tag.size_m / 2
            obj = np.array([[-s, s, 0], [s, s, 0], [s, -s, 0], [-s, -s, 0]], dtype=float)
            ok, rvec, tvec = cv2.solvePnP(obj, c.reshape(4, 2).astype(float), K, None, flags=cv2.SOLVEPNP_IPPE_SQUARE)
            if not ok:
                continue
            # OpenCV 相機座標（x 右、y 下、z 前）→ MuJoCo 相機座標（x 右、y 上、z 後）→ 世界。
            p_cv = tvec.flatten()
            p_w = cpos + cmat @ np.array([p_cv[0], -p_cv[1], -p_cv[2]])
            Rt, _ = cv2.Rodrigues(rvec)
            n_cv = Rt @ np.array([0, 0, 1.0])  # 標籤法線（朝相機的那一面）
            n_w = cmat @ np.array([n_cv[0], -n_cv[1], -n_cv[2]])
            yaw_w = math.atan2(n_w[1], n_w[0])
            bx, by = to_body(tp, p_w[0], p_w[1])
            tx, ty = to_body(tp, tag.x, tag.y)
            rng = math.hypot(tag.x - cpos[0], tag.y - cpos[1])
            side = float(np.mean([np.linalg.norm(c.reshape(4, 2)[i] - c.reshape(4, 2)[(i + 1) % 4]) for i in range(4)]))
            found.append(
                {
                    "tag_id": tid,
                    "range_m": round(rng, 3),
                    "side_px": round(side, 1),
                    "pos_err_m": round(math.hypot(bx - tx, by - ty), 4),
                    "yaw_err_deg": round(math.degrees(wrap(yaw_w - tag.yaw)), 2),
                    "height_err_m": round(float(p_w[2] - tag.z), 4),
                }
            )
        head_yaw = body.head_yaw
        mock_ids = sorted(o.tag_id for o in cam.observe(tp, head_yaw))
        rows.append(
            {
                "pose": name,
                "detector_ids": sorted(d["tag_id"] for d in found),
                "mock_ids": mock_ids,
                "agree": sorted(d["tag_id"] for d in found) == mock_ids,
                "camera_height_m": round(float(cpos[2]), 3),
                "detections": found,
            }
        )
    allf = [d for r_ in rows for d in r_["detections"]]
    return {
        "simulated": True,
        "note": "MuJoCo 相機算圖（無畸變、無模糊、無雜訊）＋ OpenCV aruco DICT_APRILTAG_36h11；不是實機偵測結果",
        "image": [W, H],
        "focal_px": round(f, 1),
        "mock_focal_px": round(FOCAL_PX, 1),
        "poses": len(rows),
        "poses_where_detector_and_mock_agree": sum(r_["agree"] for r_ in rows),
        "detections": len(allf),
        "pos_err_m_max": max((d["pos_err_m"] for d in allf), default=None),
        "pos_err_m_mean": round(float(np.mean([d["pos_err_m"] for d in allf])), 4) if allf else None,
        "yaw_err_deg_max_abs": max((abs(d["yaw_err_deg"]) for d in allf), default=None),
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m nav_sim.tagcheck")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--png", type=Path, default=None, help="另存充電座預備點的相機畫面（縮小）")
    a = ap.parse_args(argv)
    res = run()
    text = json.dumps(res, ensure_ascii=False, indent=1)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text + "\n", encoding="utf-8")
    if a.png:
        from PIL import Image

        m = synthetic_home()
        body = MujocoBody(m, start=POSES[0][1], with_tag_textures=True, obs_noise=False)
        r = mujoco.Renderer(body.sim.m, height=H, width=W)
        r.update_scene(body.sim.d, camera="head_cam")
        Image.fromarray(r.render()).resize((640, 360)).save(a.png, optimize=True)
        r.close()
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
