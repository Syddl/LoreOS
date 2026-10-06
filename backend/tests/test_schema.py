import pytest
from sqlalchemy.exc import IntegrityError

from conftest import sql
from loreos.embeddings import EMBEDDING_DIM
from loreos.workspaces import DEFAULT_WORKSPACE_ID

VECTOR = "[" + ",".join(["0.5"] * EMBEDDING_DIM) + "]"
INSERT_CHUNK = (
    "insert into loreos.chunks (workspace_id, document_id, ordinal, text, token_count, embedding) "
    "values (:w, :d, 0, 't', 1, cast(:e as vector))"
)


def test_default_workspace_exists(db):
    assert sql("select name from loreos.workspaces where id = :id", id=DEFAULT_WORKSPACE_ID) == [("Default",)]


def test_chunk_workspace_must_equal_its_documents(clean):
    other = sql("insert into loreos.workspaces (name) values ('other') returning id")[0][0]
    doc = sql(
        "insert into loreos.documents (workspace_id, filename, kind, sha256, content) "
        "values (:w, 'a.md', 'md', 'x', :c) returning id",
        w=DEFAULT_WORKSPACE_ID,
        c=b"x",
    )[0][0]
    sql(INSERT_CHUNK, w=DEFAULT_WORKSPACE_ID, d=doc, e=VECTOR)
    with pytest.raises(IntegrityError, match="foreign key"):
        sql(INSERT_CHUNK.replace("0, 't'", "1, 't'"), w=other, d=doc, e=VECTOR)
