"""說話時看著對方（批次 V3）：依人臉在畫面中的位置，算出頭部目標角度與轉身角速度。

規劃見 `nous_duck/docs/stereo_vision_plan.md` §3.3 P2、§7 V3。

在**感知服務**裡執行（ADR-0008：目前和步態＋安全服務在同一片 Pi 4，但分成不同服務）：輸入
人臉偵測結果（只有位置與大小，沒有影像、沒有身分），輸出上游 runtime 7 維指令裡的頭部 4 維
（neck_pitch、head_pitch、head_yaw、head_roll）與轉身角速度（ang_vel）。輸出只是**請求**：
步態＋安全服務的 safety 仍要再夾限；走路中、隱私設定不允許、或沒有對話時，由上層不呼叫或停用
這個控制器。

座標與正負號（用上游 `robot.xml` 在 MuJoCo 中確認，見 `docs/validation/look-at-sim-2026-11-16.md`）：

- 視線俯仰（gaze pitch）≈ neck_pitch + head_pitch，**正值＝抬頭**。
- 視線偏航（gaze yaw）＝ head_yaw，**正值＝往左**。
- 轉身角速度正值＝往左轉（逆時針）。上游 runtime 的 ang_vel 正負號**尚未在實機確認**。

頭部角度範圍預設取上游 runtime 手把的範圍（`xbox_controller.py`，v2 `376de65`），也就是步態
策略訓練時看過的頭部指令範圍；neck_pitch 上限先保守取 0.6 rad（上游 1.1），因為抬頸會讓
頭往後移，站立平衡要在模擬與實機確認後才放寬。

驗證層級：單元測試＋MuJoCo 運動學模擬（固定機身、合成人臉偵測）。**未實機。**
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum


# ---------------------------------------------------------------- 資料型別


@dataclass(frozen=True)
class CameraIntrinsics:
    """左眼影像的針孔內參（像素）。"""

    fx: float
    fy: float
    cx: float
    cy: float
    width: int
    height: int

    @classmethod
    def ar0144_nominal(cls, width: int = 1280, height: int = 720, hfov_deg: float = 65.0) -> "CameraIntrinsics":
        """AR0144 的名目內參（未校正）。V1 雙目校正後要換成實測值。"""
        f = (width / 2) / math.tan(math.radians(hfov_deg) / 2)
        return cls(fx=f, fy=f, cx=width / 2, cy=height / 2, width=width, height=height)

    def ray_angles(self, u: float, v: float) -> tuple[float, float]:
        """像素相對光軸的（偏航，俯仰）弧度；往左、往上為正。"""
        return math.atan2(self.cx - u, self.fx), math.atan2(self.cy - v, self.fy)


@dataclass(frozen=True)
class Gaze:
    """鏡頭視線相對身體正前方的方向（弧度）。yaw 往左為正，pitch 往上為正。"""

    yaw: float
    pitch: float


@dataclass(frozen=True)
class Face:
    """一個人臉偵測結果。只有位置與大小，不含影像或身分。"""

    u: float  # 臉中心（像素）
    v: float
    width: float  # 臉寬（像素）
    score: float = 1.0
    track_id: int | None = None  # 偵測器有追蹤時提供；沒有就靠角度配對


@dataclass(frozen=True)
class VisionFrame:
    """一張影像的偵測結果。"""

    t_capture: float  # 拍攝時間（秒，單調時鐘）
    faces: tuple[Face, ...]
    #: 拍攝當下的頭部視線（由舵機回讀換算）。沒有回讀時給 None，改用控制器自己的指令值。
    gaze_at_capture: Gaze | None = None


@dataclass(frozen=True)
class SpeakerDirection:
    """麥克風陣列給的說話者方向（身體座標，往左為正）。"""

    t: float
    azimuth: float


@dataclass(frozen=True)
class HeadLimits:
    neck_pitch: tuple[float, float] = (-0.34, 0.6)
    head_pitch: tuple[float, float] = (-0.78, 0.3)
    head_yaw: tuple[float, float] = (-0.5, 0.5)

    @property
    def gaze_pitch(self) -> tuple[float, float]:
        return (self.neck_pitch[0] + self.head_pitch[0], self.neck_pitch[1] + self.head_pitch[1])


@dataclass
class LookAtConfig:
    intrinsics: CameraIntrinsics = field(default_factory=CameraIntrinsics.ar0144_nominal)
    limits: HeadLimits = field(default_factory=HeadLimits)
    #: 已經看準時，誤差小於 resume 就不再追（避免偵測雜訊讓頭一直抖）。
    deadband: float = math.radians(2.0)
    resume: float = math.radians(5.0)
    #: 頭部指令趨近目標的時間常數與最大角速度（初始值，模擬中調整，實機要再調）。
    time_constant_s: float = 0.2
    max_rate_yaw: float = 2.0
    max_rate_pitch: float = 1.5
    min_score: float = 0.5
    #: 同一個人的配對門檻：新偵測和目前目標的角度差在這之內，就當成同一個人。
    match_gate: float = math.radians(10.0)
    #: 換人要連續偏好新的人這麼久才換（避免兩人之間來回跳）。
    switch_confirm_s: float = 0.6
    #: 說話者方向：跟人臉角度差在這之內才算是同一個人；超過這個時間的方向不用。
    speaker_gate: float = math.radians(25.0)
    speaker_max_age_s: float = 3.0
    #: 說話者方向和正在看的人差超過 speaker_gate、又持續這麼久（畫面裡也沒有對得上的臉，
    #: 例如說話的人在視野外），就放下目前的人，轉向說話者去找。
    speaker_search_after_s: float = 1.0
    #: 人臉不見後，先停在原處等多久；再過多久回到正前方。
    lost_hold_s: float = 1.0
    return_after_s: float = 4.0
    #: 對話中沒看到臉時的視線俯仰：人臉通常比鴨子高很多，平視只看得到約 20° 以內。
    #: 找人時在 rest_pitch 與 high_pitch 之間上下看，每個高度停 scan_dwell_s。
    rest_pitch: float = 0.4
    high_pitch: float = 0.9
    scan_dwell_s: float = 1.5
    #: 啟用或最後一次看到人、聽到說話者之後，最多找這麼久；之後停在 rest_pitch。
    scan_timeout_s: float = 8.0
    #: 舵機實際角度與指令的差（重力、背隙）估計的平滑係數（每張影像）。
    offset_alpha: float = 0.3
    #: 轉身：視線偏航超過 start 就開始轉，回到 stop 以內就停。
    allow_body_turn: bool = True
    body_turn_start: float = 0.35
    body_turn_stop: float = 0.08
    body_turn_gain: float = 1.5
    body_turn_max: float = 0.5


class LookState(str, Enum):
    IDLE = "idle"  # 停用（回到正前方），或找不到人、停在休息視線
    TRACKING = "tracking"  # 看著某個人
    HOLD = "hold"  # 人臉短暫不見，停在原處
    SEARCH = "search"  # 還沒看到臉：朝說話者方向（沒有就正前方）上下找


@dataclass(frozen=True)
class LookCommand:
    """輸出：上游 runtime 指令向量的 ang_vel 與頭部 4 維，加上狀態。"""

    neck_pitch: float
    head_pitch: float
    head_yaw: float
    head_roll: float
    body_yaw_rate: float
    state: LookState
    target_id: int | None
    #: 想看的方向超出頭部範圍（例如人太近、太高）；行為層可以考慮後退一點。
    pitch_saturated: bool
    yaw_saturated: bool


# ---------------------------------------------------------------- 工具函式


def _clip(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _ang_dist(a: Gaze, b: Gaze) -> float:
    return math.hypot(a.yaw - b.yaw, a.pitch - b.pitch)


def allocate_pitch(gaze_pitch: float, limits: HeadLimits) -> tuple[float, float, bool]:
    """把視線俯仰分給 head_pitch 與 neck_pitch：先用 head_pitch，不夠再動脖子。

    回傳（neck_pitch, head_pitch, 是否超出範圍）。
    """
    head = _clip(gaze_pitch, *limits.head_pitch)
    neck_wanted = gaze_pitch - head
    neck = _clip(neck_wanted, *limits.neck_pitch)
    return neck, head, abs(neck - neck_wanted) > 1e-9


# ---------------------------------------------------------------- 控制器


@dataclass
class _Target:
    direction: Gaze  # 身體座標
    last_seen: float
    width: float
    track_id: int | None
    uid: int


class LookAtController:
    """說話時看著對方。每個控制週期呼叫一次 `step()`（上游 runtime 是 50 Hz）。"""

    def __init__(self, config: LookAtConfig | None = None) -> None:
        self.cfg = config or LookAtConfig()
        self._active = False
        self._cmd = Gaze(0.0, 0.0)
        self._desired = Gaze(0.0, 0.0)
        self._settled = True
        self._target: _Target | None = None
        self._candidate: _Target | None = None  # 換人候選
        self._candidate_since: float | None = None
        self._next_uid = 1
        self._turning = False
        self._body_rate_cmd = 0.0
        self._last_t: float | None = None
        self._state = LookState.IDLE
        #: 累積的身體轉角（由量測角速度積分），用來修正舊的說話者方向。
        self._body_yaw = 0.0
        self._speaker_ref: tuple[float, float] | None = None  # (speaker.t, 當時的 _body_yaw)
        self._search_since: float | None = None
        self._speaker_mismatch_since: float | None = None
        self._last_activity: float | None = None  # 最後一次看到人或聽到說話者
        #: 舵機實際視線 − 指令視線（重力下垂、背隙）的估計
        self._offset = Gaze(0.0, 0.0)
        self._cmd_history: list[tuple[float, Gaze]] = []
        #: 換了幾次人（看過 A 之後改看 B 算一次；同一個人不見後再找到不算）
        self.switch_count = 0
        self._last_adopted_uid: int | None = None

    # ---- 啟用與停用 ----

    def activate(self) -> None:
        if not self._active:
            self._active = True
            self._search_since = None
            self._last_activity = None

    def deactivate(self) -> None:
        """停用：慢慢回到正前方、不轉身、忘記目前的人。"""
        self._active = False
        self._target = None
        self._candidate = None
        self._candidate_since = None
        self._desired = Gaze(0.0, 0.0)
        self._settled = False
        self._turning = False

    @property
    def state(self) -> LookState:
        return self._state

    @property
    def commanded_gaze(self) -> Gaze:
        return self._cmd

    # ---- 主迴圈 ----

    def step(
        self,
        t: float,
        frame: VisionFrame | None = None,
        speaker: SpeakerDirection | None = None,
        measured_body_yaw_rate: float | None = None,
    ) -> LookCommand:
        """推進一個控制週期。

        - `frame`：這個週期有新的偵測結果才給。
        - `speaker`：最近一次說話者方向（可以每次都給同一筆，控制器會看時間）。
        - `measured_body_yaw_rate`：IMU 量到的身體轉動角速度（rad/s，往左為正）。
          身體在轉時，人相對身體的方向會反向移動；有量測值就用它補償，沒有就假設沒在轉。
        """
        cfg = self.cfg
        dt = 0.0 if self._last_t is None else max(0.0, t - self._last_t)
        self._last_t = t

        # 1. 身體轉動補償：人相對身體的方位角反向變化
        if measured_body_yaw_rate and dt > 0:
            shift = measured_body_yaw_rate * dt
            self._body_yaw += shift
            if self._target is not None:
                d = self._target.direction
                self._target.direction = Gaze(d.yaw - shift, d.pitch)
            if self._candidate is not None:
                d = self._candidate.direction
                self._candidate.direction = Gaze(d.yaw - shift, d.pitch)
            self._desired = Gaze(self._desired.yaw - shift, self._desired.pitch)

        speaker_dir = None
        if speaker is not None and t - speaker.t <= cfg.speaker_max_age_s:
            if self._speaker_ref is None or self._speaker_ref[0] != speaker.t:
                self._speaker_ref = (speaker.t, self._body_yaw)
            # 說話者方向是當時相對身體的角度；身體之後轉了多少要扣掉
            speaker_dir = speaker.azimuth - (self._body_yaw - self._speaker_ref[1])

        # 2. 新的偵測結果：配對、選人
        if self._active and frame is not None:
            self._ingest(frame, speaker_dir)
        if self._active:
            # 剛啟用、或聽到有人說話：之後 scan_timeout_s 內沒看到臉就上下找
            if self._last_activity is None:
                self._last_activity = t
            if speaker_dir is not None and speaker is not None:
                self._last_activity = max(self._last_activity, speaker.t)

        # 說話的人不是正在看的人（而且不在畫面裡，所以上面沒有換人）：放下目前的人，轉向說話者
        if self._active and speaker_dir is not None and self._target is not None and abs(
            speaker_dir - self._target.direction.yaw
        ) > cfg.speaker_gate:
            if self._speaker_mismatch_since is None:
                self._speaker_mismatch_since = t
            elif t - self._speaker_mismatch_since >= cfg.speaker_search_after_s:
                self._target = None
                self._speaker_mismatch_since = None
        else:
            self._speaker_mismatch_since = None

        # 3. 決定想看的方向（指令空間：扣掉舵機下垂等誤差）
        off = self._offset
        if not self._active:
            self._state = LookState.IDLE
            self._set_desired(Gaze(0.0, 0.0), force=True)
        elif self._target is not None and t - self._target.last_seen <= cfg.lost_hold_s:
            self._state = LookState.TRACKING
            self._search_since = None
            d = self._target.direction
            self._set_desired(Gaze(d.yaw - off.yaw, d.pitch - off.pitch))
        elif speaker_dir is None and self._target is not None and t - self._target.last_seen <= cfg.return_after_s:
            self._state = LookState.HOLD
        else:
            self._target = None
            recent = self._last_activity is not None and t - self._last_activity <= cfg.scan_timeout_s
            if speaker_dir is not None or recent:
                self._state = LookState.SEARCH
                if self._search_since is None:
                    self._search_since = t
                phase = int((t - self._search_since) / cfg.scan_dwell_s) % 2
                pitch = cfg.rest_pitch if phase == 0 else cfg.high_pitch
                yaw = 0.0 if speaker_dir is None else speaker_dir - off.yaw
                self._set_desired(Gaze(yaw, pitch), force=True)
            else:
                self._state = LookState.IDLE
                self._search_since = None
                self._set_desired(Gaze(0.0, cfg.rest_pitch), force=True)

        # 4. 轉身：想看的方向偏太多時，請身體轉過去，讓頭回到中間
        body_rate = 0.0
        if self._active and cfg.allow_body_turn:
            yaw_err = self._desired.yaw
            if abs(yaw_err) > cfg.body_turn_start:
                self._turning = True
            elif abs(yaw_err) < cfg.body_turn_stop:
                self._turning = False
            if self._turning:
                body_rate = _clip(cfg.body_turn_gain * yaw_err, -cfg.body_turn_max, cfg.body_turn_max)
        else:
            self._turning = False
        self._body_rate_cmd = body_rate

        # 5. 頭部指令平滑趨近
        lim = cfg.limits
        if dt > 0:
            a = 1.0 - math.exp(-dt / cfg.time_constant_s)
            dy = _clip((self._desired.yaw - self._cmd.yaw) * a, -cfg.max_rate_yaw * dt, cfg.max_rate_yaw * dt)
            dp = _clip((self._desired.pitch - self._cmd.pitch) * a, -cfg.max_rate_pitch * dt, cfg.max_rate_pitch * dt)
            self._cmd = Gaze(self._cmd.yaw + dy, self._cmd.pitch + dp)
        yaw = _clip(self._cmd.yaw, *lim.head_yaw)
        pitch = _clip(self._cmd.pitch, *lim.gaze_pitch)
        self._cmd = Gaze(yaw, pitch)
        self._cmd_history.append((t, self._cmd))
        if len(self._cmd_history) > 200:
            del self._cmd_history[:100]
        if _ang_dist(self._cmd, self._desired) < cfg.deadband:
            self._settled = True

        neck, head, _ = allocate_pitch(pitch, lim)
        _, _, pitch_sat = allocate_pitch(self._desired.pitch, lim)
        yaw_sat = not (lim.head_yaw[0] <= self._desired.yaw <= lim.head_yaw[1])
        return LookCommand(
            neck_pitch=neck,
            head_pitch=head,
            head_yaw=yaw,
            head_roll=0.0,
            body_yaw_rate=body_rate,
            state=self._state,
            target_id=None if self._target is None else self._target.uid,
            pitch_saturated=pitch_sat,
            yaw_saturated=yaw_sat,
        )

    # ---- 內部 ----

    def _set_desired(self, g: Gaze, force: bool = False) -> None:
        """更新想看的方向；已經看準時，小於 resume 的變化不追。"""
        if force or not self._settled or _ang_dist(g, self._cmd) > self.cfg.resume:
            if _ang_dist(g, self._desired) > 1e-12:
                self._desired = g
                if _ang_dist(g, self._cmd) >= self.cfg.deadband:
                    self._settled = False

    def _ingest(self, frame: VisionFrame, speaker_dir: float | None) -> None:
        cfg = self.cfg
        cmd_cap = self._cmd_at(frame.t_capture)
        if frame.gaze_at_capture is not None:
            gaze = frame.gaze_at_capture
            a = cfg.offset_alpha
            self._offset = Gaze(
                self._offset.yaw + a * (gaze.yaw - cmd_cap.yaw - self._offset.yaw),
                self._offset.pitch + a * (gaze.pitch - cmd_cap.pitch - self._offset.pitch),
            )
        else:
            gaze = Gaze(cmd_cap.yaw + self._offset.yaw, cmd_cap.pitch + self._offset.pitch)
        dets: list[_Target] = []
        for f in frame.faces:
            if f.score < cfg.min_score:
                continue
            dy, dp = cfg.intrinsics.ray_angles(f.u, f.v)
            dets.append(
                _Target(Gaze(gaze.yaw + dy, gaze.pitch + dp), frame.t_capture, f.width, f.track_id, uid=0)
            )
        if not dets:
            return
        self._last_activity = frame.t_capture if self._last_activity is None else max(self._last_activity, frame.t_capture)

        def match(ref: _Target | None) -> _Target | None:
            if ref is None:
                return None
            if ref.track_id is not None:
                for d in dets:
                    if d.track_id == ref.track_id:
                        return d
            best = min(dets, key=lambda d: _ang_dist(d.direction, ref.direction))
            return best if _ang_dist(best.direction, ref.direction) <= cfg.match_gate else None

        def by_speaker() -> _Target | None:
            if speaker_dir is not None:
                near = min(dets, key=lambda d: abs(d.direction.yaw - speaker_dir))
                if abs(near.direction.yaw - speaker_dir) <= cfg.speaker_gate:
                    return near
            return None

        def preferred() -> _Target | None:
            # 選人：有說話者方向時只選那個方向的臉（沒有就繼續轉向說話者找）；
            # 沒有說話者方向時選最近（臉最大）的人
            if speaker_dir is not None:
                return by_speaker()
            return max(dets, key=lambda d: d.width)

        current = match(self._target)
        if current is not None:
            current.uid = self._target.uid  # type: ignore[union-attr]
            self._target = current

        if self._target is None or current is None and frame.t_capture - self._target.last_seen > cfg.lost_hold_s:
            # 沒有目標，或目標不見太久：直接看最合適的人
            pick = preferred()
            if pick is not None:
                self._adopt(pick)
            return

        if current is None:
            # 目前的人這張沒看到，但還在等待時間內：不換人
            return
        # 已經在看某個人時，只有說話者方向指向別人才換（臉比較大不算理由）
        pref = by_speaker()
        if pref is None or pref is current:
            self._candidate = None
            self._candidate_since = None
            return
        # 有另一個更合適的人（例如說話者方向指向他）：連續偏好一段時間才換
        cand = match(self._candidate)
        if cand is not None and (cand is pref):
            cand.uid = self._candidate.uid  # type: ignore[union-attr]
            self._candidate = cand
            if frame.t_capture - (self._candidate_since or frame.t_capture) >= cfg.switch_confirm_s:
                self._adopt(cand)
        else:
            pref.uid = self._new_uid()
            self._candidate = pref
            self._candidate_since = frame.t_capture

    def _adopt(self, t: _Target) -> None:
        if t.uid == 0:
            t.uid = self._new_uid()
        if self._last_adopted_uid is not None and t.uid != self._last_adopted_uid:
            self.switch_count += 1
        self._last_adopted_uid = t.uid
        self._target = t
        self._candidate = None
        self._candidate_since = None
        self._settled = False

    def _cmd_at(self, t: float) -> Gaze:
        """拍攝當下的指令視線（偵測結果有延遲，要和當時的指令比）。"""
        best = self._cmd
        for tt, g in reversed(self._cmd_history):
            best = g
            if tt <= t:
                break
        return best

    def _new_uid(self) -> int:
        uid = self._next_uid
        self._next_uid += 1
        return uid
