"""Test environment: a per-checkout database in the testdb container, a fake OpenAI key and an unroutable base URL.

These assignments run before any loreos module reads the environment, and they win over the
repo's .env, so no check can reach Supabase or OpenAI.

Tests connect as testdb_owner, which is not a superuser, so a missing grant fails here as it would on
Supabase. The session bootstrap recreates this checkout's database, so run one test session per
checkout at a time; separate worktrees have separate databases.
"""

import asyncio
import os
import re
import zlib
from pathlib import Path
from types import SimpleNamespace

import asyncpg
import pytest

from loreos import settings

BACKEND = Path(__file__).resolve().parents[1]
TESTDB = "127.0.0.1:54329"  # docker-compose.yml testdb, and CI's service container
# Hard-coded, never read from the environment: the bootstrap drops a database through it.
ADMIN_URL = f"postgresql://postgres:postgres@{TESTDB}"
TEST_OWNER = "testdb_owner"
START_TESTDB = "docker compose --profile test up -d testdb"


def database_for(checkout: str) -> str:
    """loreos_test_ plus the checkout directory's name, reduced to [a-z0-9_] and cut to Postgres's 63 bytes."""
    return ("loreos_test_" + re.sub(r"[^a-z0-9_]", "_", checkout.lower()))[:63]


TEST_DATABASE = database_for(BACKEND.parent.name)
# Every key settings.py reads, pinned, so a .env in the checkout changes no test.
PINNED_ENV = {
    "DATABASE_URL": f"postgresql://{TEST_OWNER}:{TEST_OWNER}@{TESTDB}/{TEST_DATABASE}",
    "OPENAI_API_KEY": "sk-test-not-a-real-key",
    # 0.0.0.0 fails at once on Windows (address not valid) and on Linux (refused); a closed 127.0.0.1
    # port takes about two seconds on Windows, which retries the refused connection.
    "OPENAI_BASE_URL": "http://0.0.0.0:9/v1",
    "EMBEDDING_MODEL": settings.DEFAULT_EMBEDDING_MODEL,
    "ANSWER_MODEL": settings.DEFAULT_ANSWER_MODEL,
    "JUDGE_MODEL": settings.DEFAULT_JUDGE_MODEL,
    "ALLOWED_HOSTS": settings.DEFAULT_ALLOWED_HOSTS,
}
os.environ.update(PINNED_ENV)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402

from loreos.db import engine  # noqa: E402
from loreos.embeddings import EMBEDDING_DIM  # noqa: E402
from loreos.workspaces import DEFAULT_WORKSPACE_ID  # noqa: E402


def sql(query: str, **params):
    """Run one statement against the test database in its own transaction; rows when it returns any."""

    async def go():
        async with engine().begin() as conn:
            result = await conn.execute(text(query), params)
            return result.all() if result.returns_rows else None

    return asyncio.run(go())


@pytest.fixture(scope="session")
def db():
    """This checkout's test database, recreated empty and migrated to head. Stops the run, never skips, on failure."""
    try:
        asyncio.run(asyncio.wait_for(_admin("select 1"), 10))
    except Exception as e:  # any failure to reach it means the container is not up
        pytest.exit(f"testdb is not reachable at {TESTDB} ({type(e).__name__}); start it with: {START_TESTDB}", returncode=1)
    try:
        asyncio.run(_bootstrap())
    except asyncpg.ObjectInUseError:
        pytest.exit(f"{TEST_DATABASE} is in use by another test run in this checkout; run one at a time", returncode=1)
    command.upgrade(Config(str(BACKEND / "alembic.ini")), "head")


async def _admin(*statements: str, database: str = "postgres") -> None:
    """Run each statement as postgres, in autocommit (DROP and CREATE DATABASE refuse a transaction block)."""
    conn = await asyncpg.connect(f"{ADMIN_URL}/{database}")
    try:
        for statement in statements:
            await conn.execute(statement)
    finally:
        await conn.close()


async def _bootstrap() -> None:
    """The non-superuser owner role, a fresh database it owns with vector in public, and loreos_app's attributes reset.

    loreos_app itself is created by migration 0002, never here, so testdb_owner holds ADMIN on it and can grant
    itself SET. Roles are cluster-wide: a drifted loreos_app left by another checkout is reset rather than inherited.
    """
    assert TEST_DATABASE.startswith("loreos_test_"), TEST_DATABASE  # the only databases this may drop
    try:
        await _admin(f"create role {TEST_OWNER} login createrole bypassrls password '{TEST_OWNER}'")
    except (asyncpg.DuplicateObjectError, asyncpg.UniqueViolationError):  # another checkout created it, maybe just now
        pass
    await _admin(
        "do $$ begin if exists (select from pg_roles where rolname = 'loreos_app') then "
        "alter role loreos_app nologin nobypassrls nosuperuser; end if; end $$",
        f'drop database if exists "{TEST_DATABASE}"',
        f'create database "{TEST_DATABASE}" owner {TEST_OWNER}',
    )
    await _admin("create extension if not exists vector", database=TEST_DATABASE)


@pytest.fixture
def clean(db):
    """Empty documents, chunks and the account tables; keep only the default workspace."""
    sql("delete from loreos.documents")
    sql("delete from loreos.users")  # memberships and sessions cascade; invites keep a null created_by
    sql("delete from loreos.invites")
    sql("delete from loreos.api_keys")
    sql("delete from loreos.rate_limits")
    sql("delete from loreos.workspaces where id <> :id", id=DEFAULT_WORKSPACE_ID)


def word_vector(text_: str) -> list[float]:
    """A deterministic embedding: word counts hashed into EMBEDDING_DIM buckets, never all zero."""
    v = [0.0] * EMBEDDING_DIM
    for word in re.findall(r"\w+", text_.lower()):
        v[zlib.crc32(word.encode()) % EMBEDDING_DIM] += 1.0
    if not any(v):
        v[0] = 1.0
    return v


@pytest.fixture
def fake_embed(monkeypatch):
    """Replace llm.embed with word_vector; the list records every input it received."""
    from loreos import llm

    calls: list[str] = []

    async def embed(texts):
        calls.extend(texts)
        return [word_vector(t) for t in texts]

    monkeypatch.setattr(llm, "embed", embed)
    return calls


@pytest.fixture
def fake_draft(monkeypatch):
    """Replace llm.draft_answer; set .reply to the Draft it returns; .calls and .hits record each call."""
    from loreos import llm

    fake = SimpleNamespace(reply=llm.Draft(found=True, text="From the documents [1]."), calls=[], hits=[])

    async def draft_answer(question, hits):
        fake.calls.append(question)
        fake.hits.append(hits)
        return fake.reply

    monkeypatch.setattr(llm, "draft_answer", draft_answer)
    return fake


@pytest.fixture
def fake_judge(monkeypatch):
    """Replace llm.judge; set .reply to the Verdict it returns or an exception it raises; .calls records each call."""
    from loreos import llm

    fake = SimpleNamespace(reply=llm.Verdict(rationale="Every claim is supported.", grade="faithful"), calls=[])

    async def judge(question, answer, passages):
        fake.calls.append((question, answer, passages))
        if isinstance(fake.reply, BaseException):
            raise fake.reply
        return fake.reply

    monkeypatch.setattr(llm, "judge", judge)
    return fake


@pytest.fixture
def client(clean):
    from fastapi.testclient import TestClient

    from loreos.main import app

    return TestClient(app, base_url="http://127.0.0.1:8000")
