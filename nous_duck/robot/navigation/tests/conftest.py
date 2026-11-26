"""讓測試可以 `import duck_nav`，並提供 `slow` 標記與共用的 fixture。"""

import sys
from pathlib import Path

import pytest

NAV_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NAV_DIR))

from duck_nav.mapfile import load_map  # noqa: E402

MAP_PATH = NAV_DIR / "maps" / "synthetic_home.duckmap.json"
SCHEMA_PATH = NAV_DIR.parents[1] / "protocol" / "schemas" / "duck-link.v0.schema.json"


def pytest_addoption(parser):
    try:
        parser.addoption("--runslow", action="store_true", default=False, help="也跑標了 slow 的測試")
    except ValueError:
        pass


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: 長時間的測試，預設跳過（加 --runslow）")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--runslow"):
        return
    skip = pytest.mark.skip(reason="slow：加 --runslow 才跑")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def home():
    return load_map(MAP_PATH)


@pytest.fixture(scope="session")
def validate_event():
    """用 duck-link v0 的 schema 驗證一則訊息。"""
    import json

    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)

    def check(msg: dict) -> None:
        errors = sorted(validator.iter_errors(msg), key=lambda e: e.path)
        assert not errors, [e.message for e in errors]

    return check
