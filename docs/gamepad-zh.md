# XGO Duck 框架与 Xbox / 盖世小鸡手柄接入

用户已明确选择**启明星蓝牙直连 UNO Q**，系统现已识别为 Xbox Wireless Controller。直接控制程序和开机服务说明见 [板载手柄直接控制](board-gamepad-zh.md)。以下浏览器方案保留作为可选输入；此前蓝牙驱动检查与首次配对记录见 [蓝牙直连检查记录](bluetooth-zh.md)。

## 已核对的项目结构

本目录是完整的 Arduino App，板卡为 UNO Q（设备树 `arduino,imola`）。运行入口是 `app.yaml` 和 `python/main.py`，上位机程序运行于板载 Linux 的 Arduino App 容器中；电脑浏览器只是遥控界面。

| 文件 | 职责 |
| --- | --- |
| `app.yaml` | 声明 `arduino:web_ui`，开放 9527 端口 |
| `assets/index.html`、`app.js` | 页面、键盘和触摸摇杆；每 50 ms 向 `/api/command` 发送命令，每 250 ms 读取 `/api/status` |
| `python/main.py` | 创建 Controller、WebUI，注册 REST 路由和 Bridge 接收函数，启动独立推理线程 |
| `python/controller.py` | 模式、输入限幅、心跳、校准及舵机调试；接收并滤波 100 Hz MCU 状态，50 Hz 执行策略 |
| `python/policy.py`、`rl_core.py` | ONNX 推理、61 维观测构造、14 维动作滤波与关节映射 |
| `python/proc.py`、`recovery.py` | IMU 与关节速度滤波、跌倒起身状态机 |
| `python/wire.py`、`sketch/protocol.h` | 共享二进制 ABI：80 字节运动指令、240 字节反馈，经 Bridge RPC 传输 |
| `sketch/sketch.ino` | Zephyr 100 Hz 控制线程及独立状态上报线程；校验序号、时效和失联超时 |
| `sketch/scs_bus.h`、`qmi8658.h` | Serial1 1 Mbps 舵机总线、I²C IMU |
| `data/zero_pos.json` | 本机校准数据，启动时推送到 MCU RAM |
| `tools/` | Bridge 修补、2 Mbps router 配置、构建检查和状态采集工具 |

控制链路：

```text
电脑上的手柄 → 浏览器 Gamepad API → [vx, vy, wz]
  → POST /api/command → Controller.command()
  → 50 Hz ONNX → 15 个目标角度 → duck_command
  → Bridge 2 Mbps → MCU 100 Hz → 舵机
                               ↓
网页状态 ← /api/status ← duck_state（IMU、关节、状态回执）
```

`vx` 正值向前，`vy` 正值向左横移，`wz` 正值向左旋转；上限依次为 0.4、0.3、1.0。手柄输出的是步态速度指令，不能直接替代 ONNX 输出去驱动单个舵机。观测的 `[48:51]` 正是这三个输入。嘴部为独立的第 15 路，不属于模型的 14 维动作。

启动先在 `shadow` 等待所有反馈和校准零点确认，连续就绪 0.5 秒后自动进入 `hold` 保持默认姿态并启用扭矩。此启动保持不依赖网页或手柄，B 可关闭；按 A 切到 `policy` 执行步行和自动起身。`off` 关闭扭矩；校准和舵机设置独占控制。拾取和翻滚使用各自的 ONNX 模型，恢复期间速度输入由控制器覆盖。当前代码的跌倒阈值是 `recovery.py` 中的 **40°**，Python 默认姿态 `rl_core.py` 的 `q` 是 **24°**；原 README/页面中的 55°、23°与部分代码不同，调试时以实际源代码为准。

## 本次集成的接法

当前实现是**手柄连接运行浏览器的电脑**，支持浏览器报告 `mapping: standard` 的 Xbox / 兼容手柄。系统和浏览器负责解析 USB、接收器或蓝牙输入，项目负责将标准摇杆映射为现有速度命令。无需改变 ONNX、Bridge ABI 或 MCU 固件。

