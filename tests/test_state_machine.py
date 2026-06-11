from claude_enter.gestures import HandPose
from claude_enter.state_machine import (
    Controller,
    HandObservation,
    State,
)

DT = 1.0 / 30


class StubSwipe:
    """可控的 swipe 检测桩：next_result 设什么，下次 update 就返回什么。"""

    def __init__(self):
        self.next_result = None
        self.update_calls = 0

    def update(self, t, x, y):
        self.update_calls += 1
        result, self.next_result = self.next_result, None
        return result

    def reset(self):
        pass


def palm():
    return HandObservation(pose=HandPose.OPEN_PALM, center=(0.5, 0.5))


def fist():
    return HandObservation(pose=HandPose.FIST, center=(0.5, 0.5))


def other():
    return HandObservation(pose=HandPose.OTHER, center=(0.5, 0.5))


def run_frames(ctrl, t0, duration, obs_fn):
    """以 30fps 连续喂帧，返回 (全部事件, 结束时间)。"""
    events = []
    steps = int(duration / DT)
    t = t0
    for i in range(1, steps + 1):
        t = t0 + i * DT
        events += ctrl.update(t, obs_fn())
    return events, t


def unlocked_controller(stub=None):
    stub = stub or StubSwipe()
    ctrl = Controller(swipe_detector=stub)
    _, t = run_frames(ctrl, 0.0, 1.2, palm)
    assert ctrl.state == State.ACTIVE
    return ctrl, stub, t


def test_palm_hold_unlocks_once():
    ctrl = Controller(swipe_detector=StubSwipe())
    events, _ = run_frames(ctrl, 0.0, 1.2, palm)
    assert events.count(("unlocked",)) == 1
    assert ctrl.state == State.ACTIVE


def test_brief_palm_does_not_unlock():
    ctrl = Controller(swipe_detector=StubSwipe())
    _, t = run_frames(ctrl, 0.0, 0.5, palm)
    assert ctrl.state == State.LOCKED
    # 放下手超过 grace（0.3s），计时清零；再短暂张掌也不解锁
    _, t = run_frames(ctrl, t, 0.5, lambda: None)
    _, t = run_frames(ctrl, t, 0.5, palm)
    assert ctrl.state == State.LOCKED


def test_dropped_frames_within_grace_still_unlock():
    ctrl = Controller(swipe_detector=StubSwipe())
    _, t = run_frames(ctrl, 0.0, 0.6, palm)
    _, t = run_frames(ctrl, t, 0.2, lambda: None)  # 0.2s 丢帧 < grace 0.3s
    events, _ = run_frames(ctrl, t, 0.6, palm)
    assert ("unlocked",) in events


def test_hand_lost_locks_after_timeout():
    ctrl, _, t = unlocked_controller()
    events, _ = run_frames(ctrl, t, 3.2, lambda: None)
    assert ("locked",) in events
    assert ctrl.state == State.LOCKED


def test_fist_hold_fires_enter_once():
    ctrl, _, t = unlocked_controller()
    events, t = run_frames(ctrl, t, 1.0, fist)
    assert events.count(("key", "enter")) == 1
    # 松拳后再握拳，可以再次触发
    _, t = run_frames(ctrl, t, 0.5, other)
    events, _ = run_frames(ctrl, t, 1.0, fist)
    assert events.count(("key", "enter")) == 1


def test_swipe_event_passes_through():
    ctrl, stub, t = unlocked_controller()
    stub.next_result = "left"
    events = ctrl.update(t + DT, other())
    assert ("key", "left") in events


def test_fist_pose_does_not_feed_swipe():
    ctrl, stub, t = unlocked_controller()
    calls_before = stub.update_calls
    run_frames(ctrl, t, 0.2, fist)
    assert stub.update_calls == calls_before


def test_locked_ignores_fist_and_swipe():
    stub = StubSwipe()
    ctrl = Controller(swipe_detector=stub)
    stub.next_result = "left"
    events, _ = run_frames(ctrl, 0.0, 0.5, fist)
    assert events == []
    assert stub.update_calls == 0


def test_relock_and_reunlock_cycle():
    ctrl, _, t = unlocked_controller()
    # 触发一次握拳回车，弄脏 fist timer 状态
    _, t = run_frames(ctrl, t, 0.6, fist)
    # 手离开 → 回锁
    events, t = run_frames(ctrl, t, 3.2, lambda: None)
    assert ("locked",) in events
    assert ctrl.state == State.LOCKED
    # 第二次解锁
    events, t = run_frames(ctrl, t, 1.2, palm)
    assert events.count(("unlocked",)) == 1
    assert ctrl.state == State.ACTIVE
    # 第二次握拳回车恰好触发一次
    events, _ = run_frames(ctrl, t, 0.6, fist)
    assert events.count(("key", "enter")) == 1
