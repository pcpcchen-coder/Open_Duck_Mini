"""讀上游文件裡的表：舵機 ID（docs/configure_motors.md）與列印清單（docs/print_guide.md）。

這兩份是上游的事實來源；pipeline 直接讀原文，不在程式裡另抄一份，避免兩邊不同步。
"""
from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path


def motor_ids(configure_motors_md: Path) -> dict[str, int]:
    """讀 `docs/configure_motors.md` 裡 ```python 區塊的 {"關節名": ID} 字典。"""
    text = Path(configure_motors_md).read_text(encoding="utf-8")
    blocks = re.findall(r"```python\n(.*?)```", text, re.S)
    for block in blocks:
        try:
            value = ast.literal_eval(block.strip())
        except (ValueError, SyntaxError):
            continue
        if isinstance(value, dict) and value and all(isinstance(k, str) and isinstance(v, int) for k, v in value.items()):
            if len(set(value.values())) != len(value):
                raise ValueError("configure_motors.md 的舵機 ID 有重複")
            return value
    raise ValueError("在 configure_motors.md 找不到舵機 ID 字典")


def print_list(print_guide_md: Path) -> dict[str, dict]:
    """讀 `docs/print_guide.md` 的「- name.stl xN」清單，回傳 {檔名: {"count": N, "material": ...}}。"""
    text = Path(print_guide_md).read_text(encoding="utf-8")
    default_material = "PLA"
    items: dict[str, dict] = {}
    for m in re.finditer(r"^- ([\w.-]+\.stl) x(\d+)(?:\s*\((\w+)\))?\s*$", text, re.M):
        name, count, material = m.group(1), int(m.group(2)), m.group(3) or default_material
        if name in items:
            raise ValueError(f"print_guide.md 重複列出 {name}")
        items[name] = {"count": count, "material": material}
    if not items:
        raise ValueError("在 print_guide.md 找不到列印清單")
    return items


def sha256(path: Path) -> str:
    """檔案內容的 sha256。輸出用它記錄來源，換 commit 但上游檔案沒變時，輸出不變。"""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
