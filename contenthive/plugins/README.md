# ContentHive 插件系统

## 系统概述

ContentHive 的插件系统采用了 **Home Assistant 风格的架构**，设计目标是实现一个灵活、模块化、易于扩展的插件管理框架。系统通过插件发现、加载、配置、执行和卸载的完整生命周期来管理各种内容解析器和扩展功能。插件通过 GitHub 仓库统一分发，支持版本检查、在线更新和热重载。

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

┌──────────────────────────────────────────────────────────┐
│                   PluginService                           │
│   (服务层：更新、重载、健康检查、配置校验、启用/禁用)    │
└───────────────────────┬──────────────────────────────────┘
                        │
              ┌─────────┴─────────┐
              ▼                   ▼
 GitHubPluginDownloader      config.py
 (从 GitHub 仓库下载并      (plugins.yaml 读写，
  安装插件)                  持久化插件配置)

┌──────────────────────────────────────────────────────────┐
│                   contracts.py                            │
│   (稳定插件接口：PluginConfigSchema、ParserResult 等)    │
└──────────────────────────────────────────────────────────┘
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
    ▲                          ▲                              │
    │                          │                              │
    │                          └────── async_unload_entry ───┘
    │                                  (无其他活跃条目时)
    │
    ├── (plugins.yaml: disabled: true)
    │
DISABLED                                               FAILED
    │                                            (设置或运行时错误)
    └── async_setup (enable API) ──> LOADED ──> ENABLED
```

**每个状态的含义**：
- **INSTALLED**：插件已被发现，`manifest.json` 已加载，但还未执行 `async_setup`
- **LOADED**：模块已加载，依赖已安装，等待配置条目的激活；插件卸载后若无报错也回到此状态
- **ENABLED**：配置条目已激活，插件正在运行
- **DISABLED**：在 `plugins.yaml` 中被标记为 `disabled: true`，启动时跳过，模块未加载
- **FAILED**：设置或运行时发生错误

#### PluginRecord 类
存储单个插件的所有信息：

```python
PluginRecord {
    domain: str              # 插件唯一标识符（来自 manifest.json）
    manifest: Dict           # 插件元数据（名称、版本、依赖等）
    instance: Optional       # 加载的插件模块对象（module，非类实例）
    state: PluginState       # 当前状态
    error: Optional[str]     # 错误信息（如果状态为 FAILED）

    # 属性
    name: str                # 来自 manifest 的显示名称
    version: str             # 来自 manifest 的版本号
    description: Optional[str]   # 来自 manifest 的描述
    author: Optional[list[str]]  # 来自 manifest 的作者列表
    config_schema: Optional[type[PluginConfigSchema]]
                             # 从已加载模块读取 CONFIG_SCHEMA，无则返回 None
    is_loaded: bool          # instance 是否非空
    is_enabled: bool         # state == ENABLED
}
```

> **`config_schema` 属性**：读取插件模块上的 `CONFIG_SCHEMA` 属性（须为 `PluginConfigSchema` 的子类），用于驱动配置管理 API。若插件未定义该属性或模块尚未加载，返回 `None`。

---

### 2. `contracts.py` - 插件契约类型

**职责**：定义 ContentHive 与插件之间的**稳定接口**。插件只应从 `contenthive.plugins.*` 导入，不得依赖核心内部模块。

#### PluginConfigSchema
插件配置 Schema 的基类，基于 Pydantic `BaseModel`。插件需在 `__init__.py` 中定义子类并赋值给 `CONFIG_SCHEMA`：

```python
from enum import Enum
from pydantic import Field
from contenthive.plugins.contracts import PluginConfigSchema

class Quality(str, Enum):
    LOW = "low"
    HIGH = "high"

class ConfigSchema(PluginConfigSchema):
    api_key: str = Field(title="API Key", json_schema_extra={"secret": True})
    quality: Quality = Field(default=Quality.HIGH, title="Video Quality")

