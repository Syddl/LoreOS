"""The real slice end to end: npm run paid:smoke (python -m loreos.smoke). Costs a few cents.

Preflight before any paid call: DATABASE_URL connects, the schema is at the migration head, and
OPENAI_API_KEY is set and accepted (listing models is free). Then, in a throwaway workspace: one
Markdown upload, one answerable and one unanswerable question, printed with their citations. The
workspace is deleted at the end, pass or fail. Exit 0 only when the answerable question is cited
and the unanswerable one is refused.
"""

import asyncio
import os
import sys
import uuid
from pathlib import Path

import openai
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from loreos import answering, ingest, llm, settings
from loreos.db import engine, workspace_session

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"
FIXTURE = """# Release process

## Schedule

Production deploys happen every Tuesday at 14:00 UTC. A deploy outside that window needs approval
from the on-call engineering manager.

## Rollbacks

Any engineer may roll back a deploy within its first hour. After an hour, a rollback needs an
incident ticket.
"""
QUESTIONS = [("When do production deploys happen?", True), ("What is the office Wi-Fi password?", False)]


async def preflight() -> None:
    settings.openai_api_key()  # raises with the fix when unset
    head = ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_current_head()
    try:
        async with engine().connect() as conn:
            current = await conn.scalar(text("select version_num from loreos.alembic_version"))
    except Exception as e:
        raise SystemExit(f"preflight: cannot read the schema version ({type(e).__name__}: {e}); check DATABASE_URL, then run npm run db:migrate") from e
    if current != head:
        raise SystemExit(f"preflight: the database is at migration {current} and the code at {head}; run npm run db:migrate")
    try:
        async with llm.client() as client:
            await client.models.list()
    except (openai.AuthenticationError, openai.PermissionDeniedError) as e:
        raise SystemExit(f"preflight: OPENAI_API_KEY was rejected ({e.status_code}); replace it in .env") from e
    except openai.APIConnectionError as e:
        raise SystemExit("preflight: cannot reach the OpenAI API; check the network and OPENAI_BASE_URL") from e
    except openai.APIStatusError as e:  # a compatible server without /models: ambiguous, so go on
        print(f"preflight: listing models returned {e.status_code}; the key is unverified, continuing")
    print(f"preflight: ok (migration {head}, models {settings.embedding_model()} and {settings.answer_model()})")


async def main() -> int:
    await preflight()
    async with engine().begin() as conn:
        workspace_id: uuid.UUID = await conn.scalar(text("insert into loreos.workspaces (name) values ('smoke') returning id"))
    try:
        async with workspace_session(workspace_id) as session:
            document = await ingest.ingest(session, workspace_id, "release-process.md", FIXTURE.encode())
        print(f"upload: {document.status}, {document.chunk_count} chunks" + (f", error: {document.error}" if document.error else ""))
        if document.status != "processed":
            return 1
        passed = True
        for question, answerable in QUESTIONS:
            async with workspace_session(workspace_id) as session:
                result = await answering.answer(session, workspace_id, question)
            print(f"\nQ: {question}\nA: {result.text}\n   found={result.found} reason={result.reason}")
            for c in result.citations:
                print(f"   [{c.n}] {c.filename} > {' > '.join(c.heading_path)}: {c.text[:80]!r}")
            passed &= result.found == answerable and (bool(result.citations) or not answerable)
        print(f"\nsmoke: {'PASS' if passed else 'FAIL'}")
        return 0 if passed else 1
    finally:
        async with engine().begin() as conn:
            await conn.execute(text("delete from loreos.workspaces where id = :w"), {"w": workspace_id})
        print("deleted the smoke workspace")


USAGE = """usage: python -m loreos.smoke [--dry-run]
  --dry-run  run only the free preflight (database, migration, key); no paid call"""


def cli(argv: list[str]) -> int:
    """--dry-run and --help must stay free, since an operator approves them as the cheap preflight; any other argument is refused.

    `npm run paid:smoke --dry-run` (no `--`) passes no argument: npm keeps the flag, sets
    npm_config_dry_run and runs the script anyway, so that counts as --dry-run too.
    """
    if argv in (["-h"], ["--help"]):
        print(USAGE)
        return 0
    if argv == ["--dry-run"] or (not argv and os.environ.get("npm_config_dry_run", "").lower() == "true"):
        asyncio.run(preflight())
        return 0
    if argv:
        print(USAGE, file=sys.stderr)
        return 2
    return asyncio.run(main())


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    sys.exit(cli(sys.argv[1:]))
