"""Ask under /api/workspaces/{id}: refusals, citations, every Answer field, the Origin rule and who may ask.

P1's cases on its unscoped ask route and test_local_only.py's ask case moved here.
"""

from dataclasses import dataclass

import pytest

from conftest import W, drain
from loreos import answering, llm
from loreos.answering import REFUSAL

ASK = f"{W}/ask"
P1_FIELDS = ("found", "answer", "reason", "citations")


def upload(client, name, data):
    """Upload, run the worker, and return the processed document."""
    response = client.post(f"{W}/documents", files={"file": (name, data)})
    assert response.status_code == 202
    assert drain() == ["processed"]
    return client.get(f"{W}/documents/{response.json()['id']}").json()


@pytest.mark.parametrize("payload", [{"question": "   "}, {"question": ""}, {}])
def test_blank_question_is_422(owner, payload):
    assert owner.client.post(ASK, json=payload).status_code == 422


def test_empty_workspace_refuses_without_spending(owner, fake_embed, fake_draft):
    body = owner.client.post(ASK, json={"question": "When do we ship?"}).json()
    # Only P1's fields: every other Answer field passes through too (see the next test).
    assert {k: body[k] for k in P1_FIELDS} == {"found": False, "answer": REFUSAL, "reason": "no_chunks", "citations": []}
    assert fake_embed == [] and fake_draft.calls == []


@dataclass
class AnswerWithMode:
    """P1's four Answer fields plus one P3 adds: only an extra field tells a field-by-field mapping from asdict."""

    found: bool
    text: str
    citations: list
    reason: str | None
    retrieval_mode: str


def test_every_answer_field_reaches_the_json(owner, monkeypatch):
    async def answer(session, workspace_id, question):
        return AnswerWithMode(False, REFUSAL, [], "no_chunks", "hybrid")

    monkeypatch.setattr(answering, "answer", answer)
    body = owner.client.post(ASK, json={"question": "When do we ship?"}).json()
    assert body == {"found": False, "answer": REFUSAL, "citations": [], "reason": "no_chunks", "retrieval_mode": "hybrid"}


def test_answer_cites_the_passage(owner, fake_embed, fake_draft):
    document = upload(owner.client, "releases.md", b"# Releases\n\nWe ship on Tuesdays.\n")
    fake_draft.reply = llm.Draft(found=True, text="On Tuesdays [1].")
    body = owner.client.post(ASK, json={"question": "  When do we ship?  "}).json()
    assert (body["found"], body["answer"], body["reason"]) == (True, "On Tuesdays [1].", None)
    [citation] = body["citations"]
    assert citation["n"] == 1 and citation["document_id"] == document["id"]
    assert (citation["filename"], citation["heading_path"], citation["page"], citation["text"]) == (
        "releases.md",
        ["Releases"],
        None,
        "We ship on Tuesdays.",
    )
    assert fake_draft.calls == ["When do we ship?"]


def test_the_answer_model_sees_the_five_closest_chunks(owner, fake_embed, fake_draft):
    sections = "".join(f"# Team {i}\n\nTeam {i} ships on day {i}.\n\n" for i in range(7))
    assert upload(owner.client, "teams.md", sections.encode())["chunk_count"] == 7
    owner.client.post(ASK, json={"question": "Which day does team 3 ship?"})
    [hits] = fake_draft.hits
    assert len(hits) == 5
    assert hits[0].text == "Team 3 ships on day 3."


def test_a_cross_origin_ask_is_refused_before_anything_is_bought(owner, fake_embed, fake_draft):
    upload(owner.client, "a.md", b"# A\n\nSome text.\n")
    fake_embed.clear()
    for origin in ("https://evil.example", "null", "http://localhost:3000"):
        assert owner.client.post(ASK, json={"question": "x"}, headers={"origin": origin}).status_code == 403
    assert fake_embed == [] and fake_draft.calls == []


# Roles


def test_a_member_asks(member, fake_embed, fake_draft):
    document = upload(member.client, "releases.md", b"# Releases\n\nWe ship on Tuesdays.\n")
    body = member.client.post(ASK, json={"question": "When do we ship?"}).json()
    assert body["found"] and [c["document_id"] for c in body["citations"]] == [document["id"]]


def test_a_key_lists_and_asks_in_its_own_workspace_and_cannot_delete(owner, key_client, fake_embed, fake_draft):
    document = upload(owner.client, "releases.md", b"# Releases\n\nWe ship on Tuesdays.\n")
    assert [d["id"] for d in key_client.get(f"{W}/documents").json()] == [document["id"]]
    body = key_client.post(ASK, json={"question": "When do we ship?"}).json()
    assert body["found"] and [c["document_id"] for c in body["citations"]] == [document["id"]]
    assert key_client.delete(f"{W}/documents/{document['id']}").status_code == 403


def test_no_credentials_get_401(client, fake_embed, fake_draft):
    assert client.post(ASK, json={"question": "When do we ship?"}).status_code == 401
    assert client.get(f"{W}/documents").status_code == 401
    assert fake_embed == [] and fake_draft.calls == []
