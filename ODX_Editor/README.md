# ODX Editor 使用说明

ODX Editor 是一个 Windows 桌面应用，用于新建、加载、查看、编辑、保存和导出 ODX/PDX 文件。当前版本以通用 XML 树编辑为核心，同时复用项目根目录下的公共 `odx` 模块处理 ODX/PDX 的读取、XML 校验、格式化和 PDX 导出。

## 1. 启动应用

运行以下文件：

```text
D:\Diagnostic simulator\ODX_Editor\dist\ODX_Editor.exe
```

启动后会自动创建一个基础 ODX 文档，界面底部会显示运行日志。日志文件会写入：

```text
D:\Diagnostic simulator\ODX_Editor\dist\logs\odx_editor.log
```

如果按钮点击后没有明显变化，先看底部“运行日志”，再查看上面的日志文件。

## 2. 界面区域

### 顶部工具栏

- `新建 ODX`：创建一个基础 ODX 文档。若当前文档有未保存修改，会提示是否丢弃。
- `加载 ODX/PDX`：打开 `.odx`、`.xml`、`.pdx` 文件。
- `保存 ODX`：把当前 XML 内容保存为 `.odx` 或 `.xml` 文件。
- `导出 PDX`：把当前 XML 内容写入一个 `.pdx` 压缩包。
- `格式化 XML`：解析右侧 XML 源码，格式化后同步左侧树形结构。
- `检查 XML`：检查右侧 XML 源码是否是合法 XML。

### 左侧工程信息

- `文件`：当前加载或保存的文件路径。
- `类型`：当前文档类型，通常是 `ODX` 或 `PDX`。
- `状态`：显示 `未修改` 或 `已修改`。

### 左侧 ODX 概览

当前统计以下标签数量：

- `DIAG-LAYER`：诊断层数量。
- `DIAG-SERVICE`：诊断服务数量。
- `REQUEST`：请求定义数量。
- `DATA-OBJECT-PROP`：DOP 数据对象属性数量。

### 左侧 XML 结构

以树形方式显示 XML 节点。点击任意节点后，右侧“可视化编辑”区域会显示该节点的属性和文本内容。

### 中间可视化编辑

选中 XML 节点后，可以编辑：

- 节点属性名。
- 节点属性值。
- 节点直接文本内容。

修改后点击 `应用属性修改`。如果只是添加属性，先点击 `添加属性`，填写属性名和值，再点击 `应用属性修改`。

`删除选中节点` 会删除当前选中的 XML 节点。根节点 `ODX` 不能删除。

### 右侧 XML 源码

显示完整 XML。可以直接编辑源码。源码编辑后，左侧树不会立即自动同步，需要点击：

- `检查 XML`：只检查合法性。
- `格式化 XML`：检查、格式化，并同步树形结构。

## 3. 基本工作流

### 新建 ODX

1. 点击 `新建 ODX`。
2. 应用会创建一个包含 `ODX`、`DIAG-LAYER`、`DIAG-SERVICE`、`REQUEST` 的基础文档。
3. 在 XML 树中选择节点。
4. 在可视化编辑区修改属性，或在 XML 源码中直接编辑。
5. 点击 `保存 ODX` 或 `导出 PDX`。

### 加载 ODX/XML

1. 点击 `加载 ODX/PDX`。
2. 选择 `.odx` 或 `.xml` 文件。
3. 应用读取 XML，刷新左侧 XML 树、ODX 概览和源码区。
4. 编辑完成后点击 `保存 ODX`。

### 加载 PDX

1. 点击 `加载 ODX/PDX`。
2. 选择 `.pdx` 文件。
3. 应用会把 PDX 当作 ZIP 容器读取。
4. 应用会在 PDX 内查找 `.odx` 或 `.xml` 条目。
5. 如果 PDX 内有多个 ODX/XML 条目，会提示输入要打开的条目名称。
6. 编辑完成后点击 `导出 PDX`。

导出 PDX 时，应用会保留原 PDX 内的其他文件，并把当前编辑的 ODX/XML 条目替换为最新内容。

