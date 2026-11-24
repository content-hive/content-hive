"""
Plugin contract types. This is the stable interface between Content Hive
and its plugins. Plugins must only import from contenthive.plugins.*.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

# Re-export enums from enumerates so plugins only need to import from here
from contenthive.models.enumerates import MediaType, ParserResultStatus

# Re-export download progress callback for plugin download services
from contenthive.utils.live_download import ProgressCallback as ProgressCallback


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


class StreamBase(BaseModel):
    """Remote addresses shared by every stream role.

    ``urls[0]`` is the primary address (filename hash, cover identity, stored
    link). Later entries are download fallbacks only.
    """

    urls: list[str] = Field(min_length=1)


class ImageStream(StreamBase):
    """Still image, GIF, or the still frame of a live photo."""

    role: Literal["image"] = "image"
    width: int | None = None
    height: int | None = None


class VideoStream(StreamBase):
    role: Literal["video"] = "video"
    codec: str | None = None
    bandwidth: int | None = None
    width: int | None = None
    height: int | None = None
    quality: str | None = None


class AudioStream(StreamBase):
    role: Literal["audio"] = "audio"
    codec: str | None = None
    bandwidth: int | None = None
    quality: str | None = None
    label: str | None = None


class CoverStream(StreamBase):
    """Poster image. Not part of the finished media file."""

    role: Literal["cover"] = "cover"


class LinkStream(StreamBase):
    """Stored URL only; not downloaded as a media file."""

    role: Literal["link"] = "link"


type MediaStream = Annotated[
    ImageStream | VideoStream | AudioStream | CoverStream | LinkStream,
    Field(discriminator="role"),
]

MEDIA_STREAMS_ADAPTER = TypeAdapter(list[MediaStream])


def source_key_from_url(url: str) -> str:
    """Stable identity from a remote URL: last path component without the query string."""
    path = url.split("?", 1)[0]
    name = path.rsplit("/", 1)[-1]
    return name or path


def dump_streams(streams: list[MediaStream]) -> list[dict[str, Any]]:
    """Serialize streams for JSON columns and plugin payloads."""
    return [stream.model_dump(mode="json") for stream in streams]


def parse_streams(raw: object) -> list[MediaStream]:
    """Parse a JSON list of streams stored on a media row."""
    if not raw:
        return []
    return MEDIA_STREAMS_ADAPTER.validate_python(raw)


def cover_locator_from_streams(streams: object, media_type: MediaType | None) -> str | None:
    """Cover identity from a stored streams JSON blob: the primary URL only."""
    parsed = parse_streams(streams)
    if media_type == MediaType.LIVEPHOTO:
        still = next((stream for stream in parsed if stream.role == "image"), None)
        return still.urls[0] if still is not None else None
    cover = next((stream for stream in parsed if stream.role == "cover"), None)
    return cover.urls[0] if cover is not None else None


def _role_counts(streams: list[MediaStream]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for stream in streams:
        counts[stream.role] = counts.get(stream.role, 0) + 1
    return counts


def _stream_roles_allowed(media_type: MediaType) -> tuple[dict[str, int], dict[str, int]]:
    """Return (minimum counts, maximum counts) for each role."""
    if media_type in (MediaType.IMAGE, MediaType.GIF):
        return {"image": 1}, {"image": 1}
    if media_type == MediaType.VIDEO:
        return {"video": 1}, {"video": 1, "audio": 1, "cover": 1}
    if media_type == MediaType.AUDIO:
        return {"audio": 1}, {"audio": 1, "cover": 1}
    if media_type == MediaType.LIVEPHOTO:
        return {"video": 1, "image": 1}, {"video": 1, "image": 1}
    if media_type == MediaType.LINK:
        return {"link": 1}, {"link": 1, "cover": 1}
    raise ValueError(f"Unsupported media type: {media_type}")


class ParserMediaInfo(BaseModel):
    """One media item exchanged between plugins and the core."""

    source_key: str
    type: MediaType
    title: str | None = None
    duration: int | None = None
    width: int | None = None
    height: int | None = None
    streams: list[MediaStream] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_stream_roles(self) -> "ParserMediaInfo":
        counts = _role_counts(self.streams)
        minimum, maximum = _stream_roles_allowed(self.type)
        extra_roles = set(counts) - set(maximum)
        if extra_roles:
            raise ValueError(f"{self.type.value} has unexpected stream roles: {sorted(extra_roles)}")
        for role, needed in minimum.items():
            if counts.get(role, 0) != needed:
                raise ValueError(f"{self.type.value} requires {needed} {role} stream(s), got {counts.get(role, 0)}")
        for role, allowed in maximum.items():
            if counts.get(role, 0) > allowed:
                raise ValueError(f"{self.type.value} allows at most {allowed} {role} stream(s), got {counts[role]}")
        return self

    def first_stream(self, role: str) -> MediaStream | None:
        """Return the first stream with the given role, if any."""
        return next((stream for stream in self.streams if stream.role == role), None)

    def hash_url(self) -> str:
        """URL used to name the archived media file."""
        for role in ("video", "audio", "image", "link"):
            stream = self.first_stream(role)
            if stream is not None:
                return stream.urls[0]
        raise ValueError(f"No hashable stream on media {self.source_key}")

    def cover_file_stream(self) -> ImageStream | CoverStream | None:
        """Stream whose bytes become cover_path, if any."""
        if self.type == MediaType.LIVEPHOTO:
            stream = self.first_stream("image")
            return stream if isinstance(stream, ImageStream) else None
        stream = self.first_stream("cover")
        return stream if isinstance(stream, CoverStream) else None

    def cover_locator(self) -> str | None:
        """Identity of the cover/still source, used to decide when to refresh cover_path."""
        stream = self.cover_file_stream()
        if stream is None:
            return None
        return stream.urls[0]

    def downloadable_streams(self) -> list[MediaStream]:
        """Streams that should be fetched as files."""
        return [stream for stream in self.streams if stream.role != "link"]


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
