"""CLI 入口：手势控制 Claude Code。"""
import argparse
import sys
import time

import cv2

from . import keys, sounds
from .camera import Camera, CameraError
from .gestures import SwipeConfig, SwipeDetector, classify_pose, palm_center
from .state_machine import Controller, ControllerConfig, HandObservation, State
from .tracker import HandTracker

KEY_LABELS = {"up": "↑", "down": "↓", "left": "←", "right": "→", "enter": "⏎"}


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="claude-enter",
        description="用前置摄像头手势向当前聚焦终端发送方向键/回车：张掌1秒解锁，挥手=方向键，握拳=回车",
    )
    p.add_argument("--camera", type=int, default=0, help="摄像头索引（默认 0 = 前置）")
    p.add_argument("--no-preview", action="store_true", help="不显示预览窗口")
    p.add_argument("--no-sound", action="store_true", help="关闭提示音")
    p.add_argument("--dry-run", action="store_true", help="只识别不注入按键（调试用）")
    p.add_argument("--swipe-dist", type=float, default=0.25, help="swipe 触发位移，画面比例（默认 0.25）")
    p.add_argument("--cooldown", type=float, default=0.6, help="swipe 冷却秒数（默认 0.6）")
    p.add_argument("--unlock-hold", type=float, default=1.0, help="张掌解锁秒数（默认 1.0）")
    p.add_argument("--fist-hold", type=float, default=0.4, help="握拳触发回车秒数（默认 0.4）")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    if not args.dry_run and not keys.accessibility_trusted():
        print("缺少「辅助功能」权限，无法注入按键。", file=sys.stderr)
        print(
            "请打开 系统设置 → 隐私与安全性 → 辅助功能，添加并勾选你的终端应用，"
            "然后重启终端再运行。",
            file=sys.stderr,
        )
        print("（可先用 --dry-run 只测试识别，不注入按键。）", file=sys.stderr)
        return 1

    swipe = SwipeDetector(SwipeConfig(min_disp=args.swipe_dist, cooldown_sec=args.cooldown))
    controller = Controller(
        ControllerConfig(unlock_hold_sec=args.unlock_hold, fist_hold_sec=args.fist_hold),
        swipe_detector=swipe,
    )
    tracker = HandTracker()
    try:
        camera = Camera(args.camera)
    except CameraError as e:
        print(str(e), file=sys.stderr)
        return 1

    last_gesture = "-"
    fps = 0.0
    prev_t = time.monotonic()
    print("启动完成：对镜头张开手掌停 1 秒解锁；挥手=方向键，握拳=回车。")
    print("把焦点切到运行 Claude Code 的终端窗口。Ctrl-C 或预览窗内按 q 退出。")
    try:
        while True:
            frame = camera.read()
            t = time.monotonic()
            fps = 0.9 * fps + 0.1 * (1.0 / max(t - prev_t, 1e-6))
            prev_t = t

            hand_result = tracker.process(frame)
            observation = None
            if hand_result:
                observation = HandObservation(
                    pose=classify_pose(hand_result.points),
                    center=palm_center(hand_result.points),
                )

            for event in controller.update(t, observation):
                if event[0] == "key":
                    key = event[1]
                    last_gesture = KEY_LABELS[key]
                    if not args.dry_run:
                        keys.press(key)
                    if not args.no_sound:
                        sounds.play("key")
                else:  # ("unlocked",) / ("locked",)
                    if not args.no_sound:
                        sounds.play(event[0])

            icon = "🟢" if controller.state == State.ACTIVE else "🔒"
            sys.stdout.write(
                f"\r{icon} {controller.state.value:<6} | 最近: {last_gesture} | FPS {fps:4.1f}  "
            )
            sys.stdout.flush()

            if not args.no_preview:
                if hand_result:
                    tracker.draw(frame, hand_result)
                color = (0, 200, 0) if controller.state == State.ACTIVE else (0, 0, 255)
                cv2.putText(
                    frame, controller.state.value.upper(), (10, 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2,
                )
                cv2.imshow("claude-enter", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    except KeyboardInterrupt:
        pass
    finally:
        print()
        camera.release()
        tracker.close()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
