"""爆炸向量：每個零件在「爆炸 100%」時的位移（檢視器座標，毫米）。

兩層位移，沿著運動樹累加：
1. 子組件：每個有關節的 body，沿「自己的中心 − 上一層 body 的中心」方向移 BODY_STEP_MM；
   子孫 body 會跟著累加，所以整條腿會一起往外移，腳再往更外移。
2. 零件：在所屬 body 內，沿「零件中心 − body 中心」方向移 PART_STEP_MM。
同一顆舵機的 5 個網格用舵機整體的中心，所以會一起移動。

中心都用零件外框中心的平均。方向長度太短（< 1e-9）時視為不移動。
"""
from __future__ import annotations

import numpy as np

BODY_STEP_MM = 40.0
PART_STEP_MM = 25.0


def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else np.zeros(3)


def explode_vectors(
    parts: list[dict],
    bodies: dict[str, dict],
) -> dict[str, list[float]]:
    """parts：每項需有 id、body、center（np 陣列）、group（同組共用中心，沒有則為 None）。
    bodies：{名稱: {"parent": 名稱或 None, "origin": np 陣列, "has_joint": bool}}，父 body 必須排在子 body 前面。
    回傳 {part id: [x, y, z]}。"""
    group_center: dict[str, np.ndarray] = {}
    for g in {p["group"] for p in parts if p["group"]}:
        group_center[g] = np.mean([p["center"] for p in parts if p["group"] == g], axis=0)

    def unit_center(p: dict) -> np.ndarray:
        return group_center[p["group"]] if p["group"] else p["center"]

    body_center: dict[str, np.ndarray] = {}
    for name, b in bodies.items():
        members = {p["group"] or p["id"]: unit_center(p) for p in parts if p["body"] == name}
        body_center[name] = np.mean(list(members.values()), axis=0) if members else b["origin"]

    chain: dict[str, np.ndarray] = {}
    for name, b in bodies.items():
        parent = b["parent"]
        base = chain[parent] if parent else np.zeros(3)
        if parent and b["has_joint"]:
            base = base + _unit(body_center[name] - body_center[parent]) * BODY_STEP_MM
        chain[name] = base

    result = {}
    for p in parts:
        offset = chain[p["body"]] + _unit(unit_center(p) - body_center[p["body"]]) * PART_STEP_MM
        result[p["id"]] = [round(float(v), 3) for v in offset]
    return result
