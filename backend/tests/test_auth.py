"""Passwords, session tokens, API keys, the current_member, require_owner and current_user dependencies, and the
signup, login, logout, me and invite routes.

The dependencies run in a small FastAPI app built here; the routes run on the real app.
"""

import asyncio
import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from typing import Annotated

import argon2
import httpx2
import pytest
from fastapi import Depends, FastAPI, Request, Response
from fastapi.testclient import TestClient

from conftest import ORIGIN, app_client, make_user, sql
from loreos import auth, main, ratelimit
from loreos.db import system_session
from loreos.workspaces import DEFAULT_WORKSPACE_ID

PASSWORD = "correct horse battery"


def call(fn, *args):
    """fn(conn, *args) inside one system_session; its result."""

    async def go():
        async with system_session() as conn:
            return await fn(conn, *args)

    return asyncio.run(go())


def sha256(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


app = FastAPI()


@app.get("/w/{workspace_id}")
async def member_route(member: Annotated[auth.Member, Depends(auth.current_member)]):
    return member


@app.get("/w/{workspace_id}/owner")
async def owner_route(member: Annotated[auth.Member, Depends(auth.require_owner)]):
    return member


@app.get("/me")
async def me_route(user: Annotated[auth.User, Depends(auth.current_user)]):
    return user


@app.post("/cookie")
async def set_cookie_route(request: Request, response: Response):
    auth.set_session_cookie(response, request, "t0ken")


@app.post("/cookie/clear")
async def clear_cookie_route(response: Response):
    auth.clear_session_cookie(response)


@pytest.fixture
def web(clean):
    """Two workspaces, A and B; an owner and a member of A, a user in neither; a session and a key for each."""
    a = sql("insert into loreos.workspaces (name) values ('a') returning id")[0][0]
    b = sql("insert into loreos.workspaces (name) values ('b') returning id")[0][0]
    users = {}
    for name, role in (("owner", "owner"), ("member", "member"), ("stranger", None)):
        user_id = call(auth.create_user, f"{name}@example.com", PASSWORD)
        if role:
            sql("insert into loreos.memberships (user_id, workspace_id, role) values (:u, :w, :r)", u=user_id, w=a, r=role)
        users[name] = {"cookie": f"{auth.SESSION_COOKIE}={call(auth.create_session, user_id)}"}
    key_a = call(auth.create_key, a, "a's key")
    key_b = call(auth.create_key, b, "b's key")
    return a, b, users, key_a, key_b, TestClient(app)


def bearer(key: str) -> dict:
    return {"authorization": f"Bearer {key}"}


# Passwords


def test_a_hash_is_argon2id_and_verifies():
    password_hash = auth.hash_password(PASSWORD)
    assert password_hash.startswith("$argon2id$")
    assert auth.verify_password(password_hash, PASSWORD) is True
    assert auth.verify_password(password_hash, PASSWORD + "x") is False
    assert auth.verify_password("not a hash", PASSWORD) is False


def test_a_password_under_12_characters_is_refused_naming_12():
    assert auth.MIN_PASSWORD == 12
    assert "12" in auth.password_problem("a" * 11)
    assert auth.password_problem("a" * 12) is None


def test_an_email_is_stripped_and_lowercased():
    assert auth.normalize_email("  Ann@Example.COM \n") == "ann@example.com"


def test_authenticate_finds_the_user_by_normalised_email(clean):
    user_id = call(auth.create_user, "Ann@Example.com", PASSWORD)
    assert call(auth.authenticate, " ANN@example.com ", PASSWORD) == auth.User(user_id, "ann@example.com")


@pytest.mark.parametrize("email, password", [("nobody@example.com", PASSWORD), ("ann@example.com", "wrong password!")])
def test_an_unknown_email_and_a_wrong_password_each_run_one_verification(clean, monkeypatch, email, password):
    call(auth.create_user, "ann@example.com", PASSWORD)
    real = argon2.PasswordHasher.verify
    calls = []

    def spy(self, *args):
        calls.append(args)
        return real(self, *args)

    monkeypatch.setattr(argon2.PasswordHasher, "verify", spy)  # PasswordHasher has __slots__, so patch the class
    assert call(auth.authenticate, email, password) is None
    assert len(calls) == 1


# Storage


def test_the_database_keeps_only_the_sha256_of_a_session_token_and_a_key(clean):
    user_id = call(auth.create_user, "ann@example.com", PASSWORD)
    token = call(auth.create_session, user_id)
    _, key = call(auth.create_key, sql("select id from loreos.workspaces limit 1")[0][0], "k")
    session_row = sql("select * from loreos.sessions")
    key_row = sql("select * from loreos.api_keys")
    assert [r.id for r in session_row] == [sha256(token)]
    assert [r.key_hash for r in key_row] == [sha256(key)]
    assert token not in str(session_row) and key not in str(key_row) and key[len(auth.KEY_PREFIX) :] not in str(key_row)


def test_an_expired_session_finds_no_user(clean):
    user_id = call(auth.create_user, "ann@example.com", PASSWORD)
    token = call(auth.create_session, user_id)
    assert call(auth.session_user, token) == auth.User(user_id, "ann@example.com")
    days = sql("select extract(epoch from expires_at - created_at) / 86400 from loreos.sessions")[0][0]
    assert round(days) == auth.SESSION_DAYS
    sql("update loreos.sessions set expires_at = now() - interval '1 second'")
    assert call(auth.session_user, token) is None


def test_delete_session_ends_it(clean):
    token = call(auth.create_session, call(auth.create_user, "ann@example.com", PASSWORD))
    call(auth.delete_session, token)
    assert call(auth.session_user, token) is None
    assert sql("select count(*) from loreos.sessions")[0][0] == 0


def test_a_key_is_lo_sk_and_43_base64url_characters_with_an_8_character_prefix(clean):
    key_id, key = call(auth.create_key, sql("select id from loreos.workspaces limit 1")[0][0], "k")
    assert re.fullmatch(r"lo_sk_[A-Za-z0-9_-]{43}", key)
    assert sql("select prefix from loreos.api_keys where id = :i", i=key_id) == [(key[6:14],)]


# current_member


def test_no_credentials_get_401(web):
    a, _, _, _, _, client = web
    assert client.get(f"/w/{a}").status_code == 401


@pytest.mark.parametrize("name, role", [("owner", "owner"), ("member", "member")])
def test_a_members_cookie_gets_its_role(web, name, role):
    a, _, users, _, _, client = web
    response = client.get(f"/w/{a}", headers={"cookie": users[name]["cookie"]})
    assert response.status_code == 200
    assert response.json()["role"] == role and response.json()["key_id"] is None and response.json()["user_id"]


def test_a_non_members_cookie_gets_404(web):
    a, b, users, _, _, client = web
    assert client.get(f"/w/{a}", headers={"cookie": users["stranger"]["cookie"]}).status_code == 404
    assert client.get(f"/w/{b}", headers={"cookie": users["owner"]["cookie"]}).status_code == 404


def test_an_unknown_or_expired_session_gets_401(web):
    a, _, users, _, _, client = web
    assert client.get(f"/w/{a}", headers={"cookie": f"{auth.SESSION_COOKIE}=nope"}).status_code == 401
    sql("update loreos.sessions set expires_at = now() - interval '1 second'")
    assert client.get(f"/w/{a}", headers={"cookie": users["owner"]["cookie"]}).status_code == 401


def test_the_workspaces_own_key_is_a_key_member_and_records_its_use(web):
    a, _, _, (key_id, key), _, client = web
    assert sql("select last_used_at from loreos.api_keys where id = :i", i=key_id) == [(None,)]
    response = client.get(f"/w/{a}", headers=bearer(key))
    assert response.status_code == 200
    assert response.json() == {"workspace_id": str(a), "role": "member", "user_id": None, "key_id": str(key_id)}
    assert sql("select last_used_at from loreos.api_keys where id = :i", i=key_id)[0][0] is not None


def test_another_workspaces_key_gets_404(web):
    a, _, _, _, (key_id, key), client = web
    assert client.get(f"/w/{a}", headers=bearer(key)).status_code == 404
    assert sql("select last_used_at from loreos.api_keys where id = :i", i=key_id) == [(None,)]


def test_a_revoked_key_gets_401(web):
    a, _, _, (key_id, key), _, client = web
    sql("update loreos.api_keys set revoked_at = now() where id = :i", i=key_id)
    assert client.get(f"/w/{a}", headers=bearer(key)).status_code == 401


@pytest.mark.parametrize(
    "authorization",
    ["Bearer lo_sk_" + "A" * 43, "Bearer not-a-key", "Bearer ", "Basic dXNlcjpwYXNz", ""],
)
def test_a_bad_authorization_header_gets_401_even_with_a_good_cookie(web, authorization):
    a, _, users, _, _, client = web
    headers = {"authorization": authorization, "cookie": users["owner"]["cookie"]}
    assert client.get(f"/w/{a}", headers=headers).status_code == 401


# require_owner and current_user


def test_require_owner_refuses_a_member_and_a_key(web):
    a, _, users, (_, key), _, client = web
    assert client.get(f"/w/{a}/owner", headers={"cookie": users["owner"]["cookie"]}).status_code == 200
    assert client.get(f"/w/{a}/owner", headers={"cookie": users["member"]["cookie"]}).status_code == 403
    assert client.get(f"/w/{a}/owner", headers=bearer(key)).status_code == 403


def test_current_user_takes_the_cookie_only(web):
    _, _, users, (_, key), _, client = web
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers={"cookie": users["member"]["cookie"]}).json()["email"] == "member@example.com"
    assert client.get("/me", headers={**bearer(key), "cookie": users["member"]["cookie"]}).status_code == 403


