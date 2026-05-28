# 插件开发者指南

Content Hive 采用 Home Assistant 风格的插件架构。每个受支持的平台（Twitter、YouTube、TikTok 等）都是独立插件，可以在不重启应用的情况下安装、更新、配置和热重载。

插件通过 GitHub 仓库统一分发，通过 REST API 进行管理。

如需了解系统内部架构，请参阅[插件系统设计](/zh/plugin-system)。

---

## 快速开始

最小可运行插件需要三个文件：

```
plugins/
└── my_parser/
    ├── manifest.json
    ├── __init__.py
    └── parser.py
```

**manifest.json**
```json
{
  "domain": "my_parser",
  "name": "My Parser",
  "version": "1.0.0",
  "requirements": [],
  "author": ["Your Name"]
}
```

**\_\_init\_\_.py**
```python
from contenthive.plugins.context import PluginContext
from contenthive.plugins.manager import PluginEntryData

DOMAIN = "my_parser"

async def async_setup_entry(context: PluginContext, entry: PluginEntryData) -> bool:
    await context.async_forward_entry_setup(entry, "parser")
    return True

async def async_unload_entry(context: PluginContext, entry: PluginEntryData) -> bool:
    return await context.async_unload_platforms(entry, ["parser"])
```

**parser.py**
```python
from typing import Any
from contenthive.plugins.context import PluginContext
from contenthive.plugins.contracts import (
    ParserResult, ParserAuthorInfo, ParserPlatformInfo, ParserResultStatus
)
from contenthive.plugins.manager import PluginEntryData

DOMAIN = "my_parser"

class MyParser:
    def __init__(self, context: PluginContext, entry: PluginEntryData):
        self.context = context

    def can_parse(self, data: dict[str, Any]) -> bool:
        url = data.get("url", "")
        return "example.com" in url

    async def parse(self, data: dict[str, Any]) -> ParserResult:
        url = data.get("url")
        return ParserResult(
            pid="unique-id",
            url=url,
            title="示例内容",
            content="内容正文",
            media=[],
            author=ParserAuthorInfo(uid="123", username="author"),
            platform=ParserPlatformInfo(code="example", name="Example", url="https://example.com"),
            post_time=None,
            parser=DOMAIN,
            state=ParserResultStatus.SUCCESS,
        )

    async def async_will_remove(self):
        pass


async def async_setup_entry(context, entry, async_add_entities):
    parser = MyParser(context, entry)
    await async_add_entities([parser])  # 注册实体，卸载时触发 async_will_remove

    # 注册服务——ContentService 通过这两个服务发现并调用解析器
    context.register_service(DOMAIN, "can_parse", parser.can_parse)
    context.register_service(DOMAIN, "parse", parser.parse)
```

---

## 插件目录结构

```
plugins/
└── {domain}/
    ├── manifest.json     # 插件元数据（必需）
    ├── __init__.py       # 生命周期钩子 + 可选的 CONFIG_SCHEMA
    ├── parser.py         # 平台模块，通过 async_forward_entry_setup 注册
    └── const.py          # 常量定义（可选）
```

`domain` 必须与 `manifest.json` 中的 `domain` 字段一致，只允许 `[a-z0-9_-]` 字符。

---

## manifest.json 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `domain` | `string` | 是 | 插件唯一标识符，仅允许字母、数字、下划线、连字符 |
| `name` | `string` | 是 | 显示名称 |
| `version` | `string` | 是 | 语义版本号（如 `"1.2.0"`）|
| `requirements` | `list[string]` | 否 | 需要安装的 PyPI 包（如 `["aiohttp~=3.9"]`）|
| `author` | `list[string]` | 否 | 作者名称列表 |
| `description` | `string` | 否 | 简短描述 |

---

## 插件生命周期

```
INSTALLED ──async_setup──> LOADED ──async_setup_entry──> ENABLED
    ▲                         ▲                               │
    │                         └──────── async_unload_entry ──┘
    │
DISABLED                                                  FAILED
```

