"""Keyword search: chunks.tsv, generated from the heading path and the text, with a GIN index.

Revision ID: 0003_keyword_search
Revises: 0002_platform

Adding a stored generated column computes it for every existing row. A generated column refuses a function that is
not immutable, and array_to_string is only stable, so the heading path goes through loreos.heading_text.
"""

from alembic import op

revision = "0003_keyword_search"
down_revision = "0002_platform"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Immutable in practice: text[] to text with a fixed separator depends on no setting.
    op.execute(
        """
        create function loreos.heading_text(text[]) returns text
        language sql immutable parallel safe
        return pg_catalog.array_to_string($1, ' ')
        """
    )
    # A chunk insert by loreos_app computes tsv, so it needs execute; not left to PUBLIC's default grant.
    op.execute("grant execute on function loreos.heading_text(text[]) to loreos_app")
    op.execute(
        """
        alter table loreos.chunks add column tsv tsvector generated always as
            (to_tsvector('english', loreos.heading_text(heading_path) || ' ' || text)) stored
        """
    )
    op.execute("create index chunks_tsv on loreos.chunks using gin (tsv)")


def downgrade() -> None:
    raise NotImplementedError("0003 is not reversed: restore from a backup instead")
