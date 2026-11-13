import sys
from pathlib import Path

import pytest

CAD_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CAD_DIR))

from dock_cad.build import build  # noqa: E402


@pytest.fixture(scope="session")
def result():
    return build()
