"""MediaPipe Hands 封装：BGR 帧 → 21 个归一化关键点。"""
from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import mediapipe as mp


@dataclass
class HandResult:
    points: List[Tuple[float, float]]  # 21 个 (x, y) 归一化坐标
    raw_landmarks: object              # MediaPipe 原始结果，预览窗绘制用


class HandTracker:
    def __init__(self):
        self._hands = mp.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            model_complexity=0,
            min_detection_confidence=0.6,
            min_tracking_confidence=0.5,
        )

    def process(self, bgr_frame) -> Optional[HandResult]:
        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        result = self._hands.process(rgb)
        if not result.multi_hand_landmarks:
            return None
        raw = result.multi_hand_landmarks[0]
        points = [(lm.x, lm.y) for lm in raw.landmark]
        return HandResult(points=points, raw_landmarks=raw)

    def draw(self, bgr_frame, hand: HandResult):
        """在帧上画关键点骨架（预览窗用）。"""
        if hand is None:
            return
        mp.solutions.drawing_utils.draw_landmarks(
            bgr_frame, hand.raw_landmarks, mp.solutions.hands.HAND_CONNECTIONS
        )

    def close(self):
        """释放 TFLite 运行时；长驻进程务必在 finally 中调用。"""
        self._hands.close()
