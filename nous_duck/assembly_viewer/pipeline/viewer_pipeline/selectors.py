"""bom.yaml 與 steps.yaml 共用的零件選擇器。

    {servos: all} / {servos: [24, 14]}       舵機（每顆含 5 個網格，算一個單位）
    {mesh: foot_top}                          這種 CAD 網格的所有實例（每個實例一個單位）
    {mesh: leg_spacer, body: [a, b]}          只取指定 body 裡的實例
    {print_only: all} / {print_only: [key]}   CAD 沒有擺放位置的列印件

每個選擇器至少要選到一個零件；名稱打錯一律報錯，不默默略過。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PartRef:
    id: str
    mesh: str
    body: str
    servo_id: int | None


class Resolver:
    def __init__(self, parts: list[PartRef], cad_meshes: set[str], bodies: set[str], print_only_keys: set[str]):
        self.parts = parts
        self.cad_meshes = cad_meshes
        self.bodies = bodies
        self.print_only_keys = print_only_keys
        self.servo_ids = sorted({p.servo_id for p in parts if p.servo_id is not None})

    def resolve(self, selector: dict, where: str) -> list[list[str]]:
        """回傳單位清單；每個單位是一組零件 id。"""
        if not isinstance(selector, dict) or not selector:
            raise ValueError(f"{where}：選擇器必須是非空的對照表，收到 {selector!r}")
        keys = set(selector)
        if keys == {"servos"}:
            return self._servos(selector["servos"], where)
        if keys <= {"mesh", "body"} and "mesh" in keys:
            return self._mesh(selector["mesh"], selector.get("body"), where)
        if keys == {"print_only"}:
            return self._print_only(selector["print_only"], where)
        raise ValueError(f"{where}：不認得的選擇器 {selector!r}")

    def resolve_all(self, selectors: list | None, where: str) -> list[list[str]]:
        units: list[list[str]] = []
        for i, sel in enumerate(selectors or []):
            units.extend(self.resolve(sel, f"{where}[{i}]"))
        return units

    def _servos(self, value, where):
        if value == "all":
            ids = self.servo_ids
        elif isinstance(value, list) and value and all(isinstance(v, int) for v in value):
            unknown = sorted(set(value) - set(self.servo_ids))
            if unknown:
                raise ValueError(f"{where}：沒有這些舵機 ID：{unknown}")
            if len(set(value)) != len(value):
                raise ValueError(f"{where}：舵機 ID 重複：{value}")
            ids = value
        else:
            raise ValueError(f"{where}：servos 必須是 all 或 ID 清單，收到 {value!r}")
        return [[p.id for p in self.parts if p.servo_id == sid] for sid in ids]

    def _mesh(self, mesh, body, where):
        if mesh not in self.cad_meshes:
            raise ValueError(f"{where}：robot.xml 沒有網格 {mesh!r}")
        bodies = None
        if body is not None:
            bodies = [body] if isinstance(body, str) else list(body)
            unknown = sorted(set(bodies) - self.bodies)
            if unknown:
                raise ValueError(f"{where}：robot.xml 沒有 body {unknown}")
        units = [[p.id] for p in self.parts if p.mesh == mesh and (bodies is None or p.body in bodies)]
        if not units:
            raise ValueError(f"{where}：{mesh!r}（body={body!r}）沒有選到任何零件")
        return units

    def _print_only(self, value, where):
        if value == "all":
            keys = sorted(self.print_only_keys)
        elif isinstance(value, list) and value:
            unknown = sorted(set(value) - self.print_only_keys)
            if unknown:
                raise ValueError(f"{where}：cad_parts.yaml 的 print_only 沒有 {unknown}")
            keys = value
        else:
            raise ValueError(f"{where}：print_only 必須是 all 或清單，收到 {value!r}")
        return [[p.id] for k in keys for p in self.parts if p.mesh == f"print:{k}"]


def check_bilingual(entry: dict, where: str) -> None:
    """每個 *_zh 欄位都要有對應的 *_en（反之亦然），而且都不能是空的。清單的長度要相同。"""
    for key, value in entry.items():
        for a, b in (("_zh", "_en"), ("_en", "_zh")):
            if key.endswith(a):
                other = key[: -len(a)] + b
                if other not in entry:
                    raise ValueError(f"{where}：有 {key} 但缺少 {other}")
                if not value or not entry[other]:
                    raise ValueError(f"{where}：{key} 或 {other} 是空的")
                if isinstance(value, list) != isinstance(entry[other], list) or (
                    isinstance(value, list) and len(value) != len(entry[other])
                ):
                    raise ValueError(f"{where}：{key} 和 {other} 的項目數不同")
