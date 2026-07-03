"""Generic path safety utilities for filesystem operations."""

from pathlib import Path


def is_path_within_base(target: Path, base: Path, *, allow_base_itself: bool = True) -> bool:
    """
    Check whether a target path resolves safely within a base directory.

    Args:
        target: Path to validate
        base: Root directory the target must stay within
        allow_base_itself: When False, reject paths that resolve exactly to base

    Returns:
        True if target is within base, otherwise False
    """
    resolved_target = target.resolve()
    resolved_base = base.resolve()
    if not allow_base_itself and resolved_target == resolved_base:
        return False
    try:
        resolved_target.relative_to(resolved_base)
        return True
    except ValueError:
        return False


def sanitize_path_separators(value: str) -> str:
    """
    Replace path separators with underscores for safe use in file paths.

    Args:
        value: Raw string that may contain slashes

    Returns:
        String with forward and back slashes replaced by underscores
    """
    separators = ["/", "\\"]
    for separator in separators:
        value = value.replace(separator, "_")
    return value


def sanitize_path_component(name: str, *, max_length: int = 100) -> str:
    """
    Sanitize a single filesystem path component.

    Args:
        name: Raw path segment such as a platform code, author uid, or content key
        max_length: Maximum length of the returned component

    Returns:
        Sanitized path component safe for use under a storage root
    """
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, "_")
    return name.strip()[:max_length]
