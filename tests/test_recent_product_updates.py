from __future__ import annotations

from io import BytesIO
from uuid import UUID

from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import AttendanceVerificationAttempt, PrincipalPasswordResetCode


def _different_jpeg() -> bytes:
    image = Image.new("RGB", (320, 320), "#ff0000")
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def _make_class_and_student(client: TestClient, headers: dict[str, str], *, roll: str, name: str):
    created_class = client.post(
        "/api/v1/teacher/class-setup",
        json={"grade_label": "9", "section_label": "B", "academic_year": "2026-27"},
        headers=headers,
    )
    assert created_class.status_code == 201, created_class.text
    student = client.post(
        "/api/v1/teacher/students",
        json={"full_name": name, "roll_number": roll},
        headers=headers,
    )
    assert student.status_code == 201, student.text
    return student.json()


def test_principal_password_reset_uses_one_time_email_code_and_revokes_sessions(
    client: TestClient, principal, auth_headers, monkeypatch
):
    sent: list[dict[str, str]] = []

    def fake_send(*, api_key: str, from_email: str, to_email: str, code: str) -> None:
        sent.append({"api_key": api_key, "from_email": from_email, "to_email": to_email, "code": code})

    monkeypatch.setattr("app.services.email_delivery.send_principal_password_reset_email", fake_send)
    client.app.state.settings.resend_api_key = "re_test_key"
    client.app.state.settings.resend_from_email = "SCOLIQ AI <no-reply@example.edu>"

    requested = client.post("/api/v1/admin/auth/password-reset/request", json={"email": "principal@example.edu"})
    assert requested.status_code == 200, requested.text
    assert len(sent) == 1
    assert sent[0]["to_email"] == "principal@example.edu"
    assert len(sent[0]["code"]) == 6

    with client.app.state.session_factory() as db:
        record = db.scalar(select(PrincipalPasswordResetCode).order_by(PrincipalPasswordResetCode.created_at.desc()))
        assert record is not None
        assert sent[0]["code"] not in record.code_hash
        assert record.user_id is not None

    reset = client.post(
        "/api/v1/admin/auth/password-reset/confirm",
        json={"email": "principal@example.edu", "code": sent[0]["code"], "new_password": "NewVeryLong!PrincipalPassword2"},
    )
    assert reset.status_code == 200, reset.text
    assert client.post("/api/v1/admin/auth/login", json={"email": "principal@example.edu", "password": "VeryLong!PrincipalPassword1"}).status_code == 401
    assert client.post("/api/v1/admin/auth/login", json={"email": "principal@example.edu", "password": "NewVeryLong!PrincipalPassword2"}).status_code == 200


