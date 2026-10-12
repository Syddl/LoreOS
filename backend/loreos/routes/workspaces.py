"""Workspaces, members, invites and API keys (task 4.3).

These run in system_session, which RLS does not bind. Every statement on memberships, invites or api_keys
therefore carries `workspace_id = :w`, where :w is the path's workspace that current_member checked, so an id
from another workspace matches no row and gets 404.
"""

import secrets
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from loreos import auth
from loreos.auth import Member, User, current_user, require_owner
from loreos.db import system_session
from loreos.workspaces import Name, name_problem, workspaces_of

INVITE_DAYS = 7

router = APIRouter(prefix="/api/workspaces")
Owner = Annotated[Member, Depends(require_owner)]


class Named(BaseModel):
    name: Name


@router.get("")
async def list_workspaces(user: Annotated[User, Depends(current_user)]) -> list[dict]:
    """The user's workspaces; evaluation workspaces never, even with a membership."""
    async with system_session() as conn:
        return await workspaces_of(conn, user.id)


@router.post("", status_code=201)
async def create_workspace(body: Named, user: Annotated[User, Depends(current_user)]) -> dict:
    if problem := name_problem(body.name):
        raise HTTPException(422, problem)
    async with system_session() as conn:
        workspace_id = (
            await conn.execute(text("insert into loreos.workspaces (name) values (:n) returning id"), {"n": body.name})
        ).scalar_one()
        await conn.execute(
            text("insert into loreos.memberships (user_id, workspace_id, role) values (:u, :w, 'owner')"),
            {"u": user.id, "w": workspace_id},
        )
    return {"id": workspace_id, "name": body.name, "role": "owner"}


# Members


@router.get("/{workspace_id}/members")
async def list_members(member: Owner) -> list[dict]:
    async with system_session() as conn:
        rows = await conn.execute(
            text(
                "select m.user_id, u.email, m.role from loreos.memberships m join loreos.users u on u.id = m.user_id "
                "where m.workspace_id = :w order by m.created_at"
            ),
            {"w": member.workspace_id},
        )
        return [dict(row._mapping) for row in rows]


@router.delete("/{workspace_id}/members/{user_id}", status_code=204)
async def remove_member(user_id: uuid.UUID, member: Owner) -> None:
    """404 for a user not in this workspace; 409 for its last owner, counted with the owner rows locked.

    Without the lock, two owners removing each other would each count two owners and both succeed.
    """
    w = member.workspace_id
    async with system_session() as conn:
        owners = (
            await conn.execute(
                text("select user_id from loreos.memberships where workspace_id = :w and role = 'owner' for update"),
                {"w": w},
            )
        ).all()
        role = (
            await conn.execute(
                text("delete from loreos.memberships where workspace_id = :w and user_id = :u returning role"),
                {"w": w, "u": user_id},
            )
        ).scalar()
        if role is None:
            raise HTTPException(404, "no such member in this workspace")
        if role == "owner" and len(owners) == 1:  # raising rolls the delete back
            raise HTTPException(409, "this is the workspace's last owner; a workspace keeps at least one, and no route makes a member an owner yet")


# Invites


@router.post("/{workspace_id}/invites", status_code=201)
async def create_invite(member: Owner) -> dict:
    """A single-use link token, shown once; the database keeps its sha256."""
    token = secrets.token_urlsafe(32)
    async with system_session() as conn:
        expires_at = (
            await conn.execute(
                text(
                    "insert into loreos.invites (token_hash, workspace_id, created_by, expires_at) "
                    "values (:h, :w, :u, now() + make_interval(days => :days)) returning expires_at"
                ),
                {"h": auth.token_hash(token), "w": member.workspace_id, "u": member.user_id, "days": INVITE_DAYS},
            )
        ).scalar_one()
    return {"token": token, "expires_at": expires_at}


@router.get("/{workspace_id}/invites")
async def list_invites(member: Owner) -> list[dict]:
    """Pending invites only: unused and unexpired."""
    async with system_session() as conn:
        rows = await conn.execute(
            text(
                "select created_at, expires_at, created_by from loreos.invites "
                "where workspace_id = :w and used_at is null and expires_at > now() order by created_at"
            ),
            {"w": member.workspace_id},
        )
        return [dict(row._mapping) for row in rows]


# API keys


@router.post("/{workspace_id}/api-keys", status_code=201)
async def create_api_key(body: Named, member: Owner) -> dict:
    """The only response that carries the key."""
    async with system_session() as conn:
        key_id, key = await auth.create_key(conn, member.workspace_id, body.name)
        row = (
            await conn.execute(
                text("select id, name, prefix, created_at from loreos.api_keys where id = :id and workspace_id = :w"),
                {"id": key_id, "w": member.workspace_id},
            )
        ).one()
    return {**row._mapping, "key": key}


@router.get("/{workspace_id}/api-keys")
async def list_api_keys(member: Owner) -> list[dict]:
    """Never the key: the database has only its hash."""
    async with system_session() as conn:
        rows = await conn.execute(
            text(
                "select id, name, prefix, created_at, last_used_at, revoked_at from loreos.api_keys "
                "where workspace_id = :w order by created_at"
            ),
            {"w": member.workspace_id},
        )
        return [dict(row._mapping) for row in rows]


@router.delete("/{workspace_id}/api-keys/{key_id}", status_code=204)
async def revoke_api_key(key_id: uuid.UUID, member: Owner) -> None:
    """Sets revoked_at, keeping the first one on a repeat; 404 for a key outside this workspace."""
    async with system_session() as conn:
        revoked = (
            await conn.execute(
                text(
                    "update loreos.api_keys set revoked_at = coalesce(revoked_at, now()) "
                    "where id = :id and workspace_id = :w returning id"
                ),
                {"id": key_id, "w": member.workspace_id},
            )
        ).scalar()
    if revoked is None:
        raise HTTPException(404, "no such API key in this workspace")
