# ContentHive 插件系统

## 系统概述

ContentHive 的插件系统采用了 **Home Assistant 风格的架构**，设计目标是实现一个灵活、模块化、易于扩展的插件管理框架。系统通过插件发现、加载、配置、执行和卸载的完整生命周期来管理各种内容解析器和扩展功能。

---

## 核心架构

### 系统组件关系图

```
插件系统架构：

┌─────────────────────────────────────────────────────────┐
│                    PluginManager                         │
│        (主管理器，协调所有插件的生命周期)                │
└──────────────┬──────────────────────────────────────────┘
               │
        ┌──────┴──────┬──────────────┬──────────────┐
        ▼             ▼              ▼              ▼
   PluginRecord  PluginContext   EventBus      Platform
   (插件记录)    (插件上下文)    (事件总线)    Registry
        ▲
        │ 使用
        │
   ┌────┴────────────────────────────┐
   │                                   │
   ▼                                   ▼
PluginState              manifest.json + Module Code
(状态管理)              (插件元数据 + 插件代码)
```

---

## 各文件详细说明

### 1. `registry.py` - 插件注册表和状态管理

**职责**：定义插件的状态机和记录结构

#### PluginState 枚举
定义了插件的生命周期状态：

```
状态转移流程：
INSTALLED ──async_setup──> LOADED ──async_setup_entry──> ENABLED
    ▲                                                         │
    │                                                         │
    └────────────────── async_unload_entry ◄────────────────┘
                                │
                                ▼
                            DISABLED
                                │
                                ▼
                            FAILED
```

**每个状态的含义**：
- **INSTALLED**：插件已被发现，`manifest.json` 已加载，但还未执行 `async_setup`
- **LOADED**：模块已加载，依赖已安装，等待配置条目的激活
- **ENABLED**：配置条目已激活，插件正在运行
- **DISABLED**：插件被显式禁用，但模块仍在内存中
- **FAILED**：设置或运行时发生错误

#### PluginRecord 类
存储单个插件的所有信息：

```python
PluginRecord {
    domain: str              # 插件唯一标识符（来自 manifest.json）
    manifest: Dict           # 插件元数据（名称、版本、依赖等）
    instance: Optional       # 加载的插件模块对象
    state: PluginState       # 当前状态
    error: Optional[str]     # 错误信息（如果状态为 FAILED）
}
```

---

### 2. `context.py` - 插件执行上下文

**职责**：为插件提供访问应用资源的接口

#### PluginContext 类
插件通过此对象与主应用交互：

```python
PluginContext {
    app: FastAPI                          # FastAPI 应用实例
    data_dir: Path                        # 数据目录
    logger: Logger                        # 日志记录器
    _db_factory: Callable                 # 数据库连接工厂
    data: Dict[str, Any]                  # 插件数据存储（类似 hass.data）
    
    # HA 风格的平台方法（由 PluginManager 注入）
    async_forward_entry_setup: Callable   # 转发平台设置
    async_unload_platforms: Callable      # 卸载平台
    register_service: Callable            # 注册服务
}
```

**关键方法**：
- `get_db_connection()`：获取新的数据库连接

**作用**：
- 为插件提供统一的资源访问通道
- 隔离插件与应用核心的直接耦合
- 支持插件间的数据共享（通过 `data` 字典）

---

### 3. `manager.py` - 核心插件管理器

**职责**：协调插件的发现、加载、设置、执行和卸载

#### PluginManager 核心方法

##### 发现阶段
```python
async_discover()
```
- 扫描 `plugins/` 目录下的所有目录
- 读取每个插件的 `manifest.json`
- 创建 `PluginRecord` 对象并存储
- 触发 `plugins_discovered` 事件

##### 设置阶段
```python
async_setup(domain: str) -> bool
```
执行流程：
1. 验证插件存在且状态正确
2. 调用 `_async_install_dependencies()`：安装插件依赖
3. 调用 `_async_load_module()`：导入插件模块
4. 调用插件模块的 `async_setup(context, config)` 函数
5. 更新状态为 `LOADED`

##### 配置条目设置
```python
async_setup_entry(entry: PluginEntryData) -> bool
```
执行流程：
1. 获取插件记录
2. 确保插件已加载（调用 async_setup 如果需要）
3. 调用插件模块的 `async_setup_entry(context, entry)` 函数
4. 转发平台设置（如 "parser" 平台）
5. 更新条目状态为 `ENABLED`

