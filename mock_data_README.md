# mock_data.xml 配置说明

`mock_data.xml` 是 ECU Simulator 的外部数据配置文件。程序启动后会读取它，并且每次收到诊断请求前都会检查文件修改时间；因此修改 XML 后通常不需要重新打包 exe，保存文件后再次发送请求即可生效。

启动 GUI 版时，在 ECU Simulator 界面选择这个 XML 文件。启动命令行版时使用：

```powershell
.\dist\ecu-simulator.exe --host 0.0.0.0 --config mock_data.xml
```

## 基本结构

```xml
<Simulator vin="LVDTESTSIM000001" logical_address="0x0E00">
  <Ecus>
    <Ecu name="Gateway" address="0x1001" s3_timeout="5.0">
      <Service id="0x22">
        <Data did="0xF190">
          <Response>62 F1 90 ...</Response>
        </Data>
      </Service>
    </Ecu>
  </Ecus>
</Simulator>
```

层级含义：

- `<Simulator>`：整车模拟器根节点，配置 DoIP 车辆发现信息。
- `<Ecus>`：ECU 列表容器。
- `<Ecu>`：一个虚拟 ECU，通过逻辑地址区分。
- `<Dtcs>`：该 ECU 的 DTC 故障码列表，用于 `0x19` 查询和 `0x14` 清除。
- `<Dtc>`：一条 DTC 状态数据。
- `<Service>`：一个 UDS 服务，例如 `0x22`、`0x2E`、`0x31`、`0x36`、`0x29`。
- `<Data>`：某个服务下的一条匹配规则。
- `<Response>`：匹配成功后返回给诊断仪的 UDS 响应报文。

## 十六进制写法

XML 中的地址、SID、DID 可以写成 `0x1001`，也可以写成十进制数字。报文字节推荐用空格分隔：

```xml
<Response>62 F1 90 31 32 33 34</Response>
```

以下写法也能被解析，但不建议混用：

```xml
<Response>62F19031323334</Response>
<Response>62-F1-90-31-32-33-34</Response>
```

注意：十六进制报文必须是完整字节，不能出现奇数位，例如 `F` 是错误的，应写成 `0F`。

## Simulator 根节点属性

```xml
<Simulator
    vin="LVDTESTSIM000001"
    logical_address="0x0E00"
    eid="00 11 22 33 44 55"
    gid="AA BB CC DD EE FF">
```

- `vin`：DoIP 车辆发现时返回的 VIN，建议 17 位 ASCII 字符。
- `logical_address`：DoIP 网关逻辑地址，路由激活响应中使用，默认 `0x0E00`。
- `eid`：Entity ID，6 字节，用于车辆发现响应。
- `gid`：Group ID，6 字节，用于车辆发现响应。

## ECU 节点

```xml
<Ecu name="Gateway" address="0x1001" s3_timeout="5.0">
```

- `name`：ECU 名称，只用于配置可读性。
- `address`：ECU 逻辑地址。Tester 的 `Target` 必须填这里的地址，例如 `0x1001`。
- `s3_timeout`：S3 Server 会话超时时间，单位秒。进入非默认会话后，如果超过该时间没有合法诊断请求，ECU 会自动回到默认会话 `0x01`。

添加一个新的 ECU 示例：

```xml
<Ecu name="PowertrainControlModule" address="0x1003" s3_timeout="5.0">
  <Service id="0x22">
    <Data did="0xF190">
      <Response>62 F1 90 50 43 4D 53 49 4D 30 30 30 30 30 30 30 30 33</Response>
    </Data>
  </Service>
</Ecu>
```

添加后，Tester 的目标地址填 `0x1003` 即可访问这个 ECU。

## DTC 节点

如果要模拟 `0x19 ReadDTCInformation` 和 `0x14 ClearDiagnosticInformation`，建议在 ECU 下配置 `<Dtcs>`：

