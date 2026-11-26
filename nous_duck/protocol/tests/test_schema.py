"""duck-link v0 schema 測試：examples/valid.jsonl 全部通過、invalid.jsonl 全部被拒絕。

執行：uv run --with jsonschema --with pytest python -m pytest nous_duck/protocol/tests -q
"""
import json
import pathlib

import jsonschema
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas" / "duck-link.v0.schema.json").read_text(encoding="utf-8"))
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)


def _lines(name):
    text = (ROOT / "examples" / name).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_schema_itself_is_valid():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)


@pytest.mark.parametrize("msg", _lines("valid.jsonl"), ids=lambda m: f"{m['type']}:{m.get('action', m.get('event', ''))}")
def test_valid_examples(msg):
    errors = list(VALIDATOR.iter_errors(msg))
    assert not errors, [e.message for e in errors]


@pytest.mark.parametrize("msg", _lines("invalid.jsonl"), ids=lambda m: f"{m['type']}:{m.get('action', m.get('event', m.get('mode', '')))}")
def test_invalid_examples(msg):
    assert list(VALIDATOR.iter_errors(msg)), "應該被 schema 拒絕"


def test_every_action_has_a_valid_example_or_is_listed():
    actions = set(SCHEMA["$defs"]["action"]["enum"])
    assert {"status", "stop", "walk", "look", "gesture"} <= actions
    # 刻意不提供的操作（ADR-0001 §4）不能出現在協定裡
    assert not actions & {"torque_off", "reboot", "shutdown", "set_offset", "set_id", "joint_stream", "estop_clear"}
