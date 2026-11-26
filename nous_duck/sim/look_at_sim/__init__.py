"""V3「說話時看著對方」的 MuJoCo 模擬。

用上游 `robot.xml`（唯讀，固定機身）的頭頸關節與致動器，加上依幾何投影產生的**合成人臉偵測**
（fixture，不是真的影像或偵測器），跑 `robot/behaviors/look_at.py` 的控制器，量追蹤誤差。

轉身用**運動學模擬**：機身固定，改成反向旋轉場景裡的人；轉身速度用一階延遲近似步態。
沒有跑步態策略，所以**不驗證平衡**。

用法：

    cd nous_duck/sim
    python -m look_at_sim          # 跑全部情境，輸出 Markdown 表格
"""

from .sim import SCENARIOS, Result, Scenario, SimOptions, run_scenario

__all__ = ["SCENARIOS", "Result", "Scenario", "SimOptions", "run_scenario"]