```xml
<Dtcs>
  <Dtc
      code="0x123456"
      status="0x09"
      severity="0x20"
      functional_unit="0x10"
      fault_detection_counter="0x7F"
      snapshot="01 02 F1 90 12 34"
      extended_data="01 AA BB CC"
      permanent="true" />
  <Dtc code="0x223344" status="0x2F" memory="mirror" />
  <Dtc code="0x334455" status="0x04" memory="obd" />
</Dtcs>
```

属性含义：

- `code`：3 字节 DTC 编码，例如 `0x123456`。
- `status`：DTC 状态字节，用于状态掩码过滤。`0x00` 表示已清除或当前不激活。
- `severity`：严重度字节，预留给需要严重度查询的扩展场景。
- `functional_unit`：功能单元字节，预留给 OEM 扩展场景。
- `fault_detection_counter`：故障检测计数器，用于 `19 14`。
- `snapshot`：快照记录数据，用于 `19 04`。
- `extended_data`：扩展数据记录，用于 `19 06`。
- `memory`：DTC 内存区域，默认 `primary`。可配置 `mirror` 或 `obd`，分别用于镜像内存和 OBD 相关查询。
- `permanent`：是否永久 DTC，`true` 时可被 `19 15` 查询到。

## Service 节点

```xml
<Service id="0x22">
```

- `id`：UDS 服务 ID，也就是请求报文第 1 个字节。
- `handler`：特殊处理器。当前支持 `dynamic_echo`、`mock_auth`、`dtc`、`clear_dtc`、`ecu_reset`。

普通查表服务使用 `<Data>` 匹配请求并返回 `<Response>`。特殊服务可以不写 `<Data>`。

当前推荐的状态化服务写法：

```xml
<Service id="0x11" handler="ecu_reset" reset_behavior="disconnect" reset_delay="2.0" />
<Service id="0x14" handler="clear_dtc" />
<Service id="0x19" handler="dtc" />
```

说明：当前程序对 `0x11`、`0x14`、`0x19` 已经有内置状态化处理，即使不写这三个 `<Service>` 也能工作。写在 XML 中主要是为了让配置文件更清晰，并方便以后添加精确 request 覆盖。

## Data 节点匹配方式

### 按 DID 匹配

适合 `0x22 ReadDataByIdentifier` 这类请求。程序会取请求第 2、3 字节作为 DID。

```xml
<Service id="0x22">
  <Data did="0xF190">
    <Response>62 F1 90 4C 56 44 54 45 53 54 53 49 4D 30 30 30 30 30 31</Response>
  </Data>
</Service>
```

当 Tester 发送：

```text
22 F1 90
```

Simulator 返回：

```text
62 F1 90 4C 56 44 54 45 53 54 53 49 4D 30 30 30 30 30 31
```

### 按完整 request 匹配

适合 `0x2E`、`0x31` 等需要匹配完整请求的服务。

```xml
<Service id="0x2E">
  <Data request="2E F1 91 12 34">
    <Response>6E F1 91</Response>
  </Data>
</Service>
```

只有请求完全等于 `2E F1 91 12 34` 时才会返回 `6E F1 91`。

## Response 节点

`<Response>` 中填写最终返回给诊断仪的完整 UDS 响应，不需要填写 DoIP 头，也不需要填写源地址/目标地址。

常见正响应规则：

- `0x10` 的正响应是 `0x50`。
- `0x22` 的正响应是 `0x62`。
- `0x2E` 的正响应是 `0x6E`。
- `0x31` 的正响应是 `0x71`。
- `0x36` 的正响应是 `0x76`。
- `0x29` 的正响应是 `0x69`。

如果没有匹配到规则，程序会返回负响应，例如：

```text
7F 22 31
```

其中 `0x31` 表示 Request Out Of Range。

## 顺序响应 response_mode="sequential"

如果同一个 DID 多次读取，希望每次返回不同数据，可以使用顺序响应：

```xml
<Data did="0xF187" response_mode="sequential">
  <Response>62 F1 87 00 00 00 01</Response>
  <Response>62 F1 87 00 00 00 02</Response>
  <Response>62 F1 87 00 00 00 03</Response>
</Data>
```

连续发送 `22 F1 87` 时，返回顺序为：

