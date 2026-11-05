# UNO Q 蓝牙手柄直接控制

## 已确认的手柄

已在本机 `/proc/bus/input/devices` 和 sysfs 中发现：

| 项目 | 值 |
| --- | --- |
| 名称 | Xbox Wireless Controller |
| 蓝牙手柄地址 | `47:84:65:FD:BE:E7` |
| 蓝牙总线 / 设备 ID | `0005` / `045e:0b13` |
| 内核输入处理器 | `event3`、`js0` |
| HID 驱动 | `/sys/bus/hid/drivers/microsoft` |
| UNO Q 蓝牙地址 | `14:B5:CD:F0:CC:E3` |

这确认手柄已经通过蓝牙注册为输入设备，板载驱动支持它当前的 Xbox 兼容身份。当前无需为基本输入安装 xpadneo。用户在宿主终端的两次预览已验证三路摇杆值和 A/B/LB 键：`axis_map=[0,1,2,5,9,10,16,17]`，其中前三路为左 X、左 Y、右 X；`button_map=[304..318]`。A 的按下代码是 304，B 是 305，LB 是 310。三路摇杆均观察到 -1 至 +1 的完整范围。

最后一次预览汇总为 `observed_buttons=[A,B,LB]`、`start_observed=true`、`stop_observed=true`，证明必需输入均已读到。该次 `motion_observed=false` 是因为推动摇杆时未按住 LB，按 LB 时三路摇杆全为 0；这与门控设计一致，无需为此重新配对或安装驱动。该次输入的 `--seconds 2020` 表示约 33 分 40 秒，用户通过 Ctrl-C 正常结束并获得汇总；通常输入 `--seconds 20` 即可。

用户随后已通过宿主脚本完成 master 切换、默认 App 和手柄服务安装，并确认 A 后可以实际行走。上电自动重连的不同次序和断连停机仍待分别验证。节点编号可能随重新连接变化，程序按蓝牙地址验证身份并查找 `js*`，不固定依赖 js0。

## 启动后自动保持 Default pose

App 每次启动时，先等待 15 路舵机与 IMU 的新鲜反馈，并确认 MCU 返回的零点与保存值一致。就绪状态连续保持 0.5 秒后，自动启用扭矩并进入 `hold`（网页的 Default pose）。它使用本目录原有的默认关节角，不运行 walk，不需要网页或手柄保持在线；手柄按 A 后再切到已经验证的 walk 模型。

该功能直接在 App 控制器中执行，所以手柄未连接、读取服务尚未启动时也能保持姿态。首次 ARM 使用当前测量角度，后续发送默认姿态目标。B 在按 A 之前也可以关闭扭矩；网页 Torque off 同样可用。B、明确的网页模式操作、反馈失效或 MCU 重启都会取消本次启动的自动启用；随后传感器恢复不会自行重新上锁。下一次 App 重启才重新等待并自动保持。启动保持期间，关网页和普通网页指令不会取消姿态或改变头部/嘴部目标。

新功能生效后，上电或点击 Run 完成启动时会**自动给舵机上扭矩并保持姿态**。重启 App 会重新经历停止扭矩与启动等待阶段，无法消除 Linux/MCU 尚未准备好期间的机械支撑需求。walk 模型文件保持原样。

`/api/status` 中预计为 `mode=hold`、`enabled=true`、`input_source=startup_pose`、`startup_pose.active=true`。保持姿态期间推理频率可降为 0，这是正常状态；按 A 切到 walk 后恢复实时推理。

## 本次增加的代码

```text
已配对蓝牙手柄
  → Linux HID / joydev → /dev/input/jsN
  → 宿主机 tools/board-gamepad.py（50 Hz）
  → 本机 POST /api/gamepad
  → App Controller → 现有 50 Hz 策略 / Bridge / MCU
```

宿主读取程序只依赖 Python 标准库；它从 Linux joystick ioctl 读取轴和按键映射，不把第几个轴直接假定为旋转轴。左摇杆 X/Y 对应 `ABS_X/Y`，右摇杆 X 使用 `ABS_RX` 或 Xbox 蓝牙描述符中的 `ABS_Z`；按钮按 Linux `BTN_A/B/THUMBL` 代码匹配。页面显示当前输入来源。

