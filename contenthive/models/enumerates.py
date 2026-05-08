from enum import Enum


class UserStatus(str, Enum):
    INACTIVE = "inactive"
    ACTIVE = "active"
    DISABLED = "disabled"


class ResponseStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"


class OperationType(str, Enum):
    DELETE = "delete"
    CANCEL = "cancel"
    UPDATE = "update"
    ENABLE = "enable"
    DISABLE = "disable"


class TaskType(str, Enum):
    PARSE_CONTENT = "parse_content"
    MEDIA_DOWNLOAD = "media_download"
    CONTENT_ANALYSIS = "content_analysis"
    # Add more task types as needed


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    CANCELED = "canceled"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskRole(str, Enum):
    PRIMARY = "primary"
    LINKED = "linked"
    REUSED = "reused"


class MediaStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"


class MediaType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    LIVEPHOTO = "livephoto"
    AUDIO = "audio"
    GIF = "gif"


class ParserResultStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