# Cookie flags


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_the_session_cookie_flags(scheme):
    response = TestClient(app, base_url=f"{scheme}://testserver").post("/cookie")
    morsel = SimpleCookie(response.headers["set-cookie"])[auth.SESSION_COOKIE]
    assert morsel.value == "t0ken"
    assert morsel["httponly"] is True and morsel["samesite"].lower() == "lax" and morsel["path"] == "/"
    assert morsel["max-age"] == str(auth.SESSION_DAYS * 24 * 3600)
    assert bool(morsel["secure"]) is (scheme == "https")


def test_clearing_the_session_cookie_expires_it():
    response = TestClient(app).post("/cookie/clear")
    morsel = SimpleCookie(response.headers["set-cookie"])[auth.SESSION_COOKIE]
    assert morsel.value == "" and morsel["max-age"] == "0" and morsel["path"] == "/"


# The Host and Origin rules (behaviour 9), on the real app. /api/nope is never routed, so a write the Origin rule
# lets through gets the GET catch-all's 405, and one it refuses gets 403.

WRITES = ["POST", "PUT", "PATCH", "DELETE"]


def test_a_foreign_host_header_is_refused():
    """DNS rebinding: a page on evil.example resolved to 127.0.0.1 still sends its own Host."""
    assert app_client().get("/api/health", headers={"host": "evil.example:8000"}).status_code == 400


