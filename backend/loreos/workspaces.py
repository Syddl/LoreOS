"""Workspace facts the routes share: P1's default workspace, the name rule, and a user's workspace list."""

import uuid
from typing import Annotated

from pydantic import StringConstraints
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

DEFAULT_WORKSPACE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
# The evaluation's workspaces: listed to no one, and no user may create one. evaluation/run.py builds the same prefix.
EVAL_PREFIX = "eval-"
EVAL_NAME = f"names starting with {EVAL_PREFIX} are kept for evaluation workspaces; choose another name"

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]

WORKSPACES_OF = (
    "select w.id, w.name, m.role from loreos.memberships m join loreos.workspaces w on w.id = m.workspace_id "
    "where m.user_id = :u and w.name not like :eval order by w.created_at, w.name"
)


def name_problem(name: str) -> str | None:
    """Why a user may not give a workspace this name, or None."""
    return EVAL_NAME if name.startswith(EVAL_PREFIX) else None


async def workspaces_of(conn: AsyncConnection, user_id: uuid.UUID) -> list[dict]:
    """[{id, name, role}] for each membership, oldest workspace first; evaluation workspaces never, even with one."""
    rows = await conn.execute(text(WORKSPACES_OF), {"u": user_id, "eval": EVAL_PREFIX + "%"})
    return [{"id": row.id, "name": row.name, "role": row.role} for row in rows]