## 4. 测试样例

可以用以下目录中的样例验证加载流程：

```text
D:\Diagnostic simulator\tests\.tmp
```

典型样例：

```text
D:\Diagnostic simulator\tests\.tmp\odx_data.xml
D:\Diagnostic simulator\tests\.tmp\sample.pdx
```

## 5. ODX 基础结构

当前项目支持的是一个轻量 ODX 子集，重点服务 Tester、ODX Editor 和后续 OTX Editor 的诊断流程。一个典型文件如下：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<ODX>
  <DATA-OBJECT-PROP ID="DOP.VIN_ASCII" SHORT-NAME="DOP.VIN_ASCII">
    <DIAG-CODED-TYPE BASE-DATA-TYPE="A_ASCIISTRING" BIT-LENGTH="136" />
  </DATA-OBJECT-PROP>

  <REQUEST ID="REQ.READ_VIN" SHORT-NAME="REQ.READ_VIN">
    <BYTES>22 F1 90</BYTES>
  </REQUEST>

  <DIAG-SERVICE ID="SERVICE.READ_VIN" SHORT-NAME="Read VIN" SEMANTIC="READ-DATA-BY-IDENTIFIER">
    <REQUEST-REF ID-REF="REQ.READ_VIN" />
    <POS-RESPONSE>62 F1 90</POS-RESPONSE>
  </DIAG-SERVICE>

  <DIAG-LAYER SHORT-NAME="Gateway" LOGICAL-ADDRESS="0x1001" ROLE="gateway" ACCESS="direct">
    <DATA-IDENTIFIER ID="0xF190" SHORT-NAME="VIN" DESC="Vehicle identification number">
      <DOP-REF ID-REF="DOP.VIN_ASCII" />
    </DATA-IDENTIFIER>
    <ROUTINE ID="0xFF00" SHORT-NAME="Pre-programming routine" CONTROL="0x01" />
  </DIAG-LAYER>

  <QUICK-ACTIONS>
    <ACTION SHORT-NAME="Read VIN" REQUEST="22 F1 90" />
  </QUICK-ACTIONS>
</ODX>
```

## 6. 常用标签和参数

### `ODX`

根节点。一个 ODX 文件必须有且只有一个 XML 根节点，当前建议根节点命名为 `ODX`。

```xml
<ODX>
  ...
</ODX>
```

### `DIAG-LAYER`

定义一个诊断层，通常可以理解为一个 ECU、网关或诊断目标。

```xml
<DIAG-LAYER SHORT-NAME="Gateway" LOGICAL-ADDRESS="0x1001" ROLE="gateway" ACCESS="direct">
  ...
</DIAG-LAYER>
```

参数说明：

- `SHORT-NAME`：诊断层名称。Tester 会把它显示为 ECU 名称。
- `LOGICAL-ADDRESS`：DoIP/UDS 目标逻辑地址。支持 `0x1001` 或 `1001` 这类写法。
- `ROLE`：角色。常见值有 `gateway`、`ecu`。
- `ACCESS`：访问方式。常见值有 `direct`、`proxied`。

Tester 用法：

- `LOGICAL-ADDRESS` 会用于 ECU 目标列表。
- `SHORT-NAME`、`ROLE`、`ACCESS` 会显示在 Tester 的 ECU 表格中。

### `DATA-IDENTIFIER`

定义一个 DID，也就是 UDS `ReadDataByIdentifier` 使用的数据标识符。

```xml
<DATA-IDENTIFIER ID="0xF190" SHORT-NAME="VIN" DESC="Vehicle identification number">
  <DOP-REF ID-REF="DOP.VIN_ASCII" />
