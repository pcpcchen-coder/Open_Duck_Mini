"""步態反應模型：「速度指令 → 實際機身速度」的查表，以及導航可用的指令集合。

數字來自 `data/gait_response.sim.json`（**模擬量測**，`sim/walk_sim/measure.py` 產生）。
上游步態策略在模擬裡有起步門檻：太小的指令鴨子留在原地。所以導航只用表裡 `started == 1` 的格子：
前進固定用 `FWD_CMD`、後退固定用 `BACK_CMD`，轉向可以連續調；原地轉用 `TURN_CMD`。
實機能走之後要重量這張表，並在 `GaitModel.load()` 換成實機的檔案。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

DATA = Path(__file__).resolve().parent / "data"
DEFAULT_TABLE = DATA / "gait_response.sim.json"

#: ADR-0009 §2.5 的加速度限制（每 20 ms）。身體端的仲裁器會做；導航預測里程時也用同一組。
RAMP_DV = 0.01
RAMP_DW = 0.05
CONTROL_DT = 0.02


@dataclass
class GaitModel:
    cmd_vx: np.ndarray
    cmd_w: np.ndarray
    vx: np.ndarray  # (len(cmd_vx), len(cmd_w))
    vy: np.ndarray
    w: np.ndarray
    started: np.ndarray
    simulated: bool
    #: 速度建立的一階時間常數（s）。模擬量到起步到 90% 約 1.5 s（含約 0.4 s 的斜率與起步延遲）。
    tau_s: float = 0.45

    FWD_CMD = 0.15
    BACK_CMD = -0.15
    TURN_CMD = 1.0
    TURN_CMD_FINE = 0.6

    @classmethod
    def load(cls, path: str | Path = DEFAULT_TABLE) -> "GaitModel":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        g = lambda k: np.array([[c[k] for c in row] for row in d["cells"]], dtype=float)  # noqa: E731
        return cls(np.array(d["cmd_vx"]), np.array(d["cmd_yaw_rate"]), g("vx"), g("vy"), g("yaw_rate"), g("started"), bool(d.get("simulated", False)))

    def response(self, vx_cmd: float, w_cmd: float) -> tuple[float, float, float]:
        """穩態的實際機身速度（vx, vy, yaw_rate）。在量過的格子之間雙線性內插；沒起步的格子當 0。"""
        i = float(np.interp(vx_cmd, self.cmd_vx, np.arange(len(self.cmd_vx))))
        j = float(np.interp(w_cmd, self.cmd_w, np.arange(len(self.cmd_w))))
        i0, j0 = int(np.floor(i)), int(np.floor(j))
        i1, j1 = min(i0 + 1, len(self.cmd_vx) - 1), min(j0 + 1, len(self.cmd_w) - 1)
        fi, fj = i - i0, j - j0
        out = []
        for tab in (self.vx, self.vy, self.w):
            t = np.where(self.started >= 0.99, tab, 0.0)
            v = (t[i0, j0] * (1 - fi) * (1 - fj) + t[i1, j0] * fi * (1 - fj) + t[i0, j1] * (1 - fi) * fj + t[i1, j1] * fi * fj)
            out.append(float(v))
        return out[0], out[1], out[2]

    def will_start(self, vx_cmd: float, w_cmd: float) -> bool:
        """這個指令從站立起步可不可靠（最近的格子 started == 1，而且不是全 0）。"""
        if abs(vx_cmd) < 1e-9 and abs(w_cmd) < 1e-9:
            return False
        i = int(np.argmin(np.abs(self.cmd_vx - vx_cmd)))
        j = int(np.argmin(np.abs(self.cmd_w - w_cmd)))
        return bool(self.started[i, j] >= 0.99) and not (self.cmd_vx[i] == 0 and self.cmd_w[j] == 0)


def ramp(cur: tuple[float, float, float], target: tuple[float, float, float]) -> tuple[float, float, float]:
    """ADR-0009 §2.5 的加速度限制：一個週期內 vx／vy 最多變 0.01 m/s、yaw 最多變 0.05 rad/s。"""
    out = []
    for c, t, lim in zip(cur, target, (RAMP_DV, RAMP_DV, RAMP_DW)):
        out.append(c + max(-lim, min(lim, t - c)))
    return (out[0], out[1], out[2])
