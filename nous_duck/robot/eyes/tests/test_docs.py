"""設計文件與程式一致：每個表情、音效代號都有寫進文件。"""

from pathlib import Path

from duck_eyes import EXPRESSIONS, SOUND_CUES

DOC = Path(__file__).resolve().parents[3] / "docs" / "eye_expressions.md"


def test_every_expression_documented():
    text = DOC.read_text(encoding="utf-8")
    for eid, e in EXPRESSIONS.items():
        assert f"`{eid}`" in text, eid
        assert e.name_zh in text, e.name_zh


def test_every_sound_documented_and_known():
    text = DOC.read_text(encoding="utf-8")
    for sid in SOUND_CUES:
        assert f"`{sid}`" in text, sid
    for e in EXPRESSIONS.values():
        assert e.sound is None or e.sound in SOUND_CUES, e.id
