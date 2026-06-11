"""前置摄像头采集，输出水平镜像后的 BGR 帧。"""
import cv2


class CameraError(RuntimeError):
    pass


class Camera:
    def __init__(self, index=0):
        self.cap = cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
        if not self.cap.isOpened():
            raise CameraError(
                "无法打开摄像头。请确认：1) 没有其他应用占用摄像头；"
                "2) 已在 系统设置 → 隐私与安全性 → 摄像头 中允许本终端访问。"
            )

    def read(self):
        ok, frame = self.cap.read()
        if not ok:
            raise CameraError("读取摄像头帧失败。")
        # 镜像翻转：用户向左挥手 = 画面中向左，方向才符合直觉
        return cv2.flip(frame, 1)

    def release(self):
        self.cap.release()
