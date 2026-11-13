from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.auth.sessions import issue_session
from app.core.config import Settings
from app.database import Base, build_engine
from app.main import create_app
from app.models import User


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        app_base_url="http://localhost:8000",
        database_url=f"sqlite:///{tmp_path / 'smartattend-test.sqlite'}",
        session_secret="pytest-session-secret-with-at-least-32-bytes",
        initial_admin_setup_token="pytest-initial-admin-token-with-32-chars-minimum",
        cors_allowed_origins=["http://localhost:3000"],
        cookie_secure=False,
        webauthn_rp_id="localhost",
        webauthn_origin="http://localhost:3000",
        face_provider="fake",
        face_template_encryption_key=base64.b64encode(b"t" * 32).decode("ascii"),
        rate_limit_requests=100,
        rate_limit_window_seconds=60,
    )


@pytest.fixture
def app(settings: Settings):
    engine = build_engine(settings.database_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return create_app(settings)


@pytest.fixture
def client(app) -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def principal(client: TestClient, settings: Settings) -> dict[str, str]:
    response = client.post(
        "/api/v1/admin/bootstrap",
        json={
            "setup_token": settings.initial_admin_setup_token,
            "full_name": "School Principal",
            "email": "principal@example.edu",
            "password": "VeryLong!PrincipalPassword1",
        },
    )
    assert response.status_code == 201, response.text
    return {
        "csrf": response.json()["csrf_token"],
        "session": client.cookies.get("smartattend_session"),
    }


@pytest.fixture
def active_teacher(client: TestClient, settings: Settings) -> dict[str, str]:
    factory = client.app.state.session_factory
    with factory.begin() as db:
        teacher = User(
            full_name="Class Teacher",
            phone="9876543210",
            email="teacher@example.edu",
            role="TEACHER",
            status="ACTIVE",
        )
        db.add(teacher)
        db.flush()
        raw, csrf, _ = issue_session(db, teacher.id, settings)
        teacher_id = str(teacher.id)
    return {"id": teacher_id, "csrf": csrf, "session": raw}


def use_session(client: TestClient, session: dict[str, str]) -> dict[str, str]:
    client.cookies.set("smartattend_session", session["session"], domain="testserver.local", path="/")
    csrf = session["csrf"]
    client.cookies.set("smartattend_csrf", csrf, domain="testserver.local", path="/")
    return {"X-CSRF-Token": csrf}


@pytest.fixture
def auth_headers():
    return use_session


@pytest.fixture
def sample_jpeg() -> bytes:
    from io import BytesIO

    from PIL import Image

    image = Image.new("RGB", (320, 320), "#d8d8d8")
    target = BytesIO()
    image.save(target, format="JPEG", quality=90)
    return target.getvalue()


@pytest.fixture
def new_teacher_request(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/api/v1/teacher-requests",
        json={
            "full_name": "New Teacher",
            "phone": "+919876543211",
            "email": "new.teacher@example.edu",
            "staff_identifier": "STAFF-009",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()
