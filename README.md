# Industrial DoIP/UDS Diagnostic Simulator

这是一个基于 Python asyncio 的 DoIP/UDS 车辆诊断 ECU 模拟器与测试工具链。项目提供两类可执行程序：

- GUI 版：适合测试工程师直接双击使用。
- CLI 版：适合自动化测试、脚本联调和命令行排错。

当前已支持：

- DoIP UDP 车辆发现，端口 `13400`
- DoIP TCP 路由激活
- DoIP Alive Check
- DoIP Diagnostic ACK/NACK
- Tester 源地址白名单
- 多 ECU 逻辑地址路由
- 网关 ECU 与代理/直连 ECU 路由策略
- XML 外部化模拟数据
- `0x10` DiagnosticSessionControl
- `0x3E` TesterPresent
- `0x22` ReadDataByIdentifier
- `0x2E` WriteDataByIdentifier
- `0x31` RoutineControl
- `0x36` TransferData 动态回显
- `0x29` Mock Authentication
- `0x27` SecurityAccess seed/key
- 会话/安全权限控制
- `0x19` ReadDTCInformation 常用子服务
- `0x14` ClearDiagnosticInformation
- `0x11` ECUReset 真实断链仿真
- `0x34` RequestDownload
- `0x36` TransferData 有状态块传输
- `0x37` RequestTransferExit
- `0x78` Pending 延迟仿真
- S3 Server 会话看门狗

## 文件位置

打包后的 exe 位于：

```text
D:\Diagnostic simulator\dist\
```

GUI 版：

```text
D:\Diagnostic simulator\dist\ecu-simulator-gui.exe
D:\Diagnostic simulator\dist\tester-gui.exe
```

CLI 版：

```text
D:\Diagnostic simulator\dist\ecu-simulator.exe
D:\Diagnostic simulator\dist\tester-cli.exe
```

配置文件：

```text
D:\Diagnostic simulator\mock_data.xml
D:\Diagnostic simulator\mock_data_README.md
```

`mock_data.xml` 不会被打包进 exe，必须作为外部配置文件使用。这样测试人员可以直接修改 XML 来增加 ECU、DID、DTC、例程响应等模拟数据。

刷写文件目录：

```text
D:\Diagnostic simulator\Flash File\
```

`Flash File` 不会被打包进 exe。Tester GUI 的 Flash 页面会从该目录加载刷写文件；点击 `Load File` 可以把外部文件添加到该目录，再选择 ECU 和文件执行刷写。

## GUI 版一台电脑使用方法

一台电脑测试适合做软件闭环验证，不需要网线，不需要真实 VCI。

### 1. 启动 ECU Simulator GUI

双击：

```text
D:\Diagnostic simulator\dist\ecu-simulator-gui.exe
```

界面参数建议填写：

```text
Bind IP: 127.0.0.1
Port: 13400
XML: D:\Diagnostic simulator\mock_data.xml
```

正常情况下，XML 输入框会自动显示 `mock_data.xml` 的完整路径。如果 XML 输入框为空，或只显示 `mock_data.xml` 这种相对路径，请点击 `Browse` 手动选择 `D:\Diagnostic simulator\mock_data.xml`。

然后点击 `Start`。

如果日志中看到类似 `DoIP simulator listening`，说明模拟器已经启动。

### 2. 启动 Tester GUI

双击：

```text
D:\Diagnostic simulator\dist\tester-gui.exe
```

界面参数建议填写：

```text
Simulator IP: 127.0.0.1
Port: 13400
Source: 0x0E80
Target: 0x1001
```

然后点击 `Connect`。

Tester GUI 默认会显示后台自动发送的会话保持报文：

```text
TX 3E 80
```

这是 P3 Client 心跳，程序会周期性发送它来维持非默认诊断会话。正常情况下 `3E 80` 抑制正响应，所以通常只看到 TX。

如果 ECU 正在 reset_delay 重启窗口内，心跳也可能收到负响应：

```text
TX 3E 80
RX 7F 3E 21
```

这类响应会归属到心跳日志，不会污染下一条手动请求的响应。取消勾选 `Show 3E 80 heartbeat` 后，心跳仍然继续发送，只是不再显示心跳 TX/RX。

### 3. 发送请求验证