| 状态 | 含义 |
|------|------|
| `INSTALLED` | `manifest.json` 已加载，模块尚未导入 |
| `LOADED` | 模块已导入，依赖已安装，等待配置条目激活 |
| `ENABLED` | 配置条目已激活，插件正在运行 |
| `DISABLED` | `plugins.yaml` 中标记为 `disabled: true`，启动时跳过 |
| `FAILED` | 设置或运行时发生错误 |

---

## 生命周期钩子（`__init__.py`）

### `async_setup(context) -> bool` *（可选）*

模块加载时调用一次，用于不依赖用户配置的初始化工作。

```python
async def async_setup(context: PluginContext) -> bool:
    context.logger.info("插件模块已加载")
    return True
```

### `async_setup_entry(context, entry) -> bool` *（必需）*

配置条目激活时调用。在此读取配置、注册平台模块。返回 `False` 则中止激活（例如必填配置项为空时）。

```python
async def async_setup_entry(context: PluginContext, entry: PluginEntryData) -> bool:
    config = context.get_config(DOMAIN)
    if not config.api_key:
        context.logger.warning("api_key 未配置，插件跳过激活")
        return False
    await context.async_forward_entry_setup(entry, "parser")
    return True
```

### `async_unload_entry(context, entry) -> bool` *（必需）*

插件禁用、热重载或应用关闭时调用。卸载所有已注册的平台，释放资源。

```python
async def async_unload_entry(context: PluginContext, entry: PluginEntryData) -> bool:
    return await context.async_unload_platforms(entry, ["parser"])
```

---

## 平台模块（`parser.py`）

平台模块通过 `context.async_forward_entry_setup(entry, "parser")` 注册。Content Hive 会加载该模块并调用其 `async_setup_entry`：

```python
async def async_setup_entry(context, entry, async_add_entities):
    parser = MyParser(context, entry)
    await parser.async_setup()       # 可选，如创建 HTTP session

    # 注册实体，卸载时触发 async_will_remove
    await async_add_entities([parser])

    # 注册服务——ContentService 通过这两个服务发现并调用解析器
    context.register_service(DOMAIN, "can_parse", parser.can_parse)
    context.register_service(DOMAIN, "parse", parser.parse)
```

> `can_parse` 和 `parse` 是 ContentService 发现和执行解析器的唯一入口，未注册这两个服务的插件不会被调用。

### 解析器需实现的方法

| 方法 | 签名 | 说明 |
|------|------|------|
| `can_parse` | `(data: dict) -> bool` | 返回 `True` 表示此插件可以处理 `data["url"]` |
| `parse` | `async (data: dict) -> ParserResult` | 解析 `data["url"]` 并返回结果 |
| `async_will_remove` | `async () -> None` | 清理资源（关闭 HTTP session 等）|

---

## 接口契约

从 `contenthive.plugins.contracts` 导入，不得依赖核心内部模块。

### `ParserResult`

| 字段 | 类型 | 说明 |
|------|------|------|
| `pid` | `str` | 平台上的内容唯一 ID |
| `url` | `str` | 原始 URL |
| `title` | `str \| None` | 标题 |
| `content` | `str \| None` | 正文 |
| `media` | `list[ParserMediaInfo]` | 媒体附件列表 |
| `author` | `ParserAuthorInfo` | 作者信息 |
| `platform` | `ParserPlatformInfo` | 平台信息 |
| `post_time` | `int \| None` | 发布时间（Unix 时间戳）|
| `parser` | `str` | 解析器标识（通常为 `DOMAIN`）|
| `state` | `ParserResultStatus` | `SUCCESS` 或 `ERROR` |

### `ParserMediaInfo`

| 字段 | 类型 | 说明 |
|------|------|------|
| `url` | `str` | 主媒体 URL |
| `type` | `MediaType \| None` | `image`、`video`、`audio` 等 |
| `title` | `str \| None` | 媒体标题 |
| `cover` | `str \| None` | 封面/缩略图 URL |
| `duration` | `int \| None` | 时长（秒，视频/音频）|
| `width` | `int \| None` | 宽度（像素）|
| `height` | `int \| None` | 高度（像素）|
| `url_fallbacks` | `list[str] \| None` | 备用下载 URL 列表 |
| `cover_fallbacks` | `list[str] \| None` | 备用封面 URL 列表 |

