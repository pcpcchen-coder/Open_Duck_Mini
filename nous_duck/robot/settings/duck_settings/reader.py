"""給鴨子上各服務讀設定用（只用標準函式庫）。

    from duck_settings.reader import Watcher
    w = Watcher(settings_dir, "duckd")
    view = w.poll(force=True)          # 第一次：讀進來
    ...每秒一次...
    view = w.poll()                    # 檔案沒變就回 None
    w.report({"head.speed_deg_s": 30.0, ...})   # 回報「我實際在用的值」，設定頁用它顯示「已生效」

讀檔永遠不丟例外：檔案不在、壞掉、某一項不合格，都退回**預設值**並把原因放在 `view.problems`
（服務照常跑，設定頁會顯示問題）。不合格的值不會被拿來用。
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import schema

SETTINGS_FILE = "settings.json"  # 使用者偏好
CALIBRATION_FILE = "calibration.json"  # 機體量測值
APPLIED_DIR = "applied"
FILE_FOR_KIND = {"preference": SETTINGS_FILE, "measurement": CALIBRATION_FILE}


def default_dir() -> Path:
    env = os.environ.get("DUCK_SETTINGS_DIR")
    return Path(env) if env else Path.home() / "duck" / "settings"


@dataclass(frozen=True)
class View:
    """某一刻的有效設定：預設值＋檔案裡合格的值。"""

    values: dict[str, Any]
    revision: dict[str, int]  # {"preference": n, "measurement": n}
    problems: tuple[str, ...] = ()
    stored: dict[str, Any] = field(default_factory=dict)  # 檔案裡有寫（且合格）的 key

    def __getitem__(self, key: str) -> Any:
        return self.values[key]


def read_file(path: Path) -> tuple[dict, list[str]]:
    """讀一個設定檔。回傳（文件, 問題）。檔案不存在不算問題。"""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, []
    except OSError as exc:
        return {}, [f"{path.name} 讀不到：{exc}"]
    try:
        doc = json.loads(text)
    except ValueError as exc:
        return {}, [f"{path.name} 不是合法的 JSON（{exc}）；先用預設值"]
    if not isinstance(doc, dict) or not isinstance(doc.get("values", {}), dict):
        return {}, [f"{path.name} 的格式不對；先用預設值"]
    if doc.get("schema_version", schema.SCHEMA_VERSION) > schema.SCHEMA_VERSION:
        return doc, [f"{path.name} 是比較新的格式（schema_version {doc.get('schema_version')}）；不認得的項目會被忽略"]
    return doc, []


def load(directory: Path | None = None) -> View:
    directory = Path(directory) if directory else default_dir()
    values = schema.defaults()
    stored: dict[str, Any] = {}
    problems: list[str] = []
    revision: dict[str, int] = {}
    for kind, name in FILE_FOR_KIND.items():
        doc, probs = read_file(directory / name)
        problems += probs
        rev = doc.get("revision", 0)
        revision[kind] = rev if isinstance(rev, int) and not isinstance(rev, bool) else 0
        for key, raw in (doc.get("values") or {}).items():
            s = schema.BY_KEY.get(key)
            if s is None or s.kind != kind:
                continue  # 不認得的 key（新版或舊版留下的）：忽略
            try:
                values[key] = stored[key] = s.validate(raw)
            except schema.SettingError as exc:
                problems.append(f"{name}：{exc}；先用預設值 {s.default!r}")
    for err in schema.check_cross_rules(values):
        # 檔案被手改成互相矛盾：兩項都退回預設
        problems.append(f"{err}；兩項都先用預設值")
        for key in ("hearing.settle_s", "hearing.window_s"):
            values[key] = schema.BY_KEY[key].default
            stored.pop(key, None)
    return View(values, revision, tuple(problems), stored)


def _signature(directory: Path) -> tuple:
    sig = []
    for name in FILE_FOR_KIND.values():
        try:
            st = (directory / name).stat()
            sig.append((st.st_mtime_ns, st.st_size, st.st_ino))
        except OSError:
            sig.append(None)
    return tuple(sig)


def atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class Watcher:
    """服務端：檔案變了才重新讀；回報實際套用的值。"""

    def __init__(self, directory: Path | None, service: str):
        self.directory = Path(directory) if directory else default_dir()
        self.service = service
        self._sig: tuple | None = None
        self.view: View = load(self.directory)
        self._reported: str | None = None

    def poll(self, force: bool = False) -> View | None:
        sig = _signature(self.directory)
        if not force and sig == self._sig:
            return None
        self._sig = sig
        self.view = load(self.directory)
        return self.view

    def keys(self) -> list[str]:
        return [s.key for s in schema.SETTINGS if s.consumer == self.service]

    def report(self, applied: dict[str, Any], note: str = "", inactive: dict[str, str] | None = None) -> None:
        """寫下「這個服務現在實際在用的值」。內容沒變就不重寫（少寫 SD 卡）。寫不進去不影響服務。

        `inactive`：值讀到了、但現在不會有效果的項目與原因（例如頭部沒有出力），設定頁不會對它們顯示「已生效」。
        """
        body = {"service": self.service, "pid": os.getpid(), "schema_version": schema.SCHEMA_VERSION,
                "revision": self.view.revision, "values": applied, "note": note}
        if inactive:
            body["inactive"] = {str(k): str(v)[:200] for k, v in inactive.items()}
        key = json.dumps(body, sort_keys=True, ensure_ascii=False)
        if key == self._reported:
            return
        try:
            atomic_write_json(self.directory / APPLIED_DIR / f"{self.service}.json", {**body, "applied_at": time.time()})
            self._reported = key
        except OSError:
            pass


def read_applied(directory: Path, service: str) -> dict | None:
    try:
        doc = json.loads((Path(directory) / APPLIED_DIR / f"{service}.json").read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) and isinstance(doc.get("values"), dict) else None
    except (OSError, ValueError):
        return None
