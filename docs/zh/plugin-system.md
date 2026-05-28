# 插件系统设计文档

本文档描述 Content Hive 插件系统的内部架构、生命周期机制和各模块的设计细节，面向维护者和贡献者。

如需开发插件，请参阅 [plugins.zh.md](plugins.zh.md)（中文开发者指南）或 [plugins.en.md](plugins.en.md)（English）。

---

## 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                    PluginManager                         │
│        （主管理器，协调所有插件的生命周期）               │
└──────────────┬──────────────────────────────────────────┘
               │
        ┌──────┴──────┬──────────────┬──────────────┐
        ▼             ▼              ▼              ▼
   PluginRecord  PluginContext   EventBus      Platform
   （插件记录）  （插件上下文）  （事件总线）    Registry
        ▲
        │ 使用
        │
   ┌────┴────────────────────────────┐
   │                                  │
   ▼                                  ▼
PluginState                manifest.json + Module Code
（状态管理）               （插件元数据 + 插件代码）

┌──────────────────────────────────────────────────────────┐
│                   PluginService                           │
│  （服务层：安装、更新、重载、配置、启用/禁用）            │
└───────────────────────┬──────────────────────────────────┘
                        │
              ┌─────────┴─────────┐
              ▼                   ▼
 GitHubPluginDownloader      config.py
 （从 GitHub 仓库下载并       （plugins.yaml 读写，
  安装插件）                   持久化插件配置）

┌──────────────────────────────────────────────────────────┐
│                   contracts.py                            │
│  （稳定接口：PluginConfigSchema、ParserResult 等）        │
└──────────────────────────────────────────────────────────┘
```

---

## 插件状态机

```
INSTALLED ──async_setup──> LOADED ──async_setup_entry──> ENABLED
    ▲                         ▲                               │
    │                         └──────── async_unload_entry ──┘
    │                                   （无其他活跃条目时）
    │
    ├── （plugins.yaml: disabled: true）
    │
DISABLED                                                  FAILED
    │                                              （设置或运行时错误）
    └── async_setup (enable API) ──> LOADED ──> ENABLED
