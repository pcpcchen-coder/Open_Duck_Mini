"""上限的來源檢查：頭部範圍要落在上游 robot.xml（內縮 2°）與 ADR-0009 §2.5 之內。"""
import math
import re

import pytest
from conftest import REPO

from duckd.limits import ADR_HEAD_RANGE, HEAD_JOINTS, HEAD_SERVO_IDS, LEG_SERVO_IDS, ROBOT_XML_HEAD_RANGE, Limits

ROBOT_XML = REPO / "mini_bdx" / "robots" / "open_duck_mini_v2" / "robot.xml"


def test_default_head_range_inside_adr_and_robot_xml_margin():
    lim = Limits()
    for n in HEAD_JOINTS:
        lo, hi = lim.head_range[n]
        assert ADR_HEAD_RANGE[n][0] <= lo < hi <= ADR_HEAD_RANGE[n][1]
        assert lo >= ROBOT_XML_HEAD_RANGE[n][0] + math.radians(2) - 1e-9
        assert hi <= ROBOT_XML_HEAD_RANGE[n][1] - math.radians(2) + 1e-9
        assert lo <= 0.0 <= hi  # 中立姿勢一定在範圍內


@pytest.mark.skipif(not ROBOT_XML.exists(), reason="上游 robot.xml 不在（Pi 部署目錄）")
def test_robot_xml_ranges_match_upstream_file():
    text = ROBOT_XML.read_text(encoding="utf-8")  # 唯讀
    for n in HEAD_JOINTS:
        m = re.search(rf'<joint name="{n}"[^>]*range="([-\d.e]+) ([-\d.e]+)"', text)
        assert m, n
        assert (float(m.group(1)), float(m.group(2))) == pytest.approx(ROBOT_XML_HEAD_RANGE[n])


def test_ids_and_speed_limits():
    assert set(HEAD_SERVO_IDS.values()) == {30, 31, 32, 33}
    assert not set(HEAD_SERVO_IDS.values()) & LEG_SERVO_IDS
    assert Limits().head_max_speed == pytest.approx(math.radians(30))
    assert Limits().lease_s == 1.5 and Limits().walk_duration_max_s == 3.0
    with pytest.raises(ValueError):
        Limits(head_max_speed=math.radians(120))


@pytest.mark.skipif(not ROBOT_XML.exists(), reason="上游 robot.xml 不在（Pi 部署目錄）")
def test_leg_ranges_match_upstream_file():
    from duckd.limits import LEG_JOINTS, LEG_SERVO_ID_BY_NAME, ROBOT_XML_LEG_RANGE

    text = ROBOT_XML.read_text(encoding="utf-8")  # 唯讀
    for n in LEG_JOINTS:
        m = re.search(rf'<joint name="{n}"[^>]*range="([-\d.e]+) ([-\d.e]+)"', text)
        assert m, n
        assert (float(m.group(1)), float(m.group(2))) == pytest.approx(ROBOT_XML_LEG_RANGE[n])
    assert set(LEG_SERVO_ID_BY_NAME.values()) == LEG_SERVO_IDS