</DATA-IDENTIFIER>
```

参数说明：

- `ID`：DID 编号。支持 `0xF190`、`F190`、`61840` 等可解析为整数的写法。
- `SHORT-NAME`：DID 名称，例如 `VIN`。
- `DESC`：描述文本，用于说明这个 DID 的含义。
- `RESPONSE-OFFSET`：可选。响应中真实数据的起始偏移，默认是 `3`。例如 `62 F1 90` 后面才是 DID 数据，所以默认偏移是 3。

子节点：

- `DOP-REF`：引用一个 `DATA-OBJECT-PROP`，用于说明响应数据如何解码。

Tester 用法：

- Signal 页面会把 DID 列出来。
- 读取 DID 时，默认生成请求 `22 DID高字节 DID低字节`。
- 收到响应后，会根据 `DOP-REF` 找到 DOP 并解码数据。

### `DOP-REF`

把 DID 连接到一个 DOP。

```xml
<DOP-REF ID-REF="DOP.VIN_ASCII" />
```

参数说明：

- `ID-REF`：引用的 DOP 名称。应与 `DATA-OBJECT-PROP` 的 `SHORT-NAME` 或 `ID` 对应。

### `DATA-OBJECT-PROP`

定义数据对象属性，说明某段响应字节是什么类型、长度是多少、如何解码。

```xml
<DATA-OBJECT-PROP ID="DOP.VIN_ASCII" SHORT-NAME="DOP.VIN_ASCII">
  <DIAG-CODED-TYPE BASE-DATA-TYPE="A_ASCIISTRING" BIT-LENGTH="136" />
</DATA-OBJECT-PROP>
```

参数说明：

- `ID`：DOP 的唯一标识。
- `SHORT-NAME`：DOP 名称。当前解码引用优先使用这个名称。
- `BASE-DATA-TYPE`：可直接写在 `DATA-OBJECT-PROP` 上，也可以写在 `DIAG-CODED-TYPE` 上。
- `BIT-LENGTH`：数据位长度。
- `BYTE-LENGTH`：数据字节长度。若没有设置，程序会用 `BIT-LENGTH` 自动换算。
- `COMPU-METHOD-REF`：可选，引用一个计算方法。

当前支持的数据类型：

- `A_ASCIISTRING`、`ASCII`、`STRING`：按 ASCII 字符串解码。
- `A_UTF8STRING`、`UTF8`：按 UTF-8 字符串解码。
- `A_UINT8`、`A_UINT16`、`A_UINT32`、`A_UINT64`：按大端无符号整数解码。
- `A_INT8`、`A_INT16`、`A_INT32`、`A_INT64`：按大端有符号整数解码。
- 其他类型：按十六进制字节串显示。

### `DIAG-CODED-TYPE`

描述 DOP 的编码类型。

```xml
<DIAG-CODED-TYPE BASE-DATA-TYPE="A_ASCIISTRING" BIT-LENGTH="136" />
```

参数说明：

- `BASE-DATA-TYPE`：基础数据类型。
- `BIT-LENGTH`：位长度。例如 VIN 是 17 字节，17 * 8 = `136`。

### `COMPU-METHOD`

定义物理值换算方法。当前公共 ODX 模型支持 `LINEAR` 线性换算。

```xml
<COMPU-METHOD SHORT-NAME="CM.SPEED" CATEGORY="LINEAR" UNIT="km/h">
  <V>0</V>
  <V>0.01</V>
  <V>1</V>
</COMPU-METHOD>
```

参数说明：

- `SHORT-NAME`：计算方法名称。
- `CATEGORY`：计算类型。当前 `LINEAR` 会执行线性换算，其他值按原始值返回。
- `UNIT`：单位，例如 `km/h`、`V`、`degC`。

`V` 参数说明：

- 第 1 个 `V`：offset。
- 第 2 个 `V`：factor。
- 第 3 个 `V`：denominator。

换算公式：

```text
physical = (internal * factor + offset) / denominator
```

### `REQUEST`

定义一条 UDS 请求。

```xml
<REQUEST ID="REQ.READ_VIN" SHORT-NAME="REQ.READ_VIN">
  <BYTES>22 F1 90</BYTES>
