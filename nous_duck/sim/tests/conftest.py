"""讓測試可以 `import look_at_sim`、`import walk_sim`，並提供 `slow` 標記。

長時間的模擬測試標 `@pytest.mark.slow`，預設跳過；加 `--runslow` 才跑。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def pytest_addoption(parser):
    try:
        parser.addoption("--runslow", action="store_true", default=False, help="也跑標了 slow 的長時間模擬測試")
    except ValueError:
        pass  # 另一個 conftest 已經加過


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: 長時間的模擬測試，預設跳過（加 --runslow）")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--runslow"):
        return
    skip = pytest.mark.skip(reason="slow：加 --runslow 才跑")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)
