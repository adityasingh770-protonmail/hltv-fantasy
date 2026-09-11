"""Persist last successful HLTV data and refresh failures."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade():
    op.create_table(
        "ingestion_resources",
        sa.Column("key", sa.String(80), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error", sa.String(500), nullable=True),
    )


def downgrade():
    op.drop_table("ingestion_resources")
