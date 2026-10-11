"""Signup, login, logout, me and invite acceptance (task 4.2).

The auth tables have no RLS and loreos_app has no rights on them, so every route here runs in system_session.
Never add CORS middleware: the Origin rule exempts Bearer requests only because another site's page cannot send
an Authorization header without a preflight this api never answers.
"""

import math
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from loreos import auth, ratelimit
from loreos.db import system_session
from loreos.workspaces import DEFAULT_WORKSPACE_ID

router = APIRouter()

LOGIN_WINDOW_S = 900
EMAIL_LIMIT = 5
IP_LIMIT = 20
UNIQUE_VIOLATION = "23505"
DEFAULT_WORKSPACE_NAME = "My workspace"

BAD_LOGIN = "the email or password is wrong"
SIGNUP_CLOSED = "signup is closed because this LoreOS already has an account; ask a workspace owner for an invite link"
INVITE_GONE = "this invite link is unknown, used or expired; ask the workspace owner for a new one"
EMAIL_TAKEN = "an account with this email already exists; log in, then open the invite link again"
NEED_ACCOUNT = "send an email and a password to create an account, or log in first"

WORKSPACES_OF = (
    "select w.id, w.name, m.role from loreos.memberships m join loreos.workspaces w on w.id = m.workspace_id "
    "where m.user_id = :u order by w.created_at desc, w.id"
)
USE_INVITE = (
    "update loreos.invites set used_at = now() "
    "where token_hash = :h and used_at is null and expires_at > now() returning workspace_id"
)

# The length bound keeps a rate-limit bucket key inside a btree entry; the pattern refuses a blank or @-less email.
Email = Annotated[str, Field(max_length=320, pattern=r"^\s*[^@\s]+@[^@\s]+\s*$")]


class Credentials(BaseModel):
    email: Email
    password: str


class Signup(Credentials):
    workspace_name: str | None = None


class Accept(BaseModel):
    token: str
    email: Email | None = None
    password: str | None = None


async def workspaces_of(conn: AsyncConnection, user_id: uuid.UUID) -> list[dict]:
    """[{id, name, role}] for each membership, newest workspace first. Evaluation workspaces have none, so never show."""
    rows = await conn.execute(text(WORKSPACES_OF), {"u": user_id})
    return [{"id": row.id, "name": row.name, "role": row.role} for row in rows]


async def me_of(conn: AsyncConnection, user: auth.User) -> dict:
    return {"user": {"id": user.id, "email": user.email}, "workspaces": await workspaces_of(conn, user.id)}


@router.post("/api/auth/signup", status_code=201)
async def signup(body: Signup, request: Request, response: Response) -> dict:
    """The first account only: owner of a new workspace and of Default. The lock serialises two first signups."""
    if problem := auth.password_problem(body.password):
        raise HTTPException(422, problem)
    async with system_session() as conn:
        await conn.execute(text("select pg_advisory_xact_lock(hashtext('loreos.signup'))"))
        if (await conn.execute(text("select exists (select from loreos.users)"))).scalar():
            raise HTTPException(403, SIGNUP_CLOSED)
        user = auth.User(await auth.create_user(conn, body.email, body.password), auth.normalize_email(body.email))
        name = (body.workspace_name or "").strip() or DEFAULT_WORKSPACE_NAME
        workspace_id = (
            await conn.execute(text("insert into loreos.workspaces (name) values (:n) returning id"), {"n": name})
        ).scalar_one()
        await conn.execute(
            text("insert into loreos.memberships (user_id, workspace_id, role) values (:u, :w, 'owner'), (:u, :d, 'owner')"),
            {"u": user.id, "w": workspace_id, "d": DEFAULT_WORKSPACE_ID},
        )
        token = await auth.create_session(conn, user.id)
        me = await me_of(conn, user)
    auth.set_session_cookie(response, request, token)
    return me


@router.post("/api/auth/login")
async def login(body: Credentials, request: Request, response: Response) -> dict:
    """Behaviour 8: reserve a slot in both buckets before verifying, so parallel guesses cannot all pass; a success
    refunds both, so only failures stay counted. Each rate-limit call is its own short session, outside authenticate's.
    """
    host = request.client.host if request.client else "unknown"
    buckets = [(f"login:email:{auth.normalize_email(body.email)}", EMAIL_LIMIT), (f"login:ip:{host}", IP_LIMIT)]
    slots = [await ratelimit.rate_limit(bucket, limit, LOGIN_WINDOW_S) for bucket, limit in buckets]
    refused = [slot.retry_after for slot in slots if not slot.allowed]
    if refused:
        wait = max(refused)
        detail = f"too many login attempts; try again in {math.ceil(wait / 60)} minutes, or ask the operator to reset the password"
        raise HTTPException(429, detail, headers={"Retry-After": str(wait)})
    async with system_session() as conn:
        user = await auth.authenticate(conn, body.email, body.password)
        if user is None:
            raise HTTPException(401, BAD_LOGIN)  # both reservations stay counted
        token = await auth.create_session(conn, user.id)
        me = await me_of(conn, user)
    for (bucket, _), slot in zip(buckets, slots, strict=True):
        await ratelimit.refund(bucket, slot.window_start)
    auth.set_session_cookie(response, request, token)
    return me


@router.post("/api/auth/logout", status_code=204)
async def logout(request: Request, response: Response, user: Annotated[auth.User, Depends(auth.current_user)]) -> None:
    """current_user has refused any Authorization header and checked the session, so the cookie read here is valid."""
    async with system_session() as conn:
        await auth.delete_session(conn, request.cookies[auth.SESSION_COOKIE])
    auth.clear_session_cookie(response)


@router.get("/api/me")
async def get_me(user: Annotated[auth.User, Depends(auth.current_user)]) -> dict:
    async with system_session() as conn:
        return await me_of(conn, user)


@router.post("/api/invites/accept")
async def accept_invite(body: Accept, request: Request, response: Response) -> dict:
    """One transaction: use the invite, then join as the logged-in user (200) or create the account (201).

    Any refusal after the invite is used raises inside the transaction, so it rolls back and the invite stays usable.
    A stale or unknown cookie counts as logged out: the invite screen offers the account form after /api/me's 401.
    """
    try:
        user = await auth.current_user(request)  # 403 for an Authorization header, as on every cookie route
    except HTTPException as e:
        if e.status_code != 401:
            raise
        user = None
    async with system_session() as conn:
        workspace_id = (await conn.execute(text(USE_INVITE), {"h": auth._sha256(body.token)})).scalar()
        if workspace_id is None:
            raise HTTPException(404, INVITE_GONE)
        token = None
        if user is None:
            if body.email is None or body.password is None:
                raise HTTPException(422, NEED_ACCOUNT)
            if problem := auth.password_problem(body.password):
                raise HTTPException(422, problem)
            try:
                user_id = await auth.create_user(conn, body.email, body.password)
            except IntegrityError as e:
                if getattr(e.orig, "sqlstate", None) != UNIQUE_VIOLATION:
                    raise
                raise HTTPException(409, EMAIL_TAKEN) from None
            user = auth.User(user_id, auth.normalize_email(body.email))
            token = await auth.create_session(conn, user.id)
        await conn.execute(
            text(
                "insert into loreos.memberships (user_id, workspace_id, role) values (:u, :w, 'member') "
                "on conflict (user_id, workspace_id) do nothing"
            ),
            {"u": user.id, "w": workspace_id},
        )
        me = await me_of(conn, user)
    if token is not None:
        auth.set_session_cookie(response, request, token)
        response.status_code = 201
    return me
