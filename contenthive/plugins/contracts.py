"""
Plugin contract types. This is the stable interface between Content Hive
and its plugins. Plugins must only import from contenthive.plugins.*.
"""

from pydantic import BaseModel, ConfigDict, Field

# Re-export enums from enumerates so plugins only need to import from here
from contenthive.models.enumerates import MediaType, ParserResultStatus

# Re-export download progress callback for plugin download services
from contenthive.utils.download_progress import ProgressCallback as ProgressCallback


class PluginConfigSchema(BaseModel):
    """Base class for plugin configuration schemas.

    Subclass this and assign to CONFIG_SCHEMA in your plugin's __init__.py.
    Supported field types: str, int, float, bool, (str, Enum) subclass.

    Mark sensitive fields:  Field(json_schema_extra={"secret": True})
    Set display label:      Field(title="My Label")

    **Convention**: All fields MUST declare a default value so the plugin loads on
    first boot without user configuration. For fields that require user input (e.g.
    API keys, cookies), use ``default=""`` and validate the value at runtime inside
    ``async_setup_entry``, returning ``False`` with a warning log if the value is empty.

    Example::

        from enum import Enum
        from pydantic import Field
        from contenthive.plugins.contracts import PluginConfigSchema

        class Quality(str, Enum):
            LOW = "low"
            HIGH = "high"

        class ConfigSchema(PluginConfigSchema):
            cookies: str = Field(default="", title="Cookies",
                                 json_schema_extra={"secret": True})
            quality: Quality = Field(default=Quality.HIGH, title="Video Quality")

        CONFIG_SCHEMA = ConfigSchema
    """

    model_config = ConfigDict(extra="ignore")


class ParserMediaInfo(BaseModel):
    """Media information exchanged between plugins and the core."""

    url: str
    type: MediaType | None = None
    title: str | None = None
    cover: str | None = None
    duration: int | None = None
    width: int | None = None
    height: int | None = None
    url_fallbacks: list[str] | None = None
    cover_fallbacks: list[str] | None = None


class ParserPlatformInfo(BaseModel):
    """Platform information exchanged between plugins and the core."""

    code: str
    name: str
    url: str
    icon_url: str | None = None


class ParserAuthorInfo(BaseModel):
    """Author information exchanged between plugins and the core."""

    uid: str
    name: str | None = None
    username: str
    avatar: str | None = None
    url: str | None = None
    banner: str | None = None
    description: str | None = None


class ParserResult(BaseModel):
    """Full parse result returned by a plugin's parse service."""

    pid: str
    url: str
    title: str | None = None
    content: str | None = None
    media: list[ParserMediaInfo] = Field(default_factory=list)
    author: ParserAuthorInfo
    platform: ParserPlatformInfo
    post_time: int | None = None
    parser: str
    state: ParserResultStatus
