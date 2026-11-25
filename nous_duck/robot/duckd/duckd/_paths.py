"""找到同一個 repo（或 Pi 上的部署目錄）裡的 `servo_console`、`duck_eyes` 套件與 duck-link schema。

兩種擺法：

- repo：`nous_duck/robot/duckd/duckd/`，旁邊有 `robot/servo_console/`、`robot/eyes/`、`protocol/schemas/`。
- Pi 部署（`deploy_duckd.sh`）：`~/duck/duckd/` 底下直接放 `duckd/`、`servo_console/`、`duck_eyes/`、
  `duck-link.v0.schema.json`。

只把路徑加進 `sys.path`，不改那些套件的任何東西。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
SCHEMA_NAME = "duck-link.v0.schema.json"


def _add(path: Path) -> None:
    if path.is_dir() and str(path) not in sys.path:
        sys.path.append(str(path))


def ensure_sibling_packages() -> None:
    root = PACKAGE_DIR.parent  # robot/duckd 或 ~/duck/duckd
    _add(root)  # Pi 部署：servo_console、duck_eyes 就在旁邊
    robot = root.parent
    _add(robot / "servo_console")
    _add(robot / "eyes")


def find_schema() -> Path:
    env = os.environ.get("DUCK_LINK_SCHEMA")
    candidates = [Path(env)] if env else []
    candidates.append(PACKAGE_DIR.parent / SCHEMA_NAME)
    for parent in PACKAGE_DIR.parents:
        candidates.append(parent / "protocol" / "schemas" / SCHEMA_NAME)
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError(f"找不到 {SCHEMA_NAME}（可用環境變數 DUCK_LINK_SCHEMA 指定）")
