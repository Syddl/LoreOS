"""Keyword search: retrieval.keyword_search against chunks.tsv (migration 0003), under workspace_session as loreos_app.

Proves: any lexeme of the question matches (ORed, not ANDed), so a long question still finds the chunk holding one
rare term; a question of stop words returns nothing; punctuation in a question is never parsed as query syntax; the
heading path is searchable; the chunk matching more lexemes ranks first; another workspace's chunk is never returned.
Does NOT exercise: ranking quality on a real corpus (the evaluation's job), or non-English stemming.
"""

import asyncio

import pytest

from conftest import sql, word_vector
from loreos.db import workspace_session
from loreos.retrieval import keyword_search, vector_literal
from loreos.workspaces import DEFAULT_WORKSPACE_ID

CHUNKS = [
    (["Catalog", "Hardware"], "The SKU-4471 bracket ships in boxes of ten."),
    (["Release process"], "Deploys happen on Tuesdays after the release review."),
    (["Release process"], "A rollback after the first hour needs an incident ticket and a deploy review."),
    (["Office"], "The cafeteria opens at noon on weekdays."),
]


def store(workspace_id, name, chunks):
    doc = sql(
        "insert into loreos.documents (workspace_id, filename, kind, sha256, content, status) "
        "values (:w, :f, 'txt', :f, :c, 'processed') returning id",
        w=workspace_id,
        f=name,
        c=b"x",
    )[0][0]
    for ordinal, (heading_path, t) in enumerate(chunks):
        sql(
            "insert into loreos.chunks (workspace_id, document_id, ordinal, text, heading_path, token_count, embedding) "
            "values (:w, :d, :o, :t, :h, 1, cast(:e as vector))",
            w=workspace_id,
            d=doc,
            o=ordinal,
            t=t,
            h=heading_path,
            e=vector_literal(word_vector(t)),
        )


def find(workspace_id, query, n=10):
    async def go():
        async with workspace_session(workspace_id) as session:
            return await keyword_search(session, workspace_id, query, n)

    return asyncio.run(go())


@pytest.fixture
def handbook(clean):
    store(DEFAULT_WORKSPACE_ID, "handbook.txt", CHUNKS)


def test_one_rare_term_in_a_long_question_finds_its_chunk(handbook):
    hits = find(DEFAULT_WORKSPACE_ID, "How many of the SKU-4471 brackets come in a single shipping carton?")
    assert hits[0].text == CHUNKS[0][1]
    assert hits[0].filename == "handbook.txt"


def test_a_question_of_stop_words_only_returns_nothing(handbook):
    assert find(DEFAULT_WORKSPACE_ID, "what is it and how was it for them?") == []


@pytest.mark.parametrize(
    "question",
    ["tuesdays & mondays", "tuesdays | mondays", "!tuesdays", "tuesdays:*", "tuesday's", "(tuesdays) <-> mondays", "tuesdays\\"],
)
def test_punctuation_is_never_query_syntax(handbook, question):
    """Only CHUNKS[1] holds 'tuesday'; parsed as syntax, & would need 'monday' too and ! would exclude it."""
    assert [h.text for h in find(DEFAULT_WORKSPACE_ID, question)] == [CHUNKS[1][1]]


def test_the_heading_path_is_searchable(handbook):
    hits = find(DEFAULT_WORKSPACE_ID, "Which hardware is in the catalog?")
    assert [h.text for h in hits] == [CHUNKS[0][1]]


def test_more_matched_lexemes_rank_first_and_n_caps_the_list(handbook):
    hits = find(DEFAULT_WORKSPACE_ID, "When do deploys happen after the release review?")
    assert hits[0].text == CHUNKS[1][1]
    assert CHUNKS[2][1] in [h.text for h in hits]
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)
    assert len(find(DEFAULT_WORKSPACE_ID, "When do deploys happen after the release review?", n=1)) == 1


def test_another_workspace_chunk_is_never_returned(handbook):
    other = sql("insert into loreos.workspaces (name) values ('other') returning id")[0][0]
    store(other, "secret.txt", [(["Catalog"], "The SKU-4471 bracket price is secret.")])
    assert all(h.filename == "handbook.txt" for h in find(DEFAULT_WORKSPACE_ID, "SKU-4471 bracket price"))
    assert [h.filename for h in find(other, "SKU-4471 bracket price")] == ["secret.txt"]
