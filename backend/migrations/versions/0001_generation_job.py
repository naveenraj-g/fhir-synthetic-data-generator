"""generation_job

Revision ID: 0001
Revises:
Create Date: 2026-10-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "generation_job",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("connector", sa.String(), nullable=True),
        sa.Column("preset", sa.String(), nullable=True),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("resolved_spec", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("artifacts", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_generation_job_status", "generation_job", ["status"])


def downgrade() -> None:
    op.drop_index("ix_generation_job_status", table_name="generation_job")
    op.drop_table("generation_job")
