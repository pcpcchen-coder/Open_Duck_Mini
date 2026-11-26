"""導航核心對外的兩個抽象：`SensorFrame`（進）與 `NavOutput`（出）。

誰來填 `SensorFrame`、誰來執行 `NavOutput`，導航核心不管：
模擬裡是 `sim/nav_sim`，實機上會是 perception（標籤、障礙）與 duckd（速度指令、IMU、充電訊號）。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TagObservation:
    """一個 AprilTag 在**機身座標**的平面位姿（perception 已經用頭頸關節角把鏡頭座標換算過來）。"""

    tag_id: int
    x: float  # 標籤中心，機身座標，m（前）
    y: float  # m（左）
    yaw: float  # 標籤面朝的方向，相對機身朝向，rad
    sigma_xy: float = 0.03  # 位置的標準差估計，m
    sigma_yaw: float = 0.08  # 方向的標準差估計，rad
    mock: bool = False  # 幾何合成的觀測（不是真的偵測器）


@dataclass(frozen=True)
class HeadTarget:
    """頭部目標（rad，上游 runtime 的關節慣例）。"""

    neck_pitch: float = 0.0
    head_pitch: float = 0.0
    head_yaw: float = 0.0
    head_roll: float = 0.0


@dataclass
class SensorFrame:
    """一個控制週期的感測輸入。"""

    t: float  # 單調時間，s
    dt: float  # 距離上一個 frame 的時間，s
    tags: list[TagObservation] = field(default_factory=list)
    #: 偏航角速度（rad/s，逆時針為正），來自 IMU 陀螺儀；沒有就 None，改用步態反應表。
    gyro_z: float | None = None
    #: 上一個週期**實際送給步態**的速度指令（經過身體端 safety 夾限與加速度限制之後）；
    #: None 表示不知道，導航用自己上一筆輸出代替。
    applied_cmd: tuple[float, float, float] | None = None
    #: 前方障礙點（機身座標，m），來自深度；沒有深度就空清單。
    obstacles: list[tuple[float, float]] = field(default_factory=list)
    #: 這個 frame 的深度有沒有更新（有更新才能把「沒看到障礙」當成清空的依據）。
    obstacles_valid: bool = False
    #: 身體端 safety 判定跌倒。
    fallen: bool = False
    #: 被抱起來（身體端由足底開關與 IMU 判斷，對應 duck-link 的 `picked_up` 事件）。
    #: 被抱起來之後位置就不可信，導航會丟掉目前的定位、重新找標籤。
    lifted: bool = False
    #: 兩腳是否有在交替離地（由足底開關判斷）；None 表示不知道。
    stepping: bool | None = None
    #: 電氣上的充電訊號（充電板或電流感測）；None 表示沒有這個感測器。
    charging: bool | None = None
    #: 充電訊號是不是 mock（模擬裡一定是 True）。
    charging_mock: bool = False
    #: 頭部偏航的回讀（rad），用來判斷轉頭掃描有沒有到位；None 表示不知道。
    head_yaw: float | None = None


@dataclass
class NavOutput:
    """一個控制週期的輸出。`active` 為 False 時導航不要求控制權（速度一定是 0）。"""

    vx: float = 0.0
    vy: float = 0.0
    yaw_rate: float = 0.0
    head: HeadTarget = field(default_factory=HeadTarget)
    #: duck-link v0 形狀的事件（`mission_progress`、`mission_done`、`mission_failed`、`docked`、`charging_started`）。
    events: list[dict] = field(default_factory=list)
    active: bool = False

    @property
    def velocity(self) -> tuple[float, float, float]:
        return (self.vx, self.vy, self.yaw_rate)
