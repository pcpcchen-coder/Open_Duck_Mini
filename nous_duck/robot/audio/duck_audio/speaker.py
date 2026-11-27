"""找鴨子的喇叭在 ALSA 裡叫什麼名字（換喇叭不用改程式）。

2026-11-27 使用者換了喇叭：舊的是 `e2b7:0811`、ALSA 卡名 `CD002`；新的是 `e2b8:0811`「CD002-AUDIO」、
卡名 `CD002AUDIO`。程式原本寫死 `CD002`，換了就找不到。現在的規則：

1. 環境變數 `DUCK_SPEAKER_DEVICE` 有設就用它（例如 `plughw:CARD=CD002AUDIO,DEV=0`）。
2. 否則在 `/proc/asound/cards` 找 USB 音效卡：卡名以 `CD002` 開頭的優先；
   沒有的話，用唯一一張「不是麥克風（XVF3800，卡名 `Array`）」的 USB 音效卡。
3. 找不到、或有好幾張分不出來：丟 `SpeakerNotFound`，照實說明，**不會**隨便挑一張或退回系統預設。

用卡名（不用編號）指定，USB 插拔順序變了也不會跑掉。

    python -m duck_audio.speaker          # 印出喇叭的 ALSA 裝置名（給 shell 腳本用），找不到就以非 0 結束
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ENV = "DUCK_SPEAKER_DEVICE"
CARDS = Path("/proc/asound/cards")
PREFERRED_PREFIX = "CD002"
#: 不是喇叭的 USB 音效卡（麥克風陣列也有一個播放端，但那是回音消除的參考，不接喇叭）。
NOT_SPEAKER = ("Array",)


class SpeakerNotFound(RuntimeError):
    pass


@dataclass(frozen=True)
class Card:
    index: int
    id: str
    driver: str
    name: str


_LINE = re.compile(r"^\s*(\d+)\s+\[(\S+)\s*\]:\s+(\S+)\s+-\s+(.*)$")


def parse_cards(text: str) -> list[Card]:
    out = []
    for line in text.splitlines():
        m = _LINE.match(line)
        if m:
            out.append(Card(int(m.group(1)), m.group(2), m.group(3), m.group(4).strip()))
    return out


def device_for(card: Card) -> str:
    return f"plughw:CARD={card.id},DEV=0"


def find_speaker(cards_text: str | None = None, env: dict | None = None) -> str:
    env = os.environ if env is None else env
    if env.get(ENV):
        return env[ENV]
    if cards_text is None:
        try:
            cards_text = CARDS.read_text(encoding="utf-8")
        except OSError as e:
            raise SpeakerNotFound(f"讀不到 {CARDS}：{e}") from e
    usb = [c for c in parse_cards(cards_text) if c.driver == "USB-Audio" and c.id not in NOT_SPEAKER]
    preferred = [c for c in usb if c.id.startswith(PREFERRED_PREFIX)]
    if len(preferred) == 1:
        return device_for(preferred[0])
    if not preferred and len(usb) == 1:
        return device_for(usb[0])
    seen = "、".join(f"{c.id}（{c.name}）" for c in usb) or "沒有"
    raise SpeakerNotFound(f"分不出哪一張是喇叭；USB 音效卡：{seen}。請設環境變數 {ENV}")


if __name__ == "__main__":
    try:
        print(find_speaker())
    except SpeakerNotFound as e:
        print(e, file=sys.stderr)
        sys.exit(1)
