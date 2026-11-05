# 启明星蓝牙直连 UNO Q：驱动检查与首次配对

**后续验证：已发现手柄和 js0。** 内核名称为 `Xbox Wireless Controller`，蓝牙地址 `47:84:65:FD:BE:E7`，设备 ID `045e:0b13`，驱动 `microsoft`，输入节点 `event3`、`js0`。这确认当前手柄模式已完成 Linux 输入设备识别。新的宿主读取程序、App 接口、开机服务模板及实测步骤见 [板载手柄直接控制](board-gamepad-zh.md)。以下内容保留首次检查时的证据和配对说明。

目标是手柄直接连接 UNO Q，板卡和手柄开机后恢复连接，后续由板载 Linux 读取输入控制小鸭子。此前增加的 `assets/gamepad.js` 负责浏览器所在电脑的手柄；它不能代替板载 Linux 输入模块。

## 当前板卡实测

本次在设备树确认 `arduino,imola`，当前内核为 `7.0.0-g122c2c22d838`。依据 `/proc/config.gz`、sysfs 和板载配置：

| 检查项 | 结果 | 含义 |
| --- | --- | --- |
| 蓝牙适配器 | `/sys/class/bluetooth/hci0` 存在 | 硬件已被内核枚举 |
| 底层驱动 | `hci_uart_qca`，`hci_uart`、`btqca` 已加载 | 高通板载蓝牙驱动存在 |
| rfkill | soft=0、hard=0 | 当前没有被软/硬开关禁用；不等同于 D-Bus 的 Powered=true |
| BlueZ | `bluetoothctl --version` 为 5.82 | 已安装 Linux 蓝牙工具 |
| 蓝牙 HID | `CONFIG_BT_BREDR=y`、`CONFIG_BT_LE=y`、`CONFIG_BT_HIDP=m` | 有经典蓝牙、BLE 和 HIDP 基础支持 |
| 通用输入 | `CONFIG_UHID=y`、`CONFIG_HID_GENERIC=y`、`CONFIG_INPUT_EVDEV=y` | 具备将支持的 HID 设备呈现为 event 输入的基础 |
| Microsoft HID | `CONFIG_HID_MICROSOFT=y`，`/sys/bus/hid/drivers/microsoft` 已注册 | 内核带部分微软设备的 HID 处理；并非全部 Xbox 协议的兼容保证 |
| PS/Switch 专用 HID | `CONFIG_HID_SONY/PLAYSTATION/NINTENDO` 均未启用 | DS4、Switch 模式不能默认当作已支持 |
| xpad / xpadneo | 当前未发现 | `xpad` 是另一条 USB 支持路径；缺少它不能据此判定蓝牙 HID 不支持 |
| 启动服务配置 | `bluetooth.target.wants/bluetooth.service` 存在；AutoEnable 保持默认 true | 有开机启用配置；尚未验证本次 bluetoothd 是否正常运行 |
| 已枚举的输入 | 只有板载按键和耳机插孔 | 尚无手柄输入设备，未验证任何摇杆/按键事件 |

结论：板子有蓝牙，且具备蓝牙 HID 手柄接入的基础条件。是否支持**这只启明星当前固件的 Xbox 兼容模式**，必须通过实际配对、HID 绑定和输入事件验证；不能只凭蓝牙版本或 Microsoft HID 配置下结论。当前无需先更换蓝牙硬件。

## 宿主终端补充验证

用户随后提供的 `bluetoothctl show` 确认了适配器当前的实际运行状态：地址 `14:B5:CD:F0:CC:E3`，名称 `jess`，`Powered: yes`、`PowerState: on`，支持 central 和 peripheral 角色。这补足了代理沙箱内无法读取 D-Bus 状态的限制；不再只是确认驱动已枚举。

此地址是**UNO Q 的蓝牙适配器地址**，不是手柄地址。还需通过 `scan on` 获取手柄自己的地址，再操作该远端设备。

