# 插件系统设计文档

本文档描述 Content Hive 插件系统的内部架构、生命周期机制和各模块的设计细节，面向维护者和贡献者。

如需开发插件，请参阅[插件开发者指南](/zh/plugins)。

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
 catalog.py +                config.py
 GitHubPluginDownloader      （plugins.yaml 读写，
 （读取插件目录，             持久化插件配置）
  安装 GitHub Release）

┌──────────────────────────────────────────────────────────┐
│                   contracts.py                            │
│  （稳定接口：PluginConfigSchema、ParserResult 等）        │
└──────────────────────────────────────────────────────────┘
```

---

## 插件状态机

```
INSTALLED ──async_setup──> LOADED ──async_setup_entry──> ENABLED
                              │            ▲                  │
                              │            └─ async_unload_entry
                              │               （模块保持加载）
                              ▼
                           DISABLED ── enable: async_setup + async_setup_entry ──> ENABLED

FAILED  （设置或运行时错误）
```

| 状态 | 含义 | 模块是否加载 |
|------|------|-------------|
| `INSTALLED` | `manifest.json` 已加载，模块尚未导入 | 否 |
| `LOADED` | 模块已导入，依赖已安装，等待配置条目激活 | 是 |
| `ENABLED` | 配置条目已激活，插件正在运行 | 是 |
| `DISABLED` | 标记 `disabled: true`。setup 之后模块仍加载，不激活 entry | 是 |
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
| `async_setup(domain)` | 安装依赖并导入模块 → 按 `CONFIG_SCHEMA` 补上尚未写入的默认配置 → 调用 `async_setup(context)` → state=LOADED |
| `async_setup_entry(entry)` | 调用插件的 `async_setup_entry(context, entry)` → 存储条目 → state=ENABLED |
| `async_forward_entry_setup(entry, platform)` | 加载平台子模块（如 `parser.py`），以 `contenthive_plugin_{domain}.{platform}` 注入 `sys.modules`，调用平台的 `async_setup_entry` |
| `async_unload_entry(entry_id)` | 调用插件的 `async_unload_entry` → 删除条目 → 若无其他活跃条目则 state=LOADED |
| `async_delete(domain)` | 卸载所有条目 → 从注册表移除 → 删除磁盘目录。unload 失败则中止，不丢弃 module、不删除目录 |
| `async_reload(domain)` | 卸载 → 清除 `sys.modules` 缓存 → 重置为 INSTALLED → 重新 setup，再用 `plugins.yaml` 里的配置执行 `setup_entry`。unload 失败则中止，不清除 module |
| `async_reload_domain(domain)` | 重载一个已在内存里的插件。DISABLED 会重新 setup，setup 失败也保持 DISABLED，不创建 entry。否则没有 entry 时用已保存的配置创建默认 entry |
| `async_discover_domain(domain)` | 读取一个已安装插件的 `manifest.json`，注册为 INSTALLED。不加载模块 |
| `unload_disabled_module(domain)` | 卸掉已导入的模块并重新读 manifest。状态保持 DISABLED，不执行 setup |
| `async_check_updates(catalog=None)` | 仅拉取插件目录，按各插件的发布轨道（stable 或 beta）选版本，比较后缓存更新信息（含 `release_notes`） |
| `has_installed_plugin_updates()` | 已安装插件是否落后于其轨道上的目录版本。health 的 `plugin_updates_available` 只反映此项；未安装插件走 `/v1/plugins/available` |
| `register_service(domain, service, callback)` | 注册命名服务 |
| `call_service(domain, service, data)` | 调用已注册的服务 |

**热重载实现细节**（`async_reload`）：

```
1. async_unload_entry（卸载所有活跃 entry）。任一 unload 失败则返回 false，不清除 module
2. 清除 sys.modules 中的 plugin_{domain} 和 contenthive_plugin_{domain}.* 缓存
3. 将 record 重置为 INSTALLED
4. async_setup
5. 从 plugins.yaml 刷新每个 entry 的 data（去掉框架保留键），再 async_setup_entry。
   某个 entry 失败不会跳过其余 entry。setup 或任一 entry 失败时返回 false。
```

---

### `catalog.py` — 插件目录客户端

读取 [content-hive/plugins](https://github.com/content-hive/plugins) 发布的插件目录，地址是内置的 `CATALOG_URL`（`https://content-hive.github.io/plugins/catalog.json`）。目录列出每个插件仓库，以及它最新的稳定版和预发布版 GitHub Release。

```python
async fetch_catalog() -> dict[str, CatalogPlugin]   # 以 domain 为键；失败时抛 CatalogError
CatalogPlugin.select_release(prerelease: bool) -> CatalogRelease | None
```

- 只接受 `schema` 为 1 的目录
- 格式不对的条目和重复的 domain 会被跳过并记录警告
- `min_core_version` 高于当前 Content Hive 版本的插件会被跳过
- `select_release(False)` 返回 `stable`；`select_release(True)` 有 `beta` 时返回 `beta`，否则返回 `stable`