</REQUEST>
```

参数说明：

- `ID`：请求唯一标识。
- `SHORT-NAME`：请求名称。`REQUEST-REF` 会通过这个名称或标识引用请求。

子节点：

- `BYTES`：请求字节，使用空格分隔的十六进制字符串。

`BYTES` 写法示例：

```xml
<BYTES>22 F1 90</BYTES>
<BYTES>10 03</BYTES>
<BYTES>31 01 FF 00</BYTES>
```

### `DIAG-SERVICE`

定义诊断服务。

```xml
<DIAG-SERVICE ID="SERVICE.READ_VIN" SHORT-NAME="Read VIN" SEMANTIC="READ-DATA-BY-IDENTIFIER">
  <REQUEST-REF ID-REF="REQ.READ_VIN" />
  <POS-RESPONSE>62 F1 90</POS-RESPONSE>
</DIAG-SERVICE>
```

参数说明：

- `ID`：服务唯一标识。
- `SHORT-NAME`：服务显示名称。
- `SEMANTIC`：服务语义，例如 `READ-DATA-BY-IDENTIFIER`、`ROUTINE-CONTROL`、`SESSION-CONTROL`。
- `REQUEST`：可选，也可以直接写在属性里，例如 `REQUEST="22 F1 90"`。
- `POS-RESPONSE`：可选，也可以直接写在属性里，例如 `POS-RESPONSE="62 F1 90"`。

子节点：

- `REQUEST-REF`：引用 `REQUEST`。
- `POS-RESPONSE`：正响应前缀。

Tester 用法：

- `request_for_did()` 会优先查找请求字节为 `22 + DID` 的服务。
- 如果没有找到服务，会自动生成 `22 DID` 请求。

### `REQUEST-REF`

引用一个 `REQUEST`。

```xml
<REQUEST-REF ID-REF="REQ.READ_VIN" />
```

参数说明：

- `ID-REF`：请求引用名称。应指向某个 `REQUEST` 的 `SHORT-NAME` 或 `ID`。

### `POS-RESPONSE`

定义正响应前缀。

```xml
<POS-RESPONSE>62 F1 90</POS-RESPONSE>
```

参数说明：

- 文本内容是十六进制字节。
- 读取 VIN 请求 `22 F1 90` 的正响应通常以 `62 F1 90` 开头。

### `ROUTINE`

定义 Routine Control 使用的例程。

```xml
<ROUTINE ID="0xFF00" SHORT-NAME="Pre-programming routine" CONTROL="0x01" />
```

参数说明：

- `ID`：Routine ID。支持 `0xFF00` 或 `FF00`。
- `SHORT-NAME`：例程名称。
- `CONTROL`：Routine Control 类型。常见值：
  - `0x01`：startRoutine。
  - `0x02`：stopRoutine。
  - `0x03`：requestRoutineResults。

Tester 用法：

- Routine 页面可以使用这些 Routine 信息作为默认或候选诊断动作。

### `QUICK-ACTIONS`

快捷动作容器。

```xml
<QUICK-ACTIONS>
  <ACTION SHORT-NAME="Read VIN" REQUEST="22 F1 90" />
