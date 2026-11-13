import sys
from pathlib import Path

import pytest

PIPELINE_DIR = Path(__file__).resolve().parents[2] / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

from viewer_pipeline.scene import build, default_repo_root  # noqa: E402


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return default_repo_root()


@pytest.fixture(scope="session")
def result(repo_root):
    return build(repo_root)


@pytest.fixture(scope="session")
def scene(result):
    return result.scene


@pytest.fixture(scope="session")
def parts_by_id(scene):
    return {p["id"]: p for p in scene["parts"]}
