"""
Download progress helpers for the core media pipeline.

Not part of the plugin contract — plugins should only consume an optional
`on_progress` callable passed in download service data, and implement any
byte aggregation locally.
"""

import inspect
from collections.abc import Awaitable, Callable

# Percent callback used by callers (task service / plugins).
ProgressCallback = Callable[[int], Awaitable[None] | None]
# Per-file byte callback used inside download helpers.
ByteProgressCallback = Callable[[int, int | None], Awaitable[None] | None]


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


class ByteProgressAggregator:
    """
    Merge parallel file downloads into a single 0-100 percent via byte weighting.

    Formula: sum(downloaded) / sum(known totals) * 100.
    When no Content-Length is known yet, no percent is emitted (stays at 0).
    """

    def __init__(self, on_progress: ProgressCallback | None = None) -> None:
        self._on_progress = on_progress
        self._slots: dict[str, tuple[int, int | None]] = {}
        self._last_pct = -1

    def track(self, key: str) -> ByteProgressCallback:
        """Return a byte callback bound to the given slot key."""

        async def _report(downloaded: int, total: int | None) -> None:
            self._slots[key] = (downloaded, total)
            await self._emit()

        return _report

    async def _emit(self) -> None:
        downloaded_sum = 0
        total_sum = 0
        has_known_total = False
        for downloaded, total in self._slots.values():
            downloaded_sum += downloaded
            if total is not None and total > 0:
                has_known_total = True
                total_sum += total

        if not has_known_total or total_sum <= 0:
            return

        pct = min(100, int(downloaded_sum * 100 / total_sum))
        if pct <= self._last_pct:
            return
        self._last_pct = pct
        await invoke_progress(self._on_progress, pct)
