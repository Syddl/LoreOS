"""Runs migrations against DATABASE_URL. Online mode only."""

import asyncio

from alembic import context
from sqlalchemy import text

from loreos.db import engine


def run(connection) -> None:
    # The version table lives in the schema too, so it must exist before Alembic reads it.
    connection.execute(text("create schema if not exists loreos"))
    context.configure(connection=connection, version_table_schema="loreos")
    with context.begin_transaction():
        context.run_migrations()


async def main() -> None:
    async with engine().connect() as conn:
        await conn.run_sync(run)
        await conn.commit()


asyncio.run(main())
