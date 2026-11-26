"""鴨子端語音對話的狀態機（純邏輯，沒有 I/O）：喚醒 → 收音上行 → 等回話 → 播放下行 → 回到待命。

介面：`protocol/proposals/d-duck-voice-media-channel.md`（duck-voice v0，D 線與 B 線的媒體通道草案）。
呼叫端（`voice_service.py`）把事件丟進來，照回傳的動作去做；這樣規則可以不靠硬體測試。

紅線（ADR-0003 §6）在這裡的對應：

- **只有 `LISTENING` 狀態的麥克風音訊會上行**；`on_mic_frame()` 在其他狀態一律回 False。
- 上行從喚醒詞被偵測到**之後**開始，不含喚醒詞之前的音訊（沒有 pre-roll）。
- 沒有連上 Nous 時不收音：喚醒只播「連不上」的提示，不開上行。
- 所有逾時都在鴨子本機，不靠 Nous 記得關：沒人說話、說太久、等不到回話，都會自己結束這一輪。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class State(str, Enum):
    DISABLED = "disabled"  # 設定關掉常駐聆聽：不開麥克風
    IDLE = "idle"  # 只聽喚醒詞（音訊不離開記憶體）
    LISTENING = "listening"  # 喚醒後：麥克風音訊上行
    WAITING = "waiting"  # 上行結束，等 Nous 回話
    SPEAKING = "speaking"  # 下行播放中


@dataclass
class SessionConfig:
    #: 喚醒後一直沒有語音，多久結束這一輪。
    no_speech_timeout_s: float = 8.0
    #: 說完話之後安靜多久，鴨子自己結束這一輪（Nous 的 `listen_stop` 通常會更早到）。
    end_silence_s: float = 1.5
    #: 單輪最長收音時間。
    max_listen_s: float = 30.0
    #: 上行結束後等回話的上限。
    reply_timeout_s: float = 15.0
    #: 下行播完後，等 Nous 決定要不要接著聽（`listen`）的時間；過了就回待命。
    follow_up_grace_s: float = 1.0
    #: 播放時允許喚醒詞打斷（要回音消除夠好才開；預設關＝半雙工）。
    barge_in: bool = False


@dataclass(frozen=True)
class Action:
    """要呼叫端做的事。`kind`：
    `send`（送 JSON 給 Nous，內容在 data）、`sfx`（播本機音效 name）、`uplink`（on: 開關上行）、
    `flush_playback`、`notify`（告訴 duckd 目前狀態 state）、`kws`（on: 喚醒偵測開關）。"""

    kind: str
    data: dict[str, Any] = field(default_factory=dict)


def _send(type_: str, **kw) -> Action:
    return Action("send", {"type": type_, **kw})


class VoiceSession:
    def __init__(self, config: SessionConfig | None = None) -> None:
        self.cfg = config or SessionConfig()
        self.state = State.IDLE
        self.connected = False
        self.turn_id = 0
        self._t_state = 0.0
        self._t_last_speech: float | None = None
        self._heard_speech = False
        self._speak_ended = False
        self._t_play_done: float | None = None
        #: 統計（給 log 與測試）：上行送了幾框、被擋下幾框。
        self.frames_up = 0
        self.frames_blocked = 0

    # ---- 小工具 ----

    def _go(self, state: State, t: float) -> list[Action]:
        self.state = state
        self._t_state = t
        return [Action("notify", {"state": state.value, "turn_id": self.turn_id}),
                Action("kws", {"on": state is State.IDLE or (state is State.SPEAKING and self.cfg.barge_in)})]

    def _end_turn(self, t: float, reason: str, next_state: State) -> list[Action]:
        acts = [Action("uplink", {"on": False}), _send("turn_end", turn_id=self.turn_id, reason=reason)]
        return acts + self._go(next_state, t)

    def _start_listening(self, t: float, trigger: str, keyword_id: str | None, doa_deg: float | None) -> list[Action]:
        self.turn_id += 1
        self._heard_speech = False
        self._t_last_speech = None
        self._speak_ended = False
        self._t_play_done = None
        acts = self._go(State.LISTENING, t)
        acts.append(_send("turn_start", turn_id=self.turn_id, trigger=trigger, keyword_id=keyword_id, doa_deg=doa_deg))
        acts.append(Action("uplink", {"on": True}))
        return acts

    # ---- 事件 ----

    def set_enabled(self, enabled: bool, t: float) -> list[Action]:
        """設定頁的「常駐喚醒聆聽」。關掉：立刻結束目前這一輪並停止一切收音。"""
        if not enabled and self.state is not State.DISABLED:
            acts: list[Action] = []
            if self.state is State.LISTENING:
                acts += [Action("uplink", {"on": False}), _send("turn_end", turn_id=self.turn_id, reason="cancelled")]
            if self.state is State.SPEAKING:
                acts.append(Action("flush_playback"))
            self.state = State.DISABLED
            self._t_state = t
            return acts + [Action("notify", {"state": "disabled", "turn_id": self.turn_id}), Action("kws", {"on": False})]
        if enabled and self.state is State.DISABLED:
            return self._go(State.IDLE, t)
        return []

    def on_link(self, connected: bool, t: float) -> list[Action]:
        self.connected = connected
        if connected or self.state in (State.IDLE, State.DISABLED):
            return []
        # 斷線＝本輪結束：停止收音、丟掉還沒播的、回到只聽喚醒詞
        acts = [Action("uplink", {"on": False}), Action("flush_playback")]
        return acts + self._go(State.IDLE, t)

    def on_wake(self, t: float, keyword_id: str, doa_deg: float | None = None) -> list[Action]:
        if self.state is State.SPEAKING and self.cfg.barge_in:
            acts = [Action("flush_playback"), _send("playback", turn_id=self.turn_id, state="flushed")]
            if not self.connected:
                return acts + self._go(State.IDLE, t)
            return acts + [Action("sfx", {"name": "listen_on"})] + self._start_listening(t, "wake_word", keyword_id, doa_deg)
        if self.state is not State.IDLE:
            return []
        if not self.connected:
            # 連不上 Nous：不收音，只用提示音照實告訴使用者
            return [Action("sfx", {"name": "confused_hm"}), Action("notify", {"state": "error", "reason": "nous_unreachable", "turn_id": self.turn_id})]
        return [Action("sfx", {"name": "listen_on"})] + self._start_listening(t, "wake_word", keyword_id, doa_deg)

    def on_mic_frame(self, t: float, is_speech: bool) -> bool:
        """每一框麥克風音訊問一次：這一框可不可以上行。只有 LISTENING 回 True。"""
        if self.state is not State.LISTENING:
            self.frames_blocked += 1
            return False
        if is_speech:
            self._heard_speech = True
            self._t_last_speech = t
        self.frames_up += 1
        return True

    def on_remote(self, msg: dict[str, Any], t: float) -> list[Action]:
        """Nous 送來的控制訊息。不認得或不合時宜的訊息忽略（不讓對方把鴨子推進奇怪的狀態）。"""
        kind = msg.get("type")
        tid = msg.get("turn_id")
        if kind == "listen_stop":
            if self.state is State.LISTENING and tid == self.turn_id:
                return self._end_turn(t, "remote", State.WAITING)
        elif kind == "speak_start":
            if self.state in (State.WAITING, State.LISTENING) and tid == self.turn_id:
                acts = self._end_turn(t, "remote", State.SPEAKING) if self.state is State.LISTENING else self._go(State.SPEAKING, t)
                self._speak_ended = False
                self._t_play_done = None
                return acts
        elif kind == "speak_end":
            if self.state is State.SPEAKING and tid == self.turn_id:
                self._speak_ended = True
        elif kind == "flush":
            if self.state is State.SPEAKING:
                self._speak_ended = True
                return [Action("flush_playback"), _send("playback", turn_id=self.turn_id, state="flushed")]
        elif kind == "listen":
            # 連續對話：Nous 要求不用喚醒詞再聽一輪。只在剛說完話（或等回話）時接受，待命時不接受
            # ——否則等於讓遠端隨時開麥克風，違反「喚醒只由鴨子本機決定」。
            if self.connected and (self.state is State.WAITING or (self.state is State.SPEAKING and self._t_play_done is not None)):
                return self._start_listening(t, "follow_up", None, None)
        elif kind == "session_end":
            if self.state not in (State.IDLE, State.DISABLED):
                acts = [Action("flush_playback")]
                if self.state is State.LISTENING:
                    acts += [Action("uplink", {"on": False})]
                return acts + self._go(State.IDLE, t)
        return []

    def accepts_downlink(self) -> bool:
        """下行 PCM 只在 SPEAKING 且還沒 speak_end／flush 時收。"""
        return self.state is State.SPEAKING and not self._speak_ended

    def on_playback_done(self, t: float) -> list[Action]:
        """播放端回報：這一輪的聲音真的播完了（或被丟掉）。"""
        if self.state is State.SPEAKING and self._t_play_done is None:
            self._t_play_done = t
            return [_send("playback", turn_id=self.turn_id, state="finished")]
        return []

    def on_playback_started(self) -> list[Action]:
        return [_send("playback", turn_id=self.turn_id, state="started")] if self.state is State.SPEAKING else []

    def tick(self, t: float) -> list[Action]:
        """定時呼叫（例如每 100 ms）：處理逾時。"""
        cfg = self.cfg
        if self.state is State.LISTENING:
            elapsed = t - self._t_state
            if elapsed >= cfg.max_listen_s:
                return self._end_turn(t, "max_duration", State.WAITING)
            if not self._heard_speech and elapsed >= cfg.no_speech_timeout_s:
                return self._end_turn(t, "no_speech", State.IDLE) + [Action("sfx", {"name": "listen_off"})]
            if self._heard_speech and self._t_last_speech is not None and t - self._t_last_speech >= cfg.end_silence_s:
                return self._end_turn(t, "silence", State.WAITING)
        elif self.state is State.WAITING:
            if t - self._t_state >= cfg.reply_timeout_s:
                return [Action("sfx", {"name": "confused_hm"})] + self._go(State.IDLE, t)
        elif self.state is State.SPEAKING:
            if self._speak_ended and self._t_play_done is not None and t - self._t_play_done >= cfg.follow_up_grace_s:
                return self._go(State.IDLE, t)
            if not self._speak_ended and t - self._t_state >= 120.0:
                return [Action("flush_playback")] + self._go(State.IDLE, t)  # 對方一直不結束：保險絲
        return []
