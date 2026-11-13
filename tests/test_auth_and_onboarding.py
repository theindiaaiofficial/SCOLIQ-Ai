from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from uuid import UUID

from app.auth.sessions import issue_session
from app.models import AppSession, TeacherActivationToken, TeacherAccessRequest, User


def test_bootstrap_is_one_time_and_principal_can_login(client: TestClient, settings, principal, auth_headers):
    assert client.get("/api/v1/admin/me").status_code == 200
    second = client.post(
        "/api/v1/admin/bootstrap",
        json={
            "setup_token": settings.initial_admin_setup_token,
            "full_name": "Another Principal",
            "email": "other@example.edu",
            "password": "Another!LongPassword123",
        },
    )
    assert second.status_code == 409

    headers = auth_headers(client, principal)
    changed = client.post(
        "/api/v1/admin/auth/password",
        json={"current_password": "VeryLong!PrincipalPassword1", "new_password": "EvenLonger!PrincipalPassword2"},
        headers=headers,
    )
    assert changed.status_code == 200, changed.text
    assert client.get("/api/v1/admin/me").status_code == 200

    logout = client.post("/api/v1/admin/auth/logout", headers={"X-CSRF-Token": changed.json()["csrf_token"]})
    assert logout.status_code == 200
    assert client.get("/api/v1/admin/me").status_code == 401

    login = client.post(
        "/api/v1/admin/auth/login",
        json={"email": "principal@example.edu", "password": "EvenLonger!PrincipalPassword2"},
    )
    assert login.status_code == 200, login.text
    assert client.get("/api/v1/admin/me").status_code == 200


def test_wrong_bootstrap_token_and_csrf_are_rejected(client: TestClient, settings):
    response = client.post(
        "/api/v1/admin/bootstrap",
        json={"setup_token": "wrong-token-value-long-enough-to-pass-validation", "full_name": "Principal", "email": "p@example.edu", "password": "Long!Password123456"},
    )
    assert response.status_code == 403
    boot = client.post(
        "/api/v1/admin/bootstrap",
        json={"setup_token": settings.initial_admin_setup_token, "full_name": "Principal Person", "email": "p@example.edu", "password": "Long!Password123456"},
    )
    assert boot.status_code == 201
    response = client.patch("/api/v1/admin/settings/profile", json={"school_name": "Updated School"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_VALIDATION_FAILED"


def test_teacher_request_status_and_principal_approval(client, principal, new_teacher_request, auth_headers, app, settings):
    reference = new_teacher_request["public_reference"]
    status = client.get(f"/api/v1/teacher-requests/{reference}/status")
    assert status.status_code == 200
    assert status.json()["status"] == "PENDING"

    response = client.get("/api/v1/admin/teacher-requests")
    assert response.status_code == 200
    request_id = response.json()["items"][0]["id"]
    headers = auth_headers(client, principal)
    approved = client.post(
        f"/api/v1/admin/teacher-requests/{request_id}/approve",
        json={"review_note": "Verified against school staff records"},
        headers=headers,
    )
    assert approved.status_code == 200, approved.text
    data = approved.json()
    assert data["status"] == "APPROVED_PENDING_PASSKEY"
    assert len(data["activation_code"]) >= 40

    factory = app.state.session_factory
    with factory() as db:
        token = db.scalar(select(TeacherActivationToken).where(TeacherActivationToken.teacher_user_id == UUID(data["teacher_id"])))
        assert token is not None
        assert token.token_hash != data["activation_code"]
        assert token.redeemed_at is None

    redeemed = client.post("/api/v1/teacher/activation/redeem", json={"activation_code": data["activation_code"]})
    assert redeemed.status_code == 200, redeemed.text
    assert redeemed.json()["registration_required"] is True
    second_redeem = client.post("/api/v1/teacher/activation/redeem", json={"activation_code": data["activation_code"]})
    assert second_redeem.status_code == 400
    assert client.get("/api/v1/teacher/me").status_code == 403


def test_duplicate_phone_request_is_rejected(client: TestClient, new_teacher_request):
    duplicate = client.post(
        "/api/v1/teacher-requests",
        json={"full_name": "Duplicate Person", "phone": "+919876543211"},
    )
    assert duplicate.status_code == 409


def test_public_status_lookup_does_not_accept_short_guess(client: TestClient):
    missing = client.get("/api/v1/teacher-requests/short/status")
    assert missing.status_code == 404
    assert "error" in missing.json()


def test_unauthed_teacher_and_admin_apis_are_blocked(client: TestClient):
    assert client.get("/api/v1/admin/dashboard").status_code == 401
    assert client.get("/api/v1/teacher/me").status_code == 401


def test_invalid_payload_uses_standard_error_shape(client: TestClient):
    response = client.post("/api/v1/teacher-requests", json={"full_name": "A"})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert isinstance(body["error"]["fields"], list)


def test_passkey_api_fails_closed_when_library_is_unavailable(client: TestClient, settings, principal, new_teacher_request, auth_headers, app):
    try:
        import webauthn  # noqa: F401
    except ImportError:
        headers = auth_headers(client, principal)
        requests = client.get("/api/v1/admin/teacher-requests", headers=headers)
        request_id = requests.json()["items"][0]["id"]
        approved = client.post(
            f"/api/v1/admin/teacher-requests/{request_id}/approve",
            json={"review_note": "Verified"},
            headers=headers,
        )
        assert approved.status_code == 200
        activation = client.post("/api/v1/teacher/activation/redeem", json={"activation_code": approved.json()["activation_code"]})
        assert activation.status_code == 200
        options = client.post("/api/v1/teacher/passkeys/register/options", headers={"X-CSRF-Token": activation.json()["csrf_token"]})
        assert options.status_code == 503
        assert options.json()["error"]["code"] == "WEBAUTHN_UNAVAILABLE"
    else:
        pytest.skip("Cryptographic WebAuthn ceremony needs browser authenticator integration testing.")


def test_principal_can_suspend_teacher_and_revoke_existing_session(client, principal, active_teacher, auth_headers):
    principal_headers = auth_headers(client, principal)
    suspended = client.patch(
        f"/api/v1/admin/teachers/{active_teacher['id']}/status",
        json={"status": "SUSPENDED", "reason": "Employment status review"},
        headers=principal_headers,
    )
    assert suspended.status_code == 200
    teacher_headers = auth_headers(client, active_teacher)
    response = client.get("/api/v1/teacher/me", headers=teacher_headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "SESSION_INVALID"


def test_activation_session_can_be_recovered_after_refresh(client, principal, new_teacher_request, auth_headers):
    headers = auth_headers(client, principal)
    request_id = client.get("/api/v1/admin/teacher-requests", headers=headers).json()["items"][0]["id"]
    approved = client.post(
        f"/api/v1/admin/teacher-requests/{request_id}/approve",
        json={"review_note": "Staff identity verified"},
        headers=headers,
    )
    assert approved.status_code == 200
    redeemed = client.post(
        "/api/v1/teacher/activation/redeem",
        json={"activation_code": approved.json()["activation_code"]},
    )
    assert redeemed.status_code == 200
    status = client.get("/api/v1/teacher/activation/status")
    assert status.status_code == 200
    assert status.json()["registration_required"] is True
    assert status.json()["full_name"] == "New Teacher"