```text
第 1 次: 62 F1 87 00 00 00 01
第 2 次: 62 F1 87 00 00 00 02
第 3 次: 62 F1 87 00 00 00 03
第 4 次: 62 F1 87 00 00 00 01
```

如果不写 `response_mode`，默认是静态模式，只返回第一个 `<Response>`。

## Pending 延迟 simulate_pending

如果想模拟 ECU 处理耗时，并在最终响应前周期发送 `7F SID 78`，可以这样配置：

```xml
<Data did="0xF18C" simulate_pending="true" total_delay="2.5" pending_interval="0.8">
  <Response>62 F1 8C 53 49 4D 2D 53 4C 4F 57</Response>
</Data>
```

属性含义：

- `simulate_pending="true"`：开启 Pending 仿真。
- `total_delay="2.5"`：总延迟时间，单位秒。
- `pending_interval="0.8"`：每隔多少秒发送一次 `7F SID 78`。

例如请求是 `22 F1 8C`，Pending 报文就是：

```text
7F 22 78
```

倒计时结束后返回最终正响应。

## 0x36 TransferData 动态回显

刷写数据块通常数量很多，不适合在 XML 中逐条写完整请求。可以使用 `dynamic_echo`：

```xml
<Service id="0x36" handler="dynamic_echo" />
```

收到请求：

```text
36 7A 01 02 03 04
```

返回：

```text
76 7A
```

规则是：返回 `请求 SID + 0x40`，再拼接请求第 2 个字节，也就是 block sequence counter。

## 0x29 Authentication Mock Auth

如果只想绕过真实 PKI 证书链，用于业务流程测试，可以配置：

```xml
<Service id="0x29" handler="mock_auth" />
```

行为：

- 收到 `29 01` 或 `29 02`：返回 `69 01/02 + 16 字节随机 Challenge`。
- 收到 `29 03`：忽略签名，直接返回 `69 03`，并在内存中把 ECU 标记为已认证。
- 其他子功能：返回 `7F 29 12`。

示例：

```text
请求: 29 01
响应: 69 01 xx xx xx xx xx xx xx xx xx xx xx xx xx xx xx xx

请求: 29 03
响应: 69 03
```

## 0x19 ReadDTCInformation

`0x19` 已经支持状态化 DTC 查询，不需要为每个请求都写 `<Data request="...">`。先在 ECU 下配置 `<Dtcs>`，再添加：

```xml
<Service id="0x19" handler="dtc" />
```

当前支持的常用子服务：

- `19 01 mask`：按状态掩码统计 DTC 数量。
- `19 02 mask`：按状态掩码读取 DTC 列表。
- `19 04 dtc record`：读取某个 DTC 的快照记录。
- `19 06 dtc record`：读取某个 DTC 的扩展数据记录。
- `19 0A`：读取支持的 DTC 列表。
- `19 0F mask`：读取 mirror memory 中符合状态掩码的 DTC。
- `19 11 mask`：统计 mirror memory 中符合状态掩码的 DTC 数量。
- `19 12 mask`：统计 OBD memory 中符合状态掩码的 DTC 数量。
- `19 14`：读取 DTC fault detection counter。
- `19 15`：读取 permanent DTC 列表。

示例：

```text
请求: 19 01 FF
响应: 59 01 FF 01 00 03
```

含义：

- `59`：`0x19` 的正响应 SID。
- `01`：子服务。
- `FF`：statusAvailabilityMask。
- `01`：DTCFormatIdentifier。
- `00 03`：当前匹配到 3 个 DTC。

读取 DTC 列表示例：

```text
请求: 19 02 FF
响应: 59 02 FF 12 34 56 09 22 33 44 2F 33 44 55 04
```

响应中每 4 字节为一组：`3 字节 DTC + 1 字节 status`。

读取快照：

```text
请求: 19 04 12 34 56 01
响应: 59 04 12 34 56 09 01 ...
```

读取扩展数据：

```text
请求: 19 06 12 34 56 01
响应: 59 06 12 34 56 09 01 ...
```

