import pytest

from conftest import sql

UPLOAD = {"file": ("a.md", b"# A\n\nSome text.\n")}


def test_a_foreign_host_header_is_refused(client):
    """DNS rebinding: a page on evil.example resolved to 127.0.0.1 still sends its own Host."""
    assert client.get("/api/documents", headers={"host": "evil.example:8000"}).status_code == 400


@pytest.mark.parametrize("origin", ["https://evil.example", "null", "http://localhost:3000", "http://127.0.0.1:3000"])
def test_a_cross_origin_upload_is_refused_before_anything_is_stored(client, fake_embed, origin):
    response = client.post("/api/documents", files=UPLOAD, headers={"origin": origin})
    assert response.status_code == 403
    assert sql("select count(*) from loreos.documents")[0][0] == 0 and fake_embed == []


def test_a_cross_origin_ask_is_refused_before_anything_is_bought(client, fake_embed, fake_draft):
    client.post("/api/documents", files=UPLOAD)
    fake_embed.clear()
    for origin in ("https://evil.example", "null", "http://localhost:3000"):
        assert client.post("/api/ask", json={"question": "x"}, headers={"origin": origin}).status_code == 403
    assert fake_embed == [] and fake_draft.calls == []


def test_a_same_origin_post_is_allowed(client, fake_embed):
    assert client.post("/api/documents", files=UPLOAD, headers={"origin": "http://127.0.0.1:8000"}).status_code == 201


def test_a_body_declared_over_the_cap_is_refused_before_it_is_parsed(client, fake_embed):
    response = client.post("/api/documents", files={"file": ("big.txt", b"x" * (21 * 1024 * 1024))})
    assert response.status_code == 413
    assert response.json()["detail"].startswith("the request is over 20 MB")
    assert sql("select count(*) from loreos.documents")[0][0] == 0
