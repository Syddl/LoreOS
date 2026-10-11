"""Accounts and credentials: argon2id passwords, session cookies, API keys, and the dependencies routes use.

The auth tables have no RLS and loreos_app has no rights on them, so every lookup here runs in system_session.
Session tokens and keys are 32 random bytes; the database keeps only their sha256 hex.
"""

import asyncio
import functools
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from typing import Annotated

import argon2
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from loreos.db import system_session

MIN_PASSWORD = 12
SESSION_COOKIE = "loreos_session"
SESSION_DAYS = 14
KEY_PREFIX = "lo_sk_"

_hasher = argon2.PasswordHasher()  # its defaults are argon2id


@dataclass(frozen=True)
class User:
    id: uuid.UUID
    email: str


@dataclass(frozen=True)
class Member:
    workspace_id: uuid.UUID
    role: str
    user_id: uuid.UUID | None
    key_id: uuid.UUID | None


# Passwords


def password_problem(password: str) -> str | None:
    if len(password) < MIN_PASSWORD:
        return f"the password needs at least {MIN_PASSWORD} characters"
    return None


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """False on a mismatch and on a hash argon2 cannot read: an unreadable hash never logs anyone in."""
    try:
        return _hasher.verify(password_hash, password)
    except (argon2.exceptions.VerificationError, argon2.exceptions.InvalidHashError):
        return False


@functools.cache
def _dummy_hash() -> str:
    return hash_password(secrets.token_urlsafe(32))


async def _verify(password_hash: str, password: str) -> bool:
    """The one place a login verifies: off the event loop, and the seam a concurrency test gates."""
    return await asyncio.to_thread(verify_password, password_hash, password)


async def authenticate(conn: AsyncConnection, email: str, password: str) -> User | None:
    """The user, or None. An unknown email verifies against a dummy hash, so both failures cost one verification."""
    row = (
        await conn.execute(
            text("select id, email, password_hash from loreos.users where email = :e"), {"e": normalize_email(email)}
        )
    ).first()
    ok = await _verify(row.password_hash if row else _dummy_hash(), password)
    return User(row.id, row.email) if row and ok else None


async def create_user(conn: AsyncConnection, email: str, password: str) -> uuid.UUID:
    """Callers check password_problem first and answer 422 themselves."""
    password_hash = await asyncio.to_thread(hash_password, password)
    return (
        await conn.execute(
            text("insert into loreos.users (email, password_hash) values (:e, :h) returning id"),
            {"e": normalize_email(email), "h": password_hash},
        )
    ).scalar_one()


# Sessions and keys


def token_hash(token: str) -> str:
    """What the database keeps of a session token, an API key or an invite token: its sha256, never the token."""
    return hashlib.sha256(token.encode()).hexdigest()


async def create_session(conn: AsyncConnection, user_id: uuid.UUID) -> str:
    """A new session for user_id; the token for the cookie, which the database never sees."""
    token = secrets.token_urlsafe(32)
    await conn.execute(
        text(
            "insert into loreos.sessions (id, user_id, expires_at) "
            "values (:id, :u, now() + make_interval(days => :days))"
        ),
        {"id": token_hash(token), "u": user_id, "days": SESSION_DAYS},
    )
    return token


async def session_user(conn: AsyncConnection, token: str) -> User | None:
    """The session's user, or None when the token is unknown or the session has expired."""
    row = (
        await conn.execute(
            text(
                "select u.id, u.email from loreos.sessions s join loreos.users u on u.id = s.user_id "
                "where s.id = :id and s.expires_at > now()"
            ),
            {"id": token_hash(token)},
        )
    ).first()
    return User(row.id, row.email) if row else None


async def delete_session(conn: AsyncConnection, token: str) -> None:
    await conn.execute(text("delete from loreos.sessions where id = :id"), {"id": token_hash(token)})


async def create_key(conn: AsyncConnection, workspace_id: uuid.UUID, name: str) -> tuple[uuid.UUID, str]:
    """A secret key for workspace_id: its id, and the key itself, which is shown once and never stored."""
    body = secrets.token_urlsafe(32)
    key = KEY_PREFIX + body
    key_id = (
        await conn.execute(
            text(
                "insert into loreos.api_keys (workspace_id, kind, name, prefix, key_hash) "
                "values (:w, 'secret', :n, :p, :h) returning id"
            ),
            {"w": workspace_id, "n": name, "p": body[:8], "h": token_hash(key)},
        )
    ).scalar_one()
    return key_id, key


# Dependencies

LOG_IN = "log in first"
BAD_KEY = "the API key is unknown, malformed or revoked; create a new one in Settings"
NOT_FOUND = "workspace not found"


async def _key_member(authorization: str, workspace_id: uuid.UUID) -> Member:
    scheme, _, key = authorization.partition(" ")
    if scheme.lower() != "bearer" or not key.startswith(KEY_PREFIX):
        raise HTTPException(401, BAD_KEY)
    async with system_session() as conn:
        row = (
            await conn.execute(
                text("select id, workspace_id from loreos.api_keys where key_hash = :h and revoked_at is null"),
                {"h": token_hash(key)},
            )
        ).first()
        if row is None:
            raise HTTPException(401, BAD_KEY)
        if row.workspace_id != workspace_id:
            raise HTTPException(404, NOT_FOUND)
        await conn.execute(text("update loreos.api_keys set last_used_at = now() where id = :id"), {"id": row.id})
    return Member(workspace_id, "member", None, row.id)  # a key uploads, lists and asks; it never manages


async def current_member(request: Request, workspace_id: uuid.UUID) -> Member:
    """Who is acting on workspace_id: 401 for missing or bad credentials, 404 when they do not reach it.

    Any Authorization header decides alone, and a request carrying one never falls back to the cookie: the
    Origin check exempts Bearer requests, so a cookie behind one would be a cross-site write.
    """
    authorization = request.headers.get("authorization")
    if authorization is not None:
        return await _key_member(authorization, workspace_id)
    token = request.cookies.get(SESSION_COOKIE)
    if token is None:
        raise HTTPException(401, LOG_IN)
    async with system_session() as conn:
        user = await session_user(conn, token)
        if user is None:
            raise HTTPException(401, LOG_IN)
        role = (
            await conn.execute(
                text("select role from loreos.memberships where user_id = :u and workspace_id = :w"),
                {"u": user.id, "w": workspace_id},
            )
        ).scalar()
    if role is None:
        raise HTTPException(404, NOT_FOUND)
    return Member(workspace_id, role, user.id, None)


def require_owner(member: Annotated[Member, Depends(current_member)]) -> Member:
    """An owner logged in; a member gets 403, and so does a key, whose role is always member."""
    if member.role != "owner":
        raise HTTPException(403, "only a workspace owner can do this, logged in; API keys reach documents and ask only")
    return member


async def current_user(request: Request) -> User:
    """The logged-in user, from the cookie only: 403 for a request carrying an API key, 401 without a session."""
    if request.headers.get("authorization") is not None:
        raise HTTPException(403, "this route takes a logged-in session, not an API key")
    token = request.cookies.get(SESSION_COOKIE)
    if token is not None:
        async with system_session() as conn:
            user = await session_user(conn, token)
        if user is not None:
            return user
    raise HTTPException(401, LOG_IN)


# The cookie


def set_session_cookie(response: Response, request: Request, token: str) -> None:
    """Secure only over https, as uvicorn reports the scheme behind a trusted proxy."""
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_DAYS * 24 * 3600,
        path="/",
        secure=request.url.scheme == "https",
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax")