本次代码仅修改 **`/home/arduino/ArduinoApps/xgoduck_runtime_arduino-master`**。用户已选择并成功切换到此目录，其中 `xgoduck_walk.onnx` 策略经过实机验证。另一目录 `xgoduck_runtime_arduino` 保留原文件。当前新增的启动保持功能尚需在正常宿主终端重启 App 后生效；代理沙箱不能访问 Docker socket。

保留的模型 SHA-256 为 `5727b909d5ea1a0f9ff63bf4cea9707339dea6a522374c7a120da633605b923f`。手柄集成没有替换或修改这份模型。读手柄的 `--run` 模式会先检查 API 协议版本；旧 App 没有新 API 时会拒绝控制。

## 切换 master 并配置开机启动

用户已授权使用 master，在板卡普通终端执行：

```bash
cd /home/arduino/ArduinoApps/xgoduck_runtime_arduino-master
bash tools/activate-board-gamepad.sh
```

该脚本校验 UNO Q、master 策略哈希、Python 语法和现有 router 2 Mbps 配置，然后通过 App CLI 切换到本目录。切换时按 App ID 读取状态，显式停止正在运行的旧版本或 master 自身，等待完全退出，再启动 master；两个 App 都叫 XGO Duck 不会影响识别。若宿主手柄服务已运行，会先停止它再重载 App。它读取启动日志，并等待新手柄 API、15 个舵机、IMU、反馈和启动保持姿态就绪：`mode=hold`、`enabled=true`。停止失败或超时则不启动 master，检查失败时不会继续配置开机服务。

首次执行曾返回 `app "XGO Duck" is running`；对应备份 `apps-before.txt` 表明旧版本已 stopped、master 已 running，原因是对已运行的目标再次调用 start。当前脚本已处理此情况，可以重跑以加载新代码。

就绪后脚本对**已经配对的** `47:84:65:FD:BE:E7` 保存 trust，将本目录设为默认启动 App，并安装/启用宿主 `board-gamepad.service`。原默认 App 和已有同名服务配置保存在本目录 `data/gamepad-setup-<UTC时间>/`。脚本不重启 router、不更改模型或校准；App 启动会自动保持姿态，行走仍由人在手柄上按 A 开始。实际机器人状态、服务日志和默认 App 会打印在终端中，供确认是否全部完成。此前的预览程序应先按 Ctrl-C 退出。

## 先预览真实输入

在 UNO Q 的普通终端运行：

```bash
cd /home/arduino/ArduinoApps/xgoduck_runtime_arduino-master
python3 tools/board-gamepad.py --mac 47:84:65:FD:BE:E7 --seconds 20
```

默认是 **PREVIEW ONLY**，不会请求 App API，不改变电机状态。首行显示设备名称、`axis_map` 和 `button_map`；后续每半秒显示状态，按键变化会立即显示 `button_events`，结束时打印 `summary`。程序保留同一批读取中的按下/松开事件，避免短按 B 被末尾的松开状态覆盖。

20 秒内先松开所有按键并将摇杆回中，按 A 后松开，再按住 **LB（左上肩键，不是 LT 扳机）** 推动左摇杆和右摇杆，松开 LB，最后按 B。回中应接近 0，LB 松开时 twist 全为 0。完整操作后，`summary.observed_buttons` 应包含 A、B、LB，`motion_observed`、`start_observed`、`stop_observed` 应为 true；这表示预览检测到了对应输入，不代表已经控制电机。反馈结果时可只提供 summary 及异常按键事件。

若报权限错误，先在普通终端检查 `id` 和 `ls -l /dev/input/js*`；当前 `/etc/group` 的 input 组包含 arduino，但已有登录会话是否已获得该组权限仍需以 `id` 为准。不要把节点设置为全局可写。

## 控制操作

部署目标已确定为本目录。完成一键切换后，服务已在后台运行，**不需要再手动启动第二个读取进程**。若选择不安装服务、仅手动使用，可在启动此 App 并检查日志后运行：

```bash
cd /home/arduino/ArduinoApps/xgoduck_runtime_arduino-master
python3 tools/board-gamepad.py --mac 47:84:65:FD:BE:E7 --run --reconnect
```

