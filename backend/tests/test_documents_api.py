"""Documents under /api/workspaces/{id}: a file or a URL, list, get and delete, the 20 MB cap, roles and row locks.

P1's cases on its unscoped document routes and test_local_only.py's upload cases moved here. An upload is pending (202) until
drain() runs the worker.
"""

import asyncio
import time

import httpx2
import pytest
from sqlalchemy import text

from conftest import ORIGIN, W, drain, sql
from loreos import llm
from loreos.db import engine
from loreos.main import app
from pdf import make_pdf

MB = 1024 * 1024
MARKDOWN = b"# Releases\n\nWe ship on Tuesdays.\n"
UPLOAD = {"file": ("a.md", b"# A\n\nSome text.\n")}
URL = "https://example.com/guide"
BUSY = "the document is being processed; try again shortly"
LOCK_ROW = text("select 1 from loreos.documents where id = :d for update")


def post(client, name, data):
    return client.post(f"{W}/documents", files={"file": (name, data, "application/octet-stream")})


def get(client, document_id):
    return client.get(f"{W}/documents/{document_id}").json()


def document_rows():
    return sql("select count(*) from loreos.documents")[0][0]


def chunk_rows():
    return sql("select count(*) from loreos.chunks")[0][0]


# Uploads


@pytest.mark.parametrize(
    "name, data, kind",
    [
        ("releases.md", MARKDOWN, "md"),
        ("releases.markdown", MARKDOWN + b"\nMarkdown twin.\n", "md"),
        ("notes.txt", b"Plain notes about releases.", "txt"),
        ("report.pdf", make_pdf(["Quarterly report text"]), "pdf"),
    ],
)
def test_upload_is_pending_then_reaches_processed(owner, fake_embed, name, data, kind):
    response = post(owner.client, name, data)
    assert response.status_code == 202
    pending = response.json()
    assert (pending["filename"], pending["kind"], pending["status"], pending["error"], pending["attempts"]) == (
        name,
        kind,
        "pending",
        None,
        0,
    )
    assert pending["chunk_count"] == 0 and pending["processed_at"] is None and fake_embed == []

    assert drain() == ["processed"]
    body = get(owner.client, pending["id"])
    assert (body["status"], body["error"], body["attempts"]) == ("processed", None, 0)
    assert body["chunk_count"] > 0 and body["processed_at"]
    assert owner.client.get(f"{W}/documents").json() == [body]


def test_over_20_mb_is_413_and_writes_nothing(owner, fake_embed):
    response = post(owner.client, "big.txt", b"x" * (20 * MB + 1))
    assert "content-length" in response.request.headers
    assert response.status_code == 413
    assert document_rows() == 0 and fake_embed == []


def test_a_body_declared_over_the_cap_is_refused_before_it_is_parsed(owner, fake_embed):
    response = owner.client.post(f"{W}/documents", files={"file": ("big.txt", b"x" * (21 * MB))})
    assert response.status_code == 413
    assert response.json()["detail"].startswith("the request is over 20 MB")
    assert document_rows() == 0 and fake_embed == []


def send_chunked(authorization: str, size: int):
    """A multipart upload of `size` bytes as a chunked body, one ASGI message per MB, with no Content-Length."""
    boundary = "loreos-test-boundary"
    head = f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="big.txt"\r\n\r\n'

    async def body():
        yield head.encode()
        for start in range(0, size, MB):
            yield b"x" * min(MB, size - start)
        yield f"\r\n--{boundary}--\r\n".encode()

    async def go():
        headers = {"authorization": authorization, "content-type": f"multipart/form-data; boundary={boundary}"}
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=ORIGIN) as c:
            return await c.post(f"{W}/documents", content=body(), headers=headers)

    return asyncio.run(go())


@pytest.mark.parametrize(
    "size, status",
    [(100, 202), (20 * MB + 1, 413), (21 * MB, 413)],
    ids=["small", "over-the-file-cap", "over-the-request-cap"],
)
def test_a_chunked_upload_is_cut_off_past_20_mb_and_writes_nothing(key_client, fake_embed, size, status):
    response = send_chunked(key_client.headers["authorization"], size)
    assert "content-length" not in response.request.headers
    assert response.status_code == status
    assert document_rows() == (1 if status == 202 else 0) and fake_embed == []


def test_other_types_are_415_naming_the_accepted_ones(owner, fake_embed):
    response = post(owner.client, "slides.pptx", b"PK\x03\x04 not a supported type")
    assert response.status_code == 415
    assert ".md, .markdown, .txt, .pdf or .docx" in response.json()["detail"]
    assert document_rows() == 0 and fake_embed == []


def test_a_body_that_is_neither_a_file_nor_a_url_is_415(owner):
    response = owner.client.post(f"{W}/documents", content=b"notes", headers={"content-type": "text/plain"})
    assert response.status_code == 415
    assert document_rows() == 0


def test_a_form_without_a_file_field_is_422(owner):
    assert owner.client.post(f"{W}/documents", files={"upload": ("a.md", b"# A")}).status_code == 422
    assert document_rows() == 0


def test_duplicate_returns_the_existing_document_without_spending(owner, fake_embed):
    first = post(owner.client, "releases.md", MARKDOWN)
    assert first.status_code == 202
    queued = post(owner.client, "releases.md", MARKDOWN)
    assert (queued.status_code, queued.json()) == (200, first.json())

    assert drain() == ["processed"]
    calls = len(fake_embed)
    processed = get(owner.client, first.json()["id"])
    again = post(owner.client, "renamed.md", MARKDOWN)
    assert again.status_code == 200
    assert again.json() == processed
    assert drain() == [] and len(fake_embed) == calls
    assert chunk_rows() == processed["chunk_count"]


