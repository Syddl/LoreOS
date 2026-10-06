from conftest import sql

UPLOAD = {"file": ("a.md", b"# A\n\nSome text.\n")}


def test_a_foreign_host_header_is_refused(client):
    """DNS rebinding: a page on evil.example resolved to 127.0.0.1 still sends its own Host."""
    assert client.get("/api/documents", headers={"host": "evil.example:8000"}).status_code == 400


def test_a_cross_origin_upload_is_refused_before_anything_is_stored(client, fake_embed):
    response = client.post("/api/documents", files=UPLOAD, headers={"origin": "https://evil.example"})
    assert response.status_code == 403
    assert sql("select count(*) from loreos.documents")[0][0] == 0 and fake_embed == []


def test_a_cross_origin_or_opaque_ask_is_refused(client, fake_embed, fake_draft):
    for origin in ("https://evil.example", "null"):
        assert client.post("/api/ask", json={"question": "x"}, headers={"origin": origin}).status_code == 403
    assert fake_embed == [] and fake_draft.calls == []


def test_a_same_origin_post_is_allowed(client, fake_embed):
    assert client.post("/api/documents", files=UPLOAD, headers={"origin": "http://127.0.0.1:8000"}).status_code == 201
