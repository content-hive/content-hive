from enum import StrEnum


class UserStatus(StrEnum):
    INACTIVE = "inactive"
    ACTIVE = "active"
    DISABLED = "disabled"


class ResponseStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"


class OperationType(StrEnum):
    DELETE = "delete"
    CANCEL = "cancel"
    UPDATE = "update"
    ENABLE = "enable"
    DISABLE = "disable"


class TaskType(StrEnum):
    PARSE_CONTENT = "parse_content"
    MEDIA_DOWNLOAD = "media_download"
    CONTENT_ANALYSIS = "content_analysis"
    # Add more task types as needed


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    CANCELED = "canceled"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskRole(StrEnum):
    PRIMARY = "primary"
    LINKED = "linked"
    REUSED = "reused"


class MediaStatus(StrEnum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"


class MediaType(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    LIVEPHOTO = "livephoto"
    AUDIO = "audio"
    GIF = "gif"
    LINK = "link"


class ParserResultStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
