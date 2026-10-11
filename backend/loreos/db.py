"""Database access. All LoreOS tables live in the `loreos` schema."""

import functools
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
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
