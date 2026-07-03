"""Content helpers for on-disk storage layout and lookup."""

import hashlib
from dataclasses import dataclass

from contenthive.utils.path_safety import sanitize_path_component


@dataclass
class ContentDirectory:
    """Locates a content directory under the media root."""

    platform_code: str
    author_uid: str
    content_id: str


def resolve_content_id(pid: str | None, url: str) -> str:
    """
    Resolve the storage key used to locate a content item on disk.

    Args:
        pid: Platform content ID from the parser, or None/empty to fall back
        url: Source content URL used when pid is absent

    Returns:
        Sanitized content directory name
    """
    if pid:
        return sanitize_path_component(pid)
    return sanitize_path_component(hashlib.md5(url.encode()).hexdigest()[:16])
