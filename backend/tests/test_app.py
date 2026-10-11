"""The app shell: health, the body limit, the 422 shape, the UI fallback, startup, and the contract's fixtures.

The Host and Origin rules are in test_auth.py.
"""

import asyncio
import hashlib
import logging
import re
from pathlib import Path

import httpx2
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from conftest import ORIGIN, W, app_client, sql
from loreos import auth, main, verify_rls
from loreos.db import system_session
from loreos.routes import documents
from loreos.workspaces import DEFAULT_WORKSPACE_ID

INDEX = "<!doctype html><title>LoreOS</title>"
UPLOAD = f"{W}/documents"  # the one path the upload cap applies to, on POST

# Health


def test_health_is_200_when_the_database_answers(client):
    assert client.get("/api/health").status_code == 200


def test_health_is_503_when_the_database_does_not_answer(client, monkeypatch):
    # 0.0.0.0 fails at once on Windows and on Linux; see conftest's OPENAI_BASE_URL.
    monkeypatch.setattr(main, "engine", lambda: create_async_engine("postgresql+asyncpg://x:x@0.0.0.0:9/x", poolclass=NullPool))
    response = client.get("/api/health")
    assert response.status_code == 503
    assert isinstance(response.json()["detail"], str)


# The body limit and the 422 shape, on a probe app carrying the real app's middleware class and exception handlers


class Question(BaseModel):
    question: str


probe = FastAPI(exception_handlers=main.app.exception_handlers)
probe.add_middleware(main.BodyLimit)


@probe.post("/echo")
@probe.post("/api/workspaces/{workspace_id}/documents")
async def echo(request: Request):
    return {"bytes": len(await request.body())}


@probe.post("/ask")
async def ask(body: Question):
    return body


def send_chunks(app, chunks: list[bytes], path: str = UPLOAD):
    """POST chunks to path as a chunked body, one ASGI message each, with no Content-Length."""

    async def body():
        for chunk in chunks:
            yield chunk

    async def go():
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=ORIGIN) as c:
            return await c.post(path, content=body())

    return asyncio.run(go())


def test_the_upload_cap_has_room_for_the_multipart_envelope():
    assert documents.MAX_UPLOAD_BYTES == 20 * 1024 * 1024
    assert main.MAX_REQUEST_BYTES > documents.MAX_UPLOAD_BYTES


def test_a_chunked_body_is_counted_across_messages_and_stops_past_the_cap(monkeypatch):
    monkeypatch.setattr(main, "MAX_REQUEST_BYTES", 1000)
    under = send_chunks(probe, [b"x" * 400] * 2)
    assert under.status_code == 200 and under.json() == {"bytes": 800}
    over = send_chunks(probe, [b"x" * 400] * 3)
    assert "content-length" not in over.request.headers
    assert over.status_code == 413
    assert over.json()["detail"].startswith("the request is over 20 MB")


def test_a_chunked_body_off_the_upload_path_stops_past_the_small_cap():
    under = send_chunks(probe, [b"x" * 30 * 1024] * 2, "/echo")
    assert under.status_code == 200 and under.json() == {"bytes": 60 * 1024}
    over = send_chunks(probe, [b"x" * 30 * 1024] * 3, "/echo")
    assert "content-length" not in over.request.headers
    assert over.status_code == 413
    assert over.json()["detail"].startswith("the request is over 64 KB")


def test_a_body_declared_over_the_cap_is_refused_by_the_real_app_before_routing(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_REQUEST_BYTES", 1000)
    response = client.post(UPLOAD, content=b"x" * 1001)  # no credentials, so past the limit it would be 401
    assert response.status_code == 413
    assert response.json()["detail"].startswith("the request is over 20 MB")


def test_a_100_kb_json_body_to_login_is_refused_before_parsing(client):
    response = client.post("/api/auth/login", json={"email": "a@example.com", "password": "x" * 100 * 1024})
    assert response.status_code == 413
    assert response.json()["detail"].startswith("the request is over 64 KB")
    assert sql("select count(*) from loreos.rate_limits") == [(0,)]  # login reserves a slot once it has parsed


def test_a_100_kb_upload_is_under_the_upload_cap(owner):
    response = owner.client.post(UPLOAD, files={"file": ("big.txt", b"word " * 20 * 1024, "text/plain")})
    assert response.status_code == 202
    assert response.json()["status"] == "pending"


def test_a_validation_error_has_a_string_detail_naming_the_field():
    response = TestClient(probe).post("/ask", json={"question": 3})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, str) and "question" in detail


# The UI fallback


