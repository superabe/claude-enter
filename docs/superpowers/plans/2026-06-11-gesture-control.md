# claude-enter 手势控制 Claude Code 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Mac 前置摄像头识别四方向挥手 + 握拳手势，向当前聚焦的终端（Claude Code）注入方向键/回车。

**Architecture:** 单进程 CLI 主循环：OpenCV 采集镜像帧 → MediaPipe Hands 输出 21 关键点 → 纯逻辑手势分类与 swipe 检测 → LOCKED/ACTIVE 状态机（张掌解锁、冷却防回弹）→ Quartz CGEvent 全局按键注入。手势逻辑与 IO 严格分离，纯逻辑全部单元测试。

**Tech Stack:** Python 3.12 venv、mediapipe（0.10.x，legacy solutions API）、opencv-python、pyobjc-framework-Quartz、pyobjc-framework-ApplicationServices、pytest。

**设计文档:** `docs/superpowers/specs/2026-06-11-gesture-control-design.md`

**约定（所有任务通用）:**
- 工作目录均为 `/Users/dong/mygit/claude-enter`
- 不激活 venv，直接用 `.venv/bin/python` / `.venv/bin/pytest`
- 坐标系：帧已水平镜像，x 向右增大（用户视角），y 向下增大；所有关键点为 0~1 归一化坐标
- 事件格式：状态机输出元组列表 `("unlocked",)`、`("locked",)`、`("key", "left"|"right"|"up"|"down"|"enter")`

---

### Task 1: 项目脚手架与依赖

**Files:**
- Create: `.gitignore`
- Create: `requirements.txt`
- Create: `conftest.py`（空文件，让 pytest 把项目根目录加入 sys.path）
- Create: `claude_enter/__init__.py`（空文件）

- [ ] **Step 1: 创建 .gitignore**

```gitignore
.venv/
__pycache__/
*.pyc
.pytest_cache/
.DS_Store
```

- [ ] **Step 2: 创建 requirements.txt**

```
mediapipe>=0.10,<0.11
opencv-python>=4.9
pyobjc-framework-Quartz>=10
pyobjc-framework-ApplicationServices>=10
pytest>=8
```

- [ ] **Step 3: 创建空的 conftest.py 和 claude_enter/__init__.py**

```bash
touch conftest.py claude_enter/__init__.py
```

（`conftest.py` 内容为空即可——它的存在让 pytest 自动把项目根目录插入 `sys.path`，使 `import claude_enter` 在测试里可用。）

- [ ] **Step 4: 创建 venv 并安装依赖**

Run:
```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```
Expected: 安装成功无报错（mediapipe + opencv 下载较大，需要一两分钟）。

- [ ] **Step 5: 验证关键依赖可导入**

Run:
```bash
.venv/bin/python -c "import mediapipe, cv2, Quartz; from ApplicationServices import AXIsProcessTrusted; print('deps OK')"
```
Expected: 输出 `deps OK`。

- [ ] **Step 6: Commit**

```bash
git add .gitignore requirements.txt conftest.py claude_enter/__init__.py
git commit -m "chore: project scaffolding and dependencies"
```

---

### Task 2: 手势姿态分类（gestures.py 第一部分）

**Files:**
- Create: `claude_enter/gestures.py`
- Test: `tests/test_gestures.py`

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_gestures.py`：

```python
import pytest

from claude_enter.gestures import HandPose, classify_pose, palm_center


def make_landmarks(extended_fingers):
    """构造 21 个关键点：wrist 在 (0.5, 0.9)，extended_fingers 中的手指伸直，其余卷曲。

    手指编号 0-3 = 食指/中指/无名指/小指（不含拇指）。
    """
    pts = [(0.5, 0.7)] * 21
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
    pts = [(0.0, 0.0)] * 21
    for i in (0, 5, 9, 13, 17):
        pts[i] = (0.5, 0.4)
    center = palm_center(pts)
    assert center[0] == pytest.approx(0.5)
    assert center[1] == pytest.approx(0.4)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_gestures.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'claude_enter.gestures'`

- [ ] **Step 3: 实现 gestures.py 姿态分类**

创建 `claude_enter/gestures.py`：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_gestures.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add claude_enter/gestures.py tests/test_gestures.py
git commit -m "feat: hand pose classification (open palm / fist)"
```

---

### Task 3: Swipe 检测器（gestures.py 第二部分）

**Files:**
- Modify: `claude_enter/gestures.py`（追加）
- Test: `tests/test_gestures.py`（追加）

- [ ] **Step 1: 追加失败的测试**

在 `tests/test_gestures.py` 顶部 import 区改为：

```python
import pytest

from claude_enter.gestures import (
    HandPose,
    SwipeDetector,
    classify_pose,
    palm_center,
)
```

