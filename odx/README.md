# 公共 ODX 模块说明

`D:\Diagnostic simulator\odx` 是当前项目的公共 ODX/PDX 解析模块。Tester、ODX Editor、后续 OTX Editor 都应优先复用这里的模型和函数，避免每个工具各写一套 ODX 解析逻辑。

## 1. 模块定位

公共模块负责：

- 打开 `.odx`、`.xml`、`.pdx`
- 从 PDX ZIP 包中提取 ODX/XML 条目
- 解析轻量 ODX 子集
- 建立诊断领域模型
- 编码 DID 和服务请求
- 解码 DID 响应
- 解释负响应 NRC
- 做引用校验和基础结构校验
- 给编辑器提供 XML 文档视图

公共模块不负责：

- GUI 布局
- DoIP 通信
- UDS socket 发送
- 完整 ASAM ODX schema 校验
- 保存时完全保留所有 XML 空白和注释

## 2. 入口 API

常用导入：

```python
from odx import (
    load_odx,
    load_pdx,
    build_index,
    validate_database,
    decode_negative_response,
    describe_nrc,
    resolve_inheritance,
)
```

加载 ODX/XML/PDX：

```python
from pathlib import Path
from odx import load_odx

database = load_odx(Path(r"D:\Diagnostic simulator\tests\.tmp\odx_data.xml"))
```

`load_odx()` 会根据后缀自动判断：

- `.odx`
- `.xml`
- `.pdx`
- `.zip`

如果是 PDX，会读取包内所有 `.odx/.xml` 条目并合并为一个 `OdxDatabase`。

## 3. 领域模型

核心模型在 `model.py` 中：

- `OdxDatabase`
- `OdxEcu`
- `OdxDid`
- `OdxDataObjectProperty`
- `OdxComputation`
- `OdxUnit`
- `OdxStructure`
- `OdxStructureField`
- `OdxDiagService`
- `OdxResponse`
- `OdxNegativeResponse`
- `OdxParameter`
- `OdxRoutine`
- `OdxDtc`
- `OdxQuickAction`
- `OdxLayer`

`OdxDatabase` 是总入口，包含：

```python
database.ecus
database.dids
database.dops
database.computations
database.units
database.structures
database.services
database.routines
database.dtcs
database.quick_actions
database.layers
```

## 4. DID 请求、解码和编码

生成读 DID 请求：

```python
request = database.request_for_did("F190")
# b"\x22\xF1\x90"
```

解码 DID 响应：

```python
value = database.decode_did_response("F190", bytes.fromhex("62 F1 90 56 49 4E"))
```

编码 DID 值：

```python
payload = database.encode_did_value("F191", 100)
```

如果 DID 引用的是 `STRUCTURE`，值应使用字典：

```python
payload = database.encode_did_value(
    "F1B0",
    {
        "Voltage": 12.3,
        "State": "ON",
    },
)
```

结构 DID 解码会返回类似：

```text
Voltage=12.3 V; State=ON
```

## 5. 服务请求编码

公共模块支持按服务参数生成请求：

```python
request = database.encode_service_request(
    "Write battery",
    {
        "BatteryData": {
            "Voltage": 12.3,
            "State": "ON",
        },
    },
)
```

编码规则：

- `CODED-VALUE` 参数会作为常量写入请求。
- `DOP-REF` 参数会使用对应 DOP 编码。
- `STRUCTURE-REF` 参数会展开结构字段并编码。
- 参数位置优先使用 `BYTE-POSITION`。
- 没有 `BYTE-POSITION` 时按顺序拼接。
- 必填输入参数缺失时抛出 `ValueError`。

Tester GUI 的 `ODX Service Request Builder` 使用的就是这个接口。

## 6. COMPU-METHOD 和 UNIT

当前支持：

- `IDENTICAL`
- `LINEAR`
- `SCALE-LINEAR`
- `TEXTTABLE`
- `TEXT-TABLE`

线性换算公式：

```text
physical = (internal * factor + offset) / denominator
internal = (physical * denominator - offset) / factor
```

支持从 `UNIT` 和 `UNIT-REF` 解析单位。

示例：

