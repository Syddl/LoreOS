"""Database access. All LoreOS tables live in the `loreos` schema."""

import collections
import functools
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from loreos import settings

log = logging.getLogger("loreos.db")
CONNECT_ATTEMPTS = 3
RETRIES = collections.Counter()  # connect_reset: resets retried in this process; the evaluation notes its run's count


@functools.cache
def engine() -> AsyncEngine:
    # ponytail: NullPool opens one connection per session, so no connection outlives its event loop; pool, with a
    # cap, when load shows the need (KNOWN-GAPS: no connection cap).
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
    """The only way code reads or writes workspace data: one transaction as loreos_app, committed on clean exit.

    The connecting role owns the tables, so RLS binds only after the switch to loreos_app. The role and
    app.workspace_id are transaction-local: code inside never commits, rolls back (a savepoint's rollback is fine)
    or resets the role, or later statements run as the owner. Every query still filters by workspace_id.
    """
    async with engine().begin() as conn:
        await conn.execute(
            text("select set_config('role','loreos_app',true), set_config('app.workspace_id',:w,true)"), {"w": str(workspace_id)}
        )
        yield conn


@asynccontextmanager
async def system_session() -> AsyncIterator[AsyncConnection]:
    """One transaction as the connecting role, which RLS does not bind: only for the cross-workspace reads the spec lists.

    test_isolation.SYSTEM_SESSION_FILES pins its callers. Every statement inside carries workspace_id = :w where
    it touches one workspace's rows.
    """
    async with engine().begin() as conn:
        yield conn
