"""nav_sim：導航核心（`robot/navigation/duck_nav`）接上 MuJoCo 全身走路模擬的閉迴路。全部是模擬。"""

import sys
from pathlib import Path

_NAV = Path(__file__).resolve().parents[2] / "robot" / "navigation"
if str(_NAV) not in sys.path:
    sys.path.insert(0, str(_NAV))