@pytest.mark.parametrize("method", WRITES)
@pytest.mark.parametrize(
    "origin", ["https://evil.example", "null", "http://localhost:8000", "http://127.0.0.1:3000", "http://localhost:3000", None]
)
def test_a_write_without_a_same_host_origin_gets_403(method, origin):
    client = app_client(origin=origin) if origin else app_client()
    response = client.request(method, "/api/nope")
    assert response.status_code == 403
    assert isinstance(response.json()["detail"], str)


@pytest.mark.parametrize("authorization", ["Basic dXNlcjpwYXNz", "lo_sk_" + "A" * 43, "Bearerlo_sk_x", "Token x"])
def test_only_a_bearer_header_is_exempt_from_the_origin_rule(authorization):
    assert app_client(authorization=authorization).post("/api/nope").status_code == 403


@pytest.mark.parametrize("method", WRITES)
def test_a_same_host_origin_gets_past_the_origin_rule(method):
    assert app_client(origin=ORIGIN).request(method, "/api/nope").status_code == 405


@pytest.mark.parametrize("method", WRITES)
@pytest.mark.parametrize("authorization", ["Bearer lo_sk_" + "A" * 43, "bearer x"])
def test_a_bearer_write_needs_no_origin(method, authorization):
    assert app_client(authorization=authorization).request(method, "/api/nope").status_code == 405