CONFIG_SCHEMA = ConfigSchema
```

字段声明约定：

| 特性 | 写法 |
|------|------|
| 敏感字段（密码/Token）| `Field(json_schema_extra={"secret": True})` |
| 显示标签 | `Field(title="My Label")` |
| 必填字段 | 无 `default` 参数 |
| 可选字段 | 提供 `default` 参数 |
| 支持的类型 | `str`, `int`, `float`, `bool`, `str` Enum 子类 |

> `model_config = ConfigDict(extra="ignore")`：schema 会忽略配置文件中未声明的键，避免因框架内部字段（如 `disabled`）导致验证报错。

#### 数据契约类型

| 类 | 说明 |
|---|---|
| `ParserResult` | 插件 `parse()` 方法的完整返回值 |
| `ParserMediaInfo` | 单条媒体信息（URL、类型、标题、封面、时长、分辨率等） |
| `ParserPlatformInfo` | 平台信息（code、name、url、icon_url） |
| `ParserAuthorInfo` | 作者信息（uid、name、username、avatar、url 等） |

```python
class ParserResult(BaseModel):
    pid: str                        # 内容唯一 ID
    url: str                        # 原始 URL
    title: Optional[str]
    content: Optional[str]
    media: list[ParserMediaInfo]
    author: ParserAuthorInfo
    platform: ParserPlatformInfo
    post_time: Optional[int]        # Unix 时间戳
    parser: str                     # 解析器标识
    state: ParserResultStatus
```

---

### 3. `context.py` - 插件执行上下文

**职责**：为插件提供访问应用资源的接口

#### PluginContext 类
插件通过此对象与主应用交互：

```python
PluginContext {
    logger: Logger                        # 日志记录器
    data: Dict[str, Any]                  # 插件数据存储（类似 hass.data）
    
    # HA 风格的平台方法（由 PluginManager 在启动时注入）
    async_forward_entry_setup: Callable   # 转发平台设置
    async_unload_platforms: Callable      # 卸载平台
    register_service: Callable            # 注册服务
}
```

> **注意**：`PluginContext` 不再持有 `app`、`data_dir` 或数据库连接工厂。这些资源由插件自行通过 `settings` 或依赖注入获取。

---

### 4. `manager.py` - 核心插件管理器

**职责**：协调插件的发现、加载、设置、执行、卸载、更新检查和热重载

#### PluginEntryData
配置条目数据，代表一个已激活的插件实例：

```python
PluginEntryData {
    entry_id: str              # 条目唯一 ID（通常为 "{domain}_default"）
    domain: str                # 插件域（关联到某个插件）
    data: Dict[str, Any]       # 条目配置数据
    options: Dict              # 条目选项
    state: PluginState         # 条目状态
}
```

#### EventBus - 事件总线
插件间通信的轻量级机制，支持同步与异步监听器。

主要事件：

| 事件名             | 触发时机                     | 数据字段                        |
|--------------------|------------------------------|---------------------------------|
| `plugins_discovered` | 所有插件发现完成             | `count`                         |
| `plugin_discovered`  | 单个插件被发现               | `domain`, `manifest`            |
| `plugin_setup`       | 插件 setup 完成              | `domain`                        |
| `plugin_enabled`     | 插件 entry 激活              | `domain`, `entry_id`            |
| `plugin_disabled`    | 插件 entry 卸载              | `domain`, `entry_id`            |

#### PluginManager 核心方法

##### 发现阶段
```python
async async_discover()
```
- 并发扫描 `plugins/` 目录下的所有子目录
- 读取每个插件的 `manifest.json`
- 创建 `PluginRecord` 对象（state=INSTALLED）并存储
- 触发 `plugins_discovered` 事件

##### 设置阶段
```python
async async_setup(domain: str, config: dict | None = None) -> bool
```
执行流程：
1. 验证插件存在且状态为 `INSTALLED` 或 `DISABLED`
2. 调用 `_async_install_dependencies()`：在线程池中安装 pip 依赖
3. 调用 `_async_load_module()`：动态导入插件的 `__init__.py` 模块
4. 调用插件模块的 `async_setup(context, config)` 函数（若存在）
5. 状态更新为 `LOADED`

##### 配置条目设置
```python
async async_setup_entry(entry: PluginEntryData) -> bool
```
执行流程：
1. 若插件仍为 `INSTALLED` 状态则先调用 `async_setup`
2. 调用插件模块的 `async_setup_entry(context, entry)` 函数
3. 存储条目，状态更新为 `ENABLED`

##### 平台转发
```python
async async_forward_entry_setup(entry: PluginEntryData, platform: str) -> bool
```
- 加载平台模块（如 `parser.py`），并以插件包的子模块方式注入 `sys.modules`
- 调用平台模块的 `async_setup_entry(context, entry, async_add_entities)`
- 通过 `async_add_entities` 回调将实体注册到平台注册表 `_platforms`

##### 卸载阶段
```python
async async_unload_entry(entry_id: str) -> bool
```
- 调用插件的 `async_unload_entry(context, entry)`
- 删除条目记录
- 若该插件无其他活跃条目，状态回退为 `LOADED`

##### 删除插件
```python
async async_delete(domain: str) -> bool
```
- 卸载所有活跃 entry
- 从 `plugin_manager.plugins` 注册表中移除记录
- 从磁盘上删除插件目录及其所有文件

##### 版本检查
```python
async async_check_updates(repo_url: str, ref: str = "main") -> dict[str, str | None]
```
- 轻量操作：仅从远程仓库获取 `plugins-manifest.json`，不下载完整包
- 使用 `packaging.version` 进行语义版本比较
- 返回值：`{domain: latest_version}` — `None` 表示已是最新
- 结果缓存在 `_available_updates` 和 `_last_update_check`

##### 激活新插件
```python
async async_activate(domain: str) -> bool
```
用于安装后首次激活从未被发现的插件，相当于：`discover → setup → setup_entry`

##### 热重载
```python
async async_reload(domain: str) -> bool
```
执行流程：
1. 卸载所有该插件的活跃 entry
2. 从 `sys.modules` 中清除 `plugin_{domain}` 和 `contenthive_plugin_{domain}.*` 等模块缓存
3. 将 record 重置为 `INSTALLED`
4. 重新 `async_setup` + `async_setup_entry`

##### 其他方法

| 方法 | 说明 |
|------|------|
| `register_service(domain, service, callback)` | 注册插件服务 |
| `call_service(domain, service, data)` | 调用已注册的服务 |
| `get_parser_entities()` | 获取所有已注册的解析器实体列表 |

#### 全局单例

```python
set_plugin_manager(manager)   # 设置全局实例
get_plugin_manager()          # 获取全局实例（可能为 None）
```

---

### 5. `downloader.py` - GitHub 插件下载器

**职责**：从 GitHub 仓库安全地下载、解压并安装插件

#### GitHubPluginDownloader 类

##### 远程仓库格式
下载器要求远程仓库根目录存在 `plugins-manifest.json`：

```json
{
  "plugins": [
    {
      "domain": "my_parser",
      "name": "My Parser",
      "version": "1.2.0",
      "path": "plugins/my_parser",
      "enabled": true,
      "requirements": ["aiohttp"]
    }
  ]
}
```

- `path`：插件目录相对于仓库根目录的路径
- `enabled`：为 `false` 时不会被自动安装（除非显式指定）
- 安装后此条目内容会被写入插件目录的 `manifest.json`

##### 主要方法

```python
async download_plugins(
    repo_url: str,
    ref: str = "main",
    ref_type: str = "branch",       # "branch" | "tag" | "commit"
    selected_plugins: list[str] | None = None,
    force_reinstall: bool = False
) -> dict[str, bool]
```
- 下载仓库 zip 包，解压后按 `plugins-manifest.json` 安装选定插件
- 安装完毕后自动清理临时文件

```python
async fetch_remote_manifest(repo_url: str, ref: str = "main") -> dict | None
```
- 仅抓取 `raw.githubusercontent.com` 上的 `plugins-manifest.json`
- 不下载完整包，用于轻量级版本检查及列出可用插件

##### URL 格式支持

| 格式 | 示例 |
|------|------|
| 裸域名 | `github.com/owner/repo` |
| HTTPS | `https://github.com/owner/repo` |
| .git 后缀 | `https://github.com/owner/repo.git` |

