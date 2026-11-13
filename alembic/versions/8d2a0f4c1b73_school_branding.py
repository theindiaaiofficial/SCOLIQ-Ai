"""Persist school logo URL and validated visual branding.

Revision ID: 8d2a0f4c1b73
Revises: 154fdef3b0f4
Create Date: 2026-11-09
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "8d2a0f4c1b73"
down_revision = "154fdef3b0f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.add_column("school_profile", sa.Column("logo_url", sa.String(length=2048), nullable=True))
    op.add_column(
        "school_profile",
        sa.Column("branding", json_type, nullable=False, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    op.drop_column("school_profile", "branding")
    op.drop_column("school_profile", "logo_url")
