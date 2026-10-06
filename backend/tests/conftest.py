"""Test environment: the testdb container, a fake OpenAI key and an unroutable OpenAI base URL.

These assignments run before any loreos module reads the environment, and they win over the
repo's .env, so no check can reach Supabase or OpenAI.
"""

import asyncio
import os
import re
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest

TEST_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:54329/loreos_test"  # docker-compose.yml testdb
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["OPENAI_API_KEY"] = "sk-test-not-a-real-key"
# 0.0.0.0 fails at once on Windows (address not valid) and on Linux (refused); a closed 127.0.0.1
# port takes about two seconds on Windows, which retries the refused connection.
os.environ["OPENAI_BASE_URL"] = "http://0.0.0.0:9/v1"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402

from loreos.db import engine  # noqa: E402
from loreos.embeddings import EMBEDDING_DIM  # noqa: E402
from loreos.workspaces import DEFAULT_WORKSPACE_ID  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
START_TESTDB = "docker compose --profile test up -d testdb"


def sql(query: str, **params):
    """Run one statement against the test database in its own transaction; rows when it returns any."""

    async def go():
        async with engine().begin() as conn:
            result = await conn.execute(text(query), params)
            return result.all() if result.returns_rows else None

    return asyncio.run(go())


@pytest.fixture(scope="session")
def db():
    """The test database, migrated to head. Stops the run, never skips, when testdb is unreachable."""
    try:
        asyncio.run(asyncio.wait_for(_ping(), 10))
    except Exception as e:  # any failure to reach it means the container is not up
        pytest.exit(f"testdb is not reachable at 127.0.0.1:54329 ({type(e).__name__}); start it with: {START_TESTDB}", returncode=1)
    command.upgrade(Config(str(BACKEND / "alembic.ini")), "head")


async def _ping():
    async with engine().connect() as conn:
        await conn.execute(text("select 1"))


@pytest.fixture
def clean(db):
    """Empty documents and chunks; keep only the default workspace."""
    sql("delete from loreos.documents")
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
    """Replace llm.draft_answer; set .reply to the Draft it returns; .calls records each question."""
    from loreos import llm

    fake = SimpleNamespace(reply=llm.Draft(found=True, text="From the documents [1]."), calls=[])

    async def draft_answer(question, hits):
        fake.calls.append(question)
        return fake.reply

    monkeypatch.setattr(llm, "draft_answer", draft_answer)
    return fake


@pytest.fixture
def client(clean):
    from fastapi.testclient import TestClient

    from loreos.main import app

    return TestClient(app, base_url="http://127.0.0.1:8000")
