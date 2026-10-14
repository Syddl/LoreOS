import asyncio
import threading

import pytest

from conftest import sql, word_vector
from loreos import rerank, retrieval
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


def find(workspace_id, query, k, mode=None):
    async def go():
        async with workspace_session(workspace_id) as session:
            if mode is None:  # P1's call, with no mode argument
                return await search(session, workspace_id, query, k)
            return await search(session, workspace_id, query, k, mode)

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


# P3's modes. Under the fake embedding (hashed word counts, stop words included) the question below sits closest to
# TEXTS[3], then TEXTS[1], and the SKU chunk only fourth; keyword search, which drops stop words, matches only TEXTS[3]
# (end, month) and the SKU chunk (sku, -4471). So vector top 2 misses the SKU chunk, and RRF brings it in.
SKU = "Replacement brackets ship as SKU-4471, quoting its purchase number printed on each shipping label."
QUESTION = "Are they at the end of the month for SKU-4471?"


@pytest.fixture
def handbook(clean):
    store(DEFAULT_WORKSPACE_ID, "handbook.txt", [*TEXTS, SKU])


def test_hybrid_brings_in_a_chunk_the_vector_order_ranks_low(handbook, fake_embed):
    assert SKU not in [h.text for h in find(DEFAULT_WORKSPACE_ID, QUESTION, k=2, mode="vector")]
    hybrid = find(DEFAULT_WORKSPACE_ID, QUESTION, k=2, mode="hybrid")
    assert [h.text for h in hybrid] == [TEXTS[3], SKU]
    assert hybrid[0].score > hybrid[1].score > 0  # RRF scores, not cosine similarity
    assert fake_embed == [QUESTION, QUESTION]  # one embedding per search, whatever the mode


def test_hybrid_rerank_rescores_the_fused_candidates_and_keeps_k(handbook, fake_embed, monkeypatch):
    fused = [h.text for h in find(DEFAULT_WORKSPACE_ID, QUESTION, k=10, mode="hybrid")]
    seen = []

    def reverse(query, hits):
        seen.append((query, [h.text for h in hits]))
        return list(reversed(hits))

    monkeypatch.setattr(rerank, "rerank", reverse)
    monkeypatch.setattr(retrieval, "RERANK_DEPTH", 3)
    reranked = find(DEFAULT_WORKSPACE_ID, QUESTION, k=2, mode="hybrid_rerank")
    assert seen == [(QUESTION, fused[:3])]
    assert [h.text for h in reranked] == [fused[2], fused[1]]


@pytest.mark.parametrize("mode", retrieval.MODES)
def test_no_mode_buys_an_embedding_for_a_workspace_without_chunks(clean, fake_embed, monkeypatch, mode):
    monkeypatch.setattr(rerank, "rerank", lambda query, hits: pytest.fail("reranked an empty workspace"))
    assert find(DEFAULT_WORKSPACE_ID, "anything", k=5, mode=mode) == []
    assert fake_embed == []


def test_an_unknown_mode_is_refused_before_anything_is_bought(handbook, fake_embed):
    with pytest.raises(ValueError, match="'bogus' is not one of vector, hybrid, hybrid_rerank"):
        find(DEFAULT_WORKSPACE_ID, QUESTION, k=2, mode="bogus")
    assert fake_embed == []


@pytest.mark.parametrize("mode", ["hybrid", "hybrid_rerank"])
def test_keyword_search_runs_before_the_embedding_is_bought(handbook, fake_embed, monkeypatch, mode):
    """It is free and the first place the raw question reaches Postgres, so a failure there must come before the spend."""

    async def refused(session, workspace_id, query, n):
        raise RuntimeError("keyword search refused the question")

    monkeypatch.setattr(retrieval, "keyword_search", refused)
    with pytest.raises(RuntimeError, match="keyword search refused"):
        find(DEFAULT_WORKSPACE_ID, QUESTION, k=2, mode=mode)
    assert fake_embed == []


def test_the_rerank_runs_off_the_event_loop_thread(handbook, fake_embed, monkeypatch):
    """Seconds of CPU on the loop's thread would stall every other request the api is serving."""
    threads = []

    def record(query, hits):
        threads.append((threading.get_ident(), threading.current_thread().name))
        return hits

    monkeypatch.setattr(rerank, "rerank", record)
    find(DEFAULT_WORKSPACE_ID, QUESTION, k=2, mode="hybrid_rerank")  # asyncio.run's loop runs on this thread
    [(ident, name)] = threads
    assert ident != threading.get_ident()
    # Its own pool, not asyncio's default executor, which argon2 uses for logins: reranks queue among themselves.
    assert name.startswith("rerank")


def test_an_exact_distance_tie_orders_by_chunk_id(clean, fake_embed):
    """The vector order feeds RRF, so a tie must not depend on the scan order."""
    store(DEFAULT_WORKSPACE_ID, "same.txt", ["Deploys happen on Tuesdays."] * 6)
    hits = find(DEFAULT_WORKSPACE_ID, "When do deploys happen?", k=6, mode="vector")
    assert len({h.score for h in hits}) == 1
    assert [h.chunk_id for h in hits] == sorted(h.chunk_id for h in hits)
