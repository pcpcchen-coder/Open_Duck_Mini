"""duckd 讀「鴨子設定」（`robot/settings`，ADR-0019）。

- 啟動時讀一次：頭部最高角速度、活動範圍（這兩項改了要重啟 duckd 才生效）。
- 之後每秒看一次檔案有沒有變：功能開關、聽聲轉頭的時間與死區、對話小動作幅度、presence 對應的表情，即時套用。
- 每次套用後回報「實際在用的值」，設定頁用它顯示「已生效／要重啟」。

設定只能在 schema 允許的範圍內改（範圍檢查在 `duck_settings.schema`，讀檔時再檢查一次）；
安全上限（`limits.py`）、緊急停止、扭力都不在設定裡。

`duck_settings` 匯入不了、或設定資料夾讀不到時，duckd 照常啟動，頭部用 `CONSERVATIVE`（無人看顧時的規定值）。
"""
from __future__ import annotations

import logging
from pathlib import Path

from ._paths import ensure_sibling_packages

log = logging.getLogger("duckd.settings")

#: 讀不到設定時用的頭部限制（°/s、±°）。和 schema 的預設值相同（tests/test_settings_in.py 會核對）。
CONSERVATIVE = {"head.speed_deg_s": 30.0, "head.window_deg": 15.0}
RESTART_KEYS = tuple(CONSERVATIVE)
SERVICE = "duckd"


class SettingsInput:
    def __init__(self, directory: Path | None):
        self.watcher = None
        self.error = ""
        self._last_inactive: dict | None = None
        self.startup = dict(CONSERVATIVE)
        try:
            ensure_sibling_packages()
            from duck_settings.reader import Watcher  # noqa: PLC0415

            self.watcher = Watcher(directory, SERVICE)
            view = self.watcher.poll(force=True)
            self.startup = {k: float(view.values[k]) for k in RESTART_KEYS}
            for problem in view.problems:
                log.warning("設定檔有問題：%s", problem)
        except Exception as exc:  # noqa: BLE001 設定壞了不能讓 duckd 起不來
            self.error = f"{type(exc).__name__}: {exc}"
            log.warning("讀不到鴨子設定（%s）；頭部用保守值 %s，其他用內建預設", self.error, CONSERVATIVE)

    def status(self) -> dict:
        if self.watcher is None:
            return {"ok": False, "error": self.error}
        return {"ok": True, "directory": str(self.watcher.directory), "revision": self.watcher.view.revision,
                "problems": list(self.watcher.view.problems)}

    def poll(self, core, force: bool = False) -> bool:
        """檔案有變就套用到 core。回傳有沒有套用。

        另外：「讀到了但現在不會動」的原因（`core.settings_inactive()`，例如頭沒有出力）變了，就重新回報，
        讓設定頁不要對這些項目顯示「已生效」。
        """
        if self.watcher is None:
            return False
        try:
            view = self.watcher.view if force else self.watcher.poll()
            inactive = core.settings_inactive() if hasattr(core, "settings_inactive") else {}
            if view is None:
                if inactive != self._last_inactive:
                    self._report(core.settings_applied(), inactive)
                return False
            applied = core.apply_settings(view.values)
            self._report(applied, core.settings_inactive() if hasattr(core, "settings_inactive") else {})
            return True
        except Exception:  # noqa: BLE001
            log.exception("套用設定失敗；維持原本的值")
            return False

    def _report(self, applied: dict, inactive: dict) -> None:
        values = {**applied, **self.startup}
        try:
            self.watcher.report(values, inactive=inactive)
        except TypeError:  # duck_settings 是舊版（reader.report 還沒有 inactive）：照舊回報，不帶原因
            self.watcher.report(values)
        self._last_inactive = dict(inactive)
