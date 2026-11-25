"""duck-link v0：用 `protocol/schemas/duck-link.v0.schema.json` 驗證收發的每一則訊息。

schema 是兩端唯一的契約；這裡不重新定義欄位，只載入、驗證、補上共同欄位。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import jsonschema

from ._paths import find_schema

PROTOCOL_VERSION = "0.1"


class Protocol:
    def __init__(self, schema_path: Path | None = None):
        self.schema_path = Path(schema_path) if schema_path else find_schema()
        self.schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(self.schema)
        self._validator = jsonschema.Draft202012Validator(self.schema)
        defs = self.schema["$defs"]
        self.actions: frozenset[str] = frozenset(defs["action"]["enum"])
        self.reasons: frozenset[str] = frozenset(defs["reason"]["enum"])
        self.events: frozenset[str] = frozenset(defs["event"]["properties"]["event"]["enum"])

    def errors(self, msg: object) -> list[str]:
        return [e.message[:160] for e in self._validator.iter_errors(msg)]

    def make(self, type_: str, **fields) -> dict:
        """組一則要送出的訊息並驗證；不合 schema 是程式錯誤，直接丟例外（不送出壞訊息）。"""
        msg = {"protocol_version": PROTOCOL_VERSION, "type": type_, "sent_at_ms": int(time.time() * 1000)}
        msg.update({k: v for k, v in fields.items() if v is not None})
        errs = self.errors(msg)
        if errs:
            raise ValueError(f"duckd 產生了不合 schema 的 {type_}：{errs[:3]}")
        return msg
