"""本機命令列（登入鴨子的人用；來源算 `local_cli`，可以放寬隱私設定，ADR-0019 §2.5）。

    python -m duck_settings.cli list
    python -m duck_settings.cli get hearing.min_speech_energy
    python -m duck_settings.cli set hearing.min_speech_energy 300000
    python -m duck_settings.cli set privacy.sound_direction true
    python -m duck_settings.cli reset hearing.settle_s
    python -m duck_settings.cli import-doa ~/duck/doa/config/doa.json     # 把舊的 doa.json 搬進來（一次）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import schema
from .store import SaveError, Store

#: 舊 `doa.json` 的欄位 → 設定的 key
DOA_JSON_KEYS = {
    "mount": "calibration.mic.mount",
    "front_angle_deg": "calibration.mic.front_angle_deg",
    "counterclockwise": "calibration.mic.counterclockwise",
    "calibrated": "calibration.mic.calibrated",
    "speech_source": "hearing.speech_source",
    "min_speech_energy": "hearing.min_speech_energy",
    "window_s": "hearing.window_s",
    "min_speech_samples": "hearing.min_speech_samples",
    "cluster_tolerance_deg": "hearing.cluster_tolerance_deg",
}


def import_doa(store: Store, path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    changes = {DOA_JSON_KEYS[k]: v for k, v in data.items() if k in DOA_JSON_KEYS}
    if "calibration.mic.front_angle_deg" in changes:
        changes["calibration.mic.front_angle_deg"] = float(changes["calibration.mic.front_angle_deg"]) % 360.0
    ignored = sorted(k for k in data if k not in DOA_JSON_KEYS)
    result = store.apply(changes, "local_cli", note=f"import {Path(path).name}")
    return {"imported": changes, "changed": result.changed, "ignored_fields": ignored}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="鴨子設定的本機命令列")
    p.add_argument("--dir", type=Path, default=None)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    g = sub.add_parser("get")
    g.add_argument("key")
    s = sub.add_parser("set")
    s.add_argument("key")
    s.add_argument("value", help="JSON 值：true／false／數字／\"字串\"（沒加引號的字串也可以）")
    r = sub.add_parser("reset")
    r.add_argument("keys", nargs="+")
    i = sub.add_parser("import-doa")
    i.add_argument("path", type=Path)
    args = p.parse_args(argv)
    store = Store(args.dir)
    try:
        if args.cmd == "list":
            view = store.load()
            for st in schema.SETTINGS:
                mark = "" if st.writable else f"  [{schema.STATUS_LABEL[st.status]}]"
                print(f"{st.key} = {json.dumps(view.values[st.key], ensure_ascii=False)}{mark}")
            for problem in view.problems:
                print(f"問題：{problem}", file=sys.stderr)
        elif args.cmd == "get":
            if args.key not in schema.BY_KEY:
                print(f"沒有這個設定：{args.key}", file=sys.stderr)
                return 2
            print(json.dumps(store.load().values[args.key], ensure_ascii=False))
        elif args.cmd == "set":
            try:
                value = json.loads(args.value)
            except ValueError:
                value = args.value
            result = store.apply({args.key: value}, "local_cli")
            print(json.dumps({"changed": result.changed, "revision": result.revision}, ensure_ascii=False))
        elif args.cmd == "reset":
            # 本機可以把量測值以外的項目回復預設（含放寬隱私）
            changes = {k: schema.BY_KEY[k].default for k in args.keys if k in schema.BY_KEY}
            unknown = [k for k in args.keys if k not in schema.BY_KEY]
            if unknown:
                print(f"沒有這個設定：{'、'.join(unknown)}", file=sys.stderr)
                return 2
            result = store.apply(changes, "local_cli", note="reset")
            print(json.dumps({"changed": result.changed, "revision": result.revision}, ensure_ascii=False))
        elif args.cmd == "import-doa":
            print(json.dumps(import_doa(store, args.path), ensure_ascii=False, indent=1))
    except SaveError as exc:
        for key, why in exc.errors.items():
            print(f"拒絕：{why}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f"失敗：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