```

| 状态 | 含义 | 模块是否加载 |
|------|------|-------------|
| `INSTALLED` | `manifest.json` 已加载，模块尚未导入 | 否 |
| `LOADED` | 模块已导入，依赖已安装，等待配置条目激活 | 是 |
| `ENABLED` | 配置条目已激活，插件正在运行 | 是 |
| `DISABLED` | `plugins.yaml` 标记 `disabled: true`，启动时跳过 | 否 |
| `FAILED` | 设置或运行时发生错误 | 可能 |

状态转移严格受 PluginManager 控制，外部只能通过 API 触发（enable / disable / reload / delete）。

---

## 各模块详细说明

### `registry.py` — 插件注册表和状态管理

定义 `PluginState` 枚举和 `PluginRecord` 类。

**`PluginRecord`** 存储单个插件的所有信息：

```python
PluginRecord {
    domain: str              # 插件唯一标识符
    manifest: dict           # 插件元数据
    instance: Any | None     # 加载的插件模块对象（module，非类实例）
    state: PluginState       # 当前状态
    error: str | None        # 错误信息（state 为 FAILED 时）

    # 计算属性（从 manifest / instance 派生）
    name: str
    version: str
    description: str | None
    author: list[str] | None
    config_schema: type[PluginConfigSchema] | None  # 读取模块的 CONFIG_SCHEMA
    is_loaded: bool
    is_enabled: bool
}
```

> `config_schema` 读取已加载模块上的 `CONFIG_SCHEMA` 属性。若模块未加载或插件未定义该属性，返回 `None`。

---

### `contracts.py` — 插件接口契约

定义 Content Hive 与插件之间的**稳定边界**。插件只应从 `contenthive.plugins.*` 导入，不得引用核心内部模块，以确保版本升级时的兼容性。

包含：`PluginConfigSchema`、`ParserResult`、`ParserMediaInfo`、`ParserAuthorInfo`、`ParserPlatformInfo`。

`PluginConfigSchema` 使用 `model_config = ConfigDict(extra="ignore")`，忽略配置文件中未声明的键（如框架内置的 `disabled` 字段），避免验证报错。

---

### `context.py` — 插件执行上下文

`PluginContext` 是插件与应用之间的接口层，在应用启动时由 PluginManager 创建并注入方法。

```python
PluginContext {
    logger: Logger
    data: dict[str, Any]                  # 插件数据存储

    # 由 PluginManager 在启动时注入
    async_forward_entry_setup: Callable
    async_unload_platforms: Callable
    register_service: Callable
    get_config: Callable                   # 读取 PluginConfigSchema 实例
    save_config: Callable                  # 持久化 PluginConfigSchema 实例
}
```

设计原则：`PluginContext` 不持有数据库连接或应用实例，插件通过 `settings` 或依赖注入自行获取所需资源。

---

### `manager.py` — 核心插件管理器

`PluginManager` 是插件系统的核心，协调发现、加载、激活、卸载、版本检查和热重载。

#### `PluginEntryData` — 配置条目

```python
PluginEntryData {
    entry_id: str        # 通常为 "{domain}_default"
    domain: str
    data: dict           # 条目配置数据
    options: dict
    state: PluginState
}
```

#### `EventBus` — 事件总线

轻量级插件间通信机制，支持同步与异步监听器。

| 事件名 | 触发时机 | 数据字段 |
|--------|----------|----------|
| `plugins_discovered` | 所有插件发现完成 | `count` |
| `plugin_discovered` | 单个插件被发现 | `domain`, `manifest` |
| `plugin_setup` | 插件 setup 完成 | `domain` |
| `plugin_enabled` | 插件 entry 激活 | `domain`, `entry_id` |
| `plugin_disabled` | 插件 entry 卸载 | `domain`, `entry_id` |

#### 核心方法

| 方法 | 说明 |
|------|------|
| `async_discover()` | 并发扫描 `plugins/` 目录，读取所有 `manifest.json`，创建 `PluginRecord`（state=INSTALLED）|
| `async_setup(domain)` | 安装依赖（线程池执行 `uv pip install`）→ 动态导入模块 → 调用 `async_setup(context)` → state=LOADED |
| `async_setup_entry(entry)` | 调用插件的 `async_setup_entry(context, entry)` → 存储条目 → state=ENABLED |
| `async_forward_entry_setup(entry, platform)` | 加载平台子模块（如 `parser.py`），以 `contenthive_plugin_{domain}.{platform}` 注入 `sys.modules`，调用平台的 `async_setup_entry` |
| `async_unload_entry(entry_id)` | 调用插件的 `async_unload_entry` → 删除条目 → 若无其他活跃条目则 state=LOADED |
| `async_delete(domain)` | 卸载所有条目 → 从注册表移除 → 删除磁盘目录 |
| `async_reload(domain)` | 卸载 → 清除 `sys.modules` 缓存 → 重置为 INSTALLED → 重新 setup + setup_entry |
| `async_activate(domain)` | 首次激活新安装插件：discover → setup → setup_entry |
| `async_check_updates(repo_url, ref)` | 仅拉取远端 `plugins-manifest.json`，进行语义版本比较，缓存结果 |
| `register_service(domain, service, callback)` | 注册命名服务 |
| `call_service(domain, service, data)` | 调用已注册的服务 |

**热重载实现细节**（`async_reload`）：

```
1. async_unload_entry（卸载所有活跃 entry）
2. 清除 sys.modules 中的 plugin_{domain} 和 contenthive_plugin_{domain}.* 缓存
3. 将 record 重置为 INSTALLED
4. async_setup(config) + async_setup_entry
```

---

### `downloader.py` — GitHub 插件下载器

`GitHubPluginDownloader` 从 GitHub 仓库安全地下载、解压并安装插件。

**远端仓库格式**：仓库根目录需包含 `plugins-manifest.json`，描述所有可用插件及其路径。

**主要方法**：

```python
async download_plugins(
    repo_url: str,
    ref: str = "main",
    ref_type: str = "branch",        # "branch" | "tag" | "commit"
    selected_plugins: list[str] | None = None,
    force_reinstall: bool = False
) -> dict[str, bool]
```

```python
async fetch_remote_manifest(repo_url: str, ref: str = "main") -> dict | None
# 仅拉取 plugins-manifest.json，不下载完整包
```

**支持的 URL 格式**：裸域名、HTTPS、`.git` 后缀均可。

**安全机制**：

| 机制 | 说明 |
|------|------|
| Domain 验证 | 仅允许 `[a-z0-9_-]`，防止路径穿越 |
| Ref 验证 | 仅允许 `[a-zA-Z0-9._/\-]`，防止注入 |
| Zip Slip 防护 | 解压时逐条验证路径不逃出目标目录 |
| 路径安全检查 | `_validate_path_safety()` 确保目标在 `plugins_dir` 内 |

---

### `config.py` — 插件配置文件工具

读写 `PLUGINS_DIR/plugins.yaml`，持久化每个插件的配置（含启用/禁用状态）。

```yaml
fxtwitter:
  disabled: true

