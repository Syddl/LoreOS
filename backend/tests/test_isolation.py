"""Workspace isolation: workspace_session runs as loreos_app under RLS, verify_rls's assertions, the routes, and the source scans.

The role and app.workspace_id are transaction-local, so the scans pin that nothing in backend/loreos ends a
session's transaction early or switches the role back, and that only the listed files open a session that
RLS does not bind.
"""

import ast
import asyncio
import re
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from conftest import ADMIN_URL, BACKEND, TEST_DATABASE, TEST_OWNER, make_key, make_user, sql
from loreos import llm, verify_rls
from loreos.db import engine, system_session, workspace_session
from loreos.embeddings import EMBEDDING_DIM

VECTOR = "[" + ",".join(["0.5"] * EMBEDDING_DIM) + "]"
COUNTS = "select (select count(*) from loreos.documents), (select count(*) from loreos.chunks)"
INSERT_DOCUMENT = (
    "insert into loreos.documents (workspace_id, filename, kind, sha256, content) "
    "values (:w, 'a.md', 'md', :s, 'x') returning id"
)
LOREOS = BACKEND / "loreos"
# The files that may call system_session() or engine(): cross-workspace reads the spec lists. main.py only for the
# health check and the startup verify_rls. A new file here needs a spec row naming its cross-workspace read.
SYSTEM_SESSION_FILES = {
    "db.py",
    "auth.py",
    "ratelimit.py",
    "worker.py",
    "admin.py",
    "verify_rls.py",
    "smoke.py",
    "main.py",
    "routes/auth.py",
    "routes/workspaces.py",
    "evaluation/run.py",
}
# The files that may build an engine or read DATABASE_URL themselves, each with its reason. An engine built anywhere
# else opens connections the system_session scan does not see, which RLS binds only if that code switches the role.
ENGINE_FILES = {
    "db.py": "builds the one engine that workspace_session and system_session open",
    "settings.py": "defines database_url(), the one reader of DATABASE_URL",
}
BUILDS_AN_ENGINE = re.compile(r"\bcreate_(async_)?engine\b|\bdatabase_url\(")
# Whole-literal anchoring on the first keeps prose such as "commit or remove" out.
ENDS_THE_SWITCH = [
    re.compile(r"^\s*(commit|rollback|end|abort)\s*;?\s*$", re.I | re.M),
    re.compile(r"\b(re)?set\s+(local\s+|session\s+)?role\b", re.I),
    re.compile(r"set_config\(", re.I),
]


def seed(name: str):
    """A workspace with one document and one chunk, inserted as the owner; its id."""
    workspace = sql("insert into loreos.workspaces (name) values (:n) returning id", n=name)[0][0]
    document = sql(INSERT_DOCUMENT, w=workspace, s=name)[0][0]
    sql(
        "insert into loreos.chunks (workspace_id, document_id, ordinal, text, token_count, embedding) "
        "values (:w, :d, 0, 't', 1, cast(:e as vector))",
        w=workspace,
        d=document,
        e=VECTOR,
    )
    return workspace


@pytest.fixture
def ab(clean):
    return seed("a"), seed("b")


def in_session(workspace_id, query: str, **params):
    """One statement inside workspace_id's session: its rows, or the count of rows it changed."""

    async def go():
        async with workspace_session(workspace_id) as session:
            result = await session.execute(text(query), params)
            return result.all() if result.returns_rows else result.rowcount

    return asyncio.run(go())


def test_a_session_runs_as_loreos_app(ab):
    assert in_session(ab[0], "select current_user, current_setting('app.workspace_id')") == [("loreos_app", str(ab[0]))]


def test_unfiltered_counts_in_a_session_are_its_workspaces_own(ab):
    counts = in_session(ab[0], COUNTS)
    assert counts == [(1, 1)], f"unfiltered counts inside A's session are {counts}, not A's own (1, 1): RLS did not bind"


def test_a_session_cannot_insert_a_row_for_another_workspace(ab):
    a, b = ab
    with pytest.raises(DBAPIError, match="row-level security"):
        in_session(a, INSERT_DOCUMENT, w=b, s="planted")


@pytest.mark.parametrize("table", ["documents", "chunks"])
def test_a_session_cannot_update_another_workspaces_rows(ab, table):
    a, b = ab
    assert in_session(a, f"update loreos.{table} set workspace_id = :b where workspace_id = :b", b=b) == 0


def test_a_session_cannot_read_the_auth_tables(ab):
    with pytest.raises(DBAPIError, match="permission denied for table users"):
        in_session(ab[0], "select * from loreos.users")


