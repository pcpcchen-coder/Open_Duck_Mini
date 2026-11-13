"""充電座 AprilTag：產生的圖案要能被偵測器讀回正確 ID，repo 裡的 SVG 與程式一致。"""

from dock_cad import params as P
from dock_cad.build import OUT_DIR
from dock_cad.tag import detect_id, tag_bits, tag_svg


def test_tag_bits_decode_to_configured_id():
    bits = tag_bits()
    assert bits.shape == (10, 10)
    assert bits[0].all() and bits[-1].all()  # 最外圈白邊
    assert not bits[1, 1:9].any() and not bits[8, 1:9].any()  # 黑框
    assert detect_id(bits) == [P.TAG_ID]


def test_svg_has_real_size_and_matches_committed_file():
    svg = tag_svg()
    outer = P.TAG_BLACK_SIZE * 10 / 8
    assert f'width="{outer + 20:.1f}mm"' in svg
    assert svg.count("<rect") == 2 + int((tag_bits() == 0).sum())
    committed = (OUT_DIR / f"dock_apriltag_{P.TAG_FAMILY}_id{P.TAG_ID}.svg").read_text(encoding="utf-8")
    assert committed == svg
