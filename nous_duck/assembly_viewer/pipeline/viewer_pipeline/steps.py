"""讀 `data/steps.yaml`，把零件選擇器展開成 scene.json 的零件 id，並檢查步驟資料。

檢查項目（任何一項不符就失敗，不產生輸出）：
- 每個選擇器都對得到至少一個零件，語法錯誤或對不到就報錯。
- 每個零件剛好在一個步驟的 `adds` 裡（不漏裝、不重複裝）。
- `focus` 只能指向之前（或同一步）已經裝上的零件；`show_all: true` 的步驟（顯示整機）不受此限。
- 必要欄位齊全、步驟 id 不重複。
"""
from __future__ import annotations

from pathlib import Path

import yaml

from . import STEPS_SCHEMA

STEPS = Path("nous_duck/assembly_viewer/data/steps.yaml")
_REQUIRED = ("id", "title", "summary", "tasks", "check")
_ALLOWED = set(_REQUIRED) | {"warnings", "adds", "focus", "optional", "show_all", "sources"}


class StepsError(ValueError):
    pass


def resolve_selector(selector: str, scene: dict) -> list[str]:
    """把一個選擇器展開成零件 id（依 scene.json 的順序）。"""
    kind, sep, arg = selector.partition(":")
    if not sep or not arg:
        raise StepsError(f"選擇器格式錯誤：{selector!r}")
    parts = scene["parts"]
    if kind == "servo":
        try:
            sid = int(arg)
        except ValueError as e:
            raise StepsError(f"舵機 ID 不是數字：{selector!r}") from e
        found = [s for s in scene["servos"] if s["id"] == sid]
        ids = list(found[0]["parts"]) if found else []
    elif kind == "body":
        ids = [p["id"] for p in parts if p["body"] == arg and p["kind"] != "servo_part"]
    elif kind == "mesh":
        mesh, _, body = arg.partition("@")
        ids = [
            p["id"]
            for p in parts
            if p["mesh"] == mesh and p["kind"] != "servo_part" and (not body or p["body"] == body)
        ]
    elif kind == "part":
        ids = [p["id"] for p in parts if p["id"] == arg]
    else:
        raise StepsError(f"不認得的選擇器類型：{selector!r}")
    if not ids:
        raise StepsError(f"選擇器對不到任何零件：{selector!r}")
    return ids


def _expand(selectors, scene: dict, where: str) -> list[str]:
    if selectors is None:
        return []
    if not isinstance(selectors, list):
        raise StepsError(f"{where} 必須是清單")
    out: list[str] = []
    for sel in selectors:
        for pid in resolve_selector(str(sel), scene):
            if pid not in out:
                out.append(pid)
    return out


def build_steps(doc: dict, scene: dict) -> dict:
    if doc.get("version") != 1:
        raise StepsError("steps.yaml 的 version 必須是 1")
    raw_steps = doc.get("steps") or []
    all_ids = [p["id"] for p in scene["parts"]]
    added_in: dict[str, str] = {}
    seen_steps: set[str] = set()
    steps_out = []
    for i, raw in enumerate(raw_steps):
        missing = [k for k in _REQUIRED if not raw.get(k)]
        if missing:
            raise StepsError(f"第 {i + 1} 步缺少欄位：{missing}")
        extra = set(raw) - _ALLOWED
        if extra:
            raise StepsError(f"步驟 {raw['id']} 有不認得的欄位：{sorted(extra)}")
        sid = raw["id"]
        if sid in seen_steps:
            raise StepsError(f"步驟 id 重複：{sid}")
        seen_steps.add(sid)

        adds = _expand(raw.get("adds"), scene, f"{sid}.adds")
        for pid in adds:
            if pid in added_in:
                raise StepsError(f"{pid} 同時在 {added_in[pid]} 與 {sid} 裝上")
            added_in[pid] = sid
        focus = _expand(raw.get("focus"), scene, f"{sid}.focus")
        not_yet = [pid for pid in focus if pid not in added_in]
        if not_yet and not raw.get("show_all"):
            raise StepsError(f"{sid}.focus 指向還沒裝上的零件：{not_yet[:5]}")

        sources = []
        for src in raw.get("sources") or []:
            if bool(src.get("path")) == bool(src.get("url")) or not src.get("label"):
                raise StepsError(f"{sid} 的來源要有 label，且 path、url 擇一：{src}")
            sources.append({k: src[k] for k in ("label", "path", "url") if src.get(k)})

        steps_out.append(
            {
                "id": sid,
                "title": raw["title"],
                "summary": raw["summary"],
                "tasks": list(raw["tasks"]),
                "check": raw["check"],
                "warnings": list(raw.get("warnings") or []),
                "optional": bool(raw.get("optional", False)),
                "show_all": bool(raw.get("show_all", False)),
                "adds": adds,
                "focus": [pid for pid in focus if pid not in adds],
                "sources": sources,
            }
        )

    never = [pid for pid in all_ids if pid not in added_in]
    if never:
        raise StepsError(f"有 {len(never)} 個零件沒有在任何步驟裝上，例如：{never[:5]}")
    return {"schema": STEPS_SCHEMA, "steps": steps_out}


def load_steps(repo_root: Path, scene: dict) -> dict:
    doc = yaml.safe_load((Path(repo_root) / STEPS).read_text(encoding="utf-8"))
    return build_steps(doc, scene)