文件末尾追加：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_gestures.py -v`
Expected: ImportError，`cannot import name 'SwipeDetector'`

- [ ] **Step 3: 在 gestures.py 实现 SwipeDetector**

在 `claude_enter/gestures.py` 顶部 import 区加入：

```python
from collections import deque
from dataclasses import dataclass
```

文件末尾追加：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_gestures.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add claude_enter/gestures.py tests/test_gestures.py
git commit -m "feat: swipe detector with cooldown and return-stroke suppression"
```

---

### Task 4: LOCKED/ACTIVE 状态机

**Files:**
- Create: `claude_enter/state_machine.py`
- Test: `tests/test_state_machine.py`

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_state_machine.py`：

```python
from claude_enter.gestures import HandPose
from claude_enter.state_machine import (
    Controller,
    ControllerConfig,
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_state_machine.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'claude_enter.state_machine'`

- [ ] **Step 3: 实现 state_machine.py**

创建 `claude_enter/state_machine.py`：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest -v`
Expected: 19 passed（gestures 11 + state_machine 8）

- [ ] **Step 5: Commit**

```bash
git add claude_enter/state_machine.py tests/test_state_machine.py
git commit -m "feat: LOCKED/ACTIVE state machine with palm unlock and fist enter"
```

---

### Task 5: 按键注入（keys.py）

**Files:**
- Create: `claude_enter/keys.py`

依赖系统 API，无法单元测试，用手动验证。

- [ ] **Step 1: 实现 keys.py**

创建 `claude_enter/keys.py`：

```python
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
```

- [ ] **Step 2: 手动验证权限检测**

Run:
```bash
.venv/bin/python -c "from claude_enter import keys; print('trusted:', keys.accessibility_trusted())"
```
Expected: 输出 `trusted: True` 或 `trusted: False`。若为 False：打开 系统设置 → 隐私与安全性 → 辅助功能，添加并勾选当前终端应用，**重启终端**后重测应为 True。

- [ ] **Step 3: 手动验证按键注入**

Run（运行后 3 秒内点击任意一个文本输入区，比如另一个终端窗口）:
```bash
.venv/bin/python -c "
import time
print('3 秒内请把焦点切到一个文本框，将注入一个 → 方向键')
time.sleep(3)
from claude_enter import keys
keys.press('right')
print('done')
"
```
Expected: 聚焦的文本框中光标右移一格（或终端命令行光标右移）。

- [ ] **Step 4: Commit**

```bash
git add claude_enter/keys.py
git commit -m "feat: Quartz keyboard injection and accessibility check"
```

---

### Task 6: 提示音（sounds.py）

**Files:**
- Create: `claude_enter/sounds.py`

- [ ] **Step 1: 实现 sounds.py**

创建 `claude_enter/sounds.py`：

```python
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
```

- [ ] **Step 2: 手动验证**

Run:
```bash
.venv/bin/python -c "from claude_enter import sounds; import time; sounds.play('unlocked'); time.sleep(1); sounds.play('key'); time.sleep(1)"
```
Expected: 听到两声不同的系统音效。

- [ ] **Step 3: Commit**

```bash
git add claude_enter/sounds.py
git commit -m "feat: system sound feedback via afplay"
```

---

### Task 7: 摄像头与手部追踪（camera.py、tracker.py）

**Files:**
- Create: `claude_enter/camera.py`
- Create: `claude_enter/tracker.py`

依赖摄像头硬件与 MediaPipe 运行时，用 smoke 脚本手动验证。

- [ ] **Step 1: 实现 camera.py**

创建 `claude_enter/camera.py`：

```python
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
```

- [ ] **Step 2: 实现 tracker.py**

创建 `claude_enter/tracker.py`：

```python
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
        mp.solutions.drawing_utils.draw_landmarks(
            bgr_frame, hand.raw_landmarks, mp.solutions.hands.HAND_CONNECTIONS
        )

    def close(self):
        self._hands.close()
```

- [ ] **Step 3: smoke 测试（把手举到镜头前）**

Run:
```bash
.venv/bin/python - <<'EOF'
from claude_enter.camera import Camera
from claude_enter.tracker import HandTracker

cam = Camera()
tracker = HandTracker()
detected = 0
for _ in range(90):  # 约 3 秒，期间把手举到镜头前
    frame = cam.read()
    if tracker.process(frame):
        detected += 1
print(f"90 帧中检测到手的帧数: {detected}")
cam.release()
tracker.close()
EOF
```
Expected: 首次运行系统弹出摄像头授权弹窗（允许）；手举在镜头前时 `detected` 明显大于 0（通常 >50）。

- [ ] **Step 4: Commit**

```bash
git add claude_enter/camera.py claude_enter/tracker.py
git commit -m "feat: camera capture (mirrored) and MediaPipe hand tracker"
```

---

### Task 8: CLI 主程序（main.py）

**Files:**
- Create: `claude_enter/main.py`
- Create: `claude_enter/__main__.py`

- [ ] **Step 1: 实现 main.py**

创建 `claude_enter/main.py`：

```python
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
```

- [ ] **Step 2: 创建 __main__.py**

创建 `claude_enter/__main__.py`：

```python
import sys

from .main import main

sys.exit(main())
```

- [ ] **Step 3: 跑全部单元测试确认没破坏纯逻辑**

Run: `.venv/bin/pytest -v`
Expected: 19 passed

- [ ] **Step 4: 端到端手动验证（dry-run）**

Run:
```bash
.venv/bin/python -m claude_enter --dry-run
```
验证清单：
1. 预览窗显示摄像头画面，手出现时画出 21 点骨架
2. 初始状态行显示 🔒 locked；张掌停 1 秒 → 提示音 + 变 🟢 active
3. 向左/右/上/下挥手 → 状态行「最近」显示对应箭头 + Pop 音；挥手后收手不触发反方向
4. 握拳 0.4 秒 → 显示 ⏎；持续握拳不连发；松开再握又触发
5. 手离开画面 3 秒 → 回 🔒 locked + 提示音
6. 预览窗按 q 正常退出

- [ ] **Step 5: 端到端手动验证（真实注入）**

Run:
```bash
.venv/bin/python -m claude_enter
```
然后点击聚焦另一个终端窗口（或任意文本编辑器），解锁后挥手/握拳，确认方向键和回车真实生效。

- [ ] **Step 6: Commit**

```bash
git add claude_enter/main.py claude_enter/__main__.py
git commit -m "feat: CLI main loop with preview, status line and key injection"
```

---

### Task 9: README 与收尾

**Files:**
- Create: `README.md`

- [ ] **Step 1: 写 README.md**

```markdown
# claude-enter

用 Mac 前置摄像头手势控制终端里的 Claude Code：

| 手势 | 按键 |
|---|---|
| 向上/下/左/右挥手 | ↑ ↓ ← → |
| 握拳保持 0.4 秒 | Enter |

防误触：默认锁定，对镜头**张开手掌停 1 秒**解锁；手离开画面 3 秒自动回锁。

## 安装

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 权限（首次运行前）

1. **辅助功能**（注入按键必需）：系统设置 → 隐私与安全性 → 辅助功能，添加并勾选你的终端应用（Terminal/iTerm/VS Code），然后重启终端。
2. **摄像头**：首次运行时系统会弹窗，点允许。

## 使用

```bash
.venv/bin/python -m claude_enter
```

启动后**点击聚焦运行 Claude Code 的终端窗口**（按键发给当前聚焦窗口；预览窗启动时会抢走焦点，记得点回终端）。

流程：张掌停 1 秒解锁（听到提示音）→ 挥手发方向键、握拳发回车 → 手离开 3 秒自动锁定。

常用选项：

```
--dry-run        只识别不注入按键（调试）
--no-preview     不开预览窗
--no-sound       关提示音
--swipe-dist F   swipe 触发位移，画面比例（默认 0.25，越大越不灵敏）
--cooldown F     swipe 冷却秒数（默认 0.6）
--unlock-hold F  张掌解锁秒数（默认 1.0）
--fist-hold F    握拳触发回车秒数（默认 0.4）
```

退出：Ctrl-C 或在预览窗按 q。

## 手动测试清单

1. `--dry-run`：解锁/锁定、四方向挥手、握拳在状态行正确显示，挥手回程不触发反方向
2. 真实注入：聚焦另一终端，确认方向键/回车生效
3. 未授辅助功能权限时启动：打印设置指引并退出（`--dry-run` 可绕过）
4. 摄像头被占用/未授权时启动：打印指引并退出

## 开发

```bash
.venv/bin/pytest -v   # 手势逻辑与状态机单元测试
```
```

- [ ] **Step 2: 跑全部测试收尾**

Run: `.venv/bin/pytest -v`
Expected: 19 passed

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README with setup, permissions and manual test checklist"
```

---

## 自查记录

- **Spec 覆盖**：五个手势映射（Task 3/4/8）、张掌解锁与自动回锁（Task 4）、防回弹（Task 3）、全局注入与权限检测（Task 5/8）、镜像（Task 7）、状态行/预览/声音（Task 6/8）、错误处理（Task 7/8）、单元测试（Task 2/3/4）、手动清单（Task 9）——全部有对应任务。
- **占位符**：无 TBD/TODO；所有代码步骤含完整代码。
- **类型一致性**：事件元组格式、`HandObservation(pose, center)`、`SwipeDetector.update(t, x, y)`/`reset()`、`Controller(config, swipe_detector)`、`HandResult(points, raw_landmarks)` 在各任务间一致；sounds 的键名 `unlocked`/`locked`/`key` 与状态机事件名对应。
