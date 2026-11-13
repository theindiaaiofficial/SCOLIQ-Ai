"""Add Principal-delegated guardian-consent recording permission to teachers.

Revision ID: f5a8c2d91e44
Revises: 8d2a0f4c1b73
Create Date: 2026-11-12
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "f5a8c2d91e44"
down_revision = "8d2a0f4c1b73"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column["name"] for column in inspector.get_columns("users")}
    if "can_record_guardian_consent" not in existing:
        op.add_column(
            "users",
            sa.Column(
                "can_record_guardian_consent",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column["name"] for column in inspector.get_columns("users")}
    if "can_record_guardian_consent" in existing:
        op.drop_column("users", "can_record_guardian_consent")
