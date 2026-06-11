"""LOCKED/ACTIVE 状态机：输入每帧手部观测，输出动作事件。纯逻辑可测。

事件格式：("unlocked",)、("locked",)、("key", "left"|"right"|"up"|"down"|"enter")
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from .gestures import HandPose, SwipeDetector


class State(Enum):
    LOCKED = "locked"
    ACTIVE = "active"


@dataclass
class ControllerConfig:
    unlock_hold_sec: float = 1.0  # 张掌解锁所需时长
    pose_grace_sec: float = 0.3   # 姿势判定容忍的丢帧间隙
    hand_lost_sec: float = 3.0    # 无手自动锁定时长
    fist_hold_sec: float = 0.4    # 握拳触发 Enter 所需时长


@dataclass
class HandObservation:
    pose: HandPose
    center: Tuple[float, float]


class _HoldTimer:
    """目标姿势持续 hold_sec（容忍 grace_sec 内的丢帧）则触发一次。

    触发后保持 fired 状态，直到姿势中断超过 grace_sec 才能再次触发。
    """

    def __init__(self, hold_sec, grace_sec):
        self.hold_sec = hold_sec
        self.grace_sec = grace_sec
        self._start_t = None
        self._last_hit_t = None
        self._fired = False

    def update(self, t, hit):
        if hit:
            if self._start_t is None:
                self._start_t = t
            self._last_hit_t = t
            if not self._fired and t - self._start_t >= self.hold_sec:
                self._fired = True
                return True
        elif self._last_hit_t is None or t - self._last_hit_t > self.grace_sec:
            self.reset()
        return False

    def reset(self):
        self._start_t = None
        self._last_hit_t = None
        self._fired = False


class Controller:
    def __init__(self, config=None, swipe_detector=None):
        self.cfg = config or ControllerConfig()
        self.state = State.LOCKED
        self.swipe = swipe_detector or SwipeDetector()
        self._unlock_timer = _HoldTimer(self.cfg.unlock_hold_sec, self.cfg.pose_grace_sec)
        self._fist_timer = _HoldTimer(self.cfg.fist_hold_sec, self.cfg.pose_grace_sec)
        self._last_hand_t = None

    def update(self, t, hand: Optional[HandObservation]):
        events = []
        if hand is not None:
            self._last_hand_t = t

        if self.state == State.LOCKED:
            palm = hand is not None and hand.pose == HandPose.OPEN_PALM
            if self._unlock_timer.update(t, palm):
                self.state = State.ACTIVE
                self._unlock_timer.reset()
                self._fist_timer.reset()
                self.swipe.reset()
                events.append(("unlocked",))
            return events

        # ACTIVE
        if self._last_hand_t is not None and t - self._last_hand_t >= self.cfg.hand_lost_sec:
            self.state = State.LOCKED
            self._unlock_timer.reset()
            events.append(("locked",))
            return events

        if hand is None:
            return events

        if self._fist_timer.update(t, hand.pose == HandPose.FIST):
            self.swipe.reset()
            events.append(("key", "enter"))

        if hand.pose != HandPose.FIST:
            direction = self.swipe.update(t, hand.center[0], hand.center[1])
            if direction:
                events.append(("key", direction))
        return events
