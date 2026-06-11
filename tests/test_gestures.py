import pytest

from claude_enter.gestures import (
    HandPose,
    SwipeDetector,
    classify_pose,
    palm_center,
)


def make_landmarks(extended_fingers):
    """构造 21 个关键点：wrist 在 (0.5, 0.9)，extended_fingers 中的手指伸直，其余卷曲。

    手指编号 0-3 = 食指/中指/无名指/小指（不含拇指）。
    """
    pts = [(0.5, 0.7) for _ in range(21)]
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
    pts = [(0.0, 0.0) for _ in range(21)]
    for i in (0, 5, 9, 13, 17):
        pts[i] = (0.5, 0.4)
    center = palm_center(pts)
    assert center[0] == pytest.approx(0.5)
    assert center[1] == pytest.approx(0.4)


FPS = 30
DT = 1.0 / FPS


def feed_motion(det, t0, start, end, duration):
    """以 30fps 从 start 线性移动到 end，返回 (首次检出的方向, 结束时间)。"""
    steps = max(int(duration / DT), 1)
    fired = None
    t = t0
    for i in range(1, steps + 1):
        t = t0 + i * DT
        x = start[0] + (end[0] - start[0]) * i / steps
        y = start[1] + (end[1] - start[1]) * i / steps
        result = det.update(t, x, y)
        fired = fired or result
    return fired, t


def feed_still(det, t0, pos, duration):
    steps = int(duration / DT)
    t = t0
    for i in range(1, steps + 1):
        t = t0 + i * DT
        det.update(t, pos[0], pos[1])
    return t


def test_swipe_left():
    det = SwipeDetector()
    fired, _ = feed_motion(det, 0.0, (0.8, 0.5), (0.4, 0.5), 0.3)
    assert fired == "left"


def test_swipe_right():
    det = SwipeDetector()
    fired, _ = feed_motion(det, 0.0, (0.4, 0.5), (0.8, 0.5), 0.3)
    assert fired == "right"


def test_swipe_up():
    det = SwipeDetector()
    fired, _ = feed_motion(det, 0.0, (0.5, 0.8), (0.5, 0.4), 0.3)
    assert fired == "up"


def test_swipe_down():
    det = SwipeDetector()
    fired, _ = feed_motion(det, 0.0, (0.5, 0.4), (0.5, 0.8), 0.3)
    assert fired == "down"


def test_diagonal_does_not_fire():
    det = SwipeDetector()
    fired, _ = feed_motion(det, 0.0, (0.3, 0.3), (0.7, 0.7), 0.3)
    assert fired is None


def test_slow_drift_does_not_fire():
    det = SwipeDetector()
    fired, _ = feed_motion(det, 0.0, (0.3, 0.5), (0.7, 0.5), 2.0)
    assert fired is None


def test_return_stroke_suppressed_then_rearms():
    det = SwipeDetector()
    # 向左挥 → 触发 left
    fired, t = feed_motion(det, 0.0, (0.8, 0.5), (0.4, 0.5), 0.3)
    assert fired == "left"
    # 立刻收手往回（向右）：处于冷却且未静止，不应触发
    fired, t = feed_motion(det, t, (0.4, 0.5), (0.8, 0.5), 0.3)
    assert fired is None
    # 手静止 0.5s → 重新武装
    t = feed_still(det, t, (0.8, 0.5), 0.5)
    # 再次向左挥 → 触发 left
    fired, t = feed_motion(det, t, (0.8, 0.5), (0.4, 0.5), 0.3)
    assert fired == "left"