</QUICK-ACTIONS>
```

### `ACTION`

定义 Tester 中可直接点击的快捷诊断请求。

```xml
<ACTION SHORT-NAME="Read VIN" REQUEST="22 F1 90" />
```

参数说明：

- `SHORT-NAME`：按钮显示名称。
- `REQUEST`：点击后发送的 UDS 请求字节。

Tester 用法：

- Tester Overview 页面会把 `ACTION` 转成 Guided Actions 按钮。

## 7. 十六进制参数写法

当前公共 ODX 模型对整数参数会做归一化。

### DID / Routine / Address

下面写法通常都可以被解析：

```text
0xF190
F190
61840
```

解析后 DID 会统一显示成 4 位大写十六进制：

```text
F190
```

逻辑地址也会统一显示成 4 位大写十六进制：

```text
1001
```

### 请求字节

请求字节应使用完整字节，每个字节两个十六进制字符，推荐用空格分隔：

```text
22 F1 90
10 03
27 01
31 01 FF 00
```

不建议写成：

```text
22F190
```

因为当前 ODX 解析器的 `BYTES` 字段按空格拆分字节。

## 8. PDX 文件说明

PDX 在当前项目中按 ZIP 容器处理。一个 PDX 内可以包含：

- 一个或多个 `.odx` / `.xml` 文件。
- 其他附属文件。

加载规则：

- 应用会读取所有文件条目。
- 查找后缀为 `.odx` 或 `.xml` 的条目。
- 默认打开第一个 ODX/XML 条目。
- 如果有多个，会提示输入条目名称。

导出规则：

- 当前编辑的 ODX/XML 条目会被替换成最新 XML。
- 原 PDX 中其他文件会被保留。
- 导出的 PDX 使用 ZIP deflate 压缩。

## 9. 与 Tester 的关系

ODX Editor 和 Tester 现在共用项目根目录下的公共 `odx` 包：

```text
D:\Diagnostic simulator\odx
```

Tester 会使用其中的领域模型：

- `OdxDatabase`
- `OdxEcu`
- `OdxDid`
- `OdxDataObjectProperty`
- `OdxRoutine`
- `OdxQuickAction`

因此，ODX Editor 中编辑出来的 ODX/PDX，如果包含 Tester 支持的标签和参数，就可以被 Tester 读取并用于：

- ECU 目标列表。
- Signal/DID 列表。
- Quick Actions。
- DID 响应解码。
- Routine 页面候选项。

## 10. 常见问题排查

### 点击按钮没有反应

查看界面底部“运行日志”。如果仍不清楚，再打开：

```text
D:\Diagnostic simulator\ODX_Editor\dist\logs\odx_editor.log
```

重点看：

- 是否记录了 `开始：加载文件`。
- 文件选择结果是否为空。
- XML 是否解析失败。
- PDX 中是否找到了 `.odx` 或 `.xml` 条目。

### 加载 PDX 失败

可能原因：

- 文件不是合法 ZIP/PDX。
- PDX 内没有 `.odx` 或 `.xml` 文件。
- PDX 内 XML 编码不是 UTF-8 或 UTF-8 BOM。
- XML 本身不合法。

### XML 树没有同步

如果你直接编辑了右侧 XML 源码，需要点击 `格式化 XML`。仅输入源码不会自动刷新左侧树。

### 保存后 Tester 没有看到新 DID

检查：

- DID 是否写在 `DIAG-LAYER` 内。
- `DATA-IDENTIFIER` 是否有 `ID` 和 `SHORT-NAME`。
- 如果需要解码，是否配置了 `DOP-REF`。
- `DOP-REF ID-REF` 是否能匹配 `DATA-OBJECT-PROP SHORT-NAME`。

## 11. 当前限制

- 当前是通用 XML 树编辑器，不是完整 ASAM ODX 专用建模器。
- 尚未提供图形化 DID/Service/Routine 向导。
- 尚未做完整 ODX schema 校验。
- 命名空间 ODX 可以读取一部分，但专用表单统计主要面向当前轻量 ODX 子集。
- 源码区编辑后需要点击 `格式化 XML` 才会同步树。

## 12. 后续建议

后续可以继续扩展：

- DID 专用编辑表单。
- DOP 类型选择器。
- Service 请求/响应编辑器。
- Routine 向导。
- 引用校验，例如 `DOP-REF`、`REQUEST-REF` 是否有效。
- ODX 与 Tester 配置的一键同步。
- OTX Editor 通过同一套 `odx` 公共模型引用 DID、Service 和 Routine。

## 13. 当前版本重点更新

### 13.1 新建节点交互

`新建子节点` 和 `新建同级节点` 已经改为直接在左侧 XML 树中生成节点，不再弹出小输入框。

操作方式：

1. 在左侧 XML 树选中一个节点。
2. 点击中间按钮 `新建子节点`，或在左侧 XML 树右键选择 `新建子节点`。
3. 新节点会立即出现在选中节点下面。
4. 应用会自动选中新节点。
5. 中间 `可视化编辑` 区会显示空白编辑表单。
6. 在 `节点名称` 中输入真实 XML 标签名，例如 `DATA-OBJECT-PROP`、`DIAG-CODED-TYPE`、`DIAG-SERVICE`。
7. 在属性表中填写 `ID`、`SHORT-NAME`、`BASE-DATA-TYPE`、`BIT-LENGTH` 等属性。
8. 点击 `应用属性修改`，左侧 XML 树、右侧 XML 源码、Domain 视图会同步刷新。

同级节点默认沿用当前选中节点的标签名。子节点会尽量根据已有子节点推断默认标签名；如果没有参考节点，则使用 `NEW-NODE`。

### 13.2 节点名称、属性和文本

中间 `可视化编辑` 区现在可以编辑三类内容：

- `节点名称`：XML 标签名，例如 `DATA-OBJECT-PROP`。
- `属性`：XML 属性键值对，例如 `ID="DOP.SPEED"`、`SHORT-NAME="DOP.SPEED"`。
- `文本内容`：节点直接文本，例如 `<BYTES>22 F1 90</BYTES>` 中的 `22 F1 90`。

属性行左侧是属性名，右侧是属性值。空属性名不会写入 XML。

### 13.3 XML 源码高亮

左侧 XML 树选中节点后，右侧 XML 源码会高亮同一个节点。

现在高亮不再通过简单文本搜索实现，而是基于内部选中节点计算源码位置。因此多个同名节点、多个 `DATA-OBJECT-PROP`、多个相似片段同时存在时，也会定位到当前选中的那个节点。

### 13.4 中间编辑区与源码区同步

ODX Editor 支持两种编辑方式：

- 在中间 `可视化编辑` 区编辑节点。
- 在右侧 `XML 源码` 区直接编辑 XML。

同步规则：

- 修改中间编辑区后，点击 `应用属性修改`，会刷新右侧 XML 源码、左侧 XML 树、Domain 视图。
- 修改右侧 XML 源码后，点击 `应用属性修改`，会先解析右侧源码并同步到内部 XML 树，再把中间编辑区当前内容应用到选中节点。
- 修改右侧 XML 源码后，点击 `检查 XML`，会校验 XML，并同步左侧 XML 树、Domain 视图和中间编辑区。
- 修改右侧 XML 源码后，点击 `格式化 XML`，会解析、格式化并同步所有视图。

如果右侧源码不是合法 XML，同步会失败并显示错误。先修复 XML 语法，再继续编辑。

### 13.5 Domain 领域视图

左侧 `XML 结构` 区现在包含两个标签页：

- `XML`：原始 XML 树。
- `Domain`：基于公共 `odx` 模块解析出的诊断领域对象。

`Domain` 视图显示：

- ECU
- Service
- DID
- DOP
- Structure
- NRC
- Validation

选中 DID 后，下方详情区会显示引用链：

```text
DID -> DOP/STRUCTURE -> COMPU -> UNIT
```

这可以帮助确认 DID 是否正确连接到 DOP、STRUCTURE、COMPU-METHOD 和 UNIT。

### 13.6 保存、另存为和 PDX 导出

- `保存 ODX`：如果当前文件是 `.odx` 或 `.xml`，会直接写回原路径。
- `另存为 ODX`：选择新路径保存当前 XML。
- `导出 PDX`：将当前 XML 写入 PDX 包；如果原来是 PDX，会保留包内其他文件并替换当前 ODX/XML 条目。

### 13.7 与 Tester 的配合

ODX Editor 编辑出的 ODX/PDX 可以在 Tester GUI 中加载：

```text
Tester GUI -> Settings -> ODX / PDX Database -> Choose ODX/PDX
```

Tester 会基于公共 `odx` 模块解析：

- ECU 目标列表
- DID/Signal 列表
- STRUCTURE 字段表单
- ODX Service Request Builder
- Routine 默认值
- Quick Actions
- NRC 语义

建议编辑完成后先在 ODX Editor 中点击 `检查 XML` 或 `格式化 XML`，确认 XML 能解析，再在 Tester 中加载。
