"""
Download progress helpers for the core media pipeline.

Plugins should import `ProgressCallback` from contenthive.plugins.contracts
(re-exported from here), not from this module directly.
"""

import inspect
from collections.abc import Awaitable, Callable

# Percent callback used by the download pipeline and exposed to plugins via contracts.
ProgressCallback = Callable[[int], Awaitable[None] | None]
# Per-file byte callback used inside download helpers (core-only).
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


def bind_percent_progress(on_progress: ProgressCallback | None) -> ByteProgressCallback | None:
    """
    Bind a percent callback to a single-file byte progress callback.

    Emits 0-99 from downloaded/total when Content-Length is known.
    No emit when total is unknown. Updates are monotonic so a retry that
    restarts from byte 0 does not yank the UI back to 0%.
    100 is reserved for the caller's final invoke_progress after success.
    """
    if on_progress is None:
        return None

    last_pct = -1

    async def _report(downloaded: int, total: int | None) -> None:
        nonlocal last_pct
        if total is None or total <= 0:
            return
        pct = min(99, int(downloaded * 100 / total))
        if pct <= last_pct:
            return
        last_pct = pct
        await invoke_progress(on_progress, pct)

    return _report
