
from enum import Enum

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
    WAITING_FOR_PRIMARY = "waiting_for_primary"

class TaskRole(str, Enum):
    PRIMARY = "primary"
    LINKED = "linked"
    REUSED = "reused"

class MediaStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
