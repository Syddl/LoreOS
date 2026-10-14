"""`npm run paid:demo-load -- --workspace-id <id> [--dry-run]`: the evaluation corpus into a workspace you own.

The free preflight runs first, and each failure stops it with its fix:
- the database, the migration head, the grants and the key (smoke's preflight, without the reranker);
- the embedding model is in the API's model list;
- the fetched corpus matches eval/corpus.json;
- the workspace exists, is not an evaluation workspace, and has an owner.

Then each corpus file goes through ingest.ingest into that workspace, one at a time. A file already processed there
is found by its content and not embedded again, so a second run spends nothing. The guard asks before every form,
the dry run included.
"""

import argparse
import asyncio
import os
import sys
import uuid

from sqlalchemy import text

from loreos import chunking, ingest, parsing, settings, smoke
from loreos.db import system_session, workspace_session
from loreos.evaluation import dataset, fetch, preflight, run
from loreos.workspaces import EVAL_PREFIX

FORM = "npm run paid:demo-load -- --workspace-id <id>"
# One cross-workspace read, as the connecting role: loreos_app has no grant on workspaces or memberships (spec P5).
WORKSPACE = text(
    "select w.name, exists (select 1 from loreos.memberships m where m.workspace_id = w.id and m.role = 'owner') "
    "from loreos.workspaces w where w.id = :w"
)
PROCESSED = text("select sha256 from loreos.documents where workspace_id = :w and status = 'processed'")


def _swallowed() -> str | None:
    """npm takes --workspace-id given before `--` as its own config and drops it; the corrected form, if so."""
    for key in os.environ:
        if key.lower().startswith("npm_config_") and "workspace-id".startswith(key[len("npm_config_") :].lower().replace("_", "-") or "-"):
            return f"npm took --workspace-id as its own option and dropped it; put it after the separator: {FORM}"
    return None


async def check(workspace_id: uuid.UUID) -> dict[str, bytes]:
    """The free preflight; the corpus files the workspace does not hold yet, by name, with a printed plan."""
    try:
        await smoke.preflight(reranker=False)
    except RuntimeError as e:  # settings raises a missing key or DATABASE_URL as RuntimeError, with its fix
        raise SystemExit(f"preflight: {e}") from e
    for note in await preflight.check_models({"EMBEDDING_MODEL": settings.embedding_model()}):
        print(f"preflight: {note}")
    try:
        manifest = dataset.read_manifest(dataset.MANIFEST)
    except dataset.DatasetError as e:
        raise SystemExit(f"preflight: {e}") from e
    if problems := fetch.corpus_problems(manifest, dataset.CORPUS_DIR):
        listed = "".join(f"\n  {problem}" for problem in problems)
        raise SystemExit(f"preflight: the corpus in {dataset.CORPUS_DIR} is not the one {dataset.MANIFEST.name} pins; "
                         f"run npm run eval:fetch, then again:{listed}")
    async with system_session() as conn:
        row = (await conn.execute(WORKSPACE, {"w": workspace_id})).first()
    if row is None:
        raise SystemExit(f"preflight: no workspace has the id {workspace_id}; copy it from the address bar in the UI (/w/<id>)")
    name, owned = row
    if name.startswith(EVAL_PREFIX):
        raise SystemExit(f"preflight: {name} is an evaluation workspace, which paid:eval keys by its inputs; "
                         "create a workspace in the UI and load that one")
    if not owned:
        raise SystemExit(f"preflight: workspace {name} has no owner, so no one could see the documents; "
                         "create a workspace in the UI and load that one")
    corpus = run.load_corpus(manifest)
    async with workspace_session(workspace_id) as session:
        processed = set(await session.scalars(PROCESSED, {"w": workspace_id}))
    todo = {file: data for file, data in corpus.items() if ingest.sha256(data) not in processed}
    tokens = sum(chunking.count_tokens(ingest.embedding_input(c)) for file, data in todo.items() for c in chunking.chunk(parsing.parse(file, data)))
    print(f"preflight: ok; workspace {name} holds {len(corpus) - len(todo)} of the {len(corpus)} corpus files")
    print(f"plan: {len(todo)} files to embed, {tokens} tokens, with {settings.embedding_model()}")
    return todo


async def load(workspace_id: uuid.UUID, todo: dict[str, bytes]) -> int:
    """Each file through ingest, one transaction each, printed as it goes; the number not processed.

    ponytail: not evaluation.run._ingest, which finds its workspace by name (creating one without members) and stops
    at the first failure; a demo load reports every file and goes on.
    """
    failed = 0
    for i, (file, data) in enumerate(todo.items(), 1):
        async with workspace_session(workspace_id) as session:
            document = await ingest.ingest(session, workspace_id, file, data)
        failed += document.status != "processed"
        print(f"[{i}/{len(todo)}] {file}: {document.status}" + (f" ({document.error})" if document.error else ""), flush=True)
    return failed


def cli(argv: list[str]) -> int:
    """--help and --dry-run spend nothing; a bad argument exits 2 before the preflight."""
    if refusal := _swallowed():
        print(refusal, file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(prog="npm run paid:demo-load --", description=__doc__.splitlines()[0])
    parser.add_argument("--workspace-id", type=uuid.UUID, required=True, metavar="ID",
                        help="the workspace's id, from the address bar in the UI (/w/<id>); not npm's own --workspace")
    parser.add_argument("--dry-run", action="store_true", help="run only the free preflight and print the plan; no paid call")
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:  # argparse exits 0 after --help and 2 on a bad argument
        return e.code
    dry_run = args.dry_run or os.environ.get("npm_config_dry_run", "").lower() == "true"
    todo = asyncio.run(check(args.workspace_id))
    if dry_run:
        print("dry run: preflight only, no paid call made")
        return 0
    failed = asyncio.run(load(args.workspace_id, todo))
    if failed:
        print(f"{failed} files were not processed; their error is above. Fix or remove them, then run again", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    sys.exit(cli(sys.argv[1:]))
