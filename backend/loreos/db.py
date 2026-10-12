"""Database access. All LoreOS tables live in the `loreos` schema."""

import collections
import functools
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from loreos import settings

log = logging.getLogger("loreos.db")
CONNECT_ATTEMPTS = 3
RETRIES = collections.Counter()  # connect_reset: resets retried in this process; the evaluation notes its run's count


@functools.cache
def engine() -> AsyncEngine:
    # ponytail: NullPool opens one connection per session, so no connection outlives its event loop;
    # pool when P4's worker and UI need the throughput.
    created = create_async_engine(settings.database_url(), poolclass=NullPool)
    event.listen(created.sync_engine, "do_connect", _connect)
    return created


def _connect(dialect, conn_rec, cargs, cparams):
    """Connect, retrying a connection reset during the handshake: nothing has been sent yet, so a new attempt is safe.

    About 5% of new TLS connections from the dev machine to Supabase's pooler were reset (2026-10-11), and an
    evaluation run opens one per file and per question. Any other failure, a refused login included, is raised at once.
    """
    for attempt in range(1, CONNECT_ATTEMPTS + 1):
        try:
            return dialect.connect(*cargs, **cparams)
        except ConnectionResetError:
            if attempt == CONNECT_ATTEMPTS:
                raise
            RETRIES["connect_reset"] += 1
            log.warning("database connect reset; retrying, attempt %d of %d", attempt + 1, CONNECT_ATTEMPTS)


@asynccontextmanager
async def workspace_session(workspace_id: uuid.UUID) -> AsyncIterator[AsyncConnection]:
    """The only way code reads or writes workspace data: one transaction, committed on clean exit.

    Every query inside filters by workspace_id. P4 adds the role switch and the RLS setting here.
    """
    async with engine().begin() as conn:
        yield conn