可以直接点击 Tester GUI 里的快捷按钮，也可以手动输入 UDS 报文后点击 `Send`。

常用验证报文：

```text
22 F1 90
19 01 FF
19 02 FF
14 FF FF FF
11 01
```

预期示例：

```text
22 F1 90 -> 62 F1 90 ...
19 01 FF -> 59 01 FF 01 00 03
19 02 FF -> 59 02 FF ...
14 FF FF FF -> 54
```

## GUI 版两台电脑使用方法

两台电脑测试更接近真实 DoIP 诊断链路。

推荐拓扑：

```text
电脑 A：运行 ecu-simulator-gui.exe，作为车辆/ECU Simulator
电脑 B：运行 tester-gui.exe，作为诊断仪 Tester
两台电脑通过 RJ45 网线直连，或连接到同一个交换机
```

### 1. 配置静态 IP

在两台电脑的以太网适配器中设置同一网段静态 IP。

示例：

```text
电脑 A: 192.168.100.10
电脑 B: 192.168.100.20
子网掩码: 255.255.255.0
网关: 可留空
```

确保两台电脑能互相 ping 通：

```powershell
ping 192.168.100.10
ping 192.168.100.20
```

### 2. 电脑 A 启动 Simulator

双击电脑 A 上的：

```text
ecu-simulator-gui.exe
```

参数填写：

```text
Bind IP: 192.168.100.10
Port: 13400
XML: mock_data.xml
```

建议通过 `Browse` 选择 XML 文件，让输入框显示完整路径，例如 `D:\Diagnostic simulator\mock_data.xml`。只看到文件名不代表文件一定已经被正确定位。

点击 `Start`。

如果 Windows 防火墙弹窗，允许该程序访问专用网络。

### 3. 电脑 B 启动 Tester

双击电脑 B 上的：

```text
tester-gui.exe
```

参数填写：

```text
Simulator IP: 192.168.100.10
Port: 13400
Source: 0x0E80
Target: 0x1001
```

点击 `Connect`。

连接成功后发送：

```text
22 F1 90
```

如果收到 `62 F1 90 ...`，说明两台电脑 DoIP/UDS 链路已经打通。

## GUI 版连接真实 VCI 的拓扑

如果要模拟真实车辆端，拓扑通常是：

```text
运行 ecu-simulator-gui.exe 的电脑
        |
      RJ45 网口
        |
OBD 母头转 RJ45 诊断线缆
        |
真实诊断仪 VCI
```

注意事项：

- Simulator 电脑的以太网口需要配置与 VCI 同网段的静态 IP。
- Simulator 监听 TCP/UDP `13400`。
- Windows 防火墙需要允许 `ecu-simulator-gui.exe` 访问当前网络。
- `mock_data.xml` 中 ECU 逻辑地址要和诊断仪请求的目标地址一致。

## 0x11 ECUReset 真实断链说明

当前 `mock_data.xml` 中 `0x11` 配置为真实断链模式：

```xml
<Service id="0x11" handler="ecu_reset" reset_behavior="disconnect" reset_delay="2.0" />
```

行为如下：

```text
Tester -> 11 01
Simulator -> 51 01
Simulator 主动断开 TCP 连接
2 秒内重新连接并发送请求 -> 7F SID 21
2 秒后重新连接 -> 恢复正常响应
```

GUI 操作流程：

1. Tester GUI 点击 `11 01`。
2. 收到 `51 01`。
3. Tester GUI 会提示连接断开，状态变为 `Disconnected`。
4. 等待约 `2` 秒。
5. 再次点击 `Connect`。
6. 继续发送 `19 01 FF`、`22 F1 90` 等请求。

如果你不希望 `0x11` 后断开连接，可以把 XML 改成：

```xml
<Service id="0x11" handler="ecu_reset" reset_behavior="state_only" reset_delay="0" />
```

## XML 配置热更新

Simulator 会在每次诊断请求前检查 `mock_data.xml` 的修改时间。通常情况下：

1. 修改 `mock_data.xml`。
2. 保存文件。
3. Tester GUI 再次发送请求。
4. 新配置自动生效。

不需要重新打包 exe。

## DoIP 层配置

`mock_data.xml` 支持 DoIP 层配置：