`Pairable: no` 表示当前不接受外部发起的新配对请求。按 BlueZ 定义，该属性只影响传入配对，不能据此判断 UNO Q 无法主动对手柄执行 `pair`。`Discoverable: no` 表示板子没有向其他设备公开自身，也不妨碍板子主动扫描。`show` 中的 UUID 是本地服务清单，缺少 HID UUID 不能证明 HID 主机功能不支持。参考 [BlueZ Adapter API](https://bluez.readthedocs.io/en/latest/adapter-api/)。

用户提供的机器人诊断在两个采样点均显示：约 100 Hz 反馈、50 Hz 推理、15 路舵机与 IMU 在线，坏帧、反馈丢帧、MCU 超期均为 0，模式为 `shadow`、扭矩未开启。采集脚本最后的 `monitor ... Killed` 来自显式的 `timeout --signal=INT --kill-after=2s 6s` 限时退出，不能据此认定 MCU 崩溃。

当前运行的是 **`/home/arduino/ArduinoApps/xgoduck_runtime_arduino`**；本说明和此前浏览器改动所在的 **`xgoduck_runtime_arduino-master` 已停止**。两个目录的源代码已存在差异，不能把此前浏览器改动当作已在运行 App 中生效。仍须按用户最初指定目录和后续实际部署目标分别处理，不能直接互相覆盖。

尤其需要区别当前运行版本的失联处理：诊断中 `command_timeout_enabled=false`；核对该目录 `sketch/protocol.h` 可见 `ttlUs` 只为保持 ABI 而保留，普通指令不再按 TTL 过期。其 Python `Controller.step()` 在网页心跳超过 1 秒时仅将平移/旋转速度归零，**不会因此释放扭矩**；反馈/IMU 失效仍有单独处理。此前文档提到的 MCU 250 ms 指令失效和网页失联关扭矩属于另一个目录的实现，不能用于承诺当前运行版本的手柄断连效果。蓝牙集成需明确实现自己的断连动作和输入控制权。

## 启明星模式

启明星对应官方 `t4nlite` / Nova Lite 产品线。官方当前教程对 A+Home 的说明为 Android 黄色灯模式、名称 `GameSir-Nova Lite`；B+Home 蓝色灯模式在当前英文教程中列为 DS4 / `Wireless Controller`。其他固件可能呈现 Xbox 兼容身份，必须以实际扫描和设备 ID 为准。

若蓝灯模式实际显示 Xbox 身份，可先验证该模式。若实际为 DS4，可以测试 A+Home 的通用 HID 输入模式，它足以承载机器人所需的摇杆/按键，仍然需要检查真实输入事件。切换模式可能产生独立配对身份，不要混用某个模式的旧地址。

强制重新配对：先进入所选模式，再按住 Home+截图键约 3 秒，直到指示灯快闪。首次连接完成后保持模式不变，之后短按 Home 开机，手柄会尝试回连该模式上次配对的设备；应关闭原电脑/手机对它的抢连。

资料：[官方 Android 模式教程](https://doc.xiaoji.com/en/t4nlite/detail/1434.html)、[官方 PC 模式教程](https://doc.xiaoji.com/article/1426.html)、[官方 iOS/DS4 模式教程](https://doc.xiaoji.com/en/t4nlite/detail/1436.html)。

## 在板卡宿主终端执行

当前代理会话禁止 D-Bus、Bluetooth management socket 的访问，且没有 `/dev/input` 设备映射。这里的 `bluetoothctl show/list` 无法连接 D-Bus，`btmgmt info` 也不能打开管理 socket。这是当前会话的限制，不能推断为板卡蓝牙故障。实际配对需要通过板卡桌面终端或 SSH 的正常宿主会话完成。

先运行只读报告（不扫描、不配对、不启动 App）：

```bash
cd /home/arduino/ArduinoApps/xgoduck_runtime_arduino-master
python3 tools/check-bluetooth.py
```

手柄进入配对快闪后，在板卡宿主终端打开交互工具：

```bash
bluetoothctl
```

在 `bluetoothctl` 中逐行输入：

```text
power on
agent on
default-agent
scan on
```

找到**该手柄**的实际地址和名称后，将下列占位地址替换为扫描结果，逐行输入并检查返回值：

```text
scan off
pair AA:BB:CC:DD:EE:FF
trust AA:BB:CC:DD:EE:FF
connect AA:BB:CC:DD:EE:FF
info AA:BB:CC:DD:EE:FF
quit
```

需要确认 `Paired: yes`、`Trusted: yes`、`Connected: yes`，并重新运行只读报告确认出现手柄的 `event*` 节点。配对成功不等同于已经能控制机器人；还要检查摇杆事件、轴量程、LB/B 键映射与断连行为。

## 自动回连与后续软件

已保存配对密钥、trust、蓝牙开机服务和手柄自身回连功能共同构成自动重连的基础。当前尚未验证手柄先开、板子先开这两种次序，不能保证只做 trust 就能覆盖所有上电情况。实际需要分别测试板卡重启、手柄关开和失联重连；必要时再为**已确认的这一只手柄**增加有间隔的连接重试，不能自动配对陌生设备。

后续代码现已增加宿主手柄读取程序、独立控制会话/心跳和开机服务模板，详情见 [板载手柄直接控制](board-gamepad-zh.md)。代码只在 `-master` 目录准备完成，尚未部署到运行 App，服务尚未安装；实物摇杆读取、自动回连和实际停机效果仍待宿主终端验证。
