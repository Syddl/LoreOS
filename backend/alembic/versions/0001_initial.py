"""Initial schema: workspaces, documents and chunks in the loreos schema.

Revision ID: 0001
Revises:
"""

from alembic import op

from loreos.embeddings import EMBEDDING_DIM
from loreos.workspaces import DEFAULT_WORKSPACE_ID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A no-op on Supabase, where vector is already installed in the extensions schema.
    op.execute("create extension if not exists vector")
    op.execute(
        """
        create table loreos.workspaces (
            id uuid primary key default gen_random_uuid(),
            name text not null,
            created_at timestamptz not null default now()
        )
        """
    )
    op.execute(
        """
        create table loreos.documents (
            id uuid primary key default gen_random_uuid(),
            workspace_id uuid not null references loreos.workspaces (id) on delete cascade,
            filename text not null,
            kind text not null check (kind in ('md', 'txt', 'pdf')),
            sha256 text not null,
            content bytea not null,
            status text not null default 'pending'
                check (status in ('pending', 'processing', 'processed', 'failed')),
            error text,
            attempts int not null default 0,
            created_at timestamptz not null default now(),
            processed_at timestamptz,
            unique (workspace_id, sha256),
            unique (id, workspace_id)
        )
        """
    )
    # ponytail: no vector index, so search is an exact scan and Recall@5 measures the method, not an
    # approximate index; add HNSW with iterative scan for the workspace filter past about 50k chunks.
    op.execute(
        f"""
        create table loreos.chunks (
            id uuid primary key default gen_random_uuid(),
            workspace_id uuid not null,
            document_id uuid not null,
            ordinal int not null,
            text text not null,
            heading_path text[] not null default '{{}}',
            page int,
            token_count int not null,
            embedding vector({EMBEDDING_DIM}) not null,
            unique (document_id, ordinal),
            foreign key (document_id, workspace_id)
                references loreos.documents (id, workspace_id) on delete cascade
        )
        """
    )
    op.execute(f"insert into loreos.workspaces (id, name) values ('{DEFAULT_WORKSPACE_ID}', 'Default')")


def downgrade() -> None:
    raise NotImplementedError("0001 creates the schema; there is nothing earlier to return to")
