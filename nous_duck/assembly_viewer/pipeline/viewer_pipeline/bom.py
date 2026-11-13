"""讀 `data/bom.yaml`，檢查後和列印件合成完整 BOM，並確認每個 3D 零件都屬於剛好一個 BOM 項目。

列印件的 BOM 列由 pipeline 自動產生（依 cad_parts.yaml 與上游 docs/print_guide.md），
bom.yaml 只記採購件、耗材與工具。
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import yaml

from .catalog import Catalog
from .selectors import PartRef, Resolver, check_bilingual

CATEGORIES = ("servo", "electronics", "power", "connector", "wire", "hardware", "material", "tool")
NOT_PARTS = ("material", "tool")
PACKAGES = ("basic", "expression")
SOURCES = ("upstream_bom", "assembly_guide")
_ITEM_KEYS = {
    "id", "category", "package", "name_zh", "name_en", "qty", "qty_note_zh", "qty_note_en", "source",
    "upstream", "scene", "scene_note_zh", "scene_note_en", "note_zh", "note_en",
    "upstream_status_zh", "upstream_status_en",
}
_UPSTREAM_KEYS = {"csv_row", "name", "qty", "unit_price_eur"}


def build_bom(
    path: Path,
    catalog: Catalog,
    print_counts: dict[str, dict],
    parts: list[PartRef],
    print_stl_of: dict[str, str | None],
    resolver: Resolver,
) -> tuple[list[dict], list[dict], dict[str, str]]:
    """回傳（BOM 列、CAD 有但上游沒有的零件、{零件 id: BOM id}）。"""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if data.get("version") != 1:
        raise ValueError("bom.yaml 的 version 必須是 1")

    rows: list[dict] = []
    owner: dict[str, str] = {}

    def claim(part_ids: list[str], bom_id: str) -> None:
        for pid in part_ids:
            if pid in owner:
                raise ValueError(f"零件 {pid} 同時屬於 BOM {owner[pid]} 與 {bom_id}")
            owner[pid] = bom_id

    # ---- 列印件（自動） ----
    names: dict[str, tuple[str, str]] = {}
    for mesh, entry in catalog.cad.items():
        if entry["kind"] == "printed":
            names.setdefault(entry["print_stl"], (entry["name_zh"], entry["name_en"]))
    for extra in catalog.print_only:
        names.setdefault(extra.print_stl, (extra.name_zh, extra.name_en))
    print_only_stls = {extra.print_stl for extra in catalog.print_only}

    for stl, info in print_counts.items():
        if stl not in names:
            raise ValueError(f"print_guide.md 的 {stl} 在 cad_parts.yaml 找不到對應")
        part_ids = [p.id for p in parts if print_stl_of[p.id] == stl]
        if len(part_ids) != info["count"]:
            raise ValueError(f"{stl}：模型裡有 {len(part_ids)} 件，print_guide.md 寫 {info['count']} 件")
        bom_id = f"print:{stl}"
        claim(part_ids, bom_id)
        rows.append(
            {
                "id": bom_id,
                "category": "printed",
                "package": "expression" if stl in print_only_stls else "basic",
                "name_zh": names[stl][0],
                "name_en": names[stl][1],
                "qty": info["count"],
                "material": info["material"],
                "print_stl": stl,
                "source": "print_guide",
                "parts": part_ids,
            }
        )

    # ---- 採購件、耗材、工具 ----
    ids = Counter(item.get("id") for item in data.get("items") or [])
    dup = sorted(k for k, n in ids.items() if n > 1)
    if dup:
        raise ValueError(f"bom.yaml 的 id 重複：{dup}")
    for item in data.get("items") or []:
        where = f"bom.yaml {item.get('id')!r}"
        extra = set(item) - _ITEM_KEYS
        if extra:
            raise ValueError(f"{where}：不認得的欄位 {sorted(extra)}")
        for key in ("id", "category", "package", "name_zh", "name_en", "source"):
            if not item.get(key):
                raise ValueError(f"{where}：缺少 {key}")
        if item["id"].startswith("print:"):
            raise ValueError(f"{where}：print: 開頭的 id 保留給自動產生的列印件")
        if item["category"] not in CATEGORIES:
            raise ValueError(f"{where}：category {item['category']!r} 不在 {CATEGORIES}")
        if item["package"] not in PACKAGES:
            raise ValueError(f"{where}：package {item['package']!r} 不在 {PACKAGES}")
        if item["source"] not in SOURCES:
            raise ValueError(f"{where}：source {item['source']!r} 不在 {SOURCES}")
        check_bilingual(item, where)

        qty = item.get("qty")
        if qty is None:
            if not item.get("qty_note_zh"):
                raise ValueError(f"{where}：qty 是 null 時必須寫 qty_note_zh 說明")
        elif not (isinstance(qty, int) and qty > 0):
            raise ValueError(f"{where}：qty 必須是正整數或 null")

        up = item.get("upstream")
        if item["source"] == "upstream_bom":
            if not isinstance(up, dict) or set(up) != _UPSTREAM_KEYS:
                raise ValueError(f"{where}：source 是 upstream_bom 時必須有 upstream {sorted(_UPSTREAM_KEYS)}")
        elif up is not None:
            raise ValueError(f"{where}：source 不是 upstream_bom 時不應該有 upstream")

        has_scene = "scene" in item
        has_note = "scene_note_zh" in item
        if item["category"] in NOT_PARTS:
            # 材料與工具不是裝上去的零件：不能有 scene，也不用說明為什麼 3D 中沒有
            if has_scene:
                raise ValueError(f"{where}：{item['category']} 不是組裝零件，不應該有 scene")
        elif has_scene == has_note:
            raise ValueError(f"{where}：scene 與 scene_note_zh 必須剛好擇一（3D 有顯示就寫 scene，沒有就說明原因）")

        part_ids: list[str] = []
        if has_scene:
            units = resolver.resolve_all(item["scene"], f"{where}.scene")
            if qty is not None and len(units) != qty:
                raise ValueError(f"{where}：qty 是 {qty}，但 3D 模型裡選到 {len(units)} 個")
            part_ids = [pid for unit in units for pid in unit]
            claim(part_ids, item["id"])

        row = {k: v for k, v in item.items() if k != "scene"}
        row["parts"] = part_ids
        rows.append(row)

    # ---- CAD 有、上游沒有 ----
    without = []
    for entry in data.get("cad_without_bom") or []:
        where = f"bom.yaml cad_without_bom {entry.get('mesh')!r}"
        check_bilingual(entry, where)
        units = resolver.resolve({"mesh": entry["mesh"]}, where)
        part_ids = [pid for unit in units for pid in unit]
        claim(part_ids, f"cad_without_bom:{entry['mesh']}")
        without.append({"mesh": entry["mesh"], "reason_zh": entry["reason_zh"], "reason_en": entry["reason_en"], "parts": part_ids})

    missing = sorted(p.id for p in parts if p.id not in owner)
    if missing:
        raise ValueError(f"這些 3D 零件不屬於任何 BOM 項目，也沒有列在 cad_without_bom：{missing}")
    bom_owner = {pid: b for pid, b in owner.items() if not b.startswith("cad_without_bom:")}
    return rows, without, bom_owner
