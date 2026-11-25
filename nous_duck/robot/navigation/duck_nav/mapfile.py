"""地圖檔格式 `duck-map` 第 1 版：載入、驗證、查詢。

一個 JSON 檔，內容（欄位名稱固定為英文）：

| 欄位 | 內容 |
|---|---|
| `format`、`format_version` | 固定 `"duck-map"`、`1`；讀到不支援的版本就拒絕 |
| `map_version` | 這張地圖的版本字串；鴨子與 Nous 用同一版（ADR-0002 §3.2） |
| `synthetic` | `true`＝合成的 fixture。真的家的地圖**不進 repo**，只存在 Nous 與鴨子本機 |
| `bounds` | `[x0, y0, x1, y1]`（m） |
| `grid` | 占據柵格：`resolution_m`、`origin`（左下角格子的角落）、`width`、`height`、`rows`（由下往上，每列一個字串，`#`＝占據、`.`＝可走） |
| `rooms` | 拓撲節點：`id`、`rect` |
| `doors` | 拓撲邊：`id`、`between`（兩個房間 id）、`center`、`width_m`、`axis`（門板沿哪個軸：`x` 或 `y`） |
| `places` | 可以當目的地的地點：`id`、`room`、`pose`（`[x, y]` 或 `[x, y, yaw]`）。每個房間自動有一個同名地點 |
| `zones` | 禁區：`id`、`kind`（`stairs`／`no_go`）、`rect`。**樓梯必填**：沒有樓梯要寫 `"no_stairs": true` |
| `tags` | AprilTag：`id`、`family`（`tag36h11`）、`size_m`（黑框邊長）、`pose`（`x, y, z, yaw`；yaw 是標籤面朝的方向） |
| `dock` | 充電座：`place`、`pose`（`[x, y, yaw]`：停好時鴨子背後觸點面的位置，yaw 是鴨子面朝的方向）、`tag_id`、`staging_distance_m` |
| `structures` | （選填）向量圖層：牆、家具等長方體 `id`、`kind`、`rect`、`height_m`。模擬用它蓋場景、算遮擋；柵格由它產生 |

地點、房間、門、禁區的 `id` 只能是 `^[a-z0-9_]{1,48}$`（duck-link 的 `name`），不放真實姓名或顯示名稱；
顯示名稱的對照只存在 Nous 本機（`CLAUDE.md` 隱私規則）。
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .geometry import Pose2D, point_in_rect

FORMAT = "duck-map"
FORMAT_VERSION = 1
ID_RE = re.compile(r"^[a-z0-9_]{1,48}$")
ZONE_KINDS = ("stairs", "no_go")
TAG_FAMILY = "tag36h11"


class MapError(ValueError):
    """地圖檔不合格。訊息列出所有問題。"""


@dataclass(frozen=True)
class Room:
    id: str
    rect: tuple[float, float, float, float]

    @property
    def center(self) -> tuple[float, float]:
        return ((self.rect[0] + self.rect[2]) / 2, (self.rect[1] + self.rect[3]) / 2)


@dataclass(frozen=True)
class Door:
    id: str
    between: tuple[str, str]
    center: tuple[float, float]
    width_m: float
    axis: str  # 門板沿 "x" 或 "y"

    def rect(self, depth: float = 0.2) -> tuple[float, float, float, float]:
        """門口開口的長方形（沿門板方向寬 width_m，垂直方向厚 depth）。"""
        cx, cy = self.center
        if self.axis == "x":
            return (cx - self.width_m / 2, cy - depth / 2, cx + self.width_m / 2, cy + depth / 2)
        return (cx - depth / 2, cy - self.width_m / 2, cx + depth / 2, cy + self.width_m / 2)


@dataclass(frozen=True)
class Place:
    id: str
    room: str
    x: float
    y: float
    yaw: float | None = None


@dataclass(frozen=True)
class Zone:
    id: str
    kind: str
    rect: tuple[float, float, float, float]


@dataclass(frozen=True)
class Tag:
    id: int
    size_m: float
    x: float
    y: float
    z: float
    yaw: float
    family: str = TAG_FAMILY

    @property
    def pose(self) -> Pose2D:
        return Pose2D(self.x, self.y, self.yaw)


@dataclass(frozen=True)
class Dock:
    place: str
    pose: Pose2D
    tag_id: int
    staging_distance_m: float


@dataclass(frozen=True)
class Structure:
    id: str
    kind: str
    rect: tuple[float, float, float, float]
    height_m: float


@dataclass
class Grid:
    resolution: float
    origin: tuple[float, float]
    occ: np.ndarray  # (height, width) bool，occ[row, col]；row 0 是最下面那一列

    @property
    def shape(self) -> tuple[int, int]:
        return self.occ.shape

    def cell(self, x: float, y: float) -> tuple[int, int]:
        return (int(math.floor((y - self.origin[1]) / self.resolution)), int(math.floor((x - self.origin[0]) / self.resolution)))

    def center(self, row: int, col: int) -> tuple[float, float]:
        return (self.origin[0] + (col + 0.5) * self.resolution, self.origin[1] + (row + 0.5) * self.resolution)

    def inside(self, row: int, col: int) -> bool:
        return 0 <= row < self.occ.shape[0] and 0 <= col < self.occ.shape[1]

    def occupied(self, x: float, y: float) -> bool:
        r, c = self.cell(x, y)
        return not self.inside(r, c) or bool(self.occ[r, c])


@dataclass
class DuckMap:
    map_version: str
    synthetic: bool
    bounds: tuple[float, float, float, float]
    grid: Grid
    rooms: dict[str, Room]
    doors: dict[str, Door]
    places: dict[str, Place]
    zones: dict[str, Zone]
    tags: dict[int, Tag]
    dock: Dock | None
    structures: list[Structure] = field(default_factory=list)

    # ------------------------------------------------------------ 查詢
    def room_at(self, x: float, y: float) -> str | None:
        for r in self.rooms.values():
            if point_in_rect(x, y, r.rect):
                return r.id
        return None

    def zone_at(self, x: float, y: float, margin: float = 0.0) -> Zone | None:
        for z in self.zones.values():
            if point_in_rect(x, y, z.rect, margin):
                return z
        return None

    def nearest_place(self, x: float, y: float, same_room: bool = True) -> str | None:
        room = self.room_at(x, y)
        best, best_d = None, float("inf")
        for p in self.places.values():
            if same_room and room is not None and p.room != room:
                continue
            d = math.hypot(p.x - x, p.y - y)
            if d < best_d:
                best, best_d = p.id, d
        return best

    def neighbors(self, room: str) -> list[tuple[str, Door]]:
        out = []
        for d in self.doors.values():
            if room in d.between:
                other = d.between[0] if d.between[1] == room else d.between[1]
                out.append((other, d))
        return out

    def dock_base_pose(self, base_to_contact_m: float, extra_m: float = 0.0) -> Pose2D:
        """停好（或離充電座 extra_m）時機身原點的位姿。"""
        assert self.dock is not None
        d = self.dock.pose
        k = base_to_contact_m + extra_m
        return Pose2D(d.x + k * math.cos(d.yaw), d.y + k * math.sin(d.yaw), d.yaw)

    def places_summary(self) -> list[dict]:
        """`places` 指令要的資料：只有 ID 與所屬房間，不含座標。"""
        return [{"place": p.id, "room": p.room, "is_dock": bool(self.dock and self.dock.place == p.id)} for p in self.places.values()]


# ---------------------------------------------------------------- 載入與驗證
def _rect(v, errs: list[str], what: str) -> tuple[float, float, float, float]:
    try:
        x0, y0, x1, y1 = (float(a) for a in v)
    except Exception:
        errs.append(f"{what}: rect 要是 [x0, y0, x1, y1]")
        return (0.0, 0.0, 0.0, 0.0)
    if not (x1 > x0 and y1 > y0):
        errs.append(f"{what}: rect 的 x1、y1 要大於 x0、y0")
    return (x0, y0, x1, y1)


def _check_id(v, errs: list[str], what: str) -> str:
    if not isinstance(v, str) or not ID_RE.match(v):
        errs.append(f"{what}: id {v!r} 不符合 ^[a-z0-9_]{{1,48}}$")
        return str(v)
    return v


def parse_map(doc: dict) -> DuckMap:
    """把 JSON 物件轉成 `DuckMap`；不合格就丟 `MapError`，訊息列出全部問題。"""
    errs: list[str] = []
    if doc.get("format") != FORMAT:
        raise MapError(f"format 要是 {FORMAT!r}")
    if doc.get("format_version") != FORMAT_VERSION:
        raise MapError(f"不支援的 format_version {doc.get('format_version')!r}（只支援 {FORMAT_VERSION}）")
    for key in ("map_version", "synthetic", "bounds", "grid", "rooms", "doors", "places", "zones", "tags"):
        if key not in doc:
            errs.append(f"缺欄位 {key}")
    if errs:
        raise MapError("；".join(errs))
    if not isinstance(doc["synthetic"], bool):
        errs.append("synthetic 要是布林值")
    bounds = _rect(doc["bounds"], errs, "bounds")

    g = doc["grid"]
    rows = g.get("rows", [])
    w, h, res = int(g.get("width", 0)), int(g.get("height", 0)), float(g.get("resolution_m", 0))
    if res <= 0:
        errs.append("grid.resolution_m 要大於 0")
        res = 1.0
    if len(rows) != h or any(len(r) != w for r in rows):
        errs.append(f"grid.rows 的大小跟 width×height（{w}×{h}）不符")
        occ = np.zeros((max(h, 1), max(w, 1)), dtype=bool)
    else:
        if any(set(r) - {"#", "."} for r in rows):
            errs.append("grid.rows 只能用 '#' 與 '.'")
        occ = np.array([[ch == "#" for ch in r] for r in rows], dtype=bool).reshape(h, w)
    origin = tuple(float(v) for v in g.get("origin", (0, 0)))
    grid = Grid(res, origin, occ)

    rooms: dict[str, Room] = {}
    for r in doc["rooms"]:
        rid = _check_id(r.get("id"), errs, "room")
        if rid in rooms:
            errs.append(f"room {rid} 重複")
        rooms[rid] = Room(rid, _rect(r.get("rect"), errs, f"room {rid}"))

    doors: dict[str, Door] = {}
    for d in doc["doors"]:
        did = _check_id(d.get("id"), errs, "door")
        between = tuple(d.get("between", ()))
        if len(between) != 2 or any(b not in rooms for b in between) or between[0] == between[1]:
            errs.append(f"door {did}: between 要是兩個不同、存在的房間")
            between = (str(between[0]) if between else "", str(between[-1]) if between else "")
        if d.get("axis") not in ("x", "y"):
            errs.append(f"door {did}: axis 要是 'x' 或 'y'")
        width = float(d.get("width_m", 0))
        if width <= 0:
            errs.append(f"door {did}: width_m 要大於 0")
        if did in doors:
            errs.append(f"door {did} 重複")
        c = d.get("center", (0, 0))
        doors[did] = Door(did, between, (float(c[0]), float(c[1])), width, d.get("axis", "x"))

    zones: dict[str, Zone] = {}
    for z in doc["zones"]:
        zid = _check_id(z.get("id"), errs, "zone")
        if z.get("kind") not in ZONE_KINDS:
            errs.append(f"zone {zid}: kind 要是 {ZONE_KINDS}")
        if zid in zones:
            errs.append(f"zone {zid} 重複")
        zones[zid] = Zone(zid, z.get("kind", "no_go"), _rect(z.get("rect"), errs, f"zone {zid}"))
    has_stairs = any(z.kind == "stairs" for z in zones.values())
    if not has_stairs and doc.get("no_stairs") is not True:
        errs.append("沒有 stairs 禁區：樓梯必填，確定沒有樓梯要寫 \"no_stairs\": true")
    if has_stairs and doc.get("no_stairs") is True:
        errs.append("no_stairs 為 true 但 zones 裡有 stairs")

    places: dict[str, Place] = {}
    for rid, r in rooms.items():
        places[rid] = Place(rid, rid, r.center[0], r.center[1])
    for p in doc["places"]:
        pid = _check_id(p.get("id"), errs, "place")
        pose = p.get("pose", ())
        if len(pose) not in (2, 3):
            errs.append(f"place {pid}: pose 要是 [x, y] 或 [x, y, yaw]")
            continue
        if p.get("room") not in rooms:
            errs.append(f"place {pid}: room {p.get('room')!r} 不存在")
        places[pid] = Place(pid, p.get("room", ""), float(pose[0]), float(pose[1]), float(pose[2]) if len(pose) == 3 else None)

    tags: dict[int, Tag] = {}
    for t in doc["tags"]:
        tid = t.get("id")
        if not isinstance(tid, int) or isinstance(tid, bool) or not 0 <= tid <= 586:
            errs.append(f"tag id {tid!r} 要是 0～586 的整數（tag36h11）")
            continue
        if tid in tags:
            errs.append(f"tag {tid} 重複")
        if t.get("family", TAG_FAMILY) != TAG_FAMILY:
            errs.append(f"tag {tid}: 只支援 {TAG_FAMILY}")
        ps = t.get("pose", {})
        try:
            tags[tid] = Tag(tid, float(t["size_m"]), float(ps["x"]), float(ps["y"]), float(ps["z"]), float(ps["yaw"]))
        except Exception:
            errs.append(f"tag {tid}: 要有 size_m 與 pose.x/y/z/yaw")
            continue
        if tags[tid].size_m <= 0:
            errs.append(f"tag {tid}: size_m 要大於 0")
        if not point_in_rect(tags[tid].x, tags[tid].y, bounds, 0.01):
            errs.append(f"tag {tid}: 位置在 bounds 外")

    dock = None
    if doc.get("dock") is not None:
        dd = doc["dock"]
        ps = dd.get("pose", ())
        if dd.get("place") not in places:
            errs.append("dock.place 不在 places 裡")
        if dd.get("tag_id") not in tags:
            errs.append("dock.tag_id 不在 tags 裡")
        if len(ps) != 3:
            errs.append("dock.pose 要是 [x, y, yaw]")
        else:
            dock = Dock(dd.get("place", ""), Pose2D(float(ps[0]), float(ps[1]), float(ps[2])), dd.get("tag_id", -1), float(dd.get("staging_distance_m", 0.5)))
            if not 0.2 <= dock.staging_distance_m <= 1.5:
                errs.append("dock.staging_distance_m 要在 0.2～1.5 m")

    structures = []
    for s in doc.get("structures", []):
        sid = _check_id(s.get("id"), errs, "structure")
        structures.append(Structure(sid, str(s.get("kind", "wall")), _rect(s.get("rect"), errs, f"structure {sid}"), float(s.get("height_m", 1.0))))

    m = DuckMap(str(doc["map_version"]), bool(doc["synthetic"]), bounds, grid, rooms, doors, places, zones, tags, dock, structures)

    # 幾何一致性。
    if not errs:
        for p in places.values():
            is_dock = dock is not None and dock.place == p.id
            if grid.occupied(p.x, p.y) and not is_dock:
                errs.append(f"place {p.id} 落在占據格上")
            if m.zone_at(p.x, p.y) is not None:
                errs.append(f"place {p.id} 落在禁區 {m.zone_at(p.x, p.y).id} 裡")
            if p.room in rooms and not point_in_rect(p.x, p.y, rooms[p.room].rect, 1e-6):
                errs.append(f"place {p.id} 不在房間 {p.room} 的範圍內")
        for d in doors.values():
            if grid.occupied(*d.center):
                errs.append(f"door {d.id} 的中心落在占據格上（門口應該是空的）")
    if errs:
        raise MapError("；".join(errs))
    return m


def load_map(path: str | Path) -> DuckMap:
    return parse_map(json.loads(Path(path).read_text(encoding="utf-8")))


def rasterize(bounds, resolution: float, rects) -> list[str]:
    """把長方形清單畫成柵格的 `rows`（由下往上）。格子中心落在任何長方形裡就算占據；bounds 外圍一圈也占據。"""
    x0, y0, x1, y1 = bounds
    w = int(round((x1 - x0) / resolution))
    h = int(round((y1 - y0) / resolution))
    occ = np.zeros((h, w), dtype=bool)
    xs = x0 + (np.arange(w) + 0.5) * resolution
    ys = y0 + (np.arange(h) + 0.5) * resolution
    for rx0, ry0, rx1, ry1 in rects:
        cm = (xs >= rx0) & (xs <= rx1)
        rm = (ys >= ry0) & (ys <= ry1)
        occ[np.ix_(rm, cm)] = True
    return ["".join("#" if v else "." for v in row) for row in occ]