如果你需要对某个 `0x19` 请求返回完全自定义的 OEM 格式，可以在同一个 Service 中添加精确匹配规则，精确规则优先于内置 DTC handler：

```xml
<Service id="0x19" handler="dtc">
  <Data request="19 99 01">
    <Response>59 99 01 AA BB CC</Response>
  </Data>
</Service>
```

## 0x14 ClearDiagnosticInformation

`0x14` 会清除内存中的 DTC 状态，并影响后续 `0x19` 查询结果：

```xml
<Service id="0x14" handler="clear_dtc" />
```

清除全部 DTC：

```text
请求: 14 FF FF FF
响应: 54
```

清除后再次查询：

```text
请求: 19 01 FF
响应: 59 01 FF 01 00 00
```

groupOfDTC 匹配规则：

- `FF FF FF`：清除全部 DTC。
- `12 34 56`：只清除 DTC `0x123456`。
- `12 34`：清除高 2 字节为 `0x1234` 的 DTC。
- `12`：清除高 1 字节为 `0x12` 的 DTC。

## 0x11 ECUReset

`0x11` 会返回正响应，并重置该 ECU 的运行态：

```xml
<Service id="0x11" handler="ecu_reset" reset_behavior="disconnect" reset_delay="2.0" />
```

示例：

```text
请求: 11 01
响应: 51 01
```

属性含义：

- `handler="ecu_reset"`：启用 ECU Reset 状态化处理。
- `reset_behavior="state_only"`：默认模式，只重置内部状态，不断开 TCP。
- `reset_behavior="disconnect"`：真实断链模式。发送 `51 xx` 后，Simulator 主动断开当前 TCP 连接。
- `reset_delay="2.0"`：ECU 重启窗口，单位秒。在这段时间内，即使 Tester 重新连接并发送请求，ECU 也会返回 `7F SID 21`，表示 Busy Repeat Request。

重置内容包括：

- 会话回到默认会话 `0x01`。
- `0x29` 认证状态清除。
- 顺序响应计数器清零。
- DTC 状态恢复到 XML 初始配置。

真实断链模式下的推荐操作流程：

```text
1. Tester 发送: 11 01
2. Simulator 返回: 51 01
3. Simulator 主动断开 TCP 连接
4. Tester GUI 状态变为 Disconnected
5. 等待 reset_delay 时间，例如 2 秒
6. Tester GUI 重新点击 Connect
7. 继续发送 19、22 等诊断请求
```

如果你希望某个 reset 请求返回自定义响应，可以添加精确匹配：

```xml
<Service id="0x11" handler="ecu_reset" reset_behavior="disconnect" reset_delay="2.0">
  <Data request="11 01" simulate_pending="true" total_delay="1.0" pending_interval="0.3">
    <Response>51 01</Response>
  </Data>
</Service>
```

## 内置服务 0x10 和 0x3E

`0x10 DiagnosticSessionControl` 和 `0x3E TesterPresent` 是程序内置处理的服务，不需要在 XML 中配置。

`0x10` 示例：

```text
请求: 10 03
响应: 50 03 00 32 01 F4
```

响应中的 `00 32` 表示 P2 约 50 ms，`01 F4` 表示 P2* 约 5000 ms。

`0x3E` 示例：

```text
请求: 3E 00
响应: 7E 00
```

如果请求是 `3E 80`，表示抑制正响应，Simulator 不返回报文。

## 添加一个新的 DID

例如要给 Gateway ECU 添加软件版本 DID `F195`：

```xml
<Service id="0x22">
  <Data did="0xF195">
    <Response>62 F1 95 56 31 2E 30 2E 30</Response>
  </Data>
</Service>
```

放置位置：找到目标 ECU 下已有的 `<Service id="0x22">`，把这个 `<Data>` 放到该 Service 内部。

Tester 输入：

```text
22 F1 95
```

预期返回：

```text
62 F1 95 56 31 2E 30 2E 30
```

其中 `56 31 2E 30 2E 30` 是 ASCII 字符串 `V1.0.0`。

## 添加一个新的例程控制 0x31

例如添加启动例程 `31 01 12 34`：