@pytest.mark.parametrize("workspace", [None, ""])
def test_with_the_role_switched_and_no_workspace_set_nothing_is_visible(ab, workspace):
    switch = "select set_config('role', 'loreos_app', true)"
    if workspace is not None:  # a pooled connection that once held a workspace keeps an empty string, not null
        switch += ", set_config('app.workspace_id', :w, true)"

    async def go():
        async with engine().begin() as conn:
            await conn.execute(text(switch), {"w": workspace} if workspace is not None else {})
            return (await conn.execute(text(COUNTS))).all()

    assert asyncio.run(go()) == [(0, 0)]


# Through the api: the brief's test, with a key per workspace


def ids(table: str, workspace) -> set[str]:
    return {str(row[0]) for row in sql(f"select id from loreos.{table} where workspace_id = :w", w=workspace)}


def test_a_key_lists_and_cites_only_its_own_workspace(ab, fake_embed, fake_draft):
    a, b = ab
    key = make_key(a).client
    assert {d["id"] for d in key.get(f"/api/workspaces/{a}/documents").json()} == ids("documents", a)

    fake_draft.reply = llm.Draft(found=True, text="Here [1] and there [2].")  # [2] survives only if B's chunk is a hit
    body = key.post(f"/api/workspaces/{a}/ask", json={"question": "t"}).json()
    assert {c["chunk_id"] for c in body["citations"]} == ids("chunks", a)
    assert {str(hit.chunk_id) for hit in fake_draft.hits[0]} == ids("chunks", a)


def test_a_key_on_another_workspaces_documents_gets_404(ab, fake_embed, fake_draft):
    a, b = ab
    key = make_key(a).client
    [b_document] = ids("documents", b)
    assert key.get(f"/api/workspaces/{b}/documents").status_code == 404
    assert key.get(f"/api/workspaces/{b}/documents/{b_document}").status_code == 404
    assert key.get(f"/api/workspaces/{a}/documents/{b_document}").status_code == 404
    assert key.post(f"/api/workspaces/{b}/ask", json={"question": "t"}).status_code == 404
    assert fake_embed == [] and fake_draft.calls == []


def test_an_owner_cannot_delete_another_workspaces_document_through_its_own_path(ab):
    a, b = ab
    owner = make_user("a-owner@example.com", "owner", workspace_id=a)
    [b_document] = ids("documents", b)
    assert owner.client.delete(f"/api/workspaces/{a}/documents/{b_document}").status_code == 404
    assert owner.client.delete(f"/api/workspaces/{b}/documents/{b_document}").status_code == 404
    assert ids("documents", b) == {b_document}


def test_verify_rls_finds_no_problem_on_the_migrated_database(ab):
    """Also pins verify_rls.ISOLATION to what Postgres renders for migration 0002's condition."""

    async def go():
        async with system_session() as conn:
            return await verify_rls.problems(conn), await conn.scalar(text("select current_user"))

    assert asyncio.run(go()) == ([], TEST_OWNER)


def test_verify_rls_main_prints_each_problem_and_exits_1_on_any(db, monkeypatch, capsys):
    assert verify_rls.main() == 0
    assert capsys.readouterr().out.splitlines() == ["ok", "idle_in_transaction_session_timeout: 0"]

    async def broken(conn):
        return ["first", "second"]

    monkeypatch.setattr(verify_rls, "problems", broken)
    assert verify_rls.main() == 1
    assert capsys.readouterr().out.splitlines()[:2] == ["first", "second"]


