from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import AttendanceRecord, AttendanceScanEvent, AttendanceSessionMark, AuditLog, GuardianConsentRecord, StudentFaceTemplate


def _setup_class_and_student(client: TestClient, auth_headers: dict[str, str], *, roll: str, name: str):
    class_response = client.post(
        "/api/v1/teacher/class-setup",
        json={"grade_label": "11", "section_label": "A", "academic_year": "2026-27"},
        headers=auth_headers,
    )
    assert class_response.status_code == 201, class_response.text
    student_response = client.post(
        "/api/v1/teacher/students",
        json={"full_name": name, "roll_number": roll},
        headers=auth_headers,
    )
    assert student_response.status_code == 201, student_response.text
    return class_response.json(), student_response.json()


def test_face_identification_review_and_finalization_are_teacher_confirmed(
    client: TestClient, principal, active_teacher, auth_headers, sample_jpeg: bytes, app
):
    teacher_headers = auth_headers(client, active_teacher)
    _, first = _setup_class_and_student(client, teacher_headers, roll="01", name="Student One")
    _, second = _setup_class_and_student(client, teacher_headers, roll="02", name="Student Two")

    admin_headers = auth_headers(client, principal)
    consent = client.post(
        f"/api/v1/admin/students/{first['student_id']}/consent",
        json={"consent_status": "GRANTED", "consent_method": "signed-paper", "consent_record_reference": "CONSENT-01"},
        headers=admin_headers,
    )
    assert consent.status_code == 200
    teacher_headers = auth_headers(client, active_teacher)

    face_enrollment = client.post(
        f"/api/v1/teacher/students/{first['student_id']}/face-enrollment",
        files=[("files", ("capture.jpg", sample_jpeg, "image/jpeg"))],
        headers=teacher_headers,
    )
    assert face_enrollment.status_code == 200, face_enrollment.text
    with app.state.session_factory() as db:
        stored = db.scalar(select(StudentFaceTemplate).where(StudentFaceTemplate.student_id == UUID(first["student_id"])))
        assert stored is not None and stored.is_active
        assert sample_jpeg not in stored.ciphertext

    opened = client.post("/api/v1/teacher/attendance/sessions", headers=teacher_headers)
    assert opened.status_code == 201, opened.text
    session_id = opened.json()["session_id"]
    repeated_open = client.post("/api/v1/teacher/attendance/sessions", headers=teacher_headers)
    assert repeated_open.status_code == 201
    assert repeated_open.json()["session_id"] == session_id

    scan = client.post(
        f"/api/v1/teacher/attendance/sessions/{session_id}/identify",
        files=[
            ("files", ("front.jpg", sample_jpeg, "image/jpeg")),
            ("files", ("left.jpg", sample_jpeg, "image/jpeg")),
            ("files", ("right.jpg", sample_jpeg, "image/jpeg")),
        ],
        headers=teacher_headers,
    )
    assert scan.status_code == 200, scan.text
    assert scan.json()["status"] == "MATCHED"
    assert scan.json()["capture_count"] == 3
    assert scan.json()["score_aggregation"] == "mean_of_best_two_capture_scores"
    assert scan.json()["provisional_present_count"] == 1
    duplicate = client.post(
        f"/api/v1/teacher/attendance/sessions/{session_id}/identify",
        files={"file": ("scan.jpg", sample_jpeg, "image/jpeg")},
        headers=teacher_headers,
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "DUPLICATE"
    assert duplicate.json()["provisional_present_count"] == 1

    review = client.get(f"/api/v1/teacher/attendance/sessions/{session_id}/review")
    assert review.status_code == 200
    assert len(review.json()["absent_candidates"]) == 1
    incomplete = client.post(
        f"/api/v1/teacher/attendance/sessions/{session_id}/finalize",
        json={"confirmation": "CONFIRM_ALL_STATUSES"},
        headers=teacher_headers,
    )
    assert incomplete.status_code == 409
    assert incomplete.json()["error"]["code"] == "ATTENDANCE_REVIEW_INCOMPLETE"

    mark_first = client.patch(
        f"/api/v1/teacher/attendance/sessions/{session_id}/marks/{first['enrollment_id']}",
        json={"status": "PRESENT", "notes": "Teacher verified"},
        headers=teacher_headers,
    )
    mark_second = client.patch(
        f"/api/v1/teacher/attendance/sessions/{session_id}/marks/{second['enrollment_id']}",
        json={"status": "ABSENT", "notes": "Not present after manual check"},
        headers=teacher_headers,
    )
    assert mark_first.status_code == 200
    assert mark_second.status_code == 200

    finalized = client.post(
        f"/api/v1/teacher/attendance/sessions/{session_id}/finalize",
        json={"confirmation": "CONFIRM_ALL_STATUSES"},
        headers=teacher_headers,
    )
    assert finalized.status_code == 200, finalized.text
    assert finalized.json()["present_count"] == 1
    assert finalized.json()["absent_count"] == 1
    replay = client.post(
        f"/api/v1/teacher/attendance/sessions/{session_id}/finalize",
        json={"confirmation": "CONFIRM_ALL_STATUSES"},
        headers=teacher_headers,
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True

    with app.state.session_factory() as db:
        records = db.scalars(select(AttendanceRecord).where(AttendanceRecord.attendance_session_id == UUID(session_id))).all()
        events = db.scalars(select(AttendanceScanEvent).where(AttendanceScanEvent.session_id == UUID(session_id))).all()
        assert len(records) == 2
        assert len(events) == 2
        # A teacher's confirmation of the unchanged face candidate preserves its provenance.
        first_record = next(record for record in records if record.student_enrollment_id == UUID(first["enrollment_id"]))
        assert first_record.identification_method == "FACE_MATCH"

    admin_headers = auth_headers(client, principal)
    reports = client.get(f"/api/v1/admin/attendance/reports?from_date={date.today().isoformat()}&to_date={date.today().isoformat()}")
    assert reports.status_code == 200, reports.text
    assert any(item["session_id"] == session_id for item in reports.json()["items"])

    reopened = client.post(
        f"/api/v1/admin/attendance/sessions/{session_id}/reopen",
        json={"reason": "Principal approved correction"},
        headers=admin_headers,
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "REOPENED"
    # Existing unique provisional marks must be updated, not duplicated.
    with app.state.session_factory() as db:
        marks = db.scalars(select(AttendanceSessionMark).where(AttendanceSessionMark.session_id == UUID(session_id))).all()
        assert len(marks) == 2
        assert all(mark.source == "ADMIN" and mark.is_confirmed for mark in marks)


def test_face_consent_withdrawal_physically_removes_templates(
    client: TestClient, principal, active_teacher, auth_headers, sample_jpeg: bytes, app
):
    teacher_headers = auth_headers(client, active_teacher)
    _, student = _setup_class_and_student(client, teacher_headers, roll="10", name="Consent Student")
    admin_headers = auth_headers(client, principal)
    grant = client.post(
        f"/api/v1/admin/students/{student['student_id']}/consent",
        json={"consent_status": "GRANTED", "consent_method": "signed-paper", "consent_record_reference": "CONSENT-10"},
        headers=admin_headers,
    )
    assert grant.status_code == 200
    teacher_headers = auth_headers(client, active_teacher)
    enrollment = client.post(
        f"/api/v1/teacher/students/{student['student_id']}/face-enrollment",
        files=[("files", ("capture.jpg", sample_jpeg, "image/jpeg"))],
        headers=teacher_headers,
    )
    assert enrollment.status_code == 200
    admin_headers = auth_headers(client, principal)
    withdrawn = client.post(
        f"/api/v1/admin/students/{student['student_id']}/consent",
        json={"consent_status": "WITHDRAWN", "consent_method": "guardian-withdrawal", "consent_record_reference": "WITHDRAW-10"},
        headers=admin_headers,
    )
    assert withdrawn.status_code == 200
    with app.state.session_factory() as db:
        count = db.scalar(select(StudentFaceTemplate.id).where(StudentFaceTemplate.student_id == UUID(student["student_id"])))
        assert count is None


def test_manual_marking_path_works_without_face_processing(client: TestClient, active_teacher, auth_headers):
    teacher_headers = auth_headers(client, active_teacher)
    _, student = _setup_class_and_student(client, teacher_headers, roll="20", name="Manual Student")
    opened = client.post("/api/v1/teacher/attendance/sessions", headers=teacher_headers)
    session_id = opened.json()["session_id"]
    review = client.get(f"/api/v1/teacher/attendance/sessions/{session_id}/review")
    assert review.status_code == 200
    mark = client.patch(
        f"/api/v1/teacher/attendance/sessions/{session_id}/marks/{student['enrollment_id']}",
        json={"status": "EXCUSED", "notes": "Manual alternative"},
        headers=teacher_headers,
    )
    assert mark.status_code == 200
    finalized = client.post(
        f"/api/v1/teacher/attendance/sessions/{session_id}/finalize",
        json={"confirmation": "CONFIRM_ALL_STATUSES"},
        headers=teacher_headers,
    )
    assert finalized.status_code == 200
    assert finalized.json()["present_count"] == 0
    assert finalized.json()["absent_count"] == 0


def test_teacher_cannot_read_another_teachers_attendance_session(
    client: TestClient, active_teacher, auth_headers, app, settings
):
    teacher_headers = auth_headers(client, active_teacher)
    _setup_class_and_student(client, teacher_headers, roll="90", name="Private Roster Student")
    opened = client.post("/api/v1/teacher/attendance/sessions", headers=teacher_headers)
    assert opened.status_code == 201
    session_id = opened.json()["session_id"]

    from app.auth.sessions import issue_session
    from app.models import User

    with app.state.session_factory.begin() as db:
        outsider = User(full_name="Different Teacher", role="TEACHER", status="ACTIVE")
        db.add(outsider)
        db.flush()
        raw, csrf, _ = issue_session(db, outsider.id, settings)
        other_session = {"session": raw, "csrf": csrf}

    outsider_headers = auth_headers(client, other_session)
    response = client.get(f"/api/v1/teacher/attendance/sessions/{session_id}/review", headers=outsider_headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN_CLASS_ACCESS"


def test_face_provider_unavailable_is_recorded_and_manual_review_remains_available(
    client: TestClient, active_teacher, auth_headers, sample_jpeg: bytes, app
):
    from app.face.provider import ManualOnlyProvider

    teacher_headers = auth_headers(client, active_teacher)
    _, _ = _setup_class_and_student(client, teacher_headers, roll="70", name="Manual Fallback Student")
    opened = client.post("/api/v1/teacher/attendance/sessions", headers=teacher_headers)
    session_id = opened.json()["session_id"]

    app.state.face_provider = ManualOnlyProvider()
    response = client.post(
        f"/api/v1/teacher/attendance/sessions/{session_id}/identify",
        files={"file": ("scan.jpg", sample_jpeg, "image/jpeg")},
        headers=teacher_headers,
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "FACE_PROVIDER_UNAVAILABLE"
    with app.state.session_factory() as db:
        event = db.scalar(select(AttendanceScanEvent).where(AttendanceScanEvent.session_id == UUID(session_id)))
        assert event is not None and event.result_status == "PROVIDER_UNAVAILABLE"

    review = client.get(f"/api/v1/teacher/attendance/sessions/{session_id}/review")
    assert review.status_code == 200
    assert len(review.json()["absent_candidates"]) == 1


def test_face_identification_is_locked_after_finalization(
    client: TestClient, active_teacher, auth_headers, sample_jpeg: bytes
):
    teacher_headers = auth_headers(client, active_teacher)
    _, student = _setup_class_and_student(client, teacher_headers, roll="71", name="Finalized Student")
    opened = client.post("/api/v1/teacher/attendance/sessions", headers=teacher_headers)
    session_id = opened.json()["session_id"]
    assert client.get(f"/api/v1/teacher/attendance/sessions/{session_id}/review").status_code == 200
    marked = client.patch(
        f"/api/v1/teacher/attendance/sessions/{session_id}/marks/{student['enrollment_id']}",
        json={"status": "PRESENT"},
        headers=teacher_headers,
    )
    assert marked.status_code == 200
    finalized = client.post(
        f"/api/v1/teacher/attendance/sessions/{session_id}/finalize",
        json={"confirmation": "CONFIRM_ALL_STATUSES"},
        headers=teacher_headers,
    )
    assert finalized.status_code == 200

    scan_after_final = client.post(
        f"/api/v1/teacher/attendance/sessions/{session_id}/identify",
        files={"file": ("scan.jpg", sample_jpeg, "image/jpeg")},
        headers=teacher_headers,
    )
    assert scan_after_final.status_code == 409
    assert scan_after_final.json()["error"]["code"] == "SESSION_NOT_OPEN"


def test_principal_can_delegate_guardian_consent_recording_to_teacher(client, principal, active_teacher, auth_headers, app):
    teacher_headers = auth_headers(client, active_teacher)
    _, student = _setup_class_and_student(client, teacher_headers, roll="D-01", name="Delegated Consent Student")

    denied = client.post(
        f"/api/v1/teacher/students/{student['student_id']}/consent",
        json={"consent_status": "GRANTED", "consent_method": "guardian-paper-form", "consent_record_reference": "FORM-D-01"},
        headers=teacher_headers,
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "CONSENT_RECORD_PERMISSION_REQUIRED"

    principal_headers = auth_headers(client, principal)
    enabled = client.patch(
        f"/api/v1/admin/teachers/{active_teacher['id']}/consent-permission",
        json={"can_record_guardian_consent": True, "reason": "Teacher is authorized to file verified guardian forms."},
        headers=principal_headers,
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["can_record_guardian_consent"] is True
    teacher_headers = auth_headers(client, active_teacher)
    assert client.get("/api/v1/teacher/me", headers=teacher_headers).json()["can_record_guardian_consent"] is True

    granted = client.post(
        f"/api/v1/teacher/students/{student['student_id']}/consent",
        json={"consent_status": "GRANTED", "consent_method": "guardian-paper-form", "consent_record_reference": "FORM-D-01"},
        headers=teacher_headers,
    )
    assert granted.status_code == 200, granted.text
    with app.state.session_factory() as db:
        record = db.get(GuardianConsentRecord, UUID(granted.json()["record_id"]))
        assert record is not None
        assert str(record.recorded_by_user_id) == active_teacher["id"]
        assert record.consent_status == "GRANTED"
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "TEACHER_GUARDIAN_CONSENT_GRANTED", AuditLog.entity_id == student["student_id"]))
        assert audit is not None

    principal_headers = auth_headers(client, principal)
    disabled = client.patch(
        f"/api/v1/admin/teachers/{active_teacher['id']}/consent-permission",
        json={"can_record_guardian_consent": False, "reason": "Delegation ended by Principal."},
        headers=principal_headers,
    )
    assert disabled.status_code == 200
    teacher_headers = auth_headers(client, active_teacher)
    rejected_after_revoke = client.post(
        f"/api/v1/teacher/students/{student['student_id']}/consent",
        json={"consent_status": "WITHDRAWN", "consent_method": "guardian-request", "consent_record_reference": "WITHDRAW-D-01"},
        headers=teacher_headers,
    )
    assert rejected_after_revoke.status_code == 403