##### 安全机制

| 机制 | 说明 |
|------|------|
| Domain 验证 | 仅允许 `[a-z0-9_-]`，防止路径穿越 |
| Ref 验证 | 仅允许 `[a-zA-Z0-9._/\-]`，防止注入 |
| Zip Slip 防护 | 解压时逐条验证路径不逃出目标目录 |
| 路径安全检查 | `_validate_path_safety()` 确保目标在 `plugins_dir` 内 |

---

### 6. `config.py` - 插件配置文件工具

**职责**：读写 `plugins_dir/plugins.yaml`，持久化每个插件的配置（包括启用/禁用状态）

#### `plugins.yaml` 格式

```yaml
fxtwitter:
  disabled: true

youtube_parser:
  disabled: false
  api_key: "xxx"
```

每个插件占一个独立配置块，`disabled` 是框架内置字段（`_FRAMEWORK_KEYS`），其余字段作为插件专属配置传入 `async_setup`。

#### 主要函数

| 函数 | 说明 |
|------|------|
| `load_plugins_config()` | 加载完整配置，返回 `dict[domain, config]`；文件不存在或解析失败时返回 `{}` |
| `save_plugins_config(config)` | 将完整配置原子写回 `plugins.yaml`（使用临时文件 + rename，线程安全） |
| `get_plugin_config(domain)` | 获取单个插件的配置块，不存在时返回 `{}` |
| `set_plugin_field(domain, key, value)` | 在线程锁下设置单个插件的某个配置字段并持久化 |
| `remove_plugin_config(domain)` | 删除某个插件的整个配置块并持久化（插件删除时调用） |
| `strip_framework_keys(cfg)` | 从配置 dict 中过滤掉框架内置键（如 `disabled`） |
| `plugin_get_config(domain, schema_cls)` | 获取插件配置并反序列化为 `PluginConfigSchema` 子类实例 |
| `plugin_save_config(domain, config)` | 将 `PluginConfigSchema` 实例序列化后原子写入 `plugins.yaml` |