##### 平台转发
```python
async_forward_entry_setup(entry: PluginEntryData, platform: str) -> bool
```
- 加载平台模块（如 `parser.py`）
- 调用平台模块的 `async_setup_entry(context, entry, async_add_entities)`
- 注册返回的实体到平台注册表

##### 卸载阶段
```python
async_unload_entry(entry_id: str) -> bool
```
- 卸载平台（触发清理逻辑）
- 调用插件的 `async_unload_entry(context, entry)`
- 更新状态为 `DISABLED`

#### 其他关键组件

**PluginEntryData**：配置条目数据
```python
PluginEntryData {
    entry_id: str              # 条目唯一 ID
    domain: str                # 插件域（关联到某个插件）
    data: Dict[str, Any]       # 条目配置数据
    options: Dict              # 条目选项
    state: PluginState         # 条目状态
}
```

**EventBus**：事件总线
- 插件间通信的轻量级机制
- 支持事件监听和触发
- 主要事件：`plugins_discovered`、`plugin_discovered`、`plugin_setup`

**平台注册表** (`_platforms`)：
- 存储已加载的平台实体
- 结构：`{domain: {platform_name: [entities]}}`
- 用于查找特定平台的实体（如所有解析器）

---

### 4. `__init__.py` - 插件入口（fxtwitter 示例）

**职责**：定义插件的生命周期回调函数

#### 核心函数

##### `async_setup(context: PluginContext, config: dict) -> bool`
**何时调用**：插件首次加载时

作用：
- 执行插件基本初始化
- 安装依赖、加载配置等

fxtwitter 示例处理很简单：`只记录日志，返回 True`

##### `async_setup_entry(context: PluginContext, entry: PluginEntryData) -> bool`
**何时调用**：激活配置条目时

作用：
- 执行入口特定的初始化
- 加载该条目关联的平台

fxtwitter 实现：
```python
# 转发平台设置到 parser.py（加载 FXTwitterParser 类）
await context.async_forward_entry_setup(entry, "parser")
```

这行代码会：
1. 在 fxtwitter 包中查找 `parser.py`
2. 调用 `parser.py` 的 `async_setup_entry(context, entry, async_add_entities)`
3. 将返回的解析器实例注册到平台

##### `async_unload_entry(context: PluginContext, entry: PluginEntryData) -> bool`
**何时调用**：禁用或卸载条目时

作用：
- 清理资源
- 触发平台卸载逻辑

fxtwitter 实现：
```python
success = await context.async_unload_platforms(entry, ["parser"])
```

这行代码会：
1. 查找所有平台实体
2. 调用每个实体的 `async_will_remove()` 方法
3. 清理会话、关闭连接等

---

### 5. `parser.py` - 平台实现（fxtwitter 示例）

**职责**：实现具体的内容解析功能

#### FXTwitterParser 类

**初始化**：
```python
def __init__(self, context: PluginContext, entry: PluginEntryData):
    self.context = context      # 获取应用资源
    self.entry = entry          # 配置条目
    self._session = None        # HTTP 会话
```

**关键方法**：

##### `async_setup()`
- 创建 aiohttp 会话
- 记录初始化状态

##### `can_parse(url: str) -> bool`
- 使用正则表达式检查 URL 是否匹配
- 用于路由到正确的解析器

##### `async parse(url: str) -> ParserResult`
**主要解析流程**：
1. 将 Twitter/X URL 转换为 fxtwitter API URL
2. 调用 `_fetch_api_data()` 获取数据
3. 调用 `_validate_response()` 验证响应
4. 调用 `_build_result()` 构建结果对象

**数据提取方法**：
- `_parse_media()`：提取图片和视频
- `_parse_author()`：提取作者信息
- `_get_platform_info()`：获取平台元数据

##### `async_will_remove()`
- 清理 HTTP 会话
- 确保资源正确释放

---

## 插件执行流程详解

### 完整生命周期