def test_a_get_needs_no_origin(db):
    assert app_client().get("/api/health").status_code == 200


# The routes (task 4.2)

SIGNUP = "/api/auth/signup"
LOGIN = "/api/auth/login"
LOGOUT = "/api/auth/logout"
ME = "/api/me"
ACCEPT = "/api/invites/accept"
WRONG = "wrong password!!"
NEW = {"email": "new@example.com", "password": PASSWORD}


def asgi_client() -> httpx2.AsyncClient:
    """The real app over an ASGI transport, at ORIGIN, so requests gathered on one loop run truly at once."""
    return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=main.app), base_url=ORIGIN, headers={"origin": ORIGIN})


def login(client, email: str, password: str = WRONG):
    return client.post(LOGIN, json={"email": email, "password": password})


def invite(workspace_id=DEFAULT_WORKSPACE_ID, expires=timedelta(days=7)) -> str:
    """An unused invite to workspace_id, stored as 4.3 stores it; its token."""
    token = secrets.token_urlsafe(32)
    sql(
        "insert into loreos.invites (token_hash, workspace_id, expires_at) values (:h, :w, :x)",
        h=sha256(token),
        w=workspace_id,
        x=datetime.now(UTC) + expires,
    )
    return token


def accept(client, token: str, **account):
    return client.post(ACCEPT, json={"token": token, **account})


def users() -> int:
    return sql("select count(*) from loreos.users")[0][0]


# Signup


@pytest.mark.parametrize(
    "email, password, named",
    [("ann@example.com", "a" * 11, "12"), ("not-an-email", PASSWORD, "email"), ("a" * 320 + "@example.com", PASSWORD, "email")],
    ids=["short password", "no at sign", "email too long"],
)
def test_a_bad_signup_gets_422_and_stores_no_user(client, email, password, named):
    response = client.post(SIGNUP, json={"email": email, "password": password})
    assert response.status_code == 422
    assert named in response.json()["detail"]
    assert users() == 0


@pytest.mark.parametrize("name, expected", [({"workspace_name": " Acme "}, "Acme"), ({}, "My workspace")])
def test_the_first_signup_owns_a_new_workspace_and_default_and_never_an_eval_one(client, name, expected):
    sql("insert into loreos.workspaces (name) values ('eval-0123456789ab')")
    response = client.post(SIGNUP, json={"email": " Ann@Example.com", "password": PASSWORD, **name})
    assert response.status_code == 201
    me = response.json()
    assert me["user"]["email"] == "ann@example.com"
    assert [(w["name"], w["role"]) for w in me["workspaces"]] == [("Default", "owner"), (expected, "owner")]
    assert me["workspaces"][0]["id"] == str(DEFAULT_WORKSPACE_ID)
    assert client.get(ME).json() == me  # logged in by the cookie the signup set


@pytest.mark.parametrize("name", ["", "   ", "eval-mine", "a" * 101])
def test_a_blank_long_or_eval_workspace_name_gets_422_and_stores_nothing(client, name):
    response = client.post(SIGNUP, json={"email": "ann@example.com", "password": PASSWORD, "workspace_name": name})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)
    assert users() == 0
    assert sql("select name from loreos.workspaces") == [("Default",)]


def test_me_never_lists_an_eval_workspace_even_with_a_membership(owner):
    """The same list as GET /api/workspaces; login and invite accept build their Me the same way."""
    evaluation = sql("insert into loreos.workspaces (name) values ('eval-0123456789ab') returning id")[0][0]
    sql("insert into loreos.memberships (user_id, workspace_id, role) values (:u, :w, 'owner')", u=owner.id, w=evaluation)
    default = [{"id": str(DEFAULT_WORKSPACE_ID), "name": "Default", "role": "owner"}]
    assert owner.client.get(ME).json()["workspaces"] == default
    assert login(app_client(origin=ORIGIN), owner.email, PASSWORD).json()["workspaces"] == default
    assert owner.client.get("/api/workspaces").json() == default


