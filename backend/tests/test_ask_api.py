import pytest

from loreos import llm
from loreos.answering import REFUSAL


@pytest.mark.parametrize("payload", [{"question": "   "}, {"question": ""}, {}])
def test_blank_question_is_422(client, payload):
    assert client.post("/api/ask", json=payload).status_code == 422


def test_empty_workspace_refuses_without_spending(client, fake_embed, fake_draft):
    body = client.post("/api/ask", json={"question": "When do we ship?"}).json()
    assert body == {"found": False, "answer": REFUSAL, "reason": "no_chunks", "citations": []}
    assert fake_embed == [] and fake_draft.calls == []


def test_answer_cites_the_passage(client, fake_embed, fake_draft):
    upload = client.post("/api/documents", files={"file": ("releases.md", b"# Releases\n\nWe ship on Tuesdays.\n")}).json()
    fake_draft.reply = llm.Draft(found=True, text="On Tuesdays [1].")
    body = client.post("/api/ask", json={"question": "  When do we ship?  "}).json()
    assert (body["found"], body["answer"], body["reason"]) == (True, "On Tuesdays [1].", None)
    [citation] = body["citations"]
    assert citation["n"] == 1 and citation["document_id"] == upload["id"]
    assert (citation["filename"], citation["heading_path"], citation["page"], citation["text"]) == (
        "releases.md",
        ["Releases"],
        None,
        "We ship on Tuesdays.",
    )
    assert fake_draft.calls == ["When do we ship?"]


def test_the_answer_model_sees_the_five_closest_chunks(client, fake_embed, fake_draft):
    sections = "".join(f"# Team {i}\n\nTeam {i} ships on day {i}.\n\n" for i in range(7))
    assert client.post("/api/documents", files={"file": ("teams.md", sections.encode())}).json()["chunk_count"] == 7
    client.post("/api/ask", json={"question": "Which day does team 3 ship?"})
    [hits] = fake_draft.hits
    assert len(hits) == 5
    assert hits[0].text == "Team 3 ships on day 3."