---

### `downloader.py` — GitHub 插件下载器

`GitHubPluginDownloader` 从插件自己的 GitHub 仓库安全地下载、解压并安装单个插件版本。

**插件仓库格式**：插件代码在 Release tag 下的 `plugin/` 目录；`plugin/manifest.json` 的 `domain` 与目录一致，`version` 与该 Release 一致；tag 根目录的 `contenthive.json` 声明这一版要求的最低 Content Hive 版本。

```python
async install_release(
    plugin: CatalogPlugin,
    release: CatalogRelease,
    force_reinstall: bool = True,
) -> bool
```

下载 `https://github.com/{owner}/{repo}/archive/refs/tags/{tag}.zip`，解压后校验 `contenthive.json` 和 `plugin/manifest.json`，再把 `plugin/` 拷贝到 `PLUGINS_DIR/{domain}`。

**安全机制**：

| 机制 | 说明 |
|------|------|
| Domain 验证 | 仅允许 `[a-z0-9_-]`，防止路径穿越 |
| 仓库与 tag 验证 | 仓库必须是 `owner/repo`；tag 仅允许 `[a-zA-Z0-9._/\-]`，防止注入 |
| Manifest 校验 | `plugin/manifest.json` 必须与目录中的 domain 和 Release 版本一致 |
| 核心兼容性 | 所选 tag 的 `contenthive.json` 不得要求比当前运行更高的 Content Hive 版本 |
| Zip Slip 防护 | 解压时逐条验证路径不逃出目标目录 |
| 路径安全检查 | `_validate_path_safety()` 确保目标在 `plugins_dir` 内 |

---

### `config.py` — 插件配置文件工具

读写 `PLUGINS_DIR/plugins.yaml`，持久化每个插件的配置（含启用/禁用状态和发布轨道）。

```yaml
fxtwitter:
  disabled: true

youtube_parser:
  disabled: false
  prerelease: true
  api_key: "xxx"
  quality: "high"
```

- `disabled` 和 `prerelease` 是框架保留字段（`FRAMEWORK_KEYS`），其余字段为插件专属配置
- `prerelease: true` 表示该插件安装和更新到 beta 版本；可以在安装前设置。删除插件时会去掉整块配置，包括 `prerelease`
- **原子写入**：`tempfile.mkstemp` + `Path.replace`，在 `_config_lock` 线程锁内执行，保证并发安全

| 函数 | 说明 |
|------|------|
| `load_plugins_config()` | 加载完整配置；文件不存在或解析失败时返回 `{}` |
| `save_plugins_config(config)` | 原子写回 `plugins.yaml` |
| `get_plugin_config(domain)` | 获取单个插件配置块 |
| `set_plugin_field(domain, key, value)` | 加锁设置单个字段并持久化 |
| `remove_plugin_config(domain)` | 删除插件的整块配置，包括 `prerelease`（插件删除时调用）|
| `get_prerelease_domains()` | 返回跟踪预发布版的插件 domain |
| `strip_framework_keys(cfg)` | 过滤掉框架内置键 |
| `plugin_entry_data(domain)` | 给 config entry 用的已保存配置，不含框架保留键 |
| `plugin_get_config(domain, schema_cls)` | 获取配置并反序列化为 `PluginConfigSchema` 子类实例 |
| `plugin_save_config(domain, config)` | 序列化 `PluginConfigSchema` 实例并原子写入 |

---

### `startup.py` — 启动与关闭

#### `load_plugins_on_startup()`

