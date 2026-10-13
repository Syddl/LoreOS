"""Read-only assertions that workspace isolation holds on DATABASE_URL: npm run db:verify-rls (python -m loreos.verify_rls).

workspace_session switches to loreos_app, so RLS binds every workspace read and write only while loreos_app
is a plain role: it cannot log in, bypasses nothing, owns nothing and reaches only documents and chunks, and only
migration 0002's policy applies to those two. Last, a session for a random workspace must count no rows there.
Prints each problem with its fix, or ok, then idle_in_transaction_session_timeout, which can abort a long
processing transaction. Exit 1 on any problem.
"""

import asyncio
import sys
import uuid

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from loreos.db import system_session, workspace_session

# Check name to message. problems() emits only these, so a test can pin a negative case to each name.
CHECKS = {
    "exists": "loreos_app does not exist; run npm run db:migrate",
    "login": "loreos_app can log in; run: alter role loreos_app nologin",
    "bypassrls": "loreos_app has BYPASSRLS, so no policy binds it; run: alter role loreos_app nobypassrls",
    "superuser": "loreos_app is a superuser, so no policy binds it; run: alter role loreos_app nosuperuser",
    "owner": (
        "loreos_app owns a relation, or holds the rights of a role that does, so RLS does not bind it there; "
        "reassign the relation, or revoke that role from loreos_app"
    ),
    "rights": (
        "loreos_app has a right on a loreos table other than documents and chunks (the workspaces and auth tables "
        "have no policy); revoke it"
    ),
    "dml": (
        "loreos_app lacks select, insert, update or delete on loreos.documents or loreos.chunks; "
        "run: grant select, insert, update, delete on loreos.documents, loreos.chunks to loreos_app"
    ),
    "rls": "row level security is off on loreos.documents or loreos.chunks; run: alter table <table> enable row level security",
    "policy": (
        "the workspace_isolation policy on loreos.documents or loreos.chunks is missing or differs from migration 0002's "
        "(permissive, for all, to loreos_app, with its using and with check condition); recreate it as 0002 does"
    ),
    "other_policy": (
        "another policy applies to loreos.documents or loreos.chunks, and permissive policies are OR-ed, so it can open "
        "every workspace's rows; list them with: select polrelid::regclass, polname from pg_policy, then drop it"
    ),
    "isolated": (
        "a session for a workspace that owns no rows still sees rows in loreos.documents or loreos.chunks, "
        "or cannot read them; fix the problems above and run npm run db:verify-rls again"
    ),
    "set_option": (
        "the connecting role cannot switch to loreos_app (no SET option); run: grant loreos_app to current_user with set true"
    ),
    "schema": "loreos_app lacks USAGE on schema loreos; run: grant usage on schema loreos to loreos_app",
    "vector_schema": (
        "loreos_app lacks USAGE on the schema that holds vector, so the vector cast fails after the embedding is paid for; "
        "grant usage on that schema to loreos_app"
    ),
    "heading_text": (
        "loreos_app cannot execute loreos.heading_text, which computes chunks.tsv, so every chunk insert fails after its "
        "embedding is paid for; run npm run db:migrate, or: grant execute on function loreos.heading_text(text[]) to loreos_app"
    ),
}

# pg_get_expr's rendering of migration 0002's ISOLATION, the condition each policy must use and check.
# test_verify_rls_finds_no_problem_on_the_migrated_database pins that the two agree.
ISOLATION = "(workspace_id = (NULLIF(current_setting('app.workspace_id'::text, true), ''::text))::uuid)"

