import asyncio

from conftest import sql, word_vector
from loreos.db import workspace_session
from loreos.retrieval import search, vector_literal
from loreos.workspaces import DEFAULT_WORKSPACE_ID

TEXTS = [
    "Deploys happen on Tuesdays after the release review.",
    "The cafeteria opens at noon on weekdays.",
    "Incident reviews are held every Friday morning.",
    "Expense reports are due at the end of the month.",
]


def store(workspace_id, name, texts):
    doc = sql(
        "insert into loreos.documents (workspace_id, filename, kind, sha256, content, status) "
        "values (:w, :f, 'txt', :f, :c, 'processed') returning id",
        w=workspace_id,
        f=name,
        c=b"x",
    )[0][0]
    for ordinal, t in enumerate(texts):
        sql(
            "insert into loreos.chunks (workspace_id, document_id, ordinal, text, token_count, embedding) "
            "values (:w, :d, :o, :t, 1, cast(:e as vector))",
            w=workspace_id,
            d=doc,
            o=ordinal,
            t=t,
            e=vector_literal(word_vector(t)),
        )


def find(workspace_id, query, k):
    async def go():
        async with workspace_session(workspace_id) as session:
            return await search(session, workspace_id, query, k)

    return asyncio.run(go())


def test_closest_chunk_ranks_first_within_k_and_the_workspace(clean, fake_embed):
    other = sql("insert into loreos.workspaces (name) values ('other') returning id")[0][0]
    store(DEFAULT_WORKSPACE_ID, "handbook.txt", TEXTS)
    store(other, "secret.txt", ["When do deploys happen? Deploys happen on Tuesdays, says the other workspace."])
    hits = find(DEFAULT_WORKSPACE_ID, "When do deploys happen?", k=3)
    assert len(hits) == 3
    assert hits[0].text == TEXTS[0]
    assert hits[0].filename == "handbook.txt"
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)
    assert hits[0].score > hits[1].score
    assert all(h.filename != "secret.txt" for h in hits)
    assert fake_embed == ["When do deploys happen?"]


def test_a_workspace_without_chunks_buys_no_embedding(clean, fake_embed):
    assert find(DEFAULT_WORKSPACE_ID, "anything", k=5) == []
    assert fake_embed == []