```xml
<Service id="0x31">
  <Data request="31 01 12 34" simulate_pending="true" total_delay="1.5" pending_interval="0.5">
    <Response>71 01 12 34 00</Response>
  </Data>
</Service>
```

Tester 输入：

```text
31 01 12 34
```

预期过程：

```text
7F 31 78
71 01 12 34 00
```

## 添加一个新的写 DID 0x2E

例如允许写入 DID `F191`，写入值必须是 `12 34`：

```xml
<Service id="0x2E">
  <Data request="2E F1 91 12 34">
    <Response>6E F1 91</Response>
  </Data>
</Service>
```

如果请求中的数据不是 `12 34`，不会匹配这条规则，程序会返回负响应。

## 常见错误

- XML 标签没有闭合：程序启动或热加载时会报 XML 解析错误。
- ECU 地址和 Tester Target 不一致：会返回负响应或访问不到预期 ECU。
- DID 写错字节顺序：`F190` 请求应是 `22 F1 90`，不是 `22 90 F1`。
- `<Response>` 少写正响应 SID：例如 `0x22` 响应必须从 `62` 开始。
- 十六进制出现奇数位：例如 `1` 应写成 `01`。
- 同一个 `<Service id="...">` 在同一个 ECU 下重复出现：后面的 Service 会覆盖前面的 Service，建议把同一 SID 的 `<Data>` 都放在同一个 Service 中。

## 推荐维护流程

1. 复制一段已有的 `<Data>`。
2. 修改 `did` 或 `request`。
3. 修改 `<Response>` 为完整 UDS 响应。
4. 保存 `mock_data.xml`。
5. 在 Tester GUI 中发送请求验证响应。
6. 如果没有生效，先检查目标 ECU 地址，再检查 XML 是否保存成功。

## 网关 ECU 与代理 ECU 路由配置

ECU 节点支持 `role`、`access`、`gateway` 三个路由属性，用来模拟真实车辆中的 DoIP 网关和内部 ECU 代理访问关系。

推荐写法：

```xml
<Ecu name="Gateway" address="0x1001" role="gateway" access="direct">
  ...
</Ecu>

<Ecu name="BodyControlModule" address="0x1002" role="ecu" access="proxied" gateway="0x1001">
  ...
</Ecu>

<Ecu name="ADAS" address="0x1101" role="ecu" access="direct">
  ...
</Ecu>
```

属性含义：

- `role="gateway"`：该 ECU 具备网关身份，可以作为其他代理 ECU 的归属网关。
- `role="ecu"`：普通 ECU。未填写时默认是 `ecu`。
- `access="direct"`：Tester 可以直接用该 ECU 的逻辑地址作为 Target 访问。未填写时默认是 `direct`，因此旧 XML 不会失效。
- `access="proxied"`：该 ECU 是被代理 ECU，必须配置 `gateway="0x...."`。
- `gateway="0x1001"`：声明该 ECU 由哪个 `role="gateway"` 的 ECU 代理。

路由规则：

- direct ECU 可以直接访问。
- proxied ECU 只有在 `gateway` 指向一个存在且 `role="gateway"` 的 ECU 时才允许访问。
- proxied ECU 如果没有配置 `gateway`，或 `gateway` 指向的 ECU 不存在/不是网关，会返回负响应：

```text
7F SID 31
```

示例：

```xml
<Ecu name="Gateway" address="0x1001" role="gateway" access="direct" />
<Ecu name="BCM" address="0x1002" role="ecu" access="proxied" gateway="0x1001" />
```

Tester 的 Target 填 `0x1002` 时，模拟器会认为该请求由 Gateway `0x1001` 代理转发到 BCM。

## DoIP 层配置

可以在 `<Simulator>` 下配置 `<DoIP>`：

```xml
<DoIP allowed_testers="0x0E80" diagnostic_ack="true" />
```

属性含义：

- `allowed_testers`：允许接入的 Tester 源逻辑地址。可以写多个，例如 `0x0E80,0x0E81`。不写或留空表示不限制。
- `diagnostic_ack`：是否启用 DoIP Diagnostic Message ACK。`true` 时，Simulator 收到 `0x8001` 诊断消息后，会先返回 `0x8002` ACK，然后再返回 UDS 响应。