ROLE = text("select oid from pg_roles where rolname = 'loreos_app'")
# One column per check after exists, true when it passes. Rights go through has_table_privilege and
# has_any_column_privilege, which count PUBLIC grants, inherited roles and column grants; raw ACLs miss them.
# A policy name is unique per table, so policy's count of 2 is one exact policy on each, and other_policy makes it
# the only one there.
ASSERTIONS = text(
    """
    select
        not r.rolcanlogin as login,
        not r.rolbypassrls as bypassrls,
        not r.rolsuper as superuser,
        not exists (select from pg_class c where pg_has_role(r.oid, c.relowner, 'USAGE')) as owner,
        not exists (
            select from pg_class c
            where c.relnamespace = to_regnamespace('loreos') and c.relkind in ('r', 'p', 'v', 'm', 'f')
              and c.relname not in ('documents', 'chunks')
              and (has_table_privilege(r.oid, c.oid, 'SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER')
                   or has_any_column_privilege(r.oid, c.oid, 'SELECT, INSERT, UPDATE, REFERENCES'))
        ) as rights,
        coalesce((
            select bool_and(has_table_privilege(r.oid, t, p)) and count(*) = 8
            from unnest(array[to_regclass('loreos.documents'), to_regclass('loreos.chunks')]) t,
                 unnest(array['SELECT', 'INSERT', 'UPDATE', 'DELETE']) p
            where t is not null
        ), false) as dml,
        (select count(*) = 2 from pg_class
         where oid in (to_regclass('loreos.documents'), to_regclass('loreos.chunks')) and relrowsecurity) as rls,
        (select count(*) = 2 from pg_policy p
         where p.polrelid in (to_regclass('loreos.documents'), to_regclass('loreos.chunks'))
           and p.polname = 'workspace_isolation' and p.polpermissive and p.polcmd = '*' and p.polroles = array[r.oid]
           and pg_get_expr(p.polqual, p.polrelid) = :isolation and pg_get_expr(p.polwithcheck, p.polrelid) = :isolation
        ) as policy,
        not exists (select from pg_policy p
                    where p.polrelid in (to_regclass('loreos.documents'), to_regclass('loreos.chunks'))
                      and p.polname <> 'workspace_isolation') as other_policy,
        pg_has_role(current_user, r.oid, 'SET') as set_option,
        coalesce(has_schema_privilege(r.oid, to_regnamespace('loreos'), 'USAGE'), false) as schema,
        coalesce((select has_schema_privilege(r.oid, e.extnamespace, 'USAGE') from pg_extension e where e.extname = 'vector'), false)
            as vector_schema,
        -- null, so false, when migration 0003 has not run
        coalesce(has_function_privilege(r.oid, to_regprocedure('loreos.heading_text(text[])'), 'EXECUTE'), false)
            as heading_text
    from pg_roles r where r.oid = :role
    """
)
COUNTS = text("select (select count(*) from loreos.documents) + (select count(*) from loreos.chunks)")


async def _isolated() -> bool:
    """A workspace_session for a random workspace, which owns no rows, counts none in either table. Reads only.

    It opens its own connection, as a request does. On a database with no rows yet it proves nothing; the policy
    checks carry that case.
    """
    try:
        async with workspace_session(uuid.uuid4()) as session:
            return await session.scalar(COUNTS) == 0
    except DBAPIError:  # the switch or the read is refused, so no request could read either
        return False


async def problems(conn: AsyncConnection) -> list[str]:
    """The message of every failing check; an empty list when isolation holds. Reads only."""
    role = await conn.scalar(ROLE)
    if role is None:
        return [CHECKS["exists"]]
    row = (await conn.execute(ASSERTIONS, {"role": role, "isolation": ISOLATION})).mappings().one()
    found = [CHECKS[name] for name, ok in row.items() if not ok]
    if not await _isolated():
        found.append(CHECKS["isolated"])
    return found


async def isolation_problems() -> list[str]:
    """problems() on a session of its own: what the api and the worker check before they start."""
    async with system_session() as conn:
        return await problems(conn)


async def idle_timeout(conn: AsyncConnection) -> str:
    return await conn.scalar(text("show idle_in_transaction_session_timeout"))


async def _read() -> tuple[list[str], str]:
    async with system_session() as conn:
        return await problems(conn), await idle_timeout(conn)


def main() -> int:
    try:
        found, timeout = asyncio.run(_read())
    except RuntimeError as e:  # DATABASE_URL unset or on the transaction pooler; the message names the fix
        print(f"db:verify-rls: {e}", file=sys.stderr)
        return 1
    for line in found or ["ok"]:
        print(line)
    print(f"idle_in_transaction_session_timeout: {timeout}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