```xml
<UNIT ID="UNIT.VOLT">
  <SHORT-NAME>UNIT.VOLT</SHORT-NAME>
  <DISPLAY-NAME>V</DISPLAY-NAME>
</UNIT>

<COMPU-METHOD ID="CM.VOLTAGE">
  <SHORT-NAME>CM.VOLTAGE</SHORT-NAME>
  <CATEGORY>SCALE-LINEAR</CATEGORY>
  <UNIT-REF ID-REF="UNIT.VOLT" />
  <V>0</V>
  <V>0.1</V>
  <V>1</V>
</COMPU-METHOD>
```

## 7. STRUCTURE

支持解析：

- `STRUCTURE`
- `END-OF-PDU-FIELD`
- `PARAM`
- `STRUCTURE-FIELD`
- `DOP-REF`
- `STRUCTURE-REF`

示例：

```xml
<STRUCTURE ID="STRUCT.BATTERY" SHORT-NAME="STRUCT.BATTERY">
  <PARAM SHORT-NAME="Voltage" BYTE-POSITION="0">
    <DOP-REF ID-REF="DOP.VOLTAGE" />
  </PARAM>
  <PARAM SHORT-NAME="State" BYTE-POSITION="2">
    <DOP-REF ID-REF="DOP.STATE" />
  </PARAM>
</STRUCTURE>
```

Tester 会把引用 `STRUCTURE` 的 DID 自动显示为字段表单。

## 8. 负响应和 NRC

NRC 工具在 `nrc.py` 中：

```python
from odx import decode_negative_response, describe_nrc

decode_negative_response(bytes.fromhex("7F 22 31"))
# (0x22, 0x31, "Request Out Of Range")

describe_nrc(0x78)
# "Response Pending"
```

常见 NRC 已内置：

- `0x10` General Reject
- `0x11` Service Not Supported
- `0x12` Sub-function Not Supported
- `0x13` Incorrect Message Length Or Invalid Format
- `0x21` Busy Repeat Request
- `0x22` Conditions Not Correct
- `0x31` Request Out Of Range
- `0x33` Security Access Denied
- `0x35` Invalid Key
- `0x36` Exceeded Number Of Attempts
- `0x37` Required Time Delay Not Expired
- `0x70` Upload Download Not Accepted
- `0x71` Transfer Data Suspended
- `0x72` General Programming Failure
- `0x73` Wrong Block Sequence Counter
- `0x78` Response Pending
- `0x7F` Service Not Supported In Active Session

## 9. 索引与查询

`build_index(database)` 会构建常用索引：

```python
index = build_index(database)
index.dids["F190"]
index.routines["FF00"]
index.dop_for_did("F190")
index.computation_for_dop(dop)
index.service_for_request(bytes.fromhex("22 F1 90"))
index.services_with_input_parameters()
```

适合 GUI 快速查找引用。

## 10. 校验

使用：

```python
issues = validate_database(database)
```

当前校验包括：

- DID 引用不存在的 DOP/STRUCTURE
- DOP 引用不存在的 COMPU-METHOD
- STRUCTURE 字段引用不存在的 DOP/STRUCTURE
- 服务参数引用不存在的 DOP/STRUCTURE
- 空服务请求
- 重复 DID、Routine、DTC、Service

返回值是 `OdxValidationIssue` 列表：

```python
issue.severity
issue.code
issue.message
issue.subject
```

## 11. XML 文档模型

`document.py` 提供编辑器辅助模型：

- `OdxDocument`
- `OdxNode`

它保留 XML 节点路径、节点类型、引用状态、修改状态等信息，适合 ODX Editor 或后续 OTX Editor 做可视化导航。

## 12. 测试

运行 ODX 专项测试：

```powershell
cd "D:\Diagnostic simulator"
python -m unittest tests.test_odx
```

运行完整测试：

```powershell
python -m unittest discover -s tests
```

`tests\.tmp` 下的 `.odx/.xml/.pdx` 会作为真实样例进行 smoke test。目标是保证样例能加载并完成校验流程，不要求所有样例都没有 warning。

## 13. 后续扩展方向

建议后续继续补：

- `MUX`
- `DYNAMIC-LENGTH-FIELD`
- `TABLE`
- `TABLE-KEY`
- `SESSION` 前置条件
- `SECURITY` 前置条件
- `IO-CONTROL` 参数模板
- `ROUTINE-CONTROL` 更完整参数模板
- 更完整的 ODX inheritance effective view
- ODX Editor 的领域对象专用编辑表单
