"""網格量化與打包成 `meshes.bin`。

每個網格：頂點（毫米）在它自己的外框內量化成 uint16（每軸 65535 階），相同的量化頂點只存一次，
三角形改成索引。還原方式：`位置 = bbox_min + q × step`，每軸誤差最多 step/2。

`meshes.bin` 的版面：各網格依序存放「頂點區（uint16 ×3 ×頂點數）」與「索引區（uint16 或 uint32）」，
每一區的起點都對齊 4 bytes，全部 little-endian。各區的位置寫在 scene.json 的 meshes 欄位。
法向量不存，前端用平面著色（flat shading）。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

QUANT_LEVELS = 65535


@dataclass(frozen=True)
class EncodedMesh:
    vertices: np.ndarray  # (V, 3) uint16
    indices: np.ndarray  # (T*3,) uint16 或 uint32
    bbox_min: np.ndarray  # (3,) 毫米
    step: np.ndarray  # (3,) 毫米／階
    triangle_count: int

    def decode(self) -> np.ndarray:
        """還原成 (T, 3, 3) 的毫米座標（測試用）。"""
        pos = self.bbox_min + self.vertices.astype(np.float64) * self.step
        return pos[self.indices.astype(np.int64)].reshape(-1, 3, 3)

    @property
    def max_error_mm(self) -> float:
        return float(np.max(self.step) / 2)


def encode_mesh(triangles_mm: np.ndarray) -> EncodedMesh:
    tris = np.asarray(triangles_mm, dtype=np.float64)
    if tris.ndim != 3 or tris.shape[1:] != (3, 3) or len(tris) == 0:
        raise ValueError("網格必須是非空的 (T, 3, 3) 陣列")
    pts = tris.reshape(-1, 3)
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    extent = hi - lo
    step = np.where(extent > 0, extent / QUANT_LEVELS, 1.0)
    q = np.rint((pts - lo) / step)
    q = np.clip(q, 0, QUANT_LEVELS).astype(np.uint16)
    unique, inverse = np.unique(q, axis=0, return_inverse=True)
    index_dtype = np.uint16 if len(unique) <= 0xFFFF else np.uint32
    step = np.where(extent > 0, step, 0.0)
    return EncodedMesh(
        vertices=np.ascontiguousarray(unique, dtype="<u2"),
        indices=np.ascontiguousarray(inverse.reshape(-1), dtype=np.dtype(index_dtype).newbyteorder("<")),
        bbox_min=lo,
        step=step,
        triangle_count=len(tris),
    )


class MeshPack:
    """把多個 EncodedMesh 依序寫進同一個 bytes，記錄每一區的位置。"""

    def __init__(self) -> None:
        self._chunks: list[bytes] = []
        self._size = 0
        self.records: dict[str, dict] = {}

    def _append(self, data: bytes) -> int:
        pad = (-self._size) % 4
        if pad:
            self._chunks.append(b"\0" * pad)
            self._size += pad
        offset = self._size
        self._chunks.append(data)
        self._size += len(data)
        return offset

    def add(self, key: str, mesh: EncodedMesh, **meta) -> dict:
        if key in self.records:
            raise ValueError(f"網格 {key!r} 重複加入")
        v_off = self._append(mesh.vertices.tobytes())
        i_off = self._append(mesh.indices.tobytes())
        record = {
            "vertex_offset": v_off,
            "vertex_count": int(len(mesh.vertices)),
            "index_offset": i_off,
            "index_count": int(len(mesh.indices)),
            "index_type": "uint16" if mesh.indices.dtype.itemsize == 2 else "uint32",
            "triangle_count": mesh.triangle_count,
            "bbox_min_mm": [float(v) for v in mesh.bbox_min],
            "step_mm": [float(v) for v in mesh.step],
            "max_quant_error_mm": round(mesh.max_error_mm, 6),
            **meta,
        }
        self.records[key] = record
        return record

    def tobytes(self) -> bytes:
        return b"".join(self._chunks)