def test_school_settings_toggle_controls_teacher_student_information(client: TestClient, principal, active_teacher, auth_headers):
    admin_headers = auth_headers(client, principal)
    teacher_headers = auth_headers(client, active_teacher)

    enabled = client.patch(
        "/api/v1/admin/settings/profile",
        json={"settings": {"student_information_enabled": True, "face_verification_attempt_limit": 3}},
        headers=auth_headers(client, principal),
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["settings"]["student_information_enabled"] is True
    assert enabled.json()["settings"]["face_verification_attempt_limit"] == 3
    form_settings = client.get("/api/v1/teacher/student-form-settings", headers=auth_headers(client, active_teacher))
    assert form_settings.status_code == 200, form_settings.text
    assert form_settings.json()["student_information_enabled"] is True

    class_response = client.post(
        "/api/v1/teacher/class-setup",
        json={"grade_label": "8", "section_label": "A", "academic_year": "2026-27"},
        headers=auth_headers(client, active_teacher),
    )
    assert class_response.status_code == 201, class_response.text
    added = client.post(
        "/api/v1/teacher/students",
        json={"full_name": "Detail Student", "roll_number": "08", "father_name": "Parent One", "mother_name": "Parent Two", "guardian_phone": "+919876543210"},
        headers=auth_headers(client, active_teacher),
    )
    assert added.status_code == 201, added.text
    details = client.get(f"/api/v1/teacher/students/{added.json()['student_id']}", headers=auth_headers(client, active_teacher))
    assert details.status_code == 200
    assert details.json()["father_name"] == "Parent One"
    assert details.json()["mother_name"] == "Parent Two"
    assert details.json()["guardian_phone"] == "+919876543210"

    disabled = client.patch(
        "/api/v1/admin/settings/profile",
        json={"settings": {"student_information_enabled": False}},
        headers=auth_headers(client, principal),
    )
    assert disabled.status_code == 200, disabled.text
    redacted = client.get(f"/api/v1/teacher/students/{added.json()['student_id']}", headers=auth_headers(client, active_teacher))
    assert redacted.status_code == 200
    assert redacted.json()["father_name"] is None
    blocked = client.post(
        "/api/v1/teacher/students",
        json={"full_name": "Blocked Detail Student", "roll_number": "09", "father_name": "Should Not Save"},
        headers=auth_headers(client, active_teacher),
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "STUDENT_INFORMATION_DISABLED"


def test_sequential_attendance_manual_confirmation_advances_to_next_student(client: TestClient, active_teacher, auth_headers):
    teacher_headers = auth_headers(client, active_teacher)
    first = _make_class_and_student(client, teacher_headers, roll="01", name="First Student")
    second = client.post(
        "/api/v1/teacher/students",
        json={"full_name": "Second Student", "roll_number": "02"},
        headers=teacher_headers,
    )
    assert second.status_code == 201, second.text

    opened = client.post("/api/v1/teacher/attendance/sessions", headers=teacher_headers)
    assert opened.status_code == 201, opened.text
    session_id = opened.json()["session_id"]
    progress = client.get(f"/api/v1/teacher/attendance/sessions/{session_id}/verification-progress", headers=teacher_headers)
    assert progress.status_code == 200
    assert progress.json()["current_student"]["enrollment_id"] == first["enrollment_id"]

    lookup = client.get(f"/api/v1/teacher/attendance/sessions/{session_id}/students/lookup", params={"q": "01"}, headers=teacher_headers)
    assert lookup.status_code == 200
    assert lookup.json()["items"][0]["enrollment_id"] == first["enrollment_id"]

    marked = client.post(
        f"/api/v1/teacher/attendance/sessions/{session_id}/manual-confirm/{first['enrollment_id']}",
        json={"status": "PRESENT"},
        headers=teacher_headers,
    )
    assert marked.status_code == 200, marked.text
    progress_after = client.get(f"/api/v1/teacher/attendance/sessions/{session_id}/verification-progress", headers=teacher_headers)
    assert progress_after.status_code == 200
    assert progress_after.json()["current_student"]["enrollment_id"] == second.json()["enrollment_id"]


def test_front_face_attempt_limit_is_per_student_and_requires_manual_fallback(
    client: TestClient, principal, active_teacher, auth_headers, sample_jpeg: bytes
):
    teacher_headers = auth_headers(client, active_teacher)
    student = _make_class_and_student(client, teacher_headers, roll="11", name="Retry Student")
    admin_headers = auth_headers(client, principal)
    consent = client.post(
        f"/api/v1/admin/students/{student['student_id']}/consent",
        json={"consent_status": "GRANTED", "consent_method": "guardian-form", "consent_record_reference": "RETRY-CONSENT"},
        headers=auth_headers(client, principal),
    )
    assert consent.status_code == 200
    enrolled = client.post(
        f"/api/v1/teacher/students/{student['student_id']}/face-enrollment",
        files=[("files", ("front.jpg", sample_jpeg, "image/jpeg"))],
        headers=auth_headers(client, active_teacher),
    )
    assert enrolled.status_code == 200, enrolled.text

    opened = client.post("/api/v1/teacher/attendance/sessions", headers=auth_headers(client, active_teacher))
    session_id = opened.json()["session_id"]
    for attempt in range(1, 6):
        scan = client.post(
            f"/api/v1/teacher/attendance/sessions/{session_id}/identify",
            data={"expected_enrollment_id": student["enrollment_id"]},
            files={"file": ("front.jpg", _different_jpeg(), "image/jpeg")},
            headers=teacher_headers,
        )
        assert scan.status_code == 200, scan.text
        assert scan.json()["status"] == "NO_MATCH"
        assert scan.json()["attempt_count"] == attempt
        assert scan.json()["manual_required"] is (attempt == 5)

    blocked = client.post(
        f"/api/v1/teacher/attendance/sessions/{session_id}/identify",
        data={"expected_enrollment_id": student["enrollment_id"]},
        files={"file": ("front.jpg", _different_jpeg(), "image/jpeg")},
        headers=teacher_headers,
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "FACE_ATTEMPT_LIMIT_REACHED"
    with client.app.state.session_factory() as db:
        attempt_row = db.scalar(select(AttendanceVerificationAttempt).where(
            AttendanceVerificationAttempt.session_id == UUID(session_id),
            AttendanceVerificationAttempt.enrollment_id == UUID(student["enrollment_id"]),
        ))
        assert attempt_row is not None and attempt_row.attempt_count == 5
