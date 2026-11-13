from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


@pytest.mark.integration
def test_postgres_migrations_and_partial_unique_indexes() -> None:
    """Run against a disposable PostgreSQL database supplied by the operator.

    TEST_POSTGRES_URL must point to an empty, dedicated test database. This test
    applies the project's migrations but never drops or truncates existing data.
    """
    url = os.getenv("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set TEST_POSTGRES_URL to run PostgreSQL integration verification.")
    if not url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.fail("TEST_POSTGRES_URL must be a PostgreSQL connection URL.")

    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")

    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version()"))
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert {
            "users", "teacher_access_requests", "teacher_activation_tokens",
            "passkey_credentials", "student_face_templates", "attendance_sessions",
            "attendance_scan_events", "attendance_session_marks", "attendance_records",
        }.issubset(tables)
        user_indexes = {idx["name"] for idx in inspector.get_indexes("users")}
        session_indexes = {idx["name"] for idx in inspector.get_indexes("attendance_sessions")}
        assert "uq_single_principal_user" in user_indexes
        assert "uq_attendance_class_date" in session_indexes
    finally:
        engine.dispose()