> **原子写入**：`save_plugins_config` 通过 `tempfile.mkstemp` + `Path.replace` 保证写入的原子性，避免进程崩溃时产生损坏的配置文件。所有修改操作均在 `_config_lock` 线程锁内执行。

---

### 7. `startup.py` - 启动与关闭

**职责**：应用启动时初始化插件系统，关闭时优雅卸载

#### `load_plugins_on_startup()`

启动流程：
1. 创建 `PluginContext` 和 `PluginManager`，注入 HA 风格方法
2. `async_discover()` 并发扫描本地插件目录
3. `async_check_updates()` 轻量检查远程版本，日志记录可用更新和新插件（不自动安装）
4. 读取 `plugins.yaml`，逐个处理已发现的插件：
   - 若 `disabled: true`：状态设为 `DISABLED`，跳过加载
   - 否则：`async_setup(config)` + `async_setup_entry`，插件专属配置（除 `disabled` 外的字段）传入 `async_setup`
5. 汇总日志：`X/Y enabled`

#### `shutdown_plugins()`

遍历所有活跃 entry，逐一调用 `async_unload_entry` 完成资源清理。

---

### 8. `services/plugin.py` - 插件管理服务层

**职责**：封装插件管理操作，供 HTTP 路由层调用

#### ConfigValidationError

自定义异常类，当插件配置未通过 Schema 校验时抛出，携带结构化的错误列表。路由层将其映射为 HTTP 400。

#### PluginService 方法

| 方法 | 说明 |
|------|------|
| `reload_all()` | 热重载所有插件，返回每个 domain 的结果 |
| `check_config()` | 校验所有插件 manifest 的必填字段（domain/name/version） |
| `check_updates()` | 查询远端版本，返回各插件的当前版本与最新版本及检查时间戳 |
| `update_plugins(domains)` | 下载并安装指定插件（或全部），已有插件热重载，新插件直接激活 |
| `list_available()` | 拉取远端 `plugins-manifest.json`，合并本地安装状态，返回所有可用插件信息 |
| `list_plugins()` | 返回所有已发现插件的状态、版本、错误信息及更新可用性 |
| `disable(domain)` | 卸载插件并在 `plugins.yaml` 中写入 `disabled: true` |
| `enable(domain)` | 清除禁用标记，动态加载并激活插件 |
| `delete(domain)` | 卸载插件、从注册表移除、删除磁盘目录，并清理 `plugins.yaml` 中的配置块 |
| `get_plugin_settings(domain)` | 读取插件的 `CONFIG_SCHEMA`，返回 schema 字段列表及当前配置值 |
| `update_plugin_settings(domain, body)` | 校验并持久化插件配置字段（支持部分更新） |

#### 配置校验规则（`update_plugin_settings`）

- 框架保留键（`disabled`）被拒绝，返回 400
- 未在 `CONFIG_SCHEMA` 中声明的键被静默忽略
- 声明的键以 `strict=True` 模式做类型检查
- 必填字段须在请求体或已持久化配置中满足（支持真正的部分更新）

---

## HTTP API 端点

