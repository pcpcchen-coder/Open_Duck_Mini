"""喇叭的硬體音量（ALSA 混音器）：對話的聲音與本機提示音都經過它。

路線 2 的對話聲音是 Pi 上的 Chromium 直接送到喇叭（`--alsa-output-device=plughw:CARD=…`），不經過
`playback.py` 的軟體增益，所以「對話音量」只能調喇叭那張 USB 音效卡的硬體音量。

- 用 `amixer` 的 mapped volume（`-M`）：百分比照聽感對應（依卡片回報的 dB 範圍），50% 大約是「聽起來一半」，
  不是原始刻度的一半。
- 控制項：優先 `PCM`，再來 `Speaker`、`Master`，都沒有就用第一個能調播放音量的。
- 讀不到、寫不進去都丟 `MixerError` 並說明原因，**不假裝設好了**；設完一定回讀。
- 只改音量與靜音開關，不存 ALSA 狀態檔（`alsactl store`），也不碰麥克風那張卡。

    python -m duck_audio.mixer            # 印出喇叭卡、控制項、目前音量
    python -m duck_audio.mixer 60         # 設成 60%（回讀後印出）
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable

PREFERRED_CONTROLS = ("PCM", "Speaker", "Master")
#: 設定值和回讀值差這麼多以內算「已套用」（mapped volume 換算回原始刻度會有捨入）。
TOLERANCE_PCT = 2


class MixerError(RuntimeError):
    pass


def card_of(device: str) -> str:
    """`plughw:CARD=CD002AUDIO,DEV=0` → `CD002AUDIO`；`hw:2,0` → `2`。"""
    m = re.search(r"CARD=([A-Za-z0-9_]+)", device)
    if m:
        return m.group(1)
    m = re.match(r"^(?:plug)?hw:([A-Za-z0-9_]+)", device)
    if m:
        return m.group(1)
    raise MixerError(f"從喇叭裝置名 {device!r} 找不出是哪一張音效卡")


_CONTROL = re.compile(r"^Simple mixer control '([^']+)',(\d+)$")
_PCT = re.compile(r"\[(\d{1,3})%\]")


def parse_playback_controls(scontents: str) -> list[str]:
    """`amixer scontents` → 能調播放音量的控制項名稱（照出現順序）。"""
    out: list[str] = []
    name = None
    for line in scontents.splitlines():
        m = _CONTROL.match(line.strip())
        if m:
            name = m.group(1) if m.group(2) == "0" else None
            continue
        if name and line.strip().startswith("Capabilities:") and re.search(r"\b(pvolume|volume)\b", line):
            out.append(name)
            name = None
    return out


def parse_percent(sget: str) -> int:
    """`amixer sget` 的輸出 → 音量百分比（各聲道取平均、四捨五入）。"""
    values = [int(v) for v in _PCT.findall(sget)]
    if not values:
        raise MixerError("amixer 的輸出裡沒有音量百分比")
    return round(sum(values) / len(values))


def parse_muted(sget: str) -> bool:
    switches = re.findall(r"\[(on|off)\]", sget)
    return bool(switches) and all(s == "off" for s in switches)


@dataclass
class SpeakerMixer:
    """一張音效卡的播放音量。`run` 可以換成假的（測試用）。"""

    card: str
    run: Callable[[list[str]], str] | None = None
    control: str | None = None

    def _amixer(self, *args: str) -> str:
        cmd = ["amixer", "-c", self.card, *args]
        if self.run is not None:
            return self.run(cmd)
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        except FileNotFoundError as e:
            raise MixerError("找不到 amixer（需要 alsa-utils）") from e
        except subprocess.TimeoutExpired as e:
            raise MixerError(f"amixer 逾時（{' '.join(cmd)}）") from e
        if r.returncode != 0:
            raise MixerError(f"amixer 失敗：{(r.stderr or r.stdout).strip()[:160]}")
        return r.stdout

    def pick_control(self) -> str:
        if self.control:
            return self.control
        names = parse_playback_controls(self._amixer("scontents"))
        if not names:
            raise MixerError(f"音效卡 {self.card} 沒有可以調播放音量的控制項")
        self.control = next((n for n in PREFERRED_CONTROLS if n in names), names[0])
        return self.control

    def get(self) -> int:
        return parse_percent(self._amixer("-M", "sget", self.pick_control()))

    def muted(self) -> bool:
        return parse_muted(self._amixer("-M", "sget", self.pick_control()))

    def set(self, percent: int) -> int:
        """設成 `percent`（0～100，mapped），打開靜音開關，回讀後回傳實際的值。"""
        if isinstance(percent, bool) or not 0 <= percent <= 100:
            raise MixerError(f"音量要在 0～100，不是 {percent!r}")
        control = self.pick_control()
        self._amixer("-q", "-M", "sset", control, f"{int(round(percent))}%", "unmute")
        out = self._amixer("-M", "sget", control)
        if parse_muted(out):
            raise MixerError(f"{self.card} 的 {control} 還是靜音（設不掉）")
        return parse_percent(out)


def main(argv: list[str] | None = None) -> int:
    from .speaker import SpeakerNotFound, find_speaker  # noqa: PLC0415

    argv = sys.argv[1:] if argv is None else argv
    try:
        mixer = SpeakerMixer(card_of(find_speaker()))
        if argv:
            actual = mixer.set(int(argv[0]))
            print(f"{mixer.card} {mixer.control}：設成 {argv[0]}%，回讀 {actual}%")
        else:
            print(f"{mixer.card} {mixer.pick_control()}：{mixer.get()}%{'（靜音）' if mixer.muted() else ''}")
    except (SpeakerNotFound, MixerError, ValueError) as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
