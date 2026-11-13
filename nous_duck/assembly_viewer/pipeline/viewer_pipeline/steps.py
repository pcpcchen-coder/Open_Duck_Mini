"""讀 `data/steps.yaml`，檢查後展開成零件 id，並確認每個 3D 零件剛好在一步裡裝上。"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import yaml

from .selectors import Resolver, check_bilingual

UPSTREAM_REPO = "https://github.com/apirrone/Open_Duck_Mini/blob/v2/"
ATTACHMENT_URL = "https://github.com/user-attachments/assets/"
_ATTACHMENT_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_STEP_KEYS = {
    "id", "title_zh", "title_en", "upstream", "adds", "focus", "bom", "tasks_zh", "tasks_en",
    "check_zh", "check_en", "notes_zh", "notes_en", "deviation_zh", "deviation_en", "optional", "images",
}
_REQUIRED = ("id", "title_zh", "title_en", "upstream", "tasks_zh", "tasks_en", "check_zh", "check_en")


def build_steps(path: Path, repo_root: Path, resolver: Resolver, part_ids: list[str], bom_ids: set[str]) -> tuple[list[dict], dict[str, int]]:
    """回傳（步驟清單、{零件 id: 裝上的步驟序號（從 0 起算）}）。"""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if data.get("version") != 1:
        raise ValueError("steps.yaml 的 version 必須是 1")
    steps_in = data.get("steps") or []
    ids = Counter(s.get("id") for s in steps_in)
    dup = sorted(k for k, n in ids.items() if n > 1)
    if dup:
        raise ValueError(f"steps.yaml 的 id 重複：{dup}")

    added_at: dict[str, int] = {}
    steps_out = []
    for index, step in enumerate(steps_in):
        where = f"steps.yaml {step.get('id')!r}"
        extra = set(step) - _STEP_KEYS
        if extra:
            raise ValueError(f"{where}：不認得的欄位 {sorted(extra)}")
        for key in _REQUIRED:
            if not step.get(key):
                raise ValueError(f"{where}：缺少 {key}")
        check_bilingual(step, where)

        doc = step["upstream"].split("#", 1)[0]
        if not (repo_root / doc).is_file():
            raise ValueError(f"{where}：upstream 指向不存在的檔案 {doc}")

        adds = [pid for unit in resolver.resolve_all(step.get("adds"), f"{where}.adds") for pid in unit]
        for pid in adds:
            if pid in added_at:
                raise ValueError(f"{where}：零件 {pid} 已經在第 {added_at[pid] + 1} 步裝上")
            added_at[pid] = index
        focus = [pid for unit in resolver.resolve_all(step.get("focus"), f"{where}.focus") for pid in unit]

        unknown_bom = sorted(set(step.get("bom") or []) - bom_ids)
        if unknown_bom:
            raise ValueError(f"{where}：bom 引用了不存在的項目 {unknown_bom}")

        images = []
        for img in step.get("images") or []:
            if _ATTACHMENT_ID.match(img):
                images.append({"kind": "github_attachment", "url": ATTACHMENT_URL + img})
            elif (repo_root / img).is_file():
                images.append({"kind": "repo_file", "path": img, "url": UPSTREAM_REPO + img})
            else:
                raise ValueError(f"{where}：圖片 {img!r} 不是 GitHub 附件 ID，也不是 repo 內存在的檔案")

        out = {k: v for k, v in step.items() if k not in ("adds", "focus", "images", "upstream")}
        out.update(
            {
                "index": index,
                "upstream": step["upstream"],
                "upstream_url": UPSTREAM_REPO + step["upstream"],
                "optional": bool(step.get("optional", False)),
                "adds": adds,
                "focus": focus,
                "bom": list(step.get("bom") or []),
                "images": images,
            }
        )
        steps_out.append(out)

    missing = [pid for pid in part_ids if pid not in added_at]
    if missing:
        raise ValueError(f"這些 3D 零件沒有在任何步驟裝上：{missing}")
    return steps_out, added_at
