"""纯手势逻辑：不依赖摄像头、MediaPipe 运行时或系统 API，可单元测试。

landmarks 约定：21 个 (x, y) 归一化坐标（0~1），索引与 MediaPipe Hands 一致。
帧已水平镜像：x 向右增大（用户视角），y 向下增大。
"""
import math
from collections import deque
from dataclasses import dataclass
from enum import Enum

WRIST = 0
FINGER_PIPS = (6, 10, 14, 18)    # 食指/中指/无名指/小指 PIP 关节
FINGER_TIPS = (8, 12, 16, 20)    # 对应指尖
PALM_POINTS = (0, 5, 9, 13, 17)  # 手腕 + 四指 MCP，求均值作掌心


class HandPose(Enum):
    OPEN_PALM = "open_palm"
    FIST = "fist"
    OTHER = "other"


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def classify_pose(landmarks):
    """四根手指（不含拇指）全部伸直=张掌，全部卷曲=握拳，其余=OTHER。

    伸直/卷曲用「指尖到手腕距离 vs PIP 到手腕距离」判断，带 10% 滞回带，
    避免临界角度抖动。拇指不参与判断（对镜头角度太敏感）。
    """
    if len(landmarks) < 21:
        raise ValueError(f"Expected 21 landmarks, got {len(landmarks)}")
    wrist = landmarks[WRIST]
    extended = 0
    curled = 0
    for pip, tip in zip(FINGER_PIPS, FINGER_TIPS):
        tip_d = _dist(landmarks[tip], wrist)
        pip_d = _dist(landmarks[pip], wrist)
        if tip_d > pip_d * 1.1:
            extended += 1
        elif tip_d < pip_d * 0.9:
            curled += 1
    if extended == 4:
        return HandPose.OPEN_PALM
    if curled == 4:
        return HandPose.FIST
    return HandPose.OTHER


def palm_center(landmarks):
    """掌心位置：手腕与四指 MCP 共 5 点的均值，返回归一化 (x, y)。"""
    if len(landmarks) < 21:
        raise ValueError(f"Expected 21 landmarks, got {len(landmarks)}")
    xs = [landmarks[i][0] for i in PALM_POINTS]
    ys = [landmarks[i][1] for i in PALM_POINTS]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


@dataclass
class SwipeConfig:
    window_sec: float = 0.5     # 轨迹窗口时长
    min_disp: float = 0.25      # 触发所需位移（占画面比例）
    axis_ratio: float = 1.8     # 主轴位移须超过副轴的倍数
    cooldown_sec: float = 0.6   # 触发后的冷却时长
    settle_speed: float = 0.25  # 重新武装所需的静止速度上限（单位/秒）


class SwipeDetector:
    """掌心轨迹 swipe 检测。

    防回弹：触发后进入冷却（disarmed），须同时满足「冷却时间已过」和
    「手速降到 settle_speed 以下」才重新武装，避免挥手后的回程动作
    触发反方向按键。重新武装时清空轨迹，丢弃回程残留位移。
    """

    def __init__(self, config=None):
        self.cfg = config or SwipeConfig()
        self._samples = deque()  # (t, x, y)
        self._armed = True
        self._last_fire_t = float("-inf")

    def reset(self):
        """手丢失/状态切换时调用：清空轨迹（冷却状态保留）。"""
        self._samples.clear()

    def update(self, t, x, y):
        """喂入一帧掌心位置，返回 'up'/'down'/'left'/'right' 或 None。"""
        cfg = self.cfg
        self._samples.append((t, x, y))
        while self._samples and t - self._samples[0][0] > cfg.window_sec:
            self._samples.popleft()

        if not self._armed:
            if t - self._last_fire_t >= cfg.cooldown_sec and self._speed() < cfg.settle_speed:
                self._armed = True
                self._samples.clear()
                self._samples.append((t, x, y))
            return None

        if len(self._samples) < 2:
            return None
        t0, x0, y0 = self._samples[0]
        dx, dy = x - x0, y - y0
        direction = None
        if abs(dx) >= cfg.min_disp and abs(dx) >= cfg.axis_ratio * abs(dy):
            direction = "left" if dx < 0 else "right"
        elif abs(dy) >= cfg.min_disp and abs(dy) >= cfg.axis_ratio * abs(dx):
            direction = "up" if dy < 0 else "down"
        if direction:
            self._armed = False
            self._last_fire_t = t
            self._samples.clear()
        return direction

    def _speed(self):
        """最近两帧的瞬时速度（归一化单位/秒）。"""
        if len(self._samples) < 2:
            return 0.0
        (t1, x1, y1), (t2, x2, y2) = self._samples[-2], self._samples[-1]
        dt = t2 - t1
        if dt <= 0:
            return 0.0
        return _dist((x1, y1), (x2, y2)) / dt
