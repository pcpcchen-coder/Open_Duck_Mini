"""讀 `data/cad_parts.yaml`，檢查它涵蓋 robot.xml 的每個網格，並給每個零件類別與名稱。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

KINDS = ("printed", "servo_part", "electronics", "power", "bearing", "other")
_REQUIRED = ("kind", "name_zh", "name_en")


@dataclass(frozen=True)
class PartInfo:
    kind: str
    name_zh: str
    name_en: str
    print_stl: str | None = None
    identification: str | None = None


@dataclass(frozen=True)
class PrintOnly:
    key: str
    print_stl: str
    frame_of: str
    name_zh: str
    name_en: str


@dataclass
class Catalog:
    cad: dict[str, dict]
    print_only: list[PrintOnly]

    def info(self, mesh: str, body: str) -> PartInfo:
        entry = self.cad[mesh]
        override = (entry.get("by_body") or {}).get(body, {})
        return PartInfo(
            kind=entry["kind"],
            name_zh=override.get("name_zh", entry["name_zh"]),
            name_en=override.get("name_en", entry["name_en"]),
            print_stl=entry.get("print_stl"),
            identification=override.get("identification", entry.get("identification")),
        )


def load_catalog(path: Path, mesh_names: set[str], print_dir: Path) -> Catalog:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if data.get("version") != 1:
        raise ValueError("cad_parts.yaml 的 version 必須是 1")
    cad = data.get("cad_meshes") or {}

    missing = sorted(mesh_names - set(cad))
    extra = sorted(set(cad) - mesh_names)
    if missing:
        raise ValueError(f"cad_parts.yaml 缺少這些 robot.xml 網格：{missing}")
    if extra:
        raise ValueError(f"cad_parts.yaml 列了 robot.xml 沒有的網格：{extra}")

    for mesh, entry in cad.items():
        for key in _REQUIRED:
            if not entry.get(key):
                raise ValueError(f"cad_parts.yaml 的 {mesh} 缺少 {key}")
        if entry["kind"] not in KINDS:
            raise ValueError(f"cad_parts.yaml 的 {mesh} 類別 {entry['kind']!r} 不在 {KINDS}")
        if entry["kind"] == "printed":
            stl = entry.get("print_stl")
            if not stl or not (print_dir / stl).is_file():
                raise ValueError(f"cad_parts.yaml 的 {mesh} 指向不存在的列印檔 {stl!r}")
        elif entry.get("print_stl"):
            raise ValueError(f"cad_parts.yaml 的 {mesh} 不是列印件，不應該有 print_stl")

    print_only = []
    for key, entry in (data.get("print_only") or {}).items():
        stl = f"{key}.stl"
        if not (print_dir / stl).is_file():
            raise ValueError(f"print_only 的 {key} 在 print/ 找不到 {stl}")
        frame_of = entry.get("frame_of")
        if frame_of not in cad or cad[frame_of]["kind"] != "printed":
            raise ValueError(f"print_only 的 {key} 的 frame_of {frame_of!r} 必須是 CAD 列印件")
        print_only.append(
            PrintOnly(key=key, print_stl=stl, frame_of=frame_of, name_zh=entry["name_zh"], name_en=entry["name_en"])
        )
    return Catalog(cad=cad, print_only=print_only)
