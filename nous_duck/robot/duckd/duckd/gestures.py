"""動作庫（ADR-0011 的 A 類）：具名動作的定義檔、載入時檢查、關鍵格播放。

- 定義檔：`duckd/library/<id>.json`，鴨子本機的格式，不屬於 duck-link；Nous 只看得到名稱。
- **載入時檢查，不偷偷夾限**：任何關鍵格超出允許範圍、插值後超過角速度上限、結尾沒回到中立，
  整個動作拒絕載入。仲裁器在執行時仍會夾限，那是最後一關。
- 目前只有 `head` 軌。`vel`、`antennas`、`cues` 軌還沒實作：定義檔出現就拒絕載入，不假裝會做。
- 驗證等級（`verification.level`）：`none`／`sim`／`real`。只有 `real` 且 `hardware_profile` 符合
  目前機身設定的動作才列給 Nous（ADR-0011 §2.6）；其餘要加開發旗標才會列出。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .limits import HEAD_JOINTS, Limits

LIBRARY_DIR = Path(__file__).resolve().parent / "library"
ID_RE = re.compile(r"^[a-z0-9_]{1,48}$")
MAX_DURATION_S = 10.0
SAMPLE_DT = 0.02

# ADR-0011 §2.3 的初版允許範圍（訓練範圍與上游手把範圍的交集；neck_pitch 固定 0）
GESTURE_HEAD_RANGE: dict[str, tuple[float, float]] = {
    "neck_pitch": (0.0, 0.0),
    "head_pitch": (-0.78, 0.3),
    "head_yaw": (-0.5, 0.5),
    "head_roll": (-0.5, 0.5),
}


class GestureError(ValueError):
    pass


def min_jerk(k: float) -> float:
    k = 0.0 if k < 0 else 1.0 if k > 1 else k
    return k * k * k * (10 - 15 * k + 6 * k * k)


@dataclass(frozen=True)
class Gesture:
    id: str
    version: int
    description: str
    interpolation: str
    duration_s: float
    head: dict[str, tuple[tuple[float, float], ...]]  # 關節 -> ((t, 值), ...)
    requires: tuple[str, ...]
    verification_level: str
    hardware_profile: str | None
    record: str | None

    def sample(self, t: float) -> dict[str, float]:
        """時間 t（秒，從動作開始算）的頭部目標。超過結尾就停在最後一格。"""
        out = {}
        for joint, keys in self.head.items():
            if t <= keys[0][0]:
                out[joint] = keys[0][1]
                continue
            if t >= keys[-1][0]:
                out[joint] = keys[-1][1]
                continue
            for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
                if t0 <= t <= t1:
                    k = (t - t0) / (t1 - t0)
                    if self.interpolation == "min_jerk":
                        k = min_jerk(k)
                    out[joint] = v0 + (v1 - v0) * k
                    break
        return out

    def peak_speed(self) -> float:
        peak, prev, t = 0.0, self.sample(0.0), SAMPLE_DT
        while t <= self.duration_s + 1e-9:
            cur = self.sample(t)
            peak = max(peak, max(abs(cur[j] - prev[j]) for j in cur) / SAMPLE_DT)
            prev, t = cur, t + SAMPLE_DT
        return peak


def parse_gesture(data: dict, limits: Limits) -> Gesture:
    """檢查並建立一個動作。不合格就丟 GestureError（原因用中文，給部署的人看）。"""
    gid = data.get("id")
    if not isinstance(gid, str) or not ID_RE.match(gid):
        raise GestureError(f"id 不合格：{gid!r}")
    if data.get("category") != "A":
        raise GestureError(f"{gid}：只支援 A 類（編排）")
    interpolation = data.get("interpolation")
    if interpolation not in ("linear", "min_jerk"):
        raise GestureError(f"{gid}：interpolation 只能是 linear 或 min_jerk")
    if data.get("allowed_modes") != ["standing"] and "head" in data.get("tracks", {}):
        raise GestureError(f"{gid}：含 head 軌的動作 allowed_modes 只能是 [\"standing\"]")
    tracks = data.get("tracks")
    if not isinstance(tracks, dict) or set(tracks) - {"head"}:
        raise GestureError(f"{gid}：目前只實作 head 軌（出現了 {sorted(set(tracks or {}) - {'head'})}）")
    head_raw = tracks.get("head")
    if not isinstance(head_raw, dict) or not head_raw:
        raise GestureError(f"{gid}：沒有 head 軌")
    head: dict[str, tuple[tuple[float, float], ...]] = {}
    duration = 0.0
    for joint, keys in head_raw.items():
        if joint not in HEAD_JOINTS:
            raise GestureError(f"{gid}：沒有這個頭部關節 {joint}")
        if not isinstance(keys, list) or len(keys) < 2:
            raise GestureError(f"{gid}.{joint}：至少要兩個關鍵格")
        lo = max(GESTURE_HEAD_RANGE[joint][0], limits.head_range[joint][0])
        hi = min(GESTURE_HEAD_RANGE[joint][1], limits.head_range[joint][1])
        prev_t = None
        parsed = []
        for key in keys:
            if not (isinstance(key, list) and len(key) == 2 and all(isinstance(x, (int, float)) for x in key)):
                raise GestureError(f"{gid}.{joint}：關鍵格要是 [t, 值]")
            t, v = float(key[0]), float(key[1])
            if prev_t is None and t != 0.0:
                raise GestureError(f"{gid}.{joint}：第一格要在 t=0")
            if prev_t is not None and t <= prev_t:
                raise GestureError(f"{gid}.{joint}：時間要遞增")
            if not lo - 1e-9 <= v <= hi + 1e-9:
                raise GestureError(f"{gid}.{joint}：{v} 超出允許範圍 {lo:.3f}～{hi:.3f}")
            parsed.append((t, v))
            prev_t = t
        if parsed[0][1] != 0.0 or parsed[-1][1] != 0.0:
            raise GestureError(f"{gid}.{joint}：要從中立（0）開始、回到中立結束")
        head[joint] = tuple(parsed)
        duration = max(duration, parsed[-1][0])
    if duration > MAX_DURATION_S:
        raise GestureError(f"{gid}：長度 {duration:.1f} s 超過 {MAX_DURATION_S:.0f} s")
    ver = data.get("verification") or {}
    level = ver.get("level", "none")
    if level not in ("none", "sim", "real"):
        raise GestureError(f"{gid}：verification.level 不對")
    g = Gesture(
        id=gid,
        version=int(data.get("version", 1)),
        description=str(data.get("description", "")),
        interpolation=interpolation,
        duration_s=duration,
        head=head,
        requires=tuple(data.get("requires", [])),
        verification_level=level,
        hardware_profile=ver.get("hardware_profile"),
        record=ver.get("record"),
    )
    peak = g.peak_speed()
    if peak > limits.head_max_speed * 1.001:
        raise GestureError(f"{gid}：插值後最快 {peak:.3f} rad/s，超過上限 {limits.head_max_speed:.3f} rad/s")
    return g


class GestureLibrary:
    def __init__(self, limits: Limits, directory: Path = LIBRARY_DIR):
        self.gestures: dict[str, Gesture] = {}
        self.rejected: dict[str, str] = {}  # 檔名 -> 拒絕原因
        for path in sorted(Path(directory).glob("*.json")):
            try:
                g = parse_gesture(json.loads(path.read_text(encoding="utf-8")), limits)
                if g.id != path.stem:
                    raise GestureError(f"id {g.id} 和檔名不一致")
                self.gestures[g.id] = g
            except (GestureError, json.JSONDecodeError, KeyError, TypeError) as exc:
                self.rejected[path.name] = str(exc)

    def listed(self, hardware_profile: str, allow_unverified: bool, have: frozenset[str] = frozenset()) -> list[str]:
        """可以列給 Nous 的動作名稱。"""
        out = []
        for g in self.gestures.values():
            if any(r not in have for r in g.requires):
                continue
            verified = g.verification_level == "real" and g.hardware_profile == hardware_profile
            if verified or allow_unverified:
                out.append(g.id)
        return sorted(out)


class GesturePlayer:
    """一次只播一個動作。時間由呼叫端傳入。"""

    def __init__(self) -> None:
        self.gesture: Gesture | None = None
        self.request_id: str | None = None
        self.t0 = 0.0
        self.clamped = False

    @property
    def active(self) -> bool:
        return self.gesture is not None

    def start(self, gesture: Gesture, request_id: str, now: float) -> None:
        self.gesture, self.request_id, self.t0, self.clamped = gesture, request_id, now, False

    def sample(self, now: float) -> tuple[dict[str, float], bool]:
        """回傳（頭部目標, 是否播完）。"""
        assert self.gesture is not None
        t = now - self.t0
        return self.gesture.sample(t), t >= self.gesture.duration_s

    def finish(self) -> tuple[str, str | None, bool]:
        gid, rid, clamped = self.gesture.id, self.request_id, self.clamped
        self.gesture = self.request_id = None
        return gid, rid, clamped