| 操作 | 行为 |
| --- | --- |
| 松开 A/B/LB，左右摇杆回中 | 输入就绪 |
| App 启动、全部反馈和零点同步稳定 | 自动保持 Default pose 并启用扭矩，不需要手柄 |
| 回中且松开 LB 时按 A | 从 Default pose 切到行走模式；若扭矩已关闭则重新启用 |
| 按住 LB，左摇杆上下 | 前进 / 后退 |
| 按住 LB，左摇杆左右 | 左右横移 |
| 按住 LB，右摇杆左右 | 左右旋转 |
| 松开 LB | 速度立即归零，步态保持运行 |
| 按 B | 关闭扭矩；未按 A 时也能关闭启动姿态保持 |
| 行走会话内 Ctrl-C / SIGTERM / 手柄断开 | 请求退出手柄控制并关闭扭矩；启动姿态保持本身不依赖手柄连接 |
| 网页点击 Torque off | 停机并撤销手柄会话，旧请求不能重新启用；恢复需重新回中并按 A |

默认速度 100%，此时峰值：前进 `vx +0.4`、**后退 `vx −0.2`**、横移 `vy ±0.3`、转向 `wz ±1.0`。后退刻意只给一半——满速后退几步就会摔，前进却没有这个问题。需要保守测试时用 `--speed 0.5` 或 `--speed 0.25`，三路指令按同一倍率缩放。摇杆死区 0.12。程序刚启动、重连或请求失败后均需要松开并回中，再重新按 A；不会因连接恢复而自动恢复行走。

网页 `/api/command` 在手柄会话内不覆盖手柄命令，关闭新版网页也不结束板载手柄控制；网页明确的模式/停机按钮始终可以收回控制权。若浏览器仍缓存旧版页面脚本，应刷新后使用。手柄输入有独立的 **300 ms 心跳时限**，不会被网页心跳续期；手柄进程崩溃、请求停滞或网络超时会在控制循环中撤销会话、归零并发送 DISARM。请求序号、会话 ID 和同机单调时钟时间戳阻止迟到命令覆盖已停机的状态。校准和舵机设置期间不允许手柄启动行走。

这些保护依赖新 App 的 Python 控制循环运行；它之外仍保留本目录 MCU 原有的 250 ms 指令时限、150 ms 源数据检查。它们不适用于未修改的另一目录版本。

## 上电自动连接

首次配对由用户完成。请在宿主终端只针对这只手柄确认：

```bash
bluetoothctl info 47:84:65:FD:BE:E7
```

若尚未信任，可执行：

```bash
bluetoothctl trust 47:84:65:FD:BE:E7
```

需看到 `Paired: yes`、`Trusted: yes`。保持手柄当前模式；之后按 Home 开机时手柄会尝试回连。`--reconnect` 还会在缺少输入设备时每 2～30 秒尝试连接这一地址，且只对已配对、已信任的设备执行 connect；不会配对新设备，也不会删除现有配对。实际首次启动请验证板子先开和手柄先开两种次序。

`tools/board-gamepad.service` 是宿主系统服务模板。它会由一键脚本安装和启用；代理会话目前无法访问系统总线，尚未代为安装。如果需要单独安装，可在新 App 已就绪后运行：

```bash
sudo install -m 644 tools/board-gamepad.service /etc/systemd/system/board-gamepad.service
sudo systemctl daemon-reload
sudo systemctl enable --now board-gamepad.service
journalctl -u board-gamepad.service -n 50 --no-pager
```

服务使用 arduino 用户、input 组、已确认的手柄地址，不自动启动 Arduino App。一键脚本通过 App CLI 另行将本目录设为默认启动 App；App 就绪后会自行给舵机上扭矩、保持 Default pose，手柄服务等待按 A 才切到行走。

## 验证边界

```bash
python3 tools/test-board-gamepad.py
node tools/test-gamepad.js
```

离线检查覆盖 joystick 事件解析、Linux 轴/键映射、六个方向、启动门控、网页控制权、心跳超时、DISARM、旧会话/过期/乱序请求、校准互斥、自动重连的已配对/已信任条件，以及启动等待/零点确认/姿态保持/B 停机/不自动重新启用。Controller 测试使用真实 ONNX 模型与假的 Bridge，不连接 MCU，不开启电机。

当前代理沙箱未映射 `/dev/input`、禁止系统 D-Bus 和 Docker，无法直接读取实物输入或启动 App。用户已经完成输入、服务启动和行走的实机验证；本次新增的自动 Default pose 保持尚未完成实机重启验证。Chromium 与 systemd-analyze 也受到沙箱系统调用限制，未完成真实页面渲染和服务启动验证。
