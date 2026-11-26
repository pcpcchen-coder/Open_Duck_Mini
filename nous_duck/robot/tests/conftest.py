"""讓測試可以 `from behaviors.look_at import ...`（robot/ 還沒有打包成套件）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