@pytest.fixture
def dist(tmp_path, monkeypatch):
    """A built UI in tmp_path/dist, and a secret file beside it that no path may reach."""
    build = tmp_path / "dist"
    (build / "assets").mkdir(parents=True)
    (build / "index.html").write_text(INDEX, encoding="utf-8")
    (build / "assets" / "app.js").write_text("console.log('app')", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("SECRET", encoding="utf-8")
    monkeypatch.setattr(main, "DIST", build)
    return build


@pytest.mark.parametrize("path", ["/", "/login", "/invite", "/settings/keys", "/assets/missing.js"])
def test_an_app_path_gets_index_html(dist, path):
    response = app_client().get(path)
    assert response.status_code == 200
    assert response.text == INDEX
    assert response.headers["content-type"].startswith("text/html")


def test_an_asset_is_served(dist):
    response = app_client().get("/assets/app.js")
    assert response.status_code == 200
    assert response.text == "console.log('app')"
    assert response.headers["content-type"].startswith("text/javascript")


@pytest.mark.parametrize("path", ["/api/nope", "/api", "/api/workspaces/x/nope"])
def test_an_unknown_api_path_gets_a_json_404(dist, path):
    response = app_client().get(path)
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert isinstance(response.json()["detail"], str)


@pytest.mark.parametrize(
    "path",
    [
        "/%2e%2e/secret.txt",
        "/assets/%2e%2e/%2e%2e/secret.txt",
        "/..%2fsecret.txt",
        "/%2e%2e%5csecret.txt",
        "/assets%2f..%2f..%2fsecret.txt",
    ],
)
def test_an_encoded_dot_dot_never_leaves_dist(dist, path):
    response = app_client().get(path)
    assert "SECRET" not in response.text
    assert response.text == INDEX


def test_an_absolute_path_never_leaves_dist(dist, tmp_path):
    secret = (tmp_path / "secret.txt").as_posix()
    response = app_client().get("/" + secret.replace("/", "%2f").replace(":", "%3a"))
    assert "SECRET" not in response.text
    assert response.text == INDEX


def test_a_unc_path_never_reaches_the_filesystem(dist, monkeypatch):
    """On Windows, resolving \\\\host\\share opens an SMB connection to that host, which can leak the account's hash.

    The spy records every resolve() and runs only those lexically inside the build, so a regression fails here
    without dialling anything. On Linux the backslashes are a file name inside the build, which is harmless.
    """
    outside = []
    real = Path.resolve

    def spy(self, *args, **kwargs):
        if self.is_relative_to(dist):
            return real(self, *args, **kwargs)
        outside.append(self)
        return self

    monkeypatch.setattr(Path, "resolve", spy)
    response = app_client().get("/%5c%5cevil.example%5cshare%5cx.js")
    assert response.text == INDEX
    assert outside == []


def test_with_no_build_the_404_names_the_build_command(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DIST", tmp_path / "dist")
    response = app_client().get("/")
    assert response.status_code == 404
    assert "npm run build --prefix frontend" in response.json()["detail"]


# Startup


def test_startup_with_a_blank_openai_key_raises_naming_it(monkeypatch, caplog):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        with app_client():
            pass
    assert any(r.levelno == logging.ERROR and "OPENAI_API_KEY" in r.getMessage() for r in caplog.records)


def test_startup_with_a_verify_rls_problem_raises_naming_it(db, monkeypatch, caplog):
    problem = verify_rls.CHECKS["bypassrls"]

    async def problems(conn):
        return [problem]

    monkeypatch.setattr(verify_rls, "problems", problems)
    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError, match=re.escape(problem)):
        with app_client():
            pass
    assert any(r.levelno == logging.ERROR and problem in r.getMessage() for r in caplog.records)


def test_startup_with_every_key_set_serves(db):
    with app_client() as client:
        assert client.get("/api/health").status_code == 200


# The fixtures 4.2 to 4.4 build on


def test_the_client_fixture_sends_the_origin_and_no_credentials(client):
    headers = client.build_request("POST", "/x").headers
    assert headers["origin"] == ORIGIN and "cookie" not in headers and "authorization" not in headers


def test_the_owner_and_member_fixtures_are_logged_in_members(owner, member):
    for user, role in ((owner, "owner"), (member, "member")):
        headers = user.client.build_request("POST", "/x").headers
        assert headers["origin"] == ORIGIN and "authorization" not in headers
        token = user.client.cookies[auth.SESSION_COOKIE]
        assert headers["cookie"] == f"{auth.SESSION_COOKIE}={token}"

        async def lookup(token=token):
            async with system_session() as conn:
                return await auth.session_user(conn, token)

        assert asyncio.run(lookup()) == auth.User(user.id, user.email)
        assert sql("select workspace_id, role from loreos.memberships where user_id = :u", u=user.id) == [
            (DEFAULT_WORKSPACE_ID, role)
        ]


def test_the_key_client_sends_a_default_workspace_key_and_nothing_else(key_client):
    headers = key_client.build_request("POST", "/x").headers
    assert "origin" not in headers and "cookie" not in headers
    scheme, key = headers["authorization"].split(" ")
    assert scheme == "Bearer"
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    assert sql("select workspace_id from loreos.api_keys where key_hash = :h", h=key_hash) == [(DEFAULT_WORKSPACE_ID,)]
