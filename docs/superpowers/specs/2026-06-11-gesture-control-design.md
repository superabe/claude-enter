# claude-enter — 手势控制 Claude Code 设计文档

日期：2026-06-11
状态：已确认

## 目标

通过 Mac 前置摄像头识别五个手势，把按键发送给当前聚焦的终端（运行 Claude Code）：

| 手势 | 动作 | 按键 |
|---|---|---|
| 向上挥手（swipe up） | 手掌在镜头前向上划过 | ↑（键码 126） |
| 向下挥手（swipe down） | 手掌在镜头前向下划过 | ↓（键码 125） |
| 向左挥手（swipe left） | 手掌在镜头前向左划过 | ←（键码 123） |
| 向右挥手（swipe right） | 手掌在镜头前向右划过 | →（键码 124） |
| 握拳（fist） | 握拳保持约 0.4s | Enter（键码 36） |

全本地运行，无网络依赖。

## 已确认的关键决策

1. **方向手势形态**：挥手滑动（swipe），不是静态指向。
2. **按键注入**：全局注入（Quartz CGEvent），发给当前聚焦窗口；不用 tmux 方案。
3. **防误触**：张开手掌停顿解锁。默认 LOCKED，张开手掌持续约 1s 进入 ACTIVE 才开始识别；手离开画面 3s 自动回 LOCKED。
4. **技术栈**：Python + MediaPipe（不用 Swift/Apple Vision）。

## 技术栈

- **Python 3.11/3.12** + venv + requirements.txt（mediapipe 官方 wheel 对 macOS arm64 支持到 3.12）
- **mediapipe**：Hand Landmarker，每帧输出 21 个手部关键点，CPU 实时
- **opencv-python**：AVFoundation 后端采集前置摄像头、水平镜像翻转、预览窗渲染
- **pyobjc-framework-Quartz**：`CGEventCreateKeyboardEvent`/`CGEventPost` 注入按键；`AXIsProcessTrusted` 检测辅助功能权限
- **afplay**（macOS 自带）：系统音效反馈，零依赖
- **pytest**：单元测试（开发时）

## 架构与模块

单个 CLI 程序，主循环：摄像头帧 → MediaPipe 关键点 → 手势状态机 → 按键注入 → 状态显示。

```
前置摄像头 ──OpenCV──▶ 帧 ──MediaPipe──▶ 21关键点 ──gestures.py──▶ 手势事件
                                                                    │
Claude Code 终端 ◀──Quartz CGEvent── 方向键/回车 ◀──状态机（防误触/冷却）──┘
```

| 模块 | 职责 |
|---|---|
| `camera.py` | OpenCV 采集前置摄像头，水平镜像翻转（"你往左挥"=画面里往左） |
| `tracker.py` | 封装 MediaPipe Hands，输出 21 个关键点（归一化坐标） |
| `gestures.py` | 纯逻辑：手指伸展判断、手掌/握拳分类、swipe 轨迹检测器 |
| `state_machine.py` | LOCKED/ACTIVE 状态机、冷却、防回弹 |
| `keys.py` | Quartz CGEvent 按键注入 |
| `main.py` | CLI 入口、参数解析、主循环、终端状态行、预览窗 |

手势逻辑（gestures.py、state_machine.py）与 IO（摄像头、按键、声音）严格分离，纯函数可单元测试。

## 手势识别细节

- **手指伸直判断**：指尖到手腕的距离 vs 同指 PIP 关节到手腕的距离；拇指特殊处理（用横向展开角度/距离）。
- **张开手掌**：≥4 根手指伸直。
- **握拳**：所有手指卷曲且指尖靠近掌心。
- **Swipe 检测**：维护掌心位置约 0.5s 的轨迹环形缓冲；同时满足以下条件才触发：
  - 窗口内位移超过画面对应维度的约 25%
  - 速度达到阈值
  - 主轴明显占优（如 |dx| > 1.8|dy| 判左右，反之判上下）
- **防回弹**（关键）：挥手后收手的回程动作容易触发反方向。触发一次 swipe 后进入约 0.6s 冷却，且要求手速降回静止阈值以下后才允许下一次 swipe。
- **握拳 → Enter**：握拳保持约 0.4s 触发一次；必须检测到松拳后才能再次触发（防连发回车）。

## 状态机

```
LOCKED（默认）
  └─ 张开手掌持续 ≥1s（允许个别帧丢失）→ ACTIVE（提示音）
ACTIVE
  ├─ swipe 上/下/左/右 → 注入方向键 → 冷却
  ├─ 握拳保持 0.4s → 注入 Enter → 需松拳
  └─ 画面中无手持续 ≥3s → LOCKED（提示音）
```

## 反馈

- **终端状态行**：单行刷新显示 🔒/🟢 状态、最近触发的手势、FPS。
- **预览窗**（默认开，`--no-preview` 关闭）：摄像头画面 + 关键点骨架 + 状态标注。
- **提示音**（默认开，`--no-sound` 关闭）：激活/锁定/按键触发各有音效，用 `afplay` 播放系统自带音效。

## 权限与错误处理

- **摄像头权限**：首次运行系统弹窗授权；打不开摄像头时打印明确指引并退出。
- **辅助功能权限**：启动时用 `AXIsProcessTrusted()` 检测；未授权则打印 System Settings → 隐私与安全性 → 辅助功能 的设置路径，不静默失效。
- MediaPipe 初始化失败、帧读取失败：明确报错退出，不静默。

## 测试

- `gestures.py` 单元测试：合成 21 关键点 → 手掌/握拳分类正确；合成轨迹 → swipe 方向判断、主轴占优、防回弹。
- `state_machine.py` 单元测试：解锁计时、超时回锁、冷却期不重复触发、握拳须松开才能再触发。
- 摄像头、按键注入、声音：手动验证清单（写入 README）。

## 不做的事（YAGNI）

- 不做 tmux 模式、不做热键开关
- 不做自定义手势/按键映射配置文件（阈值仅留 CLI 参数）
- 不做多手识别（max_num_hands=1）
- 不做菜单栏 App / GUI 设置界面