youtube_parser:
  disabled: false
  api_key: "xxx"
  quality: "high"
```

- `disabled` 是框架保留字段（`_FRAMEWORK_KEYS`），其余字段为插件专属配置
- **原子写入**：`tempfile.mkstemp` + `Path.replace`，在 `_config_lock` 线程锁内执行，保证并发安全

| 函数 | 说明 |
|------|------|
| `load_plugins_config()` | 加载完整配置；文件不存在或解析失败时返回 `{}` |
| `save_plugins_config(config)` | 原子写回 `plugins.yaml` |
| `get_plugin_config(domain)` | 获取单个插件配置块 |
| `set_plugin_field(domain, key, value)` | 加锁设置单个字段并持久化 |
| `remove_plugin_config(domain)` | 删除插件整个配置块（插件删除时调用）|
| `strip_framework_keys(cfg)` | 过滤掉框架内置键 |
| `plugin_get_config(domain, schema_cls)` | 获取配置并反序列化为 `PluginConfigSchema` 子类实例 |
| `plugin_save_config(domain, config)` | 序列化 `PluginConfigSchema` 实例并原子写入 |

---

### `startup.py` — 启动与关闭

#### `load_plugins_on_startup()`

```
1. 创建 PluginContext 和 PluginManager，注入 HA 风格方法
2. async_discover()        并发扫描本地 plugins/ 目录
3. async_check_updates()   轻量检查远端版本，日志记录可用更新和新插件（不自动安装）
4. 读取 plugins.yaml
5. for each plugin:
   ├── [disabled: true] → state = DISABLED，跳过
   └── async_setup(config) + async_setup_entry
