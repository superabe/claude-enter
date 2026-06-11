"""系统音效反馈：afplay 异步播放，不阻塞主循环。"""
import subprocess

_SOUNDS = {
    "unlocked": "/System/Library/Sounds/Glass.aiff",
    "locked": "/System/Library/Sounds/Bottle.aiff",
    "key": "/System/Library/Sounds/Pop.aiff",
}


def play(name):
    path = _SOUNDS.get(name)
    if path:
        subprocess.Popen(
            ["afplay", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