```
1. 创建 PluginContext 和 PluginManager，注入 HA 风格方法
2. async_discover()        并发扫描本地 plugins/ 目录
3. async_check_updates()   轻量检查插件目录，日志记录可用更新和新插件（不自动安装）
4. 读取 plugins.yaml
5. for each plugin:
   ├── async_setup
   ├── [setup 失败] → 状态保持 FAILED
   ├── [disabled: true] → state = DISABLED，模块保持加载，不建 entry
   └── async_setup_entry
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
| `list_available()` | 拉取插件目录，合并本地安装状态和发布轨道，返回目录中所有插件 |
| `check_updates()` | 按各插件的发布轨道查询目录版本，返回各插件当前版本与最新版本 |
| `update_plugins(domains)` | 从插件的 GitHub Release 安装或更新，然后重载。禁用的插件保持 DISABLED。新插件先从 manifest 注册进内存 |
| `set_prerelease(domain, enabled)` | 把 `prerelease` 写入 `plugins.yaml`，并刷新缓存的更新信息 |
| `enable(domain)` | 清除禁用标记，动态加载并激活插件 |
| `disable(domain)` | 卸掉 entry，并在 `plugins.yaml` 中写入 `disabled: true`。模块保持加载。状态保持 DISABLED。unload 失败则中止，不改 disabled 状态、不丢弃 module |
| `delete(domain)` | 卸载模块 + 从注册表移除 + 删除磁盘目录 + 删掉 `plugins.yaml` 里的整块配置，包括 `prerelease`。unload 失败则中止，不丢弃 module、不删除目录 |
| `reload_all()` | 重载每个插件。禁用的插件会重新 setup，setup 失败也保持 DISABLED 且没有 entry，结果为 `disabled` |
| `reload(domain)` | 热重载一个插件。内存状态为 DISABLED 时，setup 失败也保持 DISABLED、不建 entry，并返回 409 `PLUGIN_NOT_ENABLED`。已有 entry 会带上已保存的配置重新加载；没有 entry 时用已保存的配置创建默认 entry。unload 失败则中止，不丢弃 module。失败返回 500 `PLUGIN_RELOAD_FAILED` |
| `get_plugin_settings(domain)` | 读取 `CONFIG_SCHEMA`，返回字段列表及当前配置值 |
| `update_plugin_settings(domain, body)` | 校验并持久化插件配置（支持部分更新，严格类型检查） |

**`update_plugin_settings` 校验规则**：
- 框架保留键（`disabled`、`prerelease`）被拒绝，返回 400
- 未声明的键静默忽略
- 声明的键以 `strict=True` 模式做类型检查
- 支持真正的部分更新

---

## HTTP 管理 API

所有端点需要管理员权限（Bearer Token），路由前缀 `/v1/plugins`。

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/v1/plugins/` | 列出所有本地已发现的插件及其状态 |
| `GET` | `/v1/plugins/available` | 列出插件目录中的所有插件（含未安装的），带 `prerelease` 和 `installable` |
| `POST` | `/v1/plugins/reload` | 热重载所有插件 |
| `POST` | `/v1/plugins/{domain}/reload` | 热重载指定插件。未启用返回 409 `PLUGIN_NOT_ENABLED`；重载失败返回 500 `PLUGIN_RELOAD_FAILED` |
| `POST` | `/v1/plugins/check-config` | 校验所有插件 manifest 的必填字段 |
| `GET` | `/v1/plugins/check-updates` | 检查各插件是否有新版本 |
| `POST` | `/v1/plugins/update` | 从插件的 GitHub Release 安装/更新插件 |
| `PUT` | `/v1/plugins/{domain}/prerelease` | 请求体 `{ "enabled": true }`。响应为 `{ "domain", "prerelease" }`，返回保存后的开关。插件未安装也可以设置 |
| `POST` | `/v1/plugins/{domain}/enable` | 启用指定插件 |
| `POST` | `/v1/plugins/{domain}/disable` | 禁用指定插件 |
| `GET` | `/v1/plugins/{domain}` | 获取一个已安装插件的状态。响应含 `domain`，以及与列表相同的 `state`、`version`、`name`、`error`、`update_available`、`description`、`author`、`prerelease`。未安装返回 404 `PLUGIN_NOT_FOUND` |
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
      ├── fetch_catalog() + plugins.yaml 的 prerelease → 每个插件要装的版本
      ├── GitHubPluginDownloader.install_release()（逐个插件）
      │   ├── 从插件仓库下载该 tag 的 zip 包
      │   ├── 安全解压（Zip Slip 防护）
      │   ├── 校验 plugin/manifest.json 的 domain 和 version
      │   └── 拷贝 plugin/ 到 PLUGINS_DIR/{domain}
      │
      ├── 已在内存或刚注册的插件 → manager.async_reload_domain(domain)
      │   ├── 内存状态 DISABLED → async_setup，setup 失败也保持 DISABLED，不建 entry
      │   └── 否则 → async_reload；没有 entry 时创建默认 entry
      │
      └── 新插件，重载之前 → async_discover_domain(domain)
          └── 把 plugins.yaml 的 disabled 写入内存，再 async_reload_domain
```

---

## 关键设计特点

1. **模块级加载** — 插件作为整个 Python 模块动态导入（`importlib`），而非实例化类，支持平台作为子模块独立注册
2. **严格状态机** — 状态转移受 PluginManager 控制，防止无效操作，错误状态可被恢复
3. **Home Assistant 风格** — `async_forward_entry_setup` / `async_unload_platforms` 模式让插件与平台高度解耦，易于横向扩展
4. **安全的远程分发** — Domain 校验、仓库与 tag 验证、manifest 校验、Zip Slip 防护多层保障
5. **无停机热更新** — 完整清除模块缓存（包括 `sys.modules` 中的所有子模块）后重新加载
6. **轻量版本检查** — 启动时仅拉取插件目录（几 KB），不下载插件包，对启动时间影响极小
7. **原子配置写入** — 临时文件 + rename + 线程锁，防止写入中断导致配置损坏
8. **类型化配置 Schema** — `CONFIG_SCHEMA` 驱动配置读取、写入、类型校验和 API 暴露，插件无需额外代码
9. **稳定接口契约** — 插件只依赖 `contenthive.plugins.*`，核心内部重构不影响已有插件
