"""`python -m loreos.admin reset-password <email>`: the operator sets a user's password and ends their sessions.

The way back in after a forgotten password (decision 0006). Free: it calls no OpenAI endpoint.
"""

import asyncio
import getpass
import sys

from sqlalchemy import text

from loreos import auth
from loreos.db import system_session

USAGE = "usage: uv --directory backend run python -m loreos.admin reset-password <email>"


async def reset_password(email: str, password_hash: str) -> int | None:
    """In one transaction, the user's new hash and every one of their sessions deleted; the count, or None for no user."""
    async with system_session() as conn:
        user_id = await conn.scalar(
            text("update loreos.users set password_hash = :h where email = :e returning id"), {"h": password_hash, "e": email}
        )
        if user_id is None:
            return None
        return (await conn.execute(text("delete from loreos.sessions where user_id = :u"), {"u": user_id})).rowcount


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "reset-password":
        print(USAGE, file=sys.stderr)
        return 2
    email = auth.normalize_email(argv[1])
    password = getpass.getpass(f"new password for {email}: ")
    if getpass.getpass("type it again: ") != password:
        print("the two passwords differ; run the command again and type the same one twice", file=sys.stderr)
        return 1
    if problem := auth.password_problem(password):
        print(f"{problem}; run the command again", file=sys.stderr)
        return 1
    try:
        ended = asyncio.run(reset_password(email, auth.hash_password(password)))
    except RuntimeError as e:  # DATABASE_URL unset or on the transaction pooler; the message names the fix
        print(f"reset-password: {e}", file=sys.stderr)
        return 1
    if ended is None:
        print(f"no user has the email {email}; check the spelling", file=sys.stderr)
        return 1
    print(f"reset the password for {email} and ended {ended} sessions")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    sys.exit(main(sys.argv[1:]))