6. 汇总日志：X/Y enabled
```

#### `shutdown_plugins()`

遍历所有活跃 entry，调用 `async_unload_entry` 完成资源清理。

---

### `services/plugin.py` — 插件管理服务层

封装插件管理操作，供 HTTP 路由层调用。

| 方法 | 说明 |
|------|------|
| `list_plugins()` | 返回所有已发现插件的状态、版本、错误信息及更新可用性 |
| `list_available()` | 拉取远端 manifest，合并本地安装状态，返回所有可用插件 |
| `check_updates()` | 查询远端版本，返回各插件当前版本与最新版本 |
| `update_plugins(domains)` | 下载并安装/更新插件；已有插件热重载，新插件直接激活 |
| `enable(domain)` | 清除禁用标记，动态加载并激活插件 |
| `disable(domain)` | 卸载插件并在 `plugins.yaml` 中写入 `disabled: true` |
| `delete(domain)` | 卸载 + 从注册表移除 + 删除磁盘目录 + 清理 `plugins.yaml` |
| `reload_all()` | 热重载所有插件 |
| `get_plugin_settings(domain)` | 读取 `CONFIG_SCHEMA`，返回字段列表及当前配置值 |
| `update_plugin_settings(domain, body)` | 校验并持久化插件配置（支持部分更新，严格类型检查）|

**`update_plugin_settings` 校验规则**：
- 框架保留键（`disabled`）被拒绝，返回 400
- 未声明的键静默忽略
- 声明的键以 `strict=True` 模式做类型检查
- 支持真正的部分更新

---

## HTTP 管理 API

所有端点需要管理员权限（Bearer Token），路由前缀 `/v1/plugins`。

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/v1/plugins/` | 列出所有本地已发现的插件及其状态 |
| `GET` | `/v1/plugins/available` | 列出远端仓库中所有可用插件（含未安装的）|
| `POST` | `/v1/plugins/reload` | 热重载所有插件 |
| `POST` | `/v1/plugins/check-config` | 校验所有插件 manifest 的必填字段 |
| `GET` | `/v1/plugins/check-updates` | 检查各插件是否有新版本 |
| `POST` | `/v1/plugins/update` | 从远端仓库下载并安装/更新插件 |
| `POST` | `/v1/plugins/{domain}/enable` | 启用指定插件 |
| `POST` | `/v1/plugins/{domain}/disable` | 禁用指定插件 |
| `DELETE` | `/v1/plugins/{domain}` | 删除插件（卸载 + 删除文件）|
| `GET` | `/v1/plugins/{domain}/config` | 获取插件配置 Schema 及当前值 |
| `PUT` | `/v1/plugins/{domain}/config` | 更新插件配置字段 |

---

## 完整执行流程

### URL 解析流程

```
POST /v1/task/parser { "url": "..." }
  │
  └── task_service.create_parser_task()
      ├── 查找运行中的 PRIMARY 任务
      │   ├── 无 → 创建 PRIMARY，入队执行
      │   ├── 有 + 同用户 → 返回现有任务
      │   └── 有 + 不同用户 → 创建 LINKED（等待 PRIMARY 完成）
      │
      └── task_queue.enqueue(task.id)  [异步执行]
          │
          └── content_service.parser_content(url)
              ├── manager.call_service(domain, "can_parse", {"url": url})
              └── manager.call_service(domain, "parse", {"url": url}) → ParserResult
```

### 在线更新流程

```
POST /v1/plugins/update
  │
  └── PluginService.update_plugins(domains)
      ├── GitHubPluginDownloader.download_plugins()
      │   ├── 下载 GitHub zip 包
      │   ├── 安全解压（Zip Slip 防护）
      │   └── 按 plugins-manifest.json 覆盖安装
      │
      ├── 已有插件 → manager.async_reload(domain)
      │   ├── async_unload_entry
      │   ├── 清除 sys.modules 缓存
      │   └── 重新 async_setup + async_setup_entry
      │
      └── 新插件 → manager.async_activate(domain)
          └── discover → setup → setup_entry
```

---

## 关键设计特点

1. **模块级加载** — 插件作为整个 Python 模块动态导入（`importlib`），而非实例化类，支持平台作为子模块独立注册
2. **严格状态机** — 状态转移受 PluginManager 控制，防止无效操作，错误状态可被恢复
3. **Home Assistant 风格** — `async_forward_entry_setup` / `async_unload_platforms` 模式让插件与平台高度解耦，易于横向扩展
4. **安全的远程分发** — Domain 校验、Ref 验证、Zip Slip 防护多层保障
5. **无停机热更新** — 完整清除模块缓存（包括 `sys.modules` 中的所有子模块）后重新加载
6. **轻量版本检查** — 启动时仅拉取远端 `plugins-manifest.json`（几 KB），对启动时间影响极小
7. **原子配置写入** — 临时文件 + rename + 线程锁，防止写入中断导致配置损坏
8. **类型化配置 Schema** — `CONFIG_SCHEMA` 驱动配置读取、写入、类型校验和 API 暴露，插件无需额外代码
9. **稳定接口契约** — 插件只依赖 `contenthive.plugins.*`，核心内部重构不影响已有插件