Routing Activation 行为：

- 源地址在白名单内：返回 routing activation response code `0x10`。
- 源地址不在白名单内：返回非 `0x10` 响应码，并关闭连接。

Diagnostic Message 行为：

- 合法诊断消息：先返回 `0x8002` ACK，再返回 `0x8001` UDS 响应。
- 非法源地址或格式错误：返回 `0x8003` NACK。

Alive Check：

```text
Payload Type 0x0007: Alive Check Request
Payload Type 0x0008: Alive Check Response
```

Tester 工具会忽略 DoIP ACK/NACK，不会把 ACK/NACK 放进 UDS 响应队列。

## 0x27 SecurityAccess 与权限控制

ECU 节点可以配置 SecurityAccess 等级：

```xml
<Security>
  <Level
      name="level1"
      request_seed="0x01"
      send_key="0x02"
      seed="12 34 56 78"
      key="87 65 43 21"
      max_attempts="3"
      lock_time="10.0" />
</Security>
```

属性含义：

- `name`：安全等级名称，供 `required_security` 引用。
- `request_seed`：请求 seed 的子功能，例如 `27 01`。
- `send_key`：发送 key 的子功能，例如 `27 02`。
- `seed`：模拟器返回给 Tester 的 seed。
- `key`：Tester 必须发送的 key。当前是 mock 固定 key，不做真实算法计算。
- `max_attempts`：错误 key 最大次数。
- `lock_time`：达到错误次数后的锁定时间，单位秒。

典型流程：

```text
请求: 27 01
响应: 67 01 12 34 56 78

请求: 27 02 87 65 43 21
响应: 67 02
```

错误 key 行为：

```text
请求: 27 02 00 00 00 00
响应: 7F 27 35
```

达到 `max_attempts` 后：

```text
响应: 7F 27 36
```

锁定时间内再次请求 seed/key：

```text
响应: 7F 27 37
```

服务或 Data 可以配置会话/安全权限：

```xml
<Service id="0x2E" required_session="0x03" required_security="level1">
  <Data request="2E F1 91 12 34">
    <Response>6E F1 91</Response>
  </Data>
</Service>
```

也可以只限制某条 Data：

```xml
<Data request="31 01 FF 00" required_session="0x03" required_security="level1">
  <Response>71 01 FF 00 00</Response>
</Data>
```

权限不足时的典型负响应：

- 会话不满足：`7F SID 7F`
- 安全等级未解锁：`7F SID 33`

推荐验证顺序：

```text
10 03
27 01
27 02 87 65 43 21
2E F1 91 12 34
31 01 FF 00
```

## 0x34 / 0x36 / 0x37 刷写下载链路

ECU 节点可以配置下载区间和权限：

```xml
<Download
    start_address="0x00010000"
    end_address="0x0001FFFF"
    max_block_length="0x08"
    required_session="0x03"
    required_security="level1" />
```

属性含义：

- `start_address`：允许下载的起始地址。
- `end_address`：允许下载的结束地址。
- `max_block_length`：每个 `36 TransferData` 块允许携带的最大数据长度。
- `required_session`：请求下载/传输/退出传输要求的会话。
- `required_security`：请求下载/传输/退出传输要求的安全等级。

需要在 ECU 下配置服务入口：

```xml
<Service id="0x34" handler="download" />
<Service id="0x36" handler="dynamic_echo" required_session="0x03" required_security="level1" />
<Service id="0x37" handler="transfer_exit" />
```

典型流程：

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

说明：

- `34` 的第 3 字节是 AddressAndLengthFormatIdentifier。
- 示例中的 `0x44` 表示地址 4 字节、长度 4 字节。
- 地址是 `00 01 00 00`，长度是 `00 00 00 04`。
- `36` 的第 2 字节是 blockSequenceCounter。
- 重复发送同一个 blockSequenceCounter 会返回上一次正响应。
- 跳号会返回 `7F 36 73`。
- 收到的数据长度等于 `34` 中声明的 memorySize 后，`37` 返回 `77`。

