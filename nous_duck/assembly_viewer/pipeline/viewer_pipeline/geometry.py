"""幾何工具：四元數、旋轉矩陣、STL 讀取、座標系轉換。"""
from __future__ import annotations

import struct
from functools import lru_cache
from pathlib import Path

import numpy as np

# MuJoCo 座標（+X 前、+Y 左、+Z 上）轉成檢視器座標（+X 左、+Y 上、+Z 前）。
# 這是軸的循環置換，行列式為 +1，仍是右手座標系。
MUJOCO_TO_VIEWER = np.array(
    [
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
        [1.0, 0.0, 0.0],
    ]
)

_STL_TRIANGLE = np.dtype([("normal", "<f4", (3,)), ("verts", "<f4", (3, 3)), ("attr", "<u2")])


def quat_wxyz_to_matrix(q) -> np.ndarray:
    """MuJoCo 的四元數（w, x, y, z）轉成 3×3 旋轉矩陣。會先正規化。"""
    q = np.asarray(q, dtype=float)
    norm = np.linalg.norm(q)
    if norm == 0:
        raise ValueError("四元數長度為 0")
    w, x, y, z = q / norm
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def matrix_to_quat_xyzw(m: np.ndarray) -> np.ndarray:
    """3×3 旋轉矩陣轉成 three.js 順序的四元數（x, y, z, w），w ≥ 0。"""
    m = np.asarray(m, dtype=float)
    trace = m[0, 0] + m[1, 1] + m[2, 2]
    if trace > 0:
        s = 2.0 * np.sqrt(trace + 1.0)
        w = 0.25 * s
        x = (m[2, 1] - m[1, 2]) / s
        y = (m[0, 2] - m[2, 0]) / s
        z = (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = 2.0 * np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2])
        w = (m[2, 1] - m[1, 2]) / s
        x = 0.25 * s
        y = (m[0, 1] + m[1, 0]) / s
        z = (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = 2.0 * np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2])
        w = (m[0, 2] - m[2, 0]) / s
        x = (m[0, 1] + m[1, 0]) / s
        y = 0.25 * s
        z = (m[1, 2] + m[2, 1]) / s
    else:
        s = 2.0 * np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1])
        w = (m[1, 0] - m[0, 1]) / s
        x = (m[0, 2] + m[2, 0]) / s
        y = (m[1, 2] + m[2, 1]) / s
        z = 0.25 * s
    q = np.array([x, y, z, w])
    q /= np.linalg.norm(q)
    return -q if q[3] < 0 else q


def is_rotation(m: np.ndarray, tol: float = 1e-6) -> bool:
    return bool(np.allclose(m @ m.T, np.eye(3), atol=tol) and abs(np.linalg.det(m) - 1.0) < tol)


@lru_cache(maxsize=None)
def _read_stl_cached(path: str) -> np.ndarray:
    data = Path(path).read_bytes()
    if len(data) < 84:
        raise ValueError(f"{path}：檔案太小，不是 binary STL")
    (count,) = struct.unpack_from("<I", data, 80)
    expected = 84 + 50 * count
    if len(data) != expected:
        raise ValueError(f"{path}：binary STL 長度不符（宣告 {count} 個三角形，應為 {expected} bytes，實際 {len(data)}）")
    tris = np.frombuffer(data, dtype=_STL_TRIANGLE, count=count, offset=84)
    verts = tris["verts"].astype(np.float64)
    if not np.all(np.isfinite(verts)):
        raise ValueError(f"{path}：含有非有限數值")
    verts.setflags(write=False)
    return verts


def read_binary_stl(path: Path) -> np.ndarray:
    """讀 binary STL，回傳形狀 (三角形數, 3, 3) 的頂點陣列（唯讀，float64，單位同檔案）。"""
    return _read_stl_cached(str(Path(path).resolve()))


def transform_points(points: np.ndarray, rotation: np.ndarray, translation: np.ndarray) -> np.ndarray:
    return points @ rotation.T + translation
