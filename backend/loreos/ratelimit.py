"""Fixed-window rate limits in loreos.rate_limits, shared by every api process. Login uses them; P6 reuses them."""

import math
from datetime import UTC, datetime
from typing import NamedTuple

from sqlalchemy import text

from loreos.db import system_session

# ponytail: past windows are never pruned, so the table grows by one row per bucket per window;
# delete rows older than the longest window when its size matters.
COUNT = (
    "insert into loreos.rate_limits (bucket, window_start, count) values (:b, :w, 1) "
    "on conflict (bucket, window_start) do update set count = rate_limits.count + 1 returning count"
)
REFUND = "update loreos.rate_limits set count = greatest(count - 1, 0) where bucket = :b and window_start = :w"


class Slot(NamedTuple):
    allowed: bool
    retry_after: int  # whole seconds to the window's end, 0 when allowed
    window_start: datetime  # the window this call counted in, for refund


def _now() -> datetime:
    return datetime.now(UTC)


async def rate_limit(bucket: str, limit: int, window_s: int) -> Slot:
    """Count this call in the bucket's current window; allowed while the count, this call included, is <= limit."""
    t = _now().timestamp()
    start = t // window_s * window_s
    window_start = datetime.fromtimestamp(start, UTC)
    async with system_session() as conn:
        count = (await conn.execute(text(COUNT), {"b": bucket, "w": window_start})).scalar_one()
    allowed = count <= limit
    return Slot(allowed, 0 if allowed else math.ceil(start + window_s - t), window_start)


async def refund(bucket: str, window_start: datetime) -> None:
    """Take back one call counted in that window, never below 0."""
    async with system_session() as conn:
        await conn.execute(text(REFUND), {"b": bucket, "w": window_start})
