from pathlib import Path

import numpy as np

from viewer_pipeline.geometry import read_binary_stl
from viewer_pipeline.meshes import QUANT_LEVELS, encode_mesh


def test_encode_round_trip_random():
    rng = np.random.default_rng(1)
    tris = rng.uniform(-80, 120, size=(500, 3, 3))
    mesh = encode_mesh(tris)
    err = np.abs(mesh.decode() - tris)
    assert np.all(err <= mesh.step / 2 + 1e-9)
    assert mesh.triangle_count == 500


def test_flat_axis_does_not_divide_by_zero():
    tris = np.array([[[0, 0, 5], [1, 0, 5], [0, 1, 5]]], dtype=float)
    mesh = encode_mesh(tris)
    assert np.allclose(mesh.decode(), tris)


def test_shared_vertices_are_deduplicated():
    a, b, c, d = [0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]
    mesh = encode_mesh(np.array([[a, b, c], [b, d, c]], dtype=float))
    assert len(mesh.vertices) == 4
    assert len(mesh.indices) == 6


def _decode_from_bin(record, blob):
    v = np.frombuffer(blob, dtype="<u2", count=record["vertex_count"] * 3, offset=record["vertex_offset"]).reshape(-1, 3)
    itype = "<u2" if record["index_type"] == "uint16" else "<u4"
    idx = np.frombuffer(blob, dtype=itype, count=record["index_count"], offset=record["index_offset"])
    pos = np.array(record["bbox_min_mm"]) + v.astype(np.float64) * np.array(record["step_mm"])
    return pos, idx


def test_meshes_bin_layout_and_fidelity(scene, result, repo_root):
    """從 meshes.bin 實際解回每個網格，和上游原始 STL 比對。"""
    blob = result.mesh_bin
    records = scene["meshes"]
    assert len(records) == 52
    for key, r in records.items():
        assert r["vertex_offset"] % 4 == 0 and r["index_offset"] % 4 == 0, key
        assert r["vertex_offset"] + r["vertex_count"] * 6 <= len(blob), key
        width = 2 if r["index_type"] == "uint16" else 4
        assert r["index_offset"] + r["index_count"] * width <= len(blob), key
        assert r["index_count"] == r["triangle_count"] * 3, key
        assert r["max_quant_error_mm"] <= 0.002, key

        pos, idx = _decode_from_bin(r, blob)
        assert idx.max() < r["vertex_count"], key
        source = read_binary_stl(repo_root / r["source"]) * (1000.0 if r["source_units"] == "m" else 1.0)
        assert len(source) == r["triangle_count"], key
        err = np.abs(pos[idx.astype(np.int64)].reshape(-1, 3, 3) - source)
        assert err.max() <= np.max(r["step_mm"]) / 2 + 1e-6, key


def test_sources_are_recorded(scene, repo_root):
    import hashlib

    for key, r in scene["meshes"].items():
        path = repo_root / r["source"]
        assert path.is_file(), key
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == r["source_sha256"], key
    assert QUANT_LEVELS == 65535