def test_a_second_signup_gets_403(client):
    assert client.post(SIGNUP, json={"email": "ann@example.com", "password": PASSWORD}).status_code == 201
    response = app_client(origin=ORIGIN).post(SIGNUP, json={"email": "bob@example.com", "password": PASSWORD})
    assert response.status_code == 403
    assert sql("select email from loreos.users") == [("ann@example.com",)]


def test_two_concurrent_first_signups_give_one_201_and_one_403(clean, monkeypatch):
    real = auth.create_user

    async def slow(conn, email, password):
        await asyncio.sleep(0.3)  # without the lock, both requests are past the "no user yet" check by now
        return await real(conn, email, password)

    monkeypatch.setattr(auth, "create_user", slow)

    async def go():
        async with asgi_client() as c:
            bodies = [{"email": f"{name}@example.com", "password": PASSWORD} for name in ("ann", "bob")]
            return await asyncio.gather(*(c.post(SIGNUP, json=body) for body in bodies))

    assert sorted(r.status_code for r in asyncio.run(go())) == [201, 403]
    assert users() == 1


# Cookie and session


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_login_sets_the_session_cookie_with_its_flags(clean, scheme):
    make_user("ann@example.com")
    base = f"{scheme}://127.0.0.1:8000"
    response = login(TestClient(main.app, base_url=base, headers={"origin": base}), "ann@example.com", PASSWORD)
    assert response.status_code == 200
    assert response.json()["user"]["email"] == "ann@example.com"
    morsel = SimpleCookie(response.headers["set-cookie"])[auth.SESSION_COOKIE]
    assert morsel["httponly"] is True and morsel["samesite"].lower() == "lax" and morsel["path"] == "/"
    assert bool(morsel["secure"]) is (scheme == "https")
    assert (sha256(morsel.value),) in sql("select id from loreos.sessions")


def test_logout_deletes_the_session_row_and_clears_the_cookie(owner):
    token = owner.client.cookies.get(auth.SESSION_COOKIE)
    assert owner.client.get(ME).json() == {
        "user": {"id": str(owner.id), "email": owner.email},
        "workspaces": [{"id": str(DEFAULT_WORKSPACE_ID), "name": "Default", "role": "owner"}],
    }
    # a Bearer request skips the Origin rule, so logout must refuse one rather than read its cookie
    assert owner.client.post(LOGOUT, headers={"authorization": "Bearer x"}).status_code == 403
    response = owner.client.post(LOGOUT)
    assert response.status_code == 204
    assert SimpleCookie(response.headers["set-cookie"])[auth.SESSION_COOKIE]["max-age"] == "0"
    assert sql("select count(*) from loreos.sessions")[0][0] == 0
    assert owner.client.get(ME).status_code == 401
    stale = app_client()
    stale.cookies.set(auth.SESSION_COOKIE, token)
    assert stale.get(ME).status_code == 401


# Login rate limit


def test_the_sixth_failure_for_one_email_gets_429_with_retry_after(client):
    make_user("ann@example.com")
    assert [login(client, "ann@example.com").status_code for _ in range(5)] == [401] * 5
    response = login(client, "ann@example.com")
    assert response.status_code == 429
    assert 0 < int(response.headers["retry-after"]) <= 900
    assert login(client, "ann@example.com", PASSWORD).status_code == 429  # refused before verifying


def test_twenty_concurrent_guesses_verify_at_most_five_times(clean, monkeypatch):
    make_user("ann@example.com")
    n = 20
    state = {"calls": 0, "settled": 0}

    async def go():
        everyone = asyncio.Event()

        def settle():
            state["settled"] += 1
            if state["settled"] >= n:
                everyone.set()

        async def spy(password_hash, password):
            state["calls"] += 1
            settle()
            await asyncio.wait_for(everyone.wait(), 5)  # hold each verification until every request is accounted for
            return False

        async def guess(c):
            response = await c.post(LOGIN, json={"email": "ann@example.com", "password": WRONG})
            settle()  # counts only a request that never reached the seam: one that did is answered after the event
            return response.status_code

        monkeypatch.setattr(auth, "_verify", spy)
        async with asgi_client() as c:
            return await asyncio.gather(*(guess(c) for _ in range(n)))

    statuses = asyncio.run(go())
    assert state["calls"] <= 5
    assert sorted(statuses) == [401] * 5 + [429] * 15


