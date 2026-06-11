import pytest

from claude_enter.gestures import HandPose, classify_pose, palm_center


def make_landmarks(extended_fingers):
    """构造 21 个关键点：wrist 在 (0.5, 0.9)，extended_fingers 中的手指伸直，其余卷曲。

    手指编号 0-3 = 食指/中指/无名指/小指（不含拇指）。
    """
    pts = [(0.5, 0.7)] * 21
    pts[0] = (0.5, 0.9)  # wrist
    pips = (6, 10, 14, 18)
    tips = (8, 12, 16, 20)
    for finger in range(4):
        x = 0.35 + finger * 0.1
        pts[pips[finger]] = (x, 0.6)       # PIP 距腕约 0.34
        if finger in extended_fingers:
            pts[tips[finger]] = (x, 0.35)  # 指尖更远 → 伸直
        else:
            pts[tips[finger]] = (x, 0.8)   # 指尖更近 → 卷曲
    return pts


def test_open_palm():
    assert classify_pose(make_landmarks({0, 1, 2, 3})) == HandPose.OPEN_PALM


def test_fist():
    assert classify_pose(make_landmarks(set())) == HandPose.FIST


def test_partial_hand_is_other():
    assert classify_pose(make_landmarks({0, 1})) == HandPose.OTHER


def test_palm_center_is_mean_of_palm_points():
    pts = [(0.0, 0.0)] * 21
    for i in (0, 5, 9, 13, 17):
        pts[i] = (0.5, 0.4)
    center = palm_center(pts)
    assert center[0] == pytest.approx(0.5)
    assert center[1] == pytest.approx(0.4)
