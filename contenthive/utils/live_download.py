"""
Live download state helpers for the core media pipeline.

Covers percent progress callbacks, retry/phase callbacks, and the in-process
LiveDownloadTracker used to overlay sub task API responses.

Plugins should import `ProgressCallback` from contenthive.plugins.contracts
(re-exported from here), not from this module directly.
"""

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from contenthive.models.download import DownloadRetryInfo

# Percent callback used by the download pipeline and exposed to plugins via contracts.
ProgressCallback = Callable[[int], Awaitable[None] | None]
# Per-file byte callback used inside download helpers (core-only).
ByteProgressCallback = Callable[[int, int | None], Awaitable[None] | None]
# Live retry / phase callback for the built-in downloader (core-only).
DownloadStateCallback = Callable[[DownloadRetryInfo], Awaitable[None] | None]


async def invoke_progress(callback: ProgressCallback | None, pct: int) -> None:
    """Invoke a sync or async percent progress callback."""
    if callback is None:
        return
    result = callback(pct)
    if inspect.isawaitable(result):
        await result


async def invoke_byte_progress(callback: ByteProgressCallback | None, downloaded: int, total: int | None) -> None:
    """Invoke a sync or async byte progress callback."""
    if callback is None:
        return
    result = callback(downloaded, total)
    if inspect.isawaitable(result):
        await result


async def invoke_download_state(callback: DownloadStateCallback | None, state: DownloadRetryInfo) -> None:
    """Invoke a sync or async download retry-state callback."""
    if callback is None:
        return
    result = callback(state)
    if inspect.isawaitable(result):
        await result


@dataclass
class BoundPercentProgress:
    """Byte progress reporter with optional per-attempt reset."""

    _callback: ProgressCallback
    _last_pct: int = -1

    def reset_attempt(self) -> None:
        """Allow the next report to emit from a lower percent (new attempt / URL)."""
        self._last_pct = -1

    async def __call__(self, downloaded: int, total: int | None) -> None:
        if total is None or total <= 0:
            return
        pct = min(99, int(downloaded * 100 / total))
        if pct <= self._last_pct:
            return
        self._last_pct = pct
        await invoke_progress(self._callback, pct)


def bind_percent_progress(on_progress: ProgressCallback | None) -> BoundPercentProgress | None:
    """
    Bind a percent callback to a single-file byte progress callback.

    Emits 0-99 from downloaded/total when Content-Length is known.
    No emit when total is unknown. Within one attempt updates are monotonic;
    call reset_attempt() before a retry or fallback URL so progress may drop.
    100 is reserved for the caller's final invoke_progress after success.
    """
    if on_progress is None:
        return None
    return BoundPercentProgress(_callback=on_progress)


@dataclass
class LiveDownloadState:
    """In-memory download overlay for one RUNNING sub task (not persisted)."""

    progress: int | None = None
    retry: DownloadRetryInfo | None = None


class LiveDownloadTracker:
    """
    Process-local map of sub_task_id → live progress / retry.

    Cleared when a sub task reaches a terminal status or the process restarts.
    """

    def __init__(self) -> None:
        self._states: dict[int, LiveDownloadState] = {}

    def set_progress(self, sub_task_id: int, progress: int) -> None:
        """Update per-attempt progress (0-100). May drop when a new attempt starts."""
        pct = max(0, min(100, int(progress)))
        state = self._states.setdefault(sub_task_id, LiveDownloadState())
        state.progress = pct

    def set_retry(self, sub_task_id: int, retry: DownloadRetryInfo) -> None:
        """Update retry / phase overlay."""
        state = self._states.setdefault(sub_task_id, LiveDownloadState())
        state.retry = retry

    def clear(self, sub_task_id: int) -> None:
        """Remove live state for a sub task."""
        self._states.pop(sub_task_id, None)

    def get(self, sub_task_id: int) -> LiveDownloadState | None:
        """Return live state when present; otherwise None."""
        return self._states.get(sub_task_id)
