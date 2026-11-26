"""Check GitHub Releases for a newer Content Hive version.

The result is cached in memory. Health checks read the cache and do not call GitHub.
"""

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import aiohttp
from packaging.version import InvalidVersion, Version

from contenthive.const import APP_VERSION
from contenthive.logger import logger

RELEASES_URL = "https://api.github.com/repos/content-hive/content-hive/releases?per_page=30"
CHECK_INTERVAL_SECONDS = 6 * 60 * 60


@dataclass(frozen=True)
class CoreUpdate:
    """A published release newer than the running server."""

    latest_version: str
    release_notes: str | None = None


@dataclass(frozen=True)
class _Candidate:
    version: Version
    version_str: str
    prerelease: bool
    release_notes: str | None


def _parse_release(data: Any) -> _Candidate | None:
    """Return a comparable release, or None for drafts and unusable tags."""
    if not isinstance(data, dict) or data.get("draft"):
        return None
    tag = data.get("tag_name")
    if not isinstance(tag, str) or not tag.startswith("v") or len(tag) == 1:
        return None
    raw = tag[1:]
    try:
        parsed = Version(raw)
    except InvalidVersion:
        return None
    if parsed.is_devrelease:
        return None
    body = data.get("body")
    notes = body.strip() if isinstance(body, str) else ""
    return _Candidate(
        version=parsed,
        version_str=raw,
        prerelease=bool(data.get("prerelease")),
        release_notes=notes or None,
    )


def select_core_update(releases: list[Any], current_version: str) -> CoreUpdate | None:
    """Pick the newest release on this server's track when it is strictly newer.

    A final or dev install only considers stable releases. A pre-release install
    considers the newer of the latest stable and the latest pre-release.
    """
    try:
        current = Version(current_version)
    except InvalidVersion:
        return None

    candidates = [item for item in (_parse_release(release) for release in releases) if item is not None]
    if not current.is_prerelease or current.is_devrelease:
        candidates = [item for item in candidates if not item.prerelease]

    newer = [item for item in candidates if item.version > current]
    if not newer:
        return None
    best = max(newer, key=lambda item: item.version)
    return CoreUpdate(latest_version=best.version_str, release_notes=best.release_notes)


class CoreUpdateChecker:
    """Refresh the cached core update on startup and every six hours."""

    def __init__(self) -> None:
        self._offer: CoreUpdate | None = None
        self._task: asyncio.Task[None] | None = None

    def current(self) -> CoreUpdate | None:
        return self._offer

    async def _fetch_releases(self) -> list[Any]:
        """Download the recent GitHub Releases for this repository."""
        timeout = aiohttp.ClientTimeout(total=30)
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "content-hive",
        }
        try:
            async with (
                aiohttp.ClientSession(timeout=timeout, trust_env=True) as session,
                session.get(RELEASES_URL, headers=headers) as response,
            ):
                if response.status != 200:
                    raise RuntimeError(f"GitHub releases request failed: HTTP {response.status}")
                data = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise RuntimeError(f"GitHub releases request failed: {exc}") from exc
        if not isinstance(data, list):
            raise RuntimeError("GitHub releases response is not a list")
        return data

    async def refresh(self) -> None:
        """Fetch releases and replace the cache. A failed fetch leaves the cache empty."""
        try:
            releases = await self._fetch_releases()
        except Exception:
            logger.warning("Failed to check for Content Hive updates", exc_info=True)
            self._offer = None
            return

        self._offer = select_core_update(releases, APP_VERSION)
        if self._offer is None:
            logger.debug("Content Hive is up to date")
        else:
            logger.info("Content Hive update available: %s → %s", APP_VERSION, self._offer.latest_version)

    async def _run(self) -> None:
        while True:
            await self.refresh()
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None


_checker: CoreUpdateChecker | None = None


def get_core_update() -> CoreUpdate | None:
    """Return the cached update, or None when none is available or the check has not run."""
    if _checker is None:
        return None
    return _checker.current()


def start_core_update_checks() -> None:
    """Start the background check. The first fetch runs without blocking startup."""
    global _checker
    _checker = CoreUpdateChecker()
    _checker.start()


async def stop_core_update_checks() -> None:
    """Cancel the background check."""
    global _checker
    if _checker is not None:
        await _checker.stop()
        _checker = None
