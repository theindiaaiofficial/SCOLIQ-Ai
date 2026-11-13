from fastapi.testclient import TestClient
from uuid import UUID

from app.models import AuditLog, SchoolProfile, User


def test_principal_can_reset_operational_data_without_losing_school_identity(
    client: TestClient, principal: dict[str, str], active_teacher: dict[str, str], auth_headers
):
    factory = client.app.state.session_factory
    with factory.begin() as db:
        profile = db.get(SchoolProfile, 1)
        profile.school_name = "Demo School"
        profile.logo_url = "https://example.edu/logo.png"
        teacher = db.get(User, UUID(active_teacher["id"]))
        assert teacher is not None

    headers = auth_headers(client, principal)
    response = client.post(
        "/api/v1/admin/system/reset-school-data",
        headers=headers,
        json={
            "current_password": "VeryLong!PrincipalPassword1",
            "confirmation": "RESET SCHOOL DATA",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["deleted_counts"]["teacher_accounts"] == 1
    assert "principal_account" in body["preserved"]

    assert client.get("/api/v1/admin/me").status_code == 200
    teachers = client.get("/api/v1/admin/teachers", headers=headers)
    assert teachers.status_code == 200
    assert teachers.json()["total"] == 0

    profile_response = client.get("/api/v1/admin/settings/profile", headers=headers)
    assert profile_response.status_code == 200
    assert profile_response.json()["school_name"] == "Demo School"
    assert profile_response.json()["logo_url"] == "https://example.edu/logo.png"

    with factory.begin() as db:
        assert db.query(User).filter(User.role == "TEACHER").count() == 0
        assert db.query(AuditLog).count() == 1
        event = db.query(AuditLog).one()
        assert event.action == "SCHOOL_DATA_RESET"


def test_school_reset_rejects_wrong_principal_password(
    client: TestClient, principal: dict[str, str], active_teacher: dict[str, str], auth_headers
):
    headers = auth_headers(client, principal)
    response = client.post(
        "/api/v1/admin/system/reset-school-data",
        headers=headers,
        json={"current_password": "wrong-password", "confirmation": "RESET SCHOOL DATA"},
    )
    assert response.status_code == 401
    teachers = client.get("/api/v1/admin/teachers", headers=headers)
    assert teachers.status_code == 200
    assert teachers.json()["total"] == 1