刷写负响应：

- 未进入要求会话：`7F SID 7F`
- 未完成安全解锁：`7F SID 33`
- 未开始下载就发送 `36/37`：`7F SID 70`
- 块序号错误：`7F 36 73`
- 传输长度不足就 `37`：`7F 37 71`
- 地址超出下载区间：`7F 34 31`

## 增强 DTC 状态字段

`<Dtc>` 现在可以配置更接近真实 ECU 的清码和记录行为：

```xml
<Dtc
    code="0x123456"
    status="0x09"
    severity="0x20"
    functional_unit="0x10"
    fault_detection_counter="0x7F"
    snapshot_record="0x01"
    snapshot="01 02 F1 90 12 34"
    extended_data_record="0x01"
    extended_data="01 AA BB CC"
    clear_status="0x08"
    clear_fault_detection_counter="0x01" />

<Dtc code="0x223344" status="0x2F" clearable="false" />
```

新增字段说明：

- `clearable`：是否允许被 `0x14` 清除，默认 `true`。配置为 `false` 时，即使发送 `14 FF FF FF` 也会保留。
- `clear_status`：清码后写入的新状态字节，默认 `0x00`。可用于模拟清码后转为 pending、history 等状态。
- `clear_fault_detection_counter`：清码后写入的新 FDC，默认 `0x00`。
- `snapshot_record`：`19 04` 支持的快照记录号，默认 `0x01`。
- `extended_data_record`：`19 06` 支持的扩展数据记录号，默认 `0x01`。

## 增强 0x19 子服务

除原有子服务外，现在支持严重度相关查询：

```text
19 07 severityMask statusMask
19 08 dtcHigh dtcMiddle dtcLow
19 09 severityMask statusMask
```

示例：

```text
请求: 19 07 20 FF
响应: 59 07 FF 01 00 01

请求: 19 08 12 34 56
响应: 59 08 20 10 12 34 56 09

请求: 19 09 20 FF
响应: 59 09 FF 20 10 12 34 56 09
```

说明：

- `severityMask` 会和 DTC 的 `severity` 做按位匹配。
- `statusMask` 会和 DTC 的 `status` 做按位匹配。
- `19 08` 返回 `severity + functional_unit + DTC + status`。

## 增强 0x14 清码逻辑

`0x14` 仍然使用 3 字节 `groupOfDTC`：

```text
14 FF FF FF
14 12 34 56
14 12 34
14 12
```

匹配到的 DTC 会按照自身 `<Dtc>` 字段处理：

- `clearable="true"`：状态变为 `clear_status`，FDC 变为 `clear_fault_detection_counter`。
- `clearable="false"`：DTC 保持原状态。
- 未匹配 group 的 DTC 不受影响。

如果 `0x14` 服务配置了权限：

```xml
<Service id="0x14" handler="clear_dtc" required_session="0x03" required_security="level1" />
```

则需要先完成：

```text
10 03
27 01
27 02 87 65 43 21
14 FF FF FF
```

否则会返回：

```text
7F 14 7F
7F 14 33
```

## 增强 0x11 Reset 逻辑

`0x11` 服务支持更多 reset 行为配置：

```xml
<Service id="0x11"
         handler="ecu_reset"
         reset_behavior="disconnect"
         reset_delay="10.0"
         supported_reset_types="0x01,0x02,0x03"
         restore_dtcs_on_reset="true" />
```

字段说明：

- `supported_reset_types`：允许的 resetType 列表。未配置时默认支持 `0x01/0x02/0x03`。
- `restore_dtcs_on_reset`：是否在 reset 后把 DTC 恢复为 XML 初始状态，默认 `true`。
- `reset_behavior="disconnect"`：正响应后主动断开 TCP。
- `reset_delay`：重启窗口，单位秒；窗口内请求会返回 `7F SID 21`。

典型负响应：

```text
11 04 -> 7F 11 12
11 01 00 -> 7F 11 13
```
