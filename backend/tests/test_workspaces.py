"""Workspace, member and invite routes (task 4.3).

They run in system_session, which RLS does not bind, so the cross-workspace cases here are what stands between
a path's workspace and another workspace's rows.
"""

import asyncio
import hashlib
import time
from datetime import UTC, datetime, timedelta

import httpx2
from sqlalchemy import text

from conftest import ORIGIN, W, make_user, sql
from loreos import auth
from loreos.db import engine
from loreos.main import app
from loreos.workspaces import DEFAULT_WORKSPACE_ID


def workspace(name: str):
    return sql("insert into loreos.workspaces (name) values (:n) returning id", n=name)[0][0]


def owners(workspace_id=DEFAULT_WORKSPACE_ID) -> set:
    rows = sql("select user_id from loreos.memberships where workspace_id = :w and role = 'owner'", w=workspace_id)
    return {row.user_id for row in rows}


def stored_anywhere(secret: str) -> list[str]:
    """Every loreos table holding a row whose text form contains secret."""
    tables = [row.tablename for row in sql("select tablename from pg_tables where schemaname = 'loreos'")]
    return [t for t in tables if sql(f"select 1 from loreos.{t} x where position(:s in x::text) > 0", s=secret)]


# Workspaces


def test_a_user_creates_a_workspace_and_lists_it_as_owner(owner):
    created = owner.client.post("/api/workspaces", json={"name": "Research"})
    assert created.status_code == 201
    body = created.json()
    assert body == {"id": body["id"], "name": "Research", "role": "owner"}
    assert owners(body["id"]) == {owner.id}
    listed = owner.client.get("/api/workspaces")
    assert listed.status_code == 200
    assert listed.json() == [
        {"id": str(DEFAULT_WORKSPACE_ID), "name": "Default", "role": "owner"},
        {"id": body["id"], "name": "Research", "role": "owner"},
    ]


def test_another_users_workspace_and_eval_workspaces_are_never_listed(member):
    other = workspace("other")
    make_user("other@example.com", "owner", other)
    evaluation = workspace("eval-0123456789ab")
    sql("insert into loreos.memberships (user_id, workspace_id, role) values (:u, :w, 'owner')", u=member.id, w=evaluation)
    assert member.client.get("/api/workspaces").json() == [
        {"id": str(DEFAULT_WORKSPACE_ID), "name": "Default", "role": "member"}
    ]


def test_a_blank_or_eval_name_is_refused(owner):
    for name in ("", "   ", "eval-mine"):
        response = owner.client.post("/api/workspaces", json={"name": name})
        assert response.status_code == 422, name
    assert sql("select count(*) from loreos.workspaces")[0][0] == 1


# Members


def test_an_owner_lists_and_removes_a_member(owner, member):
    listed = owner.client.get(f"{W}/members")
    assert listed.status_code == 200
    assert sorted(listed.json(), key=lambda m: m["email"]) == [
        {"user_id": str(member.id), "email": "member@example.com", "role": "member"},
        {"user_id": str(owner.id), "email": "owner@example.com", "role": "owner"},
    ]
    assert owner.client.delete(f"{W}/members/{member.id}").status_code == 204
    assert [m["user_id"] for m in owner.client.get(f"{W}/members").json()] == [str(owner.id)]


def test_removing_the_last_owner_gets_409(owner):
    response = owner.client.delete(f"{W}/members/{owner.id}")
    assert response.status_code == 409
    assert "last owner" in response.json()["detail"]
    assert owners() == {owner.id}


def test_an_owner_removes_another_owner(owner):
    second = make_user("second@example.com", "owner")
    assert owner.client.delete(f"{W}/members/{second.id}").status_code == 204
    assert owners() == {owner.id}


async def lock_waiters(count: int) -> None:
    """Return once count backends of this database wait on a lock; fail after 5 s."""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        async with engine().connect() as conn:  # a new connection each time: pg_stat_activity is snapshotted per transaction
            waiting = (
                await conn.execute(
                    text(
                        "select count(*) from pg_stat_activity "
                        "where datname = current_database() and wait_event_type = 'Lock'"
                    )
                )
            ).scalar()
        if waiting >= count:
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"{count} requests never waited on the owner rows")


def test_two_owners_removing_each_other_at_once_leave_exactly_one(owner):
    """A third transaction holds the owner rows, so both requests are in flight before either can count.

    With the route's `for update`, the second waits for the first and then counts one owner. Without it, both
    count two, both delete, and the workspace is left with none.
    """
    second = make_user("second@example.com", "owner")

    def session_client(user):
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url=ORIGIN,
            headers={"origin": ORIGIN},
            cookies={auth.SESSION_COOKIE: user.client.cookies[auth.SESSION_COOKIE]},
        )

    async def go():
        async with session_client(owner) as a, session_client(second) as b:
            async with engine().begin() as holder:
                await holder.execute(
                    text("select 1 from loreos.memberships where workspace_id = :w and role = 'owner' for update"),
                    {"w": DEFAULT_WORKSPACE_ID},
                )
                requests = [
                    asyncio.create_task(a.delete(f"{W}/members/{second.id}")),
                    asyncio.create_task(b.delete(f"{W}/members/{owner.id}")),
                ]
                await lock_waiters(2)
            return await asyncio.gather(*requests)

    responses = asyncio.run(go())
    assert sorted(r.status_code for r in responses) == [204, 409]
    assert len(owners()) == 1


def test_removing_a_user_of_another_workspace_gets_404_and_their_membership_stays(owner):
    b = workspace("b")
    outsider = make_user("outsider@example.com", "owner", b)
    assert owner.client.delete(f"{W}/members/{outsider.id}").status_code == 404
    assert owners(b) == {outsider.id}
    assert owner.client.delete(f"{W}/members/00000000-0000-0000-0000-00000000dead").status_code == 404


# Invites


def test_an_invite_is_listed_while_pending_and_gone_once_used(owner):
    created = owner.client.post(f"{W}/invites")
    assert created.status_code == 201
    body = created.json()
    assert set(body) == {"token", "expires_at"}
    expires = datetime.fromisoformat(body["expires_at"])
    assert abs(expires - (datetime.now(UTC) + timedelta(days=7))) < timedelta(minutes=1)
    listed = owner.client.get(f"{W}/invites").json()
    assert len(listed) == 1 and set(listed[0]) == {"created_at", "expires_at", "created_by"}
    assert listed[0]["created_by"] == str(owner.id)
    sql("update loreos.invites set used_at = now()")
    assert owner.client.get(f"{W}/invites").json() == []


def test_expired_invites_and_another_workspaces_invites_are_not_listed(owner):
    b = workspace("b")
    sql("insert into loreos.invites (token_hash, workspace_id, expires_at) values ('h1', :w, now() + interval '1 day')", w=b)
    sql(
        "insert into loreos.invites (token_hash, workspace_id, expires_at) values ('h2', :w, now() - interval '1 second')",
        w=DEFAULT_WORKSPACE_ID,
    )
    assert owner.client.get(f"{W}/invites").json() == []


def test_an_invite_is_stored_as_its_sha256_and_the_token_nowhere(owner):
    token = owner.client.post(f"{W}/invites").json()["token"]
    assert len(token) >= 43  # token_urlsafe(32)
    rows = sql("select token_hash, workspace_id, created_by from loreos.invites")
    assert [tuple(r) for r in rows] == [(hashlib.sha256(token.encode()).hexdigest(), DEFAULT_WORKSPACE_ID, owner.id)]
    assert stored_anywhere(token) == []