### `ParserAuthorInfo`

| 字段 | 类型 | 说明 |
|------|------|------|
| `uid` | `str` | 平台用户 ID |
| `username` | `str` | 用户名 / 账号 |
| `name` | `str \| None` | 显示名称 |
| `avatar` | `str \| None` | 头像 URL |
| `url` | `str \| None` | 主页 URL |
| `banner` | `str \| None` | 横幅图 URL |
| `description` | `str \| None` | 简介 |

### `ParserPlatformInfo`

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | `str` | 平台短标识（如 `"twitter"`）|
| `name` | `str` | 显示名称（如 `"Twitter / X"`）|
| `url` | `str` | 平台主页 URL |
| `icon_url` | `str \| None` | 平台图标 URL |

---

## 配置 Schema

如果插件需要用户配置（API Key、Cookies 等），在 `__init__.py` 中定义 `CONFIG_SCHEMA`：

```python
from enum import Enum
from pydantic import Field
from contenthive.plugins.contracts import PluginConfigSchema

class Quality(str, Enum):
    LOW = "low"
    HIGH = "high"

class ConfigSchema(PluginConfigSchema):
    api_key: str = Field(default="", title="API Key",
                         json_schema_extra={"secret": True})
    quality: Quality = Field(default=Quality.HIGH, title="Video Quality")

CONFIG_SCHEMA = ConfigSchema
```

**约定：**

| 特性 | 写法 |
|------|------|
| 敏感字段（密码/Token）| `Field(json_schema_extra={"secret": True})` |
| 显示标签 | `Field(title="My Label")` |
| 需用户填写的字段 | `default=""` + 在 `async_setup_entry` 内检查空值 |
| 可选调参字段 | 提供合理的 `default` 值 |
| 支持的类型 | `str`、`int`、`float`、`bool`、`str` Enum 子类 |

所有字段必须声明默认值，确保插件在首次启动时无需用户配置即可加载。配置持久化到 `plugins.yaml`，敏感字段在 API 响应中自动脱敏。

---

## 插件上下文

所有生命周期钩子都会收到 `PluginContext` 对象：

| 属性 | 类型 | 说明 |
|------|------|------|
| `logger` | `logging.Logger` | 日志记录器 |
| `data` | `dict[str, Any]` | 插件内存数据存储 |
| `get_config(domain)` | `Callable` | 获取当前配置（返回 `PluginConfigSchema` 实例）|
| `save_config(domain, config)` | `Callable` | 将配置持久化到 `plugins.yaml` |
| `async_forward_entry_setup(entry, platform)` | `Callable` | 加载并注册平台模块 |
| `async_unload_platforms(entry, platforms)` | `Callable` | 卸载已注册的平台模块 |
| `register_service(domain, service, callback)` | `Callable` | 注册命名服务 |

---

## 服务机制

插件可以注册命名服务，供核心流程调用。最常用的是 `download` 服务——核心媒体下载管道会优先调用插件的 `download` 服务，只有在未注册时才回退到内置 HTTP 下载器。

```python
async def my_download(data: dict):
    media = data["media"]
    # 自定义下载逻辑（处理签名 URL、登录态等）
    return {"path": "/tmp/file.mp4", "mime": "video/mp4"}

# 在 async_setup_entry 中注册
context.register_service(DOMAIN, "download", my_download)
```

---

## 调试

| 查看目标 | 方法 |
|----------|------|
| 插件状态 | `manager.plugins[domain].state` |
| 错误信息 | `manager.plugins[domain].error` |
| 配置 Schema | `manager.plugins[domain].config_schema` |
| 已激活的解析器域 | `[d for d, s in manager.services.items() if "can_parse" in s]` |
| 可用更新缓存 | `manager._available_updates` |
| 触发热重载 | `await manager.async_reload(domain)` |
| 监听事件 | `manager.event_bus.listen("plugin_enabled", callback)` |

日志写入 `LOGS_DIR` 目录，按日滚动。通过 `GET /v1/system/logs` 可分页查询日志内容。
