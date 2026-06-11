"""纯手势逻辑：不依赖摄像头、MediaPipe 运行时或系统 API，可单元测试。

landmarks 约定：21 个 (x, y) 归一化坐标（0~1），索引与 MediaPipe Hands 一致。
帧已水平镜像：x 向右增大（用户视角），y 向下增大。
"""
import math
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
    xs = [landmarks[i][0] for i in PALM_POINTS]
    ys = [landmarks[i][1] for i in PALM_POINTS]
    return (sum(xs) / len(xs), sum(ys) / len(ys))
