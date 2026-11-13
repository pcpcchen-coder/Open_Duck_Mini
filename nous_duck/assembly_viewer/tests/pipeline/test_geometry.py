import struct

import numpy as np
import pytest

from viewer_pipeline.geometry import (
    MUJOCO_TO_VIEWER,
    is_rotation,
    matrix_to_quat_xyzw,
    quat_wxyz_to_matrix,
    read_binary_stl,
)


def quat_xyzw_to_matrix(q):
    """three.js 的 Quaternion → Matrix4 公式（獨立實作，用來檢查輸出順序）。"""
    x, y, z, w = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ]
    )


def test_quarter_turn_about_z():
    m = quat_wxyz_to_matrix([np.cos(np.pi / 4), 0, 0, np.sin(np.pi / 4)])
    assert np.allclose(m @ [1, 0, 0], [0, 1, 0])
    assert np.allclose(m @ [0, 1, 0], [-1, 0, 0])


def test_quaternion_round_trip_random():
    rng = np.random.default_rng(0)
    for _ in range(500):
        q = rng.normal(size=4)
        m = quat_wxyz_to_matrix(q)
        assert is_rotation(m)
        assert np.allclose(quat_xyzw_to_matrix(matrix_to_quat_xyzw(m)), m, atol=1e-12)


@pytest.mark.parametrize("angle", [0.0, np.pi, -np.pi / 2])
def test_quaternion_edge_angles(angle):
    for axis in np.eye(3):
        q = np.r_[np.cos(angle / 2), np.sin(angle / 2) * axis]
        m = quat_wxyz_to_matrix(q)
        out = matrix_to_quat_xyzw(m)
        assert out[3] >= 0
        assert np.allclose(quat_xyzw_to_matrix(out), m, atol=1e-12)


def test_viewer_frame_mapping():
    assert is_rotation(MUJOCO_TO_VIEWER)
    # MuJoCo：+X 前、+Y 左、+Z 上 → 檢視器：+Z 前、+X 左、+Y 上
    assert np.allclose(MUJOCO_TO_VIEWER @ [1, 0, 0], [0, 0, 1])
    assert np.allclose(MUJOCO_TO_VIEWER @ [0, 1, 0], [1, 0, 0])
    assert np.allclose(MUJOCO_TO_VIEWER @ [0, 0, 1], [0, 1, 0])


def test_zero_quaternion_rejected():
    with pytest.raises(ValueError):
        quat_wxyz_to_matrix([0, 0, 0, 0])


def _write_stl(path, triangles, declared=None):
    triangles = np.asarray(triangles, dtype="<f4")
    count = len(triangles) if declared is None else declared
    body = b"".join(struct.pack("<3f", 0, 0, 0) + t.tobytes() + b"\0\0" for t in triangles)
    path.write_bytes(b"\0" * 80 + struct.pack("<I", count) + body)


def test_read_binary_stl(tmp_path):
    tri = [[[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 0, 1], [1, 0, 1], [0, 1, 1]]]
    path = tmp_path / "two.stl"
    _write_stl(path, tri)
    out = read_binary_stl(path)
    assert out.shape == (2, 3, 3)
    assert np.allclose(out, tri)


def test_read_binary_stl_rejects_wrong_length(tmp_path):
    path = tmp_path / "bad.stl"
    _write_stl(path, [[[0, 0, 0], [1, 0, 0], [0, 1, 0]]], declared=2)
    with pytest.raises(ValueError, match="長度不符"):
        read_binary_stl(path)
