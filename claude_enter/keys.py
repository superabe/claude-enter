"""macOS 按键注入与辅助功能权限检测。"""
import Quartz

KEY_CODES = {
    "left": 123,
    "right": 124,
    "down": 125,
    "up": 126,
    "enter": 36,
}


def press(key):
    """向当前聚焦窗口注入一次按键（按下+抬起）。"""
    code = KEY_CODES[key]
    for is_down in (True, False):
        event = Quartz.CGEventCreateKeyboardEvent(None, code, is_down)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def accessibility_trusted():
    """是否已授予「辅助功能」权限（CGEventPost 生效的前提）。"""
    from ApplicationServices import AXIsProcessTrusted

    return bool(AXIsProcessTrusted())