def test_an_embed_failure_is_recorded_with_its_class(owner, monkeypatch):
    async def embed_fails(texts):
        raise ConnectionError("upstream timed out")

    monkeypatch.setattr(llm, "embed", embed_fails)
    document_id = post(owner.client, "releases.md", MARKDOWN).json()["id"]
    assert drain() == ["transient"]
    body = get(owner.client, document_id)
    assert (body["status"], body["chunk_count"], body["attempts"]) == ("pending", 0, 1)
    assert body["error"] == "embed: transient: ConnectionError: upstream timed out"


def test_a_failed_duplicate_is_queued_again_with_attempts_reset(owner, fake_embed):
    scan = make_pdf(["", ""])
    document_id = post(owner.client, "scan.pdf", scan).json()["id"]
    assert drain() == ["permanent"]
    failed = get(owner.client, document_id)
    assert (failed["status"], failed["attempts"]) == ("failed", 1)

    retried = post(owner.client, "scan.pdf", scan)
    assert retried.status_code == 202
    body = retried.json()
    assert (body["id"], body["status"], body["attempts"], body["error"]) == (document_id, "pending", 0, None)


def test_parse_failure_is_recorded(owner, fake_embed):
    document_id = post(owner.client, "scan.pdf", make_pdf(["", ""])).json()["id"]
    assert drain() == ["permanent"]
    body = get(owner.client, document_id)
    assert (body["status"], body["attempts"], body["chunk_count"]) == ("failed", 1, 0)
    assert body["error"] == "parse: permanent: ParseError: no extractable text (scanned PDF?)"
    assert fake_embed == []


def test_unknown_document_is_404(owner):
    response = owner.client.get(f"{W}/documents/00000000-0000-0000-0000-00000000abcd")
    assert response.status_code == 404
    assert response.json()["detail"] == "no such document"


# The Origin rule, on the scoped route (moved from test_local_only.py)


@pytest.mark.parametrize("origin", ["https://evil.example", "null", "http://localhost:3000", "http://127.0.0.1:3000"])
def test_a_cross_origin_upload_is_refused_before_anything_is_stored(owner, fake_embed, origin):
    response = owner.client.post(f"{W}/documents", files=UPLOAD, headers={"origin": origin})
    assert response.status_code == 403
    assert document_rows() == 0 and fake_embed == []


def test_a_same_origin_post_is_allowed(owner, fake_embed):
    assert owner.client.post(f"{W}/documents", files=UPLOAD, headers={"origin": ORIGIN}).status_code == 202


# URLs


def test_a_url_is_queued_and_queued_again_when_submitted_again(owner):
    first = owner.client.post(f"{W}/documents", json={"url": URL})
    assert first.status_code == 202
    body = first.json()
    assert (body["kind"], body["filename"], body["status"], body["attempts"]) == ("url", URL, "pending", 0)

    again = owner.client.post(f"{W}/documents", json={"url": URL})
    assert again.status_code == 202 and again.json()["id"] == body["id"]
    assert document_rows() == 1


@pytest.mark.parametrize("payload", [{"url": "ftp://example.com/guide"}, {"url": "https://user:pw@example.com/"}, {"url": 3}, {}])
def test_a_url_that_cannot_be_imported_is_422(owner, payload):
    response = owner.client.post(f"{W}/documents", json=payload)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)
    assert document_rows() == 0


# Roles


def test_a_member_uploads_and_lists_but_cannot_delete(member, fake_embed):
    uploaded = post(member.client, "releases.md", MARKDOWN)
    assert uploaded.status_code == 202
    document_id = uploaded.json()["id"]
    assert [d["id"] for d in member.client.get(f"{W}/documents").json()] == [document_id]
    assert member.client.delete(f"{W}/documents/{document_id}").status_code == 403
    assert document_rows() == 1


def test_an_owner_deletes_a_document_and_its_chunks(owner, fake_embed):
    document_id = post(owner.client, "releases.md", MARKDOWN).json()["id"]
    assert drain() == ["processed"] and chunk_rows() > 0

    assert owner.client.delete(f"{W}/documents/{document_id}").status_code == 204
    assert owner.client.get(f"{W}/documents/{document_id}").status_code == 404
    assert (document_rows(), chunk_rows()) == (0, 0)
    assert owner.client.delete(f"{W}/documents/{document_id}").status_code == 404


# Row locks: the worker may hold a document's row for minutes, so a delete or a URL re-queue gives up after 2 s.


def while_locked(document_id, request):
    """request() in a thread while another connection holds the document's row; its response and the seconds it took.

    Bounded at 10 s, so a request that waits on the lock fails here instead of hanging the run.
    """

    async def go():
        async with engine().begin() as holder:
            await holder.execute(LOCK_ROW, {"d": document_id})
            started = time.monotonic()
            response = await asyncio.wait_for(asyncio.to_thread(request), 10)
            return response, time.monotonic() - started

    return asyncio.run(go())


def test_deleting_a_document_whose_row_is_locked_is_409_in_about_two_seconds(owner):
    document_id = post(owner.client, "releases.md", MARKDOWN).json()["id"]
    response, elapsed = while_locked(document_id, lambda: owner.client.delete(f"{W}/documents/{document_id}"))
    assert (response.status_code, response.json()["detail"]) == (409, BUSY)
    assert 1.5 < elapsed < 5
    assert document_rows() == 1


def test_resubmitting_a_url_whose_row_is_locked_is_409_in_about_two_seconds(owner):
    document_id = owner.client.post(f"{W}/documents", json={"url": URL}).json()["id"]
    response, elapsed = while_locked(document_id, lambda: owner.client.post(f"{W}/documents", json={"url": URL}))
    assert (response.status_code, response.json()["detail"]) == (409, BUSY)
    assert 1.5 < elapsed < 5