# Each negative breaks one thing, as postgres in this checkout's database, inside a transaction that is rolled
# back (role attributes, grants and policies are transactional), and names the checks it must trip. A superuser has
# every right, and an owner every right on what it owns, so some trip more than one. The ab fixture's rows are what
# "isolated" sees when a session for a random workspace reads more than nothing.
NEGATIVES = [
    pytest.param(["alter role loreos_app rename to loreos_app_gone"], {"exists"}, id="missing"),
    pytest.param(["alter role loreos_app login"], {"login"}, id="login"),
    pytest.param(["alter role loreos_app bypassrls"], {"bypassrls", "isolated"}, id="bypassrls"),
    pytest.param(["alter role loreos_app superuser"], {"superuser", "owner", "rights", "isolated"}, id="superuser"),
    pytest.param(["alter table loreos.rate_limits owner to loreos_app"], {"owner", "rights"}, id="owns-a-table"),
    # testdb_owner is a member of loreos_app, and Postgres refuses a membership loop, so that grant goes first.
    # A member of the tables' owner counts as their owner, which RLS does not bind.
    pytest.param(
        [f"revoke loreos_app from {TEST_OWNER} cascade", f"grant {TEST_OWNER} to loreos_app"],
        {"owner", "rights", "isolated"},
        id="member-of-the-owner",
    ),
    pytest.param(["grant select on loreos.users to loreos_app"], {"rights"}, id="auth-table-right"),
    pytest.param(["revoke delete on loreos.chunks from loreos_app"], {"dml"}, id="dml"),
    pytest.param(["alter table loreos.chunks disable row level security"], {"rls", "isolated"}, id="rls-off"),
    pytest.param(["drop policy workspace_isolation on loreos.documents"], {"policy"}, id="no-policy"),
    # Permissive policies are OR-ed, so a second one opens every workspace's rows: Supabase's dashboard templates.
    pytest.param(
        ["create policy open on loreos.chunks for all to public using (true)"], {"other_policy", "isolated"}, id="extra-policy"
    ),
    pytest.param(
        ["alter policy workspace_isolation on loreos.documents using (true)"], {"policy", "isolated"}, id="condition-changed"
    ),
    pytest.param(
        [
            "drop policy workspace_isolation on loreos.chunks",
            f"create policy workspace_isolation on loreos.chunks for select to loreos_app using ({verify_rls.ISOLATION})",
        ],
        {"policy"},
        id="select-only",
    ),
    # Postgres judges a role switch against the session user, postgres here, so the session in "isolated" still
    # opens; on a connection that logged in without the SET option it is refused, and "isolated" trips too.
    pytest.param(
        [
            "create role loreos_rls_probe",
            "grant loreos_app to loreos_rls_probe with set false",
            "set local role loreos_rls_probe",
        ],
        {"set_option"},
        id="no-set-option",
    ),
    pytest.param(["revoke usage on schema loreos from loreos_app"], {"schema", "isolated"}, id="loreos-usage"),
    # On testdb vector sits in public, which grants USAGE to PUBLIC, and has_schema_privilege counts that grant.
    pytest.param(
        ["revoke usage on schema public from loreos_app", "revoke usage on schema public from public"],
        {"vector_schema"},
        id="vector-usage",
    ),
    # PUBLIC holds execute on a new function by default, and has_function_privilege counts that grant.
    pytest.param(
        [
            "revoke execute on function loreos.heading_text(text[]) from loreos_app",
            "revoke execute on function loreos.heading_text(text[]) from public",
        ],
        {"heading_text"},
        id="heading-text-execute",
    ),
]


class OnConnection:
    """db.engine() for a negative: begin() is a savepoint on the admin connection.

    So the workspace_session inside problems() sees the uncommitted break, and does not wait on the locks that the
    break holds, as a second connection would.
    """

    def __init__(self, conn):
        self.conn = conn

    @asynccontextmanager
    async def begin(self):
        async with self.conn.begin_nested():
            yield self.conn


async def problems_after(statements: list[str], monkeypatch) -> list[str]:
    admin = create_async_engine(f"{ADMIN_URL.replace('postgresql:', 'postgresql+asyncpg:')}/{TEST_DATABASE}", poolclass=NullPool)
    try:
        async with admin.connect() as conn:
            for statement in statements:
                await conn.execute(text(statement))
            monkeypatch.setattr("loreos.db.engine", lambda: OnConnection(conn))
            found = await verify_rls.problems(conn)
            await conn.rollback()
            return found
    finally:
        await admin.dispose()


@pytest.mark.parametrize("statements, expected", NEGATIVES)
def test_verify_rls_names_what_breaks_isolation(ab, statements, expected, monkeypatch):
    names = {message: name for name, message in verify_rls.CHECKS.items()}
    found = asyncio.run(problems_after(statements, monkeypatch))
    assert sorted(names[message] for message in found) == sorted(expected)


def test_the_negatives_cover_every_check():
    covered = set().union(*(case.values[1] for case in NEGATIVES))
    assert covered == set(verify_rls.CHECKS)


def sources() -> dict[str, str]:
    return {path.relative_to(LOREOS).as_posix(): path.read_text(encoding="utf-8") for path in sorted(LOREOS.rglob("*.py"))}


def test_only_the_listed_files_open_a_session_rls_does_not_bind():
    callers = {name for name, source in sources().items() if "system_session(" in source or "engine()" in source}
    assert callers - SYSTEM_SESSION_FILES == set()


def test_only_the_listed_files_build_an_engine_or_read_database_url():
    callers = {name for name, source in sources().items() if BUILDS_AN_ENGINE.search(source)}
    assert callers - ENGINE_FILES.keys() == set()


def test_nothing_commits_or_rolls_back_a_transaction():
    calls = [
        f"{name}:{number}: {line.strip()}"
        for name, source in sources().items()
        for number, line in enumerate(source.splitlines(), 1)
        if ".commit(" in line or ".rollback(" in line
    ]
    assert calls == []


def test_no_sql_text_outside_db_ends_the_transaction_or_switches_the_role():
    found = [
        f"{name}:{node.lineno}: {node.value!r}"
        for name, source in sources().items()
        if name != "db.py"
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        if any(pattern.search(node.value) for pattern in ENDS_THE_SWITCH)
    ]
    assert found == []