def test_case_variants_of_one_email_share_a_bucket(client):
    make_user("ann@example.com")
    variants = ["Ann@Example.com", "ann@example.com", "ANN@EXAMPLE.COM", " ann@Example.com", "ann@example.COM "]
    assert [login(client, email).status_code for email in variants] == [401] * 5
    assert login(client, "aNN@example.com").status_code == 429


def test_twenty_failures_across_emails_from_one_client_then_429(client):
    assert [login(client, f"user{n}@example.com").status_code for n in range(20)] == [401] * 20
    response = login(client, "user20@example.com")
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0


@pytest.mark.parametrize("refunds", [True, False])
def test_a_success_refunds_its_reservation(client, monkeypatch, refunds):
    make_user("ann@example.com")
    if not refunds:

        async def keep(bucket, window_start):
            pass

        monkeypatch.setattr(ratelimit, "refund", keep)
    assert [login(client, "ann@example.com").status_code for _ in range(4)] == [401] * 4
    assert login(client, "ann@example.com", PASSWORD).status_code == 200
    if refunds:
        assert sql("select count from loreos.rate_limits where bucket = 'login:email:ann@example.com'") == [(4,)]
        assert login(client, "ann@example.com").status_code == 401  # count 5 of 5
    assert login(client, "ann@example.com").status_code == 429


def test_an_unknown_email_and_a_wrong_password_get_the_same_answer(client):
    make_user("ann@example.com")
    unknown = login(client, "nobody@example.com")
    wrong = login(client, "ann@example.com")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


# Invites


def test_an_invite_is_single_use(client):
    token = invite()
    first = accept(client, token, **NEW)
    assert first.status_code == 201
    assert first.json()["user"]["email"] == "new@example.com"
    assert [(w["id"], w["role"]) for w in first.json()["workspaces"]] == [(str(DEFAULT_WORKSPACE_ID), "member")]
    assert client.get(ME).json() == first.json()  # logged in by the cookie it set
    assert accept(app_client(origin=ORIGIN), token, email="other@example.com", password=PASSWORD).status_code == 404
    assert users() == 1


def test_an_expired_or_unknown_invite_gets_404(client):
    assert accept(client, invite(expires=timedelta(days=-1)), **NEW).status_code == 404
    assert accept(client, "not-a-token", **NEW).status_code == 404
    assert users() == 0


@pytest.mark.parametrize(
    "account, status",
    [
        ({"email": "Taken@Example.com", "password": PASSWORD}, 409),
        ({"email": "new@example.com", "password": "a" * 11}, 422),
        ({}, 422),
    ],
)
def test_a_refused_account_leaves_the_invite_usable(client, account, status):
    make_user("taken@example.com")
    token = invite()
    response = accept(client, token, **account)
    assert response.status_code == status
    assert isinstance(response.json()["detail"], str)
    assert sql("select used_at from loreos.invites") == [(None,)]
    assert accept(client, token, **NEW).status_code == 201


def test_a_stale_session_cookie_accepts_as_logged_out(client):
    client.cookies.set(auth.SESSION_COOKIE, "stale")
    assert accept(client, invite(), **NEW).status_code == 201


def test_a_logged_in_accept_adds_the_membership_once(member):
    other = sql("insert into loreos.workspaces (name) values ('Other') returning id")[0][0]
    token = invite(other)
    assert member.client.post(ACCEPT, json={"token": token}, headers={"authorization": "Bearer x"}).status_code == 403
    response = accept(member.client, token)
    assert response.status_code == 200
    assert {(w["name"], w["role"]) for w in response.json()["workspaces"]} == {("Default", "member"), ("Other", "member")}
    assert accept(member.client, invite(other)).status_code == 200  # a second invite to the same workspace changes nothing
    assert sql("select role from loreos.memberships where user_id = :u and workspace_id = :w", u=member.id, w=other) == [
        ("member",)
    ]
    assert users() == 1
