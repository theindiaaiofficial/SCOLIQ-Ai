from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_initial_migration_creates_required_schema(tmp_path: Path, monkeypatch):
    database_path = tmp_path / "migration.sqlite"
    url = f"sqlite:///{database_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    command.upgrade(config, "head")

    engine = create_engine(url)
    tables = set(inspect(engine).get_table_names())
    engine.dispose()
    required = {
        "school_profile", "users", "admin_credentials", "bootstrap_state",
        "teacher_access_requests", "teacher_activation_tokens", "passkey_credentials",
        "webauthn_challenges", "app_sessions", "classes", "teacher_class_assignments",
        "students", "student_class_enrollments", "guardian_consent_records",
        "student_face_templates", "attendance_sessions", "attendance_scan_events",
        "attendance_session_marks", "attendance_records", "audit_logs",
    }
    assert required.issubset(tables)
    columns = {column["name"] for column in inspect(engine).get_columns("school_profile")}
    assert {"logo_url", "branding"}.issubset(columns)
