"""Database access. All LoreOS tables live in the `loreos` schema."""

import functools
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from loreos import settings


@functools.cache
def engine() -> AsyncEngine:
    # ponytail: NullPool opens one connection per session, so no connection outlives its event loop;
    # pool when P4's worker and UI need the throughput.
    return create_async_engine(settings.database_url(), poolclass=NullPool)


@asynccontextmanager
async def workspace_session(workspace_id: uuid.UUID) -> AsyncIterator[AsyncConnection]:
    """The only way code reads or writes workspace data: one transaction, committed on clean exit.

    Every query inside filters by workspace_id. P4 adds the role switch and the RLS setting here.
    """
    async with engine().begin() as conn:
        yield conn