```xml
<DoIP allowed_testers="0x0E80" diagnostic_ack="true" />
```

含义：

- `allowed_testers`：允许路由激活和发送诊断请求的 Tester 源地址列表。为空或不配置时表示不限制。
- `diagnostic_ack="true"`：收到 DoIP Diagnostic Message `0x8001` 后，Simulator 会先返回 DoIP ACK `0x8002`，再返回 UDS 响应。

如果 Tester 源地址不在白名单内，Routing Activation 会被拒绝，响应码不是 `0x10`。

Tester 工具会自动忽略 DoIP ACK/NACK，不会把 ACK 当成 UDS 响应显示。GUI 下方主要显示 UDS 层的 TX/RX。

Simulator 也支持 Alive Check：

```text
Alive Check Request  -> payload type 0x0007
Alive Check Response -> payload type 0x0008
```

详细 XML 写法请看：

```text
D:\Diagnostic simulator\mock_data_README.md
```

## 网关与代理 ECU 配置

`mock_data.xml` 支持给 ECU 配置网关/访问方式：

```xml
<Ecu name="Gateway" address="0x1001" role="gateway" access="direct" />
<Ecu name="BodyControlModule" address="0x1002" role="ecu" access="proxied" gateway="0x1001" />
<Ecu name="ADAS" address="0x1101" role="ecu" access="direct" />
```

含义：

- `role="gateway"`：该 ECU 可以作为代理网关。
- `access="direct"`：该 ECU 可以直接作为 Tester Target 访问。
- `access="proxied"`：该 ECU 必须通过 `gateway="0x...."` 指定的网关代理访问。

旧 XML 不写这些属性也能继续使用，默认等价于：

```xml
role="ecu" access="direct"
```

如果某个 `proxied` ECU 没有配置有效网关，访问时会返回：

```text
7F SID 31
```

## SecurityAccess 与权限验证

`mock_data.xml` 中 Gateway 示例 ECU 已配置 `0x27 SecurityAccess`：

```xml
<Security>
  <Level name="level1" request_seed="0x01" send_key="0x02" seed="12 34 56 78" key="87 65 43 21" max_attempts="3" lock_time="10.0" />
</Security>
```

受保护服务可以这样配置：

```xml
<Service id="0x2E" required_session="0x03" required_security="level1">
```

典型操作顺序：

```text
10 03
27 01
27 02 87 65 43 21
2E F1 91 12 34
```

预期响应：

```text
10 03 -> 50 03 00 32 01 F4
27 01 -> 67 01 12 34 56 78
27 02 87 65 43 21 -> 67 02
2E F1 91 12 34 -> 6E F1 91
```

如果没有进入要求的会话，会返回：

```text
7F SID 7F
```

如果没有完成安全解锁，会返回：

```text
7F SID 33
```

## 刷写链路验证

`mock_data.xml` 中 Gateway 示例 ECU 已配置下载区间：

```xml
<Download start_address="0x00010000" end_address="0x0001FFFF" max_block_length="0x10" required_session="0x03" required_security="level1" />
```

Tester GUI 的 `Flash` 页面可以自动执行刷写流程：左侧选择 ECU，右侧点击 `Load File` 添加刷写文件，选择文件后点击 `Flash`，程序会根据文件大小构造 `34 RequestDownload`，并按文件内容自动分块发送 `36 TransferData`。

典型刷写流程：

```text
10 03
27 01
27 02 87 65 43 21
31 01 FF 00
34 00 44 00 01 00 00 00 00 00 04
36 01 AA BB
36 02 CC DD
37
31 01 FF 01
```

预期响应示例：

```text
10 03 -> 50 03 00 32 01 F4
27 01 -> 67 01 12 34 56 78
27 02 87 65 43 21 -> 67 02
31 01 FF 00 -> 71 01 FF 00 00
34 00 44 00 01 00 00 00 00 00 04 -> 74 20 00 08
36 01 AA BB -> 76 01
36 02 CC DD -> 76 02
37 -> 77
31 01 FF 01 -> 71 01 FF 01 00
```

刷写相关负响应：