```
1. 应用启动
   │
   ├── manager.async_discover()
   │   ├── 扫描 plugins/ 目录
   │   ├── 读取所有 manifest.json
   │   └── 创建 PluginRecord (state=INSTALLED)
   │
   ├── manager.async_setup(domain="fxtwitter")
   │   ├── 安装依赖
   │   ├── 导入模块
   │   ├── 调用 __init__.async_setup(context, config)
   │   └── state → LOADED
   │
   ├── 创建配置条目 entry.domain="fxtwitter"
   │
   └── manager.async_setup_entry(entry)
       ├── 调用 __init__.async_setup_entry(context, entry)
       │   │
       │   └── context.async_forward_entry_setup(entry, "parser")
       │       ├── 加载 parser.py 模块
       │       ├── 调用 parser.async_setup_entry(context, entry, async_add_entities)
       │       │   ├── 创建 FXTwitterParser 实例
       │       │   ├── 调用 parser.async_setup()
       │       │   └── 返回 parser 实例列表
       │       └── 注册到平台：_platforms["fxtwitter"]["parser"] = [parser_instance]
       │
       └── state → ENABLED

2. 插件运行
   │
   ├── 用户请求解析 URL
   ├── 系统调用 manager.async_find_parser_for_url(url)
   ├── 遍历所有解析器
   ├── 调用 parser.can_parse(url)
   └── 如果匹配，调用 parser.parse(url) → ParserResult

3. 应用关闭或卸载
   │
   └── manager.async_unload_entry(entry_id)
       ├── 调用 __init__.async_unload_entry(context, entry)
       │   └── context.async_unload_platforms(entry, ["parser"])
       │       ├── 找到所有 "parser" 平台实体
       │       └── 调用每个实例的 async_will_remove()
       │           └── FXTwitterParser 关闭 HTTP 会话
       │
       └── state → DISABLED
```

---

## 关键设计特点

### 1. **模块化架构**
- 插件作为模块加载，而非类
- 支持插件间的独立演化
- 易于版本管理和依赖控制

### 2. **状态机模型**
- 严格的状态转移规则
- 防止无效操作（如重复加载）
- 便于调试和故障诊断

### 3. **Home Assistant 风格**
- 借鉴成熟的 HA 架构
- `async_forward_entry_setup` 和 `async_unload_platforms` 模式
- 支持平台的灵活组织

### 4. **资源管理**
- 通过 `PluginContext` 集中管理资源
- 支持数据库连接池
- 日志统一收集

### 5. **事件驱动**
- `EventBus` 实现插件间通信
- 支持监听生命周期事件
- 便于实现响应式逻辑

---

## 扩展现有插件

要新增一个解析器插件，按照以下步骤：

### 1. 创建插件目录结构

```
plugins/
└── my_parser/
    ├── __init__.py          # 生命周期函数
    ├── parser.py            # 解析实现
    ├── const.py             # 常量定义
    └── manifest.json        # 元数据
```

### 2. 编写 manifest.json

```json
{
  "domain": "my_parser",
  "name": "My Parser",
  "version": "1.0.0",
  "requirements": ["requests"],
  "author": "Your Name"
}
```

### 3. 实现 __init__.py

```python
async def async_setup(context: PluginContext, config: dict) -> bool:
    context.logger.info("MyParser plugin setup")
    return True

async def async_setup_entry(context: PluginContext, entry):
    await context.async_forward_entry_setup(entry, "parser")
    return True

async def async_unload_entry(context: PluginContext, entry):
    return await context.async_unload_platforms(entry, ["parser"])
```

### 4. 实现 parser.py 中的解析器类

```python
class MyParser:
    def __init__(self, context: PluginContext, entry):
        self.context = context
        self.entry = entry
    
    async def async_setup(self):
        # 初始化逻辑
        pass
    
    def can_parse(self, url: str) -> bool:
        # 检查是否能解析此 URL
        return True
    
    async def parse(self, url: str) -> ParserResult:
        # 执行解析逻辑
        pass
    
    async def async_will_remove(self):
        # 清理逻辑
        pass
```

### 5. 系统将自动发现并加载你的插件！

---

## 调试技巧

1. **查看插件状态**：检查 `manager.plugins[domain].state`
2. **查看错误信息**：检查 `manager.plugins[domain].error`
3. **查看平台实体**：检查 `manager._platforms[domain]`
4. **查看事件**：监听 `manager.event_bus` 的事件
5. **查看日志**：通过 `context.logger` 输出调试信息

---

## 总结

这个插件系统通过 **生命周期管理** 和 **状态机** 实现了高度的模块化和可扩展性。插件从被发现到完全运行，再到卸载清理，每一步都有明确的职责划分和调用顺序。理解这个流程后，就可以轻松添加新的解析器或其他功能模块了。
