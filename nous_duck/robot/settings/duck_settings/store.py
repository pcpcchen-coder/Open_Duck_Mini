"""設定的儲存：驗證、只收緊規則、原子寫入、上一版、變更紀錄。

寫入只有這一個入口（`Store.apply`），設定頁、本機命令列、校正工具都走它。

來源（`source`）決定能做什麼（ADR-0019 §2.5）：

| 來源 | 誰 | 隱私設定 |
|---|---|---|
| `web` | 設定頁（區網內任何人） | 只能收緊 |
| `duck_link` | Nous／模型（**還沒有這條路**，只留規則） | 只能收緊；不能改機體量測值 |
| `local_cli` | 登入鴨子本機的人（要 SSH 金鑰） | 可以放寬 |

`planned`／`hardware_missing` 的項目任何來源都不能寫。
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import schema
from .reader import CALIBRATION_FILE, FILE_FOR_KIND, SETTINGS_FILE, View, atomic_write_json, default_dir, load, read_file

SOURCES = ("web", "duck_link", "local_cli")
LOOSEN_SOURCES = frozenset({"local_cli"})
HISTORY_DIR = "history"
HISTORY_KEEP = 20
CHANGES_FILE = "changes.jsonl"
CHANGES_KEEP = 500


class SaveError(Exception):
    """儲存被拒絕。`errors`：{key 或 "_": 給使用者看的原因}；什麼都沒有寫進去。"""

    def __init__(self, errors: dict[str, str], code: str = "invalid"):
        super().__init__("；".join(errors.values()))
        self.errors = errors
        self.code = code  # invalid | conflict | io


@dataclass
class SaveResult:
    changed: dict[str, dict[str, Any]] = field(default_factory=dict)  # key → {"from", "to"}
    skipped: dict[str, str] = field(default_factory=dict)  # key → 為什麼沒改
    revision: dict[str, int] = field(default_factory=dict)


class Store:
    def __init__(self, directory: Path | None = None, clock=time.time):
        self.directory = Path(directory) if directory else default_dir()
        self.clock = clock
        self._lock = threading.Lock()

    def load(self) -> View:
        return load(self.directory)

    # ---------------------------------------------------------------- 寫入
    def apply(self, changes: dict[str, Any], source: str, *, base_revision: dict[str, int] | None = None,
              confirm_measurements: bool = False, note: str = "", client: str = "") -> SaveResult:
        """驗證後寫入。有任何一項不合格就**整批不寫**，回報每一項的原因。"""
        if source not in SOURCES:
            raise SaveError({"_": f"不認得的來源 {source!r}"})
        if not isinstance(changes, dict) or not changes:
            raise SaveError({"_": "沒有要改的項目"})
        with self._lock:
            view = self.load()
            if base_revision is not None and any(base_revision.get(k) != v for k, v in view.revision.items()):
                raise SaveError({"_": "設定在你打開頁面之後被別人改過了。重新載入再改一次"}, code="conflict")
            errors: dict[str, str] = {}
            new_values = dict(view.values)
            touched: dict[str, Any] = {}
            for key, raw in changes.items():
                s = schema.BY_KEY.get(key)
                if s is None:
                    errors[str(key)[:80]] = "沒有這個設定"
                    continue
                if not s.writable:
                    errors[key] = f"{s.label}：{schema.STATUS_LABEL[s.status]}，還不能設定（{s.blocked_by}）"
                    continue
                try:
                    value = s.validate(raw)
                except schema.SettingError as exc:
                    errors[key] = str(exc)
                    continue
                if s.kind == "measurement" and source == "duck_link":
                    errors[key] = f"{s.label}：機體量測值不能經 duck-link 改"
                    continue
                if s.kind == "measurement" and source == "web" and not confirm_measurements:
                    errors[key] = f"{s.label}：這是機體量測值，要先勾選「我確定要改量測值」"
                    continue
                if source not in LOOSEN_SOURCES and s.is_looser(view.values[key], value):
                    errors[key] = (
                        f"{s.label}：這一頁只能把隱私設定收緊，不能放寬。"
                        "要放寬請登入鴨子本機執行：~/duck/settings/duck-settings set " + f"{key} {json.dumps(value)}"
                    )
                    continue
                new_values[key] = touched[key] = value
            if not errors:
                for i, err in enumerate(schema.check_cross_rules(new_values)):
                    errors[f"_cross{i}"] = err
            if errors:
                raise SaveError(errors)
            result = SaveResult()
            for key, value in touched.items():
                if view.values[key] != value:
                    result.changed[key] = {"from": view.values[key], "to": value}
            self._write(view, touched, result, source, note, client)
            return result

    def reset(self, keys: list[str], source: str, base_revision: dict[str, int] | None = None, client: str = "") -> SaveResult:
        """把指定的項目回復成預設值。量測值不能用這個回復；會放寬隱私的項目（來源不允許時）略過並回報。"""
        with self._lock:
            view = self.load()
        changes: dict[str, Any] = {}
        skipped: dict[str, str] = {}
        for key in keys:
            s = schema.BY_KEY.get(key)
            if s is None:
                raise SaveError({str(key)[:80]: "沒有這個設定"})
            if not s.writable:
                continue
            if s.kind == "measurement":
                skipped[key] = "機體量測值不會被「回復預設」動到"
            elif source not in LOOSEN_SOURCES and s.is_looser(view.values[key], s.default):
                skipped[key] = "回復預設會放寬隱私設定，這一頁不能做；要在鴨子本機用指令"
            elif view.values[key] != s.default:
                changes[key] = s.default
        if not changes:
            return SaveResult(skipped=skipped, revision=view.revision)
        result = self.apply(changes, source, base_revision=base_revision, note="reset", client=client)
        result.skipped.update(skipped)
        return result

    def restore_previous(self, source: str, client: str = "") -> SaveResult:
        """還原成上一版的使用者偏好（`history/` 裡最新的一份）。量測值不動。"""
        prev = self.previous()
        if prev is None:
            raise SaveError({"_": "沒有上一版可以還原"})
        view = self.load()
        prev_values = schema.defaults("preference")
        for key, raw in (prev.get("values") or {}).items():
            s = schema.BY_KEY.get(key)
            if s is not None and s.kind == "preference" and s.writable:
                try:
                    prev_values[key] = s.validate(raw)
                except schema.SettingError:
                    pass
        changes, skipped = {}, {}
        for key, value in prev_values.items():
            s = schema.BY_KEY[key]
            if not s.writable or view.values[key] == value:
                continue
            if source not in LOOSEN_SOURCES and s.is_looser(view.values[key], value):
                skipped[key] = "還原會放寬隱私設定，這一頁不能做；這一項維持現在的值"
            else:
                changes[key] = value
        if not changes:
            return SaveResult(skipped=skipped, revision=view.revision)
        result = self.apply(changes, source, note=f"restore revision {prev.get('revision')}", client=client)
        result.skipped.update(skipped)
        return result

    # ---------------------------------------------------------------- 讀取輔助
    def previous(self) -> dict | None:
        files = sorted((self.directory / HISTORY_DIR).glob("settings-*.json"))
        for path in reversed(files):
            doc, problems = read_file(path)
            if doc and not problems:
                return doc
        return None

    def changes(self, limit: int = 20) -> list[dict]:
        try:
            lines = (self.directory / CHANGES_FILE).read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for line in lines[-limit:]:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out[::-1]

    # ---------------------------------------------------------------- 內部
    def _write(self, view: View, touched: dict[str, Any], result: SaveResult, source: str, note: str, client: str = "") -> None:
        now = self.clock()
        result.revision = dict(view.revision)
        try:
            for kind, name in FILE_FOR_KIND.items():
                mine = {k: v for k, v in touched.items() if schema.BY_KEY[k].kind == kind}
                if not mine:
                    continue
                path = self.directory / name
                stored = {k: v for k, v in view.stored.items() if schema.BY_KEY[k].kind == kind}
                if all(stored.get(k, object()) == v for k, v in mine.items()):
                    continue  # 檔案裡已經是這些值
                if kind == "preference":
                    self._keep_history(path, view.revision[kind])
                rev = view.revision[kind] + 1
                atomic_write_json(path, {
                    "schema_version": schema.SCHEMA_VERSION, "revision": rev, "updated_at": round(now, 3),
                    "updated_by": source, "values": {**stored, **mine},
                })
                result.revision[kind] = rev
            if result.changed:
                self._log({"at": round(now, 3), "source": source, "from": client[:64], "note": note, "revision": result.revision,
                           "changes": result.changed})
        except OSError as exc:
            raise SaveError({"_": f"寫不進設定檔：{exc}"}, code="io") from exc

    def _keep_history(self, path: Path, revision: int) -> None:
        hist = self.directory / HISTORY_DIR
        hist.mkdir(parents=True, exist_ok=True)
        keep = hist / f"settings-{revision:06d}.json"
        if path.exists():
            keep.write_bytes(path.read_bytes())
        else:  # 第一次儲存：上一版就是「全部預設值」
            atomic_write_json(keep, {"schema_version": schema.SCHEMA_VERSION, "revision": revision, "values": {}})
        for old in sorted(hist.glob("settings-*.json"))[:-HISTORY_KEEP]:
            old.unlink(missing_ok=True)

    def _log(self, entry: dict) -> None:
        """變更紀錄：時間、來源、來源位址（設定頁是對方的區網 IP）、哪一項從什麼改成什麼（ADR-0006 §3、ADR-0019 §2.4）。

        只留在鴨子本機，不外傳；不含任何影像或聲音內容。"""
        path = self.directory / CHANGES_FILE
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        lines.append(json.dumps(entry, ensure_ascii=False, sort_keys=True))
        path.write_text("\n".join(lines[-CHANGES_KEEP:]) + "\n", encoding="utf-8")


__all__ = ["Store", "SaveError", "SaveResult", "SETTINGS_FILE", "CALIBRATION_FILE", "SOURCES", "LOOSEN_SOURCES"]