- 未进入要求会话：`7F SID 7F`
- 未完成安全解锁：`7F SID 33`
- 未开始下载就发送 `36/37`：`7F SID 70`
- 块序号错误：`7F 36 73`
- 传输长度不足就 `37`：`7F 37 71`
- 地址超出下载区间：`7F 34 31`

## CLI 版使用方法

CLI 版适合脚本化联调。

启动 Simulator：

```powershell
cd "D:\Diagnostic simulator"
.\dist\ecu-simulator.exe --host 0.0.0.0 --config mock_data.xml
```

启动 Tester：

```powershell
cd "D:\Diagnostic simulator"
.\dist\tester-cli.exe --host 127.0.0.1 --target 0x1001
```

CLI 输入示例：

```text
uds> 10 03
50 03 00 32 01 F4
uds> 22 F1 90
62 F1 90 ...
uds> 19 01 FF
59 01 FF 01 00 03
uds> 14 FF FF FF
54
uds> 11 01
51 01
```

`11 01` 后连接会被断开，需要重新运行或重新连接 Tester。

## 常见问题

### 连接不上 Simulator

检查：

- Simulator 是否已经点击 `Start`。
- Tester 中的 `Simulator IP` 是否填写正确。
- 两台电脑是否在同一网段。
- 是否能 ping 通。
- Windows 防火墙是否允许 exe 通信。
- 端口 `13400` 是否被其他程序占用。

### 发送请求返回负响应

常见原因：

- Tester 的 `Target` 地址和 XML 中 `<Ecu address="...">` 不一致。
- XML 中没有配置对应 DID 或 request。
- DID 字节顺序写反，例如 `F190` 应发送 `22 F1 90`。
- `0x11` reset 后 ECU 仍处于 `reset_delay` 重启窗口，可能返回 `7F SID 21`。

### 0x14 清除 DTC 后还能读到吗

发送：

```text
14 FF FF FF
```

后续再读：

```text
19 01 FF
```

DTC 数量通常会变为 `0`。如果 XML 中某些 DTC 配置了 `clearable="false"`，或者配置了 `clear_status`，清码后仍可能读到这些 DTC，这是用来模拟真实车辆里“不可清除故障”或“清码后转为 pending/历史状态”的场景。

- 发送 `11 01` ECU Reset，并且 `restore_dtcs_on_reset="true"` 时，DTC 恢复为 XML 初始状态。
- 修改并保存 XML，触发热加载。
- 重启 Simulator。

## 增强 DTC / 清码 / Reset 行为

当前 `0x19` 除了基础 `19 01/02/04/06/0A/0F/11/12/14/15`，还支持严重度相关子服务：

```text
19 07 severityMask statusMask
19 08 dtcHigh dtcMiddle dtcLow
19 09 severityMask statusMask
```

`0x14` 清码支持更真实的 XML 字段：

```xml
<Dtc code="0x123456" status="0x09" clear_status="0x08" clear_fault_detection_counter="0x01" />
<Dtc code="0x223344" status="0x2F" clearable="false" />
```

- `clearable="false"`：该 DTC 不会被 `14` 清除。
- `clear_status`：清码后 DTC 状态变成指定值，默认 `0x00`。
- `clear_fault_detection_counter`：清码后故障检测计数器变成指定值，默认 `0x00`。

`0x11` Reset 支持限制 resetType 和是否恢复 DTC：

```xml
<Service id="0x11"
         handler="ecu_reset"
         reset_behavior="disconnect"
         reset_delay="10.0"
         supported_reset_types="0x01,0x02,0x03"
         restore_dtcs_on_reset="true" />
```

- `supported_reset_types`：允许的 resetType。未配置时默认支持 `0x01/0x02/0x03`。
- `restore_dtcs_on_reset="true"`：reset 后 DTC 回到 XML 初始状态。
- `restore_dtcs_on_reset="false"`：reset 只清会话、安全、刷写等运行态，不恢复已被 `14` 改过的 DTC 状态。

常见负响应已经系统化：

```text
7F SID 11  Service not supported
7F SID 12  Sub-function not supported
7F SID 13  Incorrect message length
7F SID 21  ECU busy / rebooting
7F SID 31  Request out of range
7F SID 33  Security access denied
7F SID 35  Invalid key
7F SID 36  Exceeded number of attempts
7F SID 37  Required time delay not expired
7F SID 7F  Service not supported in active session
```