所有端点需要管理员权限（Bearer Token），路由前缀为 `/v1/plugins`。

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/v1/plugins/` | 列出所有本地已发现的插件及其状态 |
| `GET` | `/v1/plugins/available` | 列出远端仓库中所有可用插件（含未安装的） |
| `POST` | `/v1/plugins/reload` | 热重载所有插件 |
| `POST` | `/v1/plugins/check-config` | 校验所有插件 manifest 的必填字段 |
| `GET` | `/v1/plugins/check-updates` | 检查各插件是否有新版本 |
| `POST` | `/v1/plugins/update` | 从远端仓库下载并安装/更新插件 |
| `POST` | `/v1/plugins/{domain}/enable` | 启用指定插件 |
| `POST` | `/v1/plugins/{domain}/disable` | 禁用指定插件 |
| `DELETE` | `/v1/plugins/{domain}` | 删除插件（卸载 + 删除文件） |
| `GET` | `/v1/plugins/{domain}/config` | 获取插件配置 Schema 及当前值 |
| `PUT` | `/v1/plugins/{domain}/config` | 更新插件配置字段 |

---

## 插件执行流程详解

### 完整生命周期

```
1. 应用启动
   │
   ├── PluginContext + PluginManager 初始化
   │
   ├── manager.async_discover()  [并发]
   │   ├── 扫描 plugins/ 目录
   │   ├── 读取所有 manifest.json
   │   └── 创建 PluginRecord (state=INSTALLED)
   │
   ├── manager.async_check_updates()  [仅拉取 plugins-manifest.json]
   │   └── 日志记录新插件 / 可用更新，不自动安装
   │
   ├── 读取 plugins.yaml
   │
   └── for domain in plugins:
       ├── [disabled: true] → state → DISABLED，跳过
       │
       ├── manager.async_setup(domain, config)  [config 来自 plugins.yaml]
       │   ├── pip install requirements  [线程池]
       │   ├── importlib 加载 __init__.py
       │   ├── 调用 async_setup(context, config)
       │   └── state → LOADED
       │
       └── manager.async_setup_entry(entry)
           ├── 调用 async_setup_entry(context, entry)
           │   └── context.async_forward_entry_setup(entry, "parser")
           │       ├── 加载 parser.py 作为子模块
           │       ├── 调用 parser.async_setup_entry(context, entry, async_add_entities)
           │       └── 注册到 _platforms[domain]["parser"]
           └── state → ENABLED

2. 运行时 - 解析 URL
   │
   ├── manager.get_parser_entities()  → 获取所有解析器实例
   ├── 调用 parser.can_parse(url)
   └── 匹配成功 → parser.parse(url) → ParserResult

3. 在线更新
   │
   ├── PluginService.update_plugins(domains)
   │   ├── GitHubPluginDownloader.download_plugins()
   │   │   ├── 下载 GitHub zip 包（branch / tag / commit）
   │   │   ├── 安全解压（Zip Slip 防护）
   │   │   └── 按 plugins-manifest.json 覆盖安装插件目录
   │   │
   │   ├── 已有插件 → manager.async_reload(domain)
   │   │   ├── async_unload_entry（卸载所有 entry）
   │   │   ├── 清除 sys.modules 缓存
   │   │   └── 重新 async_setup + async_setup_entry
   │   │
   │   └── 新插件 → manager.async_activate(domain)
   │       └── discover → setup → setup_entry

4. 插件删除
   │
   ├── PluginService.delete(domain)
   │   ├── manager.async_delete(domain)
   │   │   ├── async_unload_entry（卸载所有 entry）
   │   │   ├── 从 plugins 注册表移除
   │   │   └── 删除磁盘上的插件目录
   │   └── remove_plugin_config(domain)
   │       └── 从 plugins.yaml 中删除配置块

5. 应用关闭
   │
   └── shutdown_plugins()
       └── for entry in config_entries:
           └── manager.async_unload_entry(entry_id)
               ├── async_unload_entry(context, entry)
               │   └── context.async_unload_platforms(entry, ["parser"])
               │       └── parser.async_will_remove()  [关闭 HTTP 会话等]
               └── state → LOADED（若无其他活跃 entry）
```

---

## 开发新插件

### 插件目录结构

```
plugins/
└── my_parser/
    ├── __init__.py          # 生命周期函数 + CONFIG_SCHEMA（可选）
    ├── parser.py            # 解析实现（可选，按平台划分）
    ├── const.py             # 常量定义（可选）
    └── manifest.json        # 元数据（本地开发用；线上由 plugins-manifest.json 生成）
