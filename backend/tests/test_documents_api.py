import pytest

from conftest import sql
from loreos import llm
from pdf import make_pdf

MARKDOWN = b"# Releases\n\nWe ship on Tuesdays.\n"


def post(client, name, data):
    return client.post("/api/documents", files={"file": (name, data, "application/octet-stream")})


def document_rows():
    return sql("select count(*) from loreos.documents")[0][0]


@pytest.mark.parametrize(
    "name, data, kind",
    [
        ("releases.md", MARKDOWN, "md"),
        ("releases.markdown", MARKDOWN + b"\nMarkdown twin.\n", "md"),
        ("notes.txt", b"Plain notes about releases.", "txt"),
        ("report.pdf", make_pdf(["Quarterly report text"]), "pdf"),
    ],
)
def test_upload_reaches_processed(client, fake_embed, name, data, kind):
    response = post(client, name, data)
    assert response.status_code == 201
    body = response.json()
    assert (body["filename"], body["kind"], body["status"], body["error"], body["attempts"]) == (name, kind, "processed", None, 1)
    assert body["chunk_count"] > 0 and body["processed_at"]
    assert client.get(f"/api/documents/{body['id']}").json() == body
    assert [d["id"] for d in client.get("/api/documents").json()] == [body["id"]]


def test_over_20_mb_is_413_and_writes_nothing(client, fake_embed):
    response = post(client, "big.txt", b"x" * (20 * 1024 * 1024 + 1))
    assert response.status_code == 413
    assert document_rows() == 0 and fake_embed == []


def test_other_types_are_415_naming_the_accepted_ones(client, fake_embed):
    response = post(client, "slides.pptx", b"PK\x03\x04 not a supported type")
    assert response.status_code == 415
    assert ".md, .markdown, .txt, .pdf or .docx" in response.json()["detail"]
    assert document_rows() == 0 and fake_embed == []


def test_duplicate_returns_the_existing_document_without_spending(client, fake_embed):
    first = post(client, "releases.md", MARKDOWN).json()
    calls = len(fake_embed)
    again = post(client, "renamed.md", MARKDOWN)
    assert again.status_code == 200
    assert again.json() == first
    assert len(fake_embed) == calls
    assert sql("select count(*) from loreos.chunks")[0][0] == first["chunk_count"]


def test_embed_failure_is_recorded_and_a_failed_duplicate_is_retried(client, monkeypatch, fake_embed):
    working_embed = llm.embed

    async def embed_fails(texts):
        raise ConnectionError("upstream timed out")

    monkeypatch.setattr(llm, "embed", embed_fails)
    failed = post(client, "releases.md", MARKDOWN)
    assert failed.status_code == 201
    body = failed.json()
    assert (body["status"], body["chunk_count"], body["attempts"]) == ("failed", 0, 1)
    assert body["error"] == "embed: ConnectionError: upstream timed out"

    monkeypatch.setattr(llm, "embed", working_embed)
    retried = post(client, "releases.md", MARKDOWN)
    assert retried.status_code == 200
    assert (retried.json()["id"], retried.json()["status"], retried.json()["attempts"], retried.json()["error"]) == (
        body["id"],
        "processed",
        2,
        None,
    )


def test_parse_failure_is_recorded(client, fake_embed):
    body = post(client, "scan.pdf", make_pdf(["", ""])).json()
    assert body["status"] == "failed"
    assert body["error"] == "parse: ParseError: no extractable text (scanned PDF?)"
    assert fake_embed == []


def test_unknown_document_is_404(client):
    assert client.get("/api/documents/00000000-0000-0000-0000-00000000abcd").status_code == 404
