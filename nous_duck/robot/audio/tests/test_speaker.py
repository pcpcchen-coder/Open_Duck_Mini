"""自動找喇叭（`duck_audio.speaker`）。/proc/asound/cards 的內容是 2026-11-26、11-27 在 Pi 上看到的原文。"""

import pytest

from duck_audio.speaker import ENV, SpeakerNotFound, find_speaker, parse_cards

OLD = """ 0 [Headphones     ]: bcm2835_headpho - bcm2835 Headphones
                      bcm2835 Headphones
 1 [CD002          ]: USB-Audio - CD002
                      CD002 CD002 at usb-0000:01:00.0-1.4, full speed
 2 [vc4hdmi0       ]: vc4-hdmi - vc4-hdmi-0
                      vc4-hdmi-0
 4 [Array          ]: USB-Audio - reSpeaker XVF3800 4-Mic Array
                      Seeed Studio reSpeaker XVF3800 4-Mic Array at usb-0000:01:00.0-1.3, high speed
"""
NEW = """ 0 [Headphones     ]: bcm2835_headpho - bcm2835 Headphones
                      bcm2835 Headphones
 1 [Array          ]: USB-Audio - reSpeaker XVF3800 4-Mic Array
                      Seeed Studio reSpeaker XVF3800 4-Mic Array at usb-0000:01:00.0-1.3, high speed
 2 [CD002AUDIO     ]: USB-Audio - CD002-AUDIO
                      Jieli Technology CD002-AUDIO at usb-0000:01:00.0-1.4, full speed
 3 [vc4hdmi0       ]: vc4-hdmi - vc4-hdmi-0
                      vc4-hdmi-0
"""


def test_parse_cards():
    cards = parse_cards(NEW)
    assert [(c.index, c.id, c.driver) for c in cards] == [(0, "Headphones", "bcm2835_headpho"), (1, "Array", "USB-Audio"), (2, "CD002AUDIO", "USB-Audio"), (3, "vc4hdmi0", "vc4-hdmi")]


def test_old_and_new_speaker_found_by_name_not_index():
    assert find_speaker(OLD, env={}) == "plughw:CARD=CD002,DEV=0"
    assert find_speaker(NEW, env={}) == "plughw:CARD=CD002AUDIO,DEV=0"


def test_env_override_wins():
    assert find_speaker(NEW, env={ENV: "plughw:CARD=Other,DEV=0"}) == "plughw:CARD=Other,DEV=0"


def test_single_other_usb_card_is_used_but_mic_never_is():
    other = NEW.replace("CD002AUDIO     ", "MySpeaker      ")
    assert find_speaker(other, env={}) == "plughw:CARD=MySpeaker,DEV=0"
    only_mic = "\n".join(l for l in NEW.splitlines() if "CD002" not in l)
    with pytest.raises(SpeakerNotFound) as e:
        find_speaker(only_mic, env={})
    assert ENV in str(e.value)


def test_ambiguous_raises_instead_of_guessing():
    two = NEW + " 5 [Speaker2       ]: USB-Audio - Speaker2\n"
    assert find_speaker(two, env={}) == "plughw:CARD=CD002AUDIO,DEV=0"  # CD002 開頭的優先
    no_pref = OLD.replace("CD002          ", "SpkA           ") + " 5 [SpkB           ]: USB-Audio - SpkB\n"
    with pytest.raises(SpeakerNotFound):
        find_speaker(no_pref, env={})
