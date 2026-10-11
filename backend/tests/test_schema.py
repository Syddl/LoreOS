import os
import re
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

from conftest import BACKEND, PINNED_ENV, TEST_OWNER, database_for, sql
from loreos import settings
from loreos.embeddings import EMBEDDING_DIM
from loreos.workspaces import DEFAULT_WORKSPACE_ID

VECTOR = "[" + ",".join(["0.5"] * EMBEDDING_DIM) + "]"
INSERT_CHUNK = (
    "insert into loreos.chunks (workspace_id, document_id, ordinal, text, token_count, embedding) "
    "values (:w, :d, 0, 't', 1, cast(:e as vector))"
)
INSERT_DOCUMENT = (
    "insert into loreos.documents (workspace_id, filename, kind, sha256, content) "
    "values (:w, :f, :k, :s, :c) returning id"
)


def test_default_workspace_exists(db):
    assert sql("select name from loreos.workspaces where id = :id", id=DEFAULT_WORKSPACE_ID) == [("Default",)]


def test_chunk_workspace_must_equal_its_documents(clean):
    other = sql("insert into loreos.workspaces (name) values ('other') returning id")[0][0]
    doc = sql(INSERT_DOCUMENT, w=DEFAULT_WORKSPACE_ID, f="a.md", k="md", s="x", c=b"x")[0][0]
    sql(INSERT_CHUNK, w=DEFAULT_WORKSPACE_ID, d=doc, e=VECTOR)
    with pytest.raises(IntegrityError, match="foreign key"):
        sql(INSERT_CHUNK.replace("0, 't'", "1, 't'"), w=other, d=doc, e=VECTOR)


@pytest.mark.parametrize("kind", ["docx", "url"])
def test_documents_accept_the_p4_kinds(clean, kind):
    sql(INSERT_DOCUMENT, w=DEFAULT_WORKSPACE_ID, f=f"a.{kind}", k=kind, s=kind, c=b"x")


def test_a_url_document_has_no_content_until_fetched(clean):
    sql(
        "insert into loreos.documents (workspace_id, filename, kind, sha256, source_url) "
        "values (:w, 'https://example.com/', 'url', 'h', 'https://example.com/')",
        w=DEFAULT_WORKSPACE_ID,
    )
    assert sql("select content, next_attempt_at, locked_until from loreos.documents") == [(None, None, None)]


def test_an_unknown_kind_is_refused(clean):
    with pytest.raises(IntegrityError, match="documents_kind_check"):
        sql(INSERT_DOCUMENT, w=DEFAULT_WORKSPACE_ID, f="a.pptx", k="pptx", s="p", c=b"x")


def test_emails_are_stored_lowercased(clean):
    with pytest.raises(IntegrityError, match="check"):
        sql("insert into loreos.users (email, password_hash) values ('A@Example.com', 'h')")


def test_a_membership_role_is_owner_or_member(clean):
    user = sql("insert into loreos.users (email, password_hash) values ('a@example.com', 'h') returning id")[0][0]
    sql("insert into loreos.memberships (user_id, workspace_id, role) values (:u, :w, 'owner')", u=user, w=DEFAULT_WORKSPACE_ID)
    with pytest.raises(IntegrityError, match="check"):
        sql("update loreos.memberships set role = 'admin'")


def test_loreos_app_cannot_log_in_or_bypass_rls(db):
    assert sql("select rolcanlogin, rolbypassrls, rolsuper from pg_roles where rolname = 'loreos_app'") == [(False, False, False)]


def test_rls_is_on_for_documents_and_chunks(db):
    rows = sql(
        "select c.relname, c.relrowsecurity, (select count(*) from pg_policy p where p.polrelid = c.oid "
        "and p.polname = 'workspace_isolation') from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname = 'loreos' and c.relname in ('documents', 'chunks') order by 1"
    )
    assert rows == [("chunks", True, 1), ("documents", True, 1)]


def test_the_tests_run_as_a_role_that_is_not_a_superuser(db):
    assert sql("select current_user, rolsuper from pg_roles where rolname = current_user") == [(TEST_OWNER, False)]


def test_there_is_one_alembic_head():
    heads = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini"))).get_heads()
    assert len(heads) == 1, heads


def test_the_test_database_is_named_after_the_checkout():
    assert database_for("p4-platform-shell") == "loreos_test_p4_platform_shell"
    assert database_for("loreos") == "loreos_test_loreos"
    long = database_for("x" * 100)
    assert len(long.encode()) == 63 and long.startswith("loreos_test_x")


def test_every_key_settings_reads_is_pinned_for_the_tests():
    read = set(re.findall(r'_env\("([A-Z_]+)"\)', Path(settings.__file__).read_text(encoding="utf-8")))
    assert read == set(PINNED_ENV)
    assert {key: os.environ[key] for key in read} == PINNED_ENV