这不是 UNO Q 直连手柄驱动。若要将手柄直接插在 UNO Q 上，需要另行确认型号、USB VID/PID、Linux 输入驱动和容器的 `/dev/input/event*` 可见性；随后可增加独立输入线程，但必须同时处理网页与手柄的控制权和心跳，避免网页零值覆盖手柄命令。蓝牙还需确认配对后的输入协议。不同盖世小鸡型号切换模式的方法不同，不能仅凭品牌推断按键组合。

## 使用

1. 手柄连接电脑，按该型号说明书切到 PC / Xbox / XInput 模式。
2. 在电脑通过 **HTTPS** 或 **localhost** 打开此 App 的控制页。普通 `http://板卡IP:9527` 可能无法使用浏览器 Gamepad API；页面会检测并提示。
3. 若板卡已开启 SSH 且 App 已运行，在电脑终端执行（将 `<board-IP>` 替换为板卡地址）：

   ```bash
   ssh -N -L 9527:127.0.0.1:9527 arduino@<board-IP>
   ```

   保持该终端打开，再访问 `http://localhost:9527`。若电脑的 9527 端口已占用，可将命令左侧端口改成 19527，并访问 `http://localhost:19527`。不能只在电脑另开一个静态页面服务器，它还需要连到板卡的 `/api/`。

4. 在页面勾选 **Use gamepad**，按一下手柄按键以便浏览器发现它。设备名称和连接提示会显示在页面上。
5. 松开 LB 并让两个摇杆回中，等待 **Ready**。默认速度为 50%。可先在 **Inference only** 模式查看网页上的 `vx / vy / ωz` 数值和策略输出；此时不会因手柄而开启扭矩。
6. 准备行走时，在网页点 **Walk / get up**。切换模式后重新松开 LB 并回中，然后按住 LB 操作。

| 操作 | 效果 |
| --- | --- |
| 左摇杆上下 | 前进 / 后退 |
| 左摇杆左右 | 左 / 右横移 |
| 右摇杆左右 | 左 / 右旋转 |
| 按住 LB | 允许摇杆发送非零速度 |
| 松开 LB | 三路速度归零，步态控制继续运行 |
| B（右侧面键） / 网页 Torque off / 空格 | 请求关闭扭矩 |
| Speed 25% / 50% / 100% | 对三路速度上限统一缩放 |

摇杆死区为 0.12，死区外连续缩放到完整量程。手柄启用时独占三路速度；关闭后恢复键盘和屏幕摇杆。启用、切换模式、归零、调整速度、失去焦点或断连后，必须松开 LB 并回中才能继续。手柄没有开启扭矩或启动拾取、翻滚的快捷键。

手柄断连、B、或启用手柄时网页失去焦点，会发送关扭矩请求。网页隐藏、关闭时沿用原有退出逻辑。网络故障可能阻止请求到达，此时由原控制器兜底：网页心跳超过 1 秒关闭位置控制；MCU 指令超时为 250 ms；Python 收到的 MCU 反馈超过 150 ms、或 MCU 端健康 IMU 超过 100 ms，也会停止位置控制。

## 验证与限制

```bash
node tools/test-gamepad.js
```

该检查仅模拟输入，覆盖六个方向、限幅、死区、LB 释放、B、回中门控、断连重连、多个手柄、焦点丢失和异常数据，以及实际页面脚本对模拟 API 的请求，不会访问硬件。

当前环境未检测到已连接的手柄，无法通过 Docker socket 查询/启动 App；Chromium 也因系统调用限制无法启动。因此尚未完成真实浏览器显示检查、盖世小鸡实物兼容性、实际行走或断连停机的实机验证。改动后需要在 App Lab 部署/重启此目录，并检查 App 日志和实际手柄映射。

协议资料：[W3C 标准手柄轴/键布局](https://www.w3.org/TR/gamepad/#remapping)、[Firefox Gamepad 安全上下文说明](https://hacks.mozilla.org/2020/07/securing-gamepad-api/)、[GameSir 官方支持](https://gamesir.com/support)。
