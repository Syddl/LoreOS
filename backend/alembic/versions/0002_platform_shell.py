"""Platform shell: accounts, keys, rate limits, the worker's columns, and workspace isolation by RLS.

Revision ID: 0002_platform
Revises: 0001

The id is 0002_platform, not 0002, so a database at P3's own 0002 shows up as a second head and fails loudly.
"""

from alembic import op

revision = "0002_platform"
down_revision = "0001"
branch_labels = None
depends_on = None

ISOLATION = "workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid"


def upgrade() -> None:
    op.execute(
        """
        create table loreos.users (
            id uuid primary key default gen_random_uuid(),
            email text not null unique check (email = lower(email)),
            password_hash text not null,
            created_at timestamptz not null default now()
        )
        """
    )
    op.execute(
        """
        create table loreos.memberships (
            user_id uuid not null references loreos.users (id) on delete cascade,
            workspace_id uuid not null references loreos.workspaces (id) on delete cascade,
            role text not null check (role in ('owner', 'member')),
            created_at timestamptz not null default now(),
            primary key (user_id, workspace_id)
        )
        """
    )
    op.execute(
        """
        create table loreos.sessions (
            id text primary key,
            user_id uuid not null references loreos.users (id) on delete cascade,
            created_at timestamptz not null default now(),
            expires_at timestamptz not null
        )
        """
    )
    op.execute(
        """
        create table loreos.invites (
            token_hash text primary key,
            workspace_id uuid not null references loreos.workspaces (id) on delete cascade,
            created_by uuid references loreos.users (id) on delete set null,
            created_at timestamptz not null default now(),
            expires_at timestamptz not null,
            used_at timestamptz
        )
        """
    )
    op.execute(
        """
        create table loreos.api_keys (
            id uuid primary key default gen_random_uuid(),
            workspace_id uuid not null references loreos.workspaces (id) on delete cascade,
            kind text not null check (kind in ('secret')),
            name text not null,
            prefix text not null,
            key_hash text not null unique,
            created_at timestamptz not null default now(),
            last_used_at timestamptz,
            revoked_at timestamptz
        )
        """
    )
    op.execute(
        """
        create table loreos.rate_limits (
            bucket text not null,
            window_start timestamptz not null,
            count int not null default 0,
            primary key (bucket, window_start)
        )
        """
    )

    # The worker's columns. A queued URL document has no content until the worker fetches it.
    op.execute("alter table loreos.documents drop constraint documents_kind_check")
    op.execute(
        "alter table loreos.documents add constraint documents_kind_check "
        "check (kind in ('md', 'txt', 'pdf', 'docx', 'url'))"
    )
    op.execute("alter table loreos.documents alter column content drop not null")
    op.execute(
        "alter table loreos.documents add column source_url text, "
        "add column next_attempt_at timestamptz, add column locked_until timestamptz"
    )

    # loreos_app: what workspace_session switches to, so RLS binds even a connecting role that owns the tables
    # or carries BYPASSRLS (postgres on Supabase). Roles are cluster-wide, and two checkouts can migrate at once:
    # concurrent create role statements fail with unique_violation rather than duplicate_object.
    op.execute(
        "do $$ begin create role loreos_app nologin; "
        "exception when duplicate_object or unique_violation then null; end $$"
    )
    op.execute("grant loreos_app to current_user with set true")  # PG16+ gives the creator ADMIN but not SET
    op.execute("grant usage on schema loreos to loreos_app")
    # vector's schema: public on testdb, extensions on Supabase. Without USAGE the vector cast fails after the
    # embedding is paid for.
    op.execute(
        "do $$ declare s text; begin "
        "select n.nspname into strict s from pg_extension e join pg_namespace n on n.oid = e.extnamespace "
        "where e.extname = 'vector'; "
        "execute format('grant usage on schema %I to loreos_app', s); end $$"
    )
    op.execute("grant select, insert, update, delete on loreos.documents, loreos.chunks to loreos_app")
    for table in ("documents", "chunks"):
        op.execute(f"alter table loreos.{table} enable row level security")
        op.execute(
            f"create policy workspace_isolation on loreos.{table} for all to loreos_app "
            f"using ({ISOLATION}) with check ({ISOLATION})"
        )


def downgrade() -> None:
    raise NotImplementedError("0002 is not reversed: restore from a backup instead")