## 打包命令

如果需要重新打包：

```powershell
pyinstaller --onefile --name ecu-simulator run_ecu_simulator.py
pyinstaller --onefile --name tester-cli run_tester_cli.py
pyinstaller --onefile --windowed --name ecu-simulator-gui run_ecu_simulator_gui.py
pyinstaller --onefile --windowed --name tester-gui run_tester_gui.py
```

不要把 `mock_data.xml` 打进 exe。请始终保持 XML 为外部文件。

## 当前版本新增能力：ODX 公共模块、Tester 与 ODX Editor

本项目现在把 ODX/PDX 解析能力集中放在公共模块：

```text
D:\Diagnostic simulator\odx
```

这个模块会被 Tester、ODX Editor 以及后续 OTX Editor 共同使用。它负责读取 `.odx`、`.xml`、`.pdx`，并解析出 ECU、DID、DOP、COMPU-METHOD、UNIT、STRUCTURE、DIAG-SERVICE、REQUEST、POS-RESPONSE、NEG-RESPONSE、NRC、Routine、DTC、Quick Action 等诊断对象。

### Tester 与 ODX/PDX

Tester GUI 不再只能使用固定写死的 ODX。可以在 `Settings` 页面选择外部 ODX/PDX/XML：

```text
Settings -> ODX / PDX Database -> Choose ODX/PDX
```

加载后会刷新：

- ECU Targets
- Signal/DID 列表
- Routine 默认值
- Guided Actions
- Flash ECU 列表
- ODX Service Request Builder

Signal 页面现在支持 `STRUCTURE` DID。如果某个 DID 的 `DOP-REF` 指向 `STRUCTURE`，Tester 会在 `DID Structure Fields` 面板中自动生成字段输入框。填写字段后可以：

- `Build 2E Request`：生成 `2E DID + payload` 请求，并写入 Custom Request 输入框。
- `Send 2E Request`：直接发送写 DID 请求。

Signal 页面还新增 `ODX Service Request Builder`。它会列出 ODX 中带输入参数的服务，基于公共模块的：

```python
database.encode_service_request(service_name, values)
```

自动编码请求。结构参数会展开成多个字段，适合后续扩展 WriteDID、RoutineControl、IOControl、Download 等参数化服务。

负响应现在会显示 NRC 语义，例如：

```text
7F 22 31 -> NRC 0x31 Request Out Of Range for SID 0x22
7F 27 35 -> NRC 0x35 Invalid Key for SID 0x27
7F 34 78 -> NRC 0x78 Response Pending for SID 0x34
```

### ODX Editor

ODX Editor 的最新 exe 位于：

```text
D:\Diagnostic simulator\ODX_Editor\dist\ODX_Editor.exe
```

当前 ODX Editor 支持：

- 新建 ODX
- 加载 ODX/XML/PDX
- 直接保存当前 ODX/XML
- 另存为 ODX/XML
- 导出 PDX
- XML 源码横向/纵向滚动
- 左侧 XML 树选择后在源码中准确高亮同一个节点
- 中间可视化编辑区修改节点名称、属性、文本
- 左侧右键或中间按钮新建子节点/同级节点
- 不弹出小输入框，新节点会直接出现在左侧树中，并在中间显示空白编辑表单
- 中间编辑和右侧源码编辑在点击 `应用属性修改`、`检查 XML`、`格式化 XML` 后互相同步
- `Domain` 标签页显示 ECU、Service、DID、DOP、Structure、NRC、Validation
- 选中 DID 后显示引用链：`DID -> DOP/STRUCTURE -> COMPU -> UNIT`

如果右侧 XML 源码处于非法 XML 状态，点击 `应用属性修改` 或 `格式化 XML` 会失败并提示解析错误。先修正源码后再同步。

### 公共 ODX 模块测试

ODX 测试覆盖公共解析模块和真实样例 smoke test：

```powershell
cd "D:\Diagnostic simulator"
python -m unittest tests.test_odx
python -m unittest discover -s tests
```

`tests\.tmp` 下的 `.odx/.xml/.pdx` 会被扫描加载，确保真实样例不会因为公共模块扩展而被破坏。该 smoke test 不要求样例没有 warning，只要求能够加载并完成校验流程。
