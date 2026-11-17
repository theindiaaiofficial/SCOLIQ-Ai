"""Add student profile fields, face verification attempts and password reset codes.

Revision ID: 4c7e91b2a6d0
Revises: f5a8c2d91e44
Create Date: 2026-11-17
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "4c7e91b2a6d0"
down_revision = "f5a8c2d91e44"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("students", sa.Column("father_name", sa.String(length=180), nullable=True))
    op.add_column("students", sa.Column("mother_name", sa.String(length=180), nullable=True))
    op.add_column("students", sa.Column("guardian_phone", sa.String(length=32), nullable=True))
    op.add_column("students", sa.Column("alternate_guardian_phone", sa.String(length=32), nullable=True))

    op.create_table(
        "attendance_verification_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("enrollment_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempt_count >= 0 AND attempt_count <= 5", name="ck_face_attempt_count"),
        sa.ForeignKeyConstraint(["enrollment_id"], ["student_class_enrollments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["attendance_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "enrollment_id", name="uq_face_attempt_session_enrollment"),
    )
    op.create_index("ix_face_attempt_session", "attendance_verification_attempts", ["session_id"])

    op.create_table(
        "principal_password_reset_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("email_hash", sa.String(length=64), nullable=False),
        sa.Column("ip_hash", sa.String(length=64), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("attempts >= 0 AND attempts <= 5", name="ck_password_reset_attempts"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_password_reset_email_created", "principal_password_reset_codes", ["email_hash", "created_at"])
    op.create_index("ix_password_reset_ip_created", "principal_password_reset_codes", ["ip_hash", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_password_reset_ip_created", table_name="principal_password_reset_codes")
    op.drop_index("ix_password_reset_email_created", table_name="principal_password_reset_codes")
    op.drop_table("principal_password_reset_codes")
    op.drop_index("ix_face_attempt_session", table_name="attendance_verification_attempts")
    op.drop_table("attendance_verification_attempts")
    op.drop_column("students", "alternate_guardian_phone")
    op.drop_column("students", "guardian_phone")
    op.drop_column("students", "mother_name")
    op.drop_column("students", "father_name")