```

### manifest.json 格式

```json
{
  "domain": "my_parser",
  "name": "My Parser",
  "version": "1.0.0",
  "requirements": ["aiohttp"],
  "author": ["Your Name"]
}
```

### `__init__.py` 实现

```python
from enum import Enum
from pydantic import Field
from contenthive.plugins.context import PluginContext
from contenthive.plugins.contracts import PluginConfigSchema
from contenthive.plugins.manager import PluginEntryData


# 可选：定义配置 Schema，驱动配置管理 API
class Quality(str, Enum):
    LOW = "low"
    HIGH = "high"

class ConfigSchema(PluginConfigSchema):
    api_key: str = Field(title="API Key", json_schema_extra={"secret": True})
    quality: Quality = Field(default=Quality.HIGH, title="Video Quality")

CONFIG_SCHEMA = ConfigSchema


async def async_setup(context: PluginContext, config: dict) -> bool:
    context.logger.info("MyParser plugin setup")
    return True

async def async_setup_entry(context: PluginContext, entry: PluginEntryData) -> bool:
    await context.async_forward_entry_setup(entry, "parser")
    return True

async def async_unload_entry(context: PluginContext, entry: PluginEntryData) -> bool:
    return await context.async_unload_platforms(entry, ["parser"])
```

### `parser.py` 平台实现

```python
from contenthive.plugins.context import PluginContext
from contenthive.plugins.contracts import ParserResult, ParserAuthorInfo, ParserPlatformInfo
from contenthive.plugins.manager import PluginEntryData

class MyParser:
    def __init__(self, context: PluginContext, entry: PluginEntryData):
        self.context = context
        self.entry = entry

    async def async_setup(self):
        # 初始化（如创建 HTTP session）
        pass

    def can_parse(self, url: str) -> bool:
        return "example.com" in url

    async def parse(self, url: str) -> ParserResult:
        # 执行解析，返回 ParserResult
        ...

    async def async_will_remove(self):
        # 清理资源（如关闭 HTTP session）
        pass


async def async_setup_entry(context, entry, async_add_entities):
    parser = MyParser(context, entry)
    await parser.async_setup()
    await async_add_entities([parser])
```

---

## 调试技巧

| 目标 | 方法 |
|------|------|
| 查看插件状态 | `manager.plugins[domain].state` |
| 查看错误信息 | `manager.plugins[domain].error` |
| 查看配置 Schema | `manager.plugins[domain].config_schema` |
| 查看平台实体 | `manager._platforms[domain]` |
| 查看可用更新缓存 | `manager._available_updates` |
| 查看上次更新检查时间 | `manager._last_update_check` |
| 触发热重载 | `await manager.async_reload(domain)` |
| 监听事件 | `manager.event_bus.listen("plugin_enabled", callback)` |

---

## 关键设计特点

### 1. 模块化架构
插件以模块（而非类）方式加载，支持平台（如 `parser.py`）作为子模块独立注册，便于版本管理和依赖控制。

### 2. 状态机模型
严格的状态转移：`INSTALLED → LOADED → ENABLED`，卸载后回退至 `LOADED`，错误则进入 `FAILED`，手动禁用则进入 `DISABLED`，防止无效操作。

### 3. Home Assistant 风格
借鉴成熟的 HA 架构，`async_forward_entry_setup` / `async_unload_platforms` 模式让插件与平台高度解耦。

### 4. 安全的远程分发
通过 `GitHubPluginDownloader` 支持 branch / tag / commit 三种 ref 类型，并内置 Domain 校验、Zip Slip 防护、路径安全检查，防止恶意插件包攻击。

### 5. 热更新
`async_reload` 完整清除模块缓存并重新加载，无需重启应用即可应用插件更新。

### 6. 轻量版本检查
`async_check_updates` 仅拉取远程 `plugins-manifest.json`（几 KB），不下载完整包，启动时开销极小。

### 7. 持久化插件配置
通过 `plugins.yaml` 集中管理每个插件的配置，包括启用/禁用状态和插件专属配置项（如 API Key）。写入使用临时文件 + rename 原子操作，并加线程锁，保证并发安全。

### 8. 类型化配置 Schema
插件可通过 `CONFIG_SCHEMA = MyConfigSchema` 声明配置 schema，框架自动支持配置的读取、写入、类型校验和 API 暴露，无需额外代码。敏感字段（如 Token）标记 `secret=True` 后可在 API 响应中被脱敏处理。

### 9. 稳定的插件接口契约
`contracts.py` 定义了插件与核心之间的稳定边界。插件只依赖 `contenthive.plugins.*`，与核心内部实现解耦，保证插件在版本升级时的兼容性。
