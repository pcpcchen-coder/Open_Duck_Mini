"""讓測試可以 `import duck_perception`，並提供 YuNet 模型是否存在的判斷。"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MODEL = ROOT / "models" / "face_detection_yunet_2023mar.onnx"
needs_model = pytest.mark.skipif(not MODEL.exists(), reason="沒有 YuNet 模型；先執行 tools/fetch_models.py")
