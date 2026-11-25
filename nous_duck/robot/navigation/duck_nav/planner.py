"""規劃：拓撲層（房間 → 門 → 房間）＋柵格層（膨脹後的占據圖上做 A*）。

- 靜態障礙依鴨子外形半徑膨脹；禁區（樓梯、no_go）另外用更大的邊界膨脹，膨脹後的格子**永遠不能走**。
- 動態障礙（深度看到、地圖上沒有的東西）放在會過期的圖層。
- 關著的門：呼叫端把門 id 放進 `closed_doors`，拓撲層就不走那扇門。
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

import numpy as np

from .mapfile import Door, DuckMap


@dataclass
class PlannerConfig:
    #: 鴨子外形半徑（腳掌外緣到中線約 0.11 m、機身長約 0.19 m；取外接圓再加一點）。
    robot_radius_m: float = 0.18
    #: 禁區與樓梯的保留邊界：路徑追蹤偏移＋定位不確定度＋停下距離都要落在這裡面。
    zone_margin_m: float = 0.45
    #: 靠近障礙的軟性代價延伸到多遠。
    soft_radius_m: float = 0.45
    soft_weight: float = 4.0
    #: 動態障礙的膨脹半徑與存活時間。
    #: 鏡頭看不到身體兩側，繞過障礙時只能靠記憶：半徑給大一點、記久一點。
    dynamic_radius_m: float = 0.28
    dynamic_ttl_s: float = 30.0
    #: 障礙點離地圖上的牆多近就當成那面牆（要小於 robot_radius_m：這個範圍本來就不能走）。
    wall_match_m: float = 0.12


class PlanError(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}")
        self.reason = reason  # door_closed / blocked / forbidden / unknown_place
        self.detail = detail


def _dilate(mask: np.ndarray, radius_cells: float) -> np.ndarray:
    r = int(math.ceil(radius_cells))
    out = mask.copy()
    h, w = mask.shape
    for dr in range(-r, r + 1):
        for dc in range(-r, r + 1):
            if (dr or dc) and dr * dr + dc * dc <= radius_cells * radius_cells + 1e-9:
                src = mask[max(0, -dr) : h - max(0, dr), max(0, -dc) : w - max(0, dc)]
                out[max(0, dr) : h - max(0, -dr), max(0, dc) : w - max(0, -dc)] |= src
    return out


class CostMap:
    def __init__(self, duck_map: DuckMap, config: PlannerConfig | None = None):
        self.map = duck_map
        self.cfg = config or PlannerConfig()
        g = duck_map.grid
        self.grid = g
        res = g.resolution
        self.static = _dilate(g.occ, self.cfg.robot_radius_m / res)
        zone = np.zeros_like(g.occ)
        for z in duck_map.zones.values():
            r0, c0 = g.cell(z.rect[0], z.rect[1])
            r1, c1 = g.cell(z.rect[2] - 1e-9, z.rect[3] - 1e-9)
            zone[max(0, r0) : r1 + 1, max(0, c0) : c1 + 1] = True
        self.zone_raw = zone
        self.forbidden = _dilate(zone, self.cfg.zone_margin_m / res)
        # 軟性代價：離障礙越近越高（逐圈膨脹）。
        rings = int(round(self.cfg.soft_radius_m / res))
        soft = np.zeros(g.occ.shape, dtype=float)
        cur = self.static.copy()
        for i in range(rings):
            nxt = _dilate(cur, 1.0)
            soft[nxt & ~cur] = (rings - i) / rings
            cur = nxt
        self.soft = soft
        # 深度看到、落在牆附近的點當成牆本身（定位與量測誤差），不算動態障礙。
        self.near_static = _dilate(g.occ, self.cfg.wall_match_m / res)
        self.dynamic: dict[tuple[int, int], float] = {}  # cell → 到期時間
        self._dyn_mask = np.zeros_like(g.occ)

    # ---------------------------------------------------------------- 動態障礙
    def add_obstacle(self, x: float, y: float, now: float) -> bool:
        """加一個動態障礙點；已經是靜態障礙（地圖上的牆）就不重複加。回傳是否為新的動態障礙。"""
        r, c = self.grid.cell(x, y)
        if not self.grid.inside(r, c) or self.grid.occ[r, c]:
            return False
        if self.near_static[r, c]:
            return False
        new = (r, c) not in self.dynamic
        self.dynamic[(r, c)] = now + self.cfg.dynamic_ttl_s
        if new:
            self._rebuild()
        return new

    def clear_obstacles_in(self, cells: list[tuple[int, int]]) -> None:
        changed = False
        for rc in cells:
            if rc in self.dynamic:
                del self.dynamic[rc]
                changed = True
        if changed:
            self._rebuild()

    def expire(self, now: float) -> None:
        dead = [k for k, t in self.dynamic.items() if t < now]
        if dead:
            for k in dead:
                del self.dynamic[k]
            self._rebuild()

    def _rebuild(self) -> None:
        m = np.zeros_like(self.grid.occ)
        for r, c in self.dynamic:
            m[r, c] = True
        self._dyn_mask = _dilate(m, self.cfg.dynamic_radius_m / self.grid.resolution) if self.dynamic else m

    # ---------------------------------------------------------------- 查詢
    def blocked(self, r: int, c: int) -> bool:
        return (not self.grid.inside(r, c)) or bool(self.static[r, c] or self.forbidden[r, c] or self._dyn_mask[r, c])

    def blocked_xy(self, x: float, y: float) -> bool:
        return self.blocked(*self.grid.cell(x, y))

    def forbidden_xy(self, x: float, y: float) -> bool:
        r, c = self.grid.cell(x, y)
        return self.grid.inside(r, c) and bool(self.forbidden[r, c])

    def dynamic_xy(self, x: float, y: float) -> bool:
        r, c = self.grid.cell(x, y)
        return self.grid.inside(r, c) and bool(self._dyn_mask[r, c])

    def door_passable(self, door: Door) -> bool:
        """門口有沒有一條穿得過去的直線（考慮膨脹後的靜態與動態障礙）。"""
        cx, cy = door.center
        res = self.grid.resolution
        n = int(door.width_m / 2 / res)
        for k in range(-n, n + 1):
            u = k * res
            if door.axis == "x":
                a, b = (cx + u, cy - 0.3), (cx + u, cy + 0.3)
            else:
                a, b = (cx - 0.3, cy + u), (cx + 0.3, cy + u)
            if self.line_free(a, b):
                return True
        return False

    def nearest_free(self, x: float, y: float, max_m: float = 0.5) -> tuple[int, int] | None:
        r0, c0 = self.grid.cell(x, y)
        if not self.blocked(r0, c0):
            return (r0, c0)
        n = int(max_m / self.grid.resolution)
        best, best_d = None, 1e9
        for dr in range(-n, n + 1):
            for dc in range(-n, n + 1):
                d = dr * dr + dc * dc
                if d < best_d and d <= n * n and not self.blocked(r0 + dr, c0 + dc):
                    best, best_d = (r0 + dr, c0 + dc), d
        return best

    def line_free(self, a, b) -> bool:
        n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / (self.grid.resolution * 0.5)))
        for i in range(n + 1):
            t = i / n
            if self.blocked_xy(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t):
                return False
        return True

    def line_cost_ok(self, a, b, limit: float = 0.5) -> bool:
        """線段上有沒有太貼近障礙（軟性代價超過 limit）；路徑拉直時用，避免貼牆走。"""
        n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / (self.grid.resolution * 0.5)))
        for i in range(n + 1):
            t = i / n
            r, c = self.grid.cell(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            if self.blocked(r, c) or self.soft[r, c] > limit:
                return False
        return True


_NEIGH = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0), (1, 1, math.sqrt(2)), (1, -1, math.sqrt(2)), (-1, 1, math.sqrt(2)), (-1, -1, math.sqrt(2))]


def astar(cm: CostMap, start_xy, goal_xy) -> list[tuple[float, float]] | None:
    """柵格 A*（8 向）。起點落在膨脹區時取最近的可走格。回傳地圖座標的路點，找不到回傳 None。"""
    g = cm.grid
    s = cm.nearest_free(*start_xy)
    t = cm.nearest_free(*goal_xy, max_m=0.3)
    if s is None or t is None:
        return None
    open_ = [(0.0, 0.0, s, None)]
    came: dict[tuple[int, int], tuple[int, int] | None] = {}
    best = {s: 0.0}
    w = cm.cfg.soft_weight
    while open_:
        _, cost, cur, parent = heapq.heappop(open_)
        if cur in came:
            continue
        came[cur] = parent
        if cur == t:
            break
        for dr, dc, step in _NEIGH:
            nb = (cur[0] + dr, cur[1] + dc)
            if nb in came or cm.blocked(*nb):
                continue
            if dr and dc and (cm.blocked(cur[0] + dr, cur[1]) or cm.blocked(cur[0], cur[1] + dc)):
                continue  # 不切過角落
            nc = cost + step * (1.0 + w * cm.soft[nb])
            if nc < best.get(nb, 1e18):
                best[nb] = nc
                h = math.hypot(nb[0] - t[0], nb[1] - t[1])
                heapq.heappush(open_, (nc + h, nc, nb, cur))
    if t not in came:
        return None
    cells = []
    cur = t
    while cur is not None:
        cells.append(cur)
        cur = came[cur]
    cells.reverse()
    pts = [g.center(r, c) for r, c in cells]
    pts[-1] = tuple(goal_xy) if not cm.blocked_xy(*goal_xy) else pts[-1]
    return simplify(cm, pts)


def simplify(cm: CostMap, pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """視線拉直：能直線到達、而且不會貼牆的路點就跳過中間的點。"""
    if len(pts) <= 2:
        return pts
    out = [pts[0]]
    i = 0
    while i < len(pts) - 1:
        j = len(pts) - 1
        while j > i + 1 and not cm.line_cost_ok(pts[i], pts[j]):
            j -= 1
        out.append(pts[j])
        i = j
    return out


def topo_route(duck_map: DuckMap, room_from: str, room_to: str, closed_doors: set[str] = frozenset()) -> list[Door] | None:
    """房間到房間要經過哪些門（廣度優先，門數最少）。走不到回傳 None。"""
    if room_from == room_to:
        return []
    prev: dict[str, tuple[str, Door]] = {}
    queue, seen = [room_from], {room_from}
    while queue:
        cur = queue.pop(0)
        for other, door in duck_map.neighbors(cur):
            if door.id in closed_doors or other in seen:
                continue
            seen.add(other)
            prev[other] = (cur, door)
            if other == room_to:
                route = []
                node = room_to
                while node != room_from:
                    node, d = prev[node]
                    route.append(d)
                return route[::-1]
            queue.append(other)
    return None


@dataclass
class Plan:
    points: list[tuple[float, float]]
    doors: list[str]
    length_m: float


def plan_path(cm: CostMap, start_xy, goal_xy, closed_doors: set[str] = frozenset()) -> Plan:
    """拓撲層決定經過哪些門，柵格層逐段規劃。失敗丟 `PlanError`（原因代碼）。"""
    m = cm.map
    if cm.forbidden_xy(*goal_xy):
        raise PlanError("forbidden", "目的地在禁區的保留邊界內")
    room_a = m.room_at(*start_xy)
    room_b = m.room_at(*goal_xy)
    doors: list[Door] = []
    if room_a and room_b:
        route = topo_route(m, room_a, room_b, closed_doors)
        if route is None:
            open_route = topo_route(m, room_a, room_b)
            raise PlanError("door_closed" if open_route is not None else "blocked", f"{room_a} → {room_b}")
        doors = route
    pts: list[tuple[float, float]] = [tuple(start_xy)]
    # 已經站在門口的門不用再當路點（否則會先折回門中心）。
    waypoints = [d.center for d in doors if math.hypot(d.center[0] - start_xy[0], d.center[1] - start_xy[1]) > 0.35] + [tuple(goal_xy)]
    cur = tuple(start_xy)
    for wp in waypoints:
        leg = astar(cm, cur, wp)
        if leg is None:
            raise PlanError("blocked", f"柵格上找不到路到 ({wp[0]:.2f}, {wp[1]:.2f})")
        pts += leg[1:]
        cur = leg[-1]
    pts = simplify(cm, pts)
    length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))
    return Plan(pts, [d.id for d in doors], length)
