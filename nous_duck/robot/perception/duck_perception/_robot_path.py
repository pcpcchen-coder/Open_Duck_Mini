"""讓 `from behaviors.look_at import ...` 可用（robot/ 還沒有打包成套件）。"""

import sys
from pathlib import Path

_ROBOT = str(Path(__file__).resolve().parents[2])
if _ROBOT not in sys.path:
    sys.path.insert(0, _ROBOT)
