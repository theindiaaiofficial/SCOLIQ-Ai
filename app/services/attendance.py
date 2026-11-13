from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import error
from app.models import (
    AttendanceRecord,
    AttendanceScanEvent,
    AttendanceSession,
    AttendanceSessionMark,
    ClassRecord,
    StudentClassEnrollment,
)
from app.services.common import add_audit


VALID_FINAL_STATUSES = {"PRESENT", "ABSENT", "LATE", "EXCUSED"}


def record_scan(
    db: Session,
    *,
    session: AttendanceSession,
    teacher_user_id,
    status: str,
    enrollment: StudentClassEnrollment | None = None,
    score: float | None = None,
) -> tuple[AttendanceScanEvent, bool]:
    if session.status not in {"OPEN", "REOPENED"}:
        raise error("SESSION_NOT_OPEN", "This attendance session is not accepting scans.", 409)
    event = AttendanceScanEvent(
        session_id=session.id,
        matched_enrollment_id=enrollment.id if enrollment else None,
        result_status=status,
        score=round(score, 5) if score is not None else None,
    )
    db.add(event)
    if enrollment is None or status != "MATCHED":
        db.flush()
        return event, False
    mark = db.scalar(select(AttendanceSessionMark).where(
        AttendanceSessionMark.session_id == session.id,
        AttendanceSessionMark.enrollment_id == enrollment.id,
    ).with_for_update())
    created = mark is None
    if mark is None:
        mark = AttendanceSessionMark(
            session_id=session.id,
            enrollment_id=enrollment.id,
            status="PRESENT",
            source="FACE",
            is_confirmed=False,
            updated_by_user_id=teacher_user_id,
        )
        db.add(mark)
    else:
        # A unique provisional mark already exists, regardless of whether it was
        # face-derived or manually confirmed. Scans never overwrite teacher review.
        event.result_status = "DUPLICATE" if mark.status in {"PRESENT", "LATE"} else "ALREADY_REVIEWED"
    db.flush()
    count = db.scalar(select(func.count()).select_from(AttendanceSessionMark).where(
        AttendanceSessionMark.session_id == session.id,
        AttendanceSessionMark.status.in_(["PRESENT", "LATE"]),
    )) or 0
    session.present_count = int(count)
    return event, created


def review_payload(db: Session, session: AttendanceSession) -> dict:
    from sqlalchemy import and_
    from app.models import Student

    enrolled = db.execute(
        select(
            StudentClassEnrollment.id,
            Student.full_name,
            StudentClassEnrollment.roll_number,
            AttendanceSessionMark.status,
            AttendanceSessionMark.source,
            AttendanceSessionMark.is_confirmed,
        )
        .join(Student, Student.id == StudentClassEnrollment.student_id)
        .outerjoin(
            AttendanceSessionMark,
            and_(
                AttendanceSessionMark.session_id == session.id,
                AttendanceSessionMark.enrollment_id == StudentClassEnrollment.id,
            ),
        )
        .where(
            StudentClassEnrollment.class_id == session.class_id,
            StudentClassEnrollment.enrollment_status == "ACTIVE",
        )
        .order_by(StudentClassEnrollment.roll_number)
    ).all()
    students = []
    absent_candidates = []
    for enrollment_id, full_name, roll_number, status, source, confirmed in enrolled:
        if status is not None:
            students.append({
                "enrollment_id": str(enrollment_id),
                "student_name": full_name,
                "roll_number": roll_number,
                "status": status,
                "source": source,
                "confirmed": confirmed,
            })
        else:
            absent_candidates.append({
                "enrollment_id": str(enrollment_id),
                "student_name": full_name,
                "roll_number": roll_number,
                "status": "UNCONFIRMED_ABSENT_CANDIDATE",
                "confirmed": False,
            })
    return {
        "session_id": str(session.id),
        "status": session.status,
        "total_enrolled": len(enrolled),
        "provisional_present_count": session.present_count,
        "marks": students,
        "absent_candidates": absent_candidates,
        "message": "Absent candidates are not final absences. Confirm every student's status before submission.",
    }


def finalize_session(db: Session, session: AttendanceSession, teacher_user_id) -> dict:
    if session.status == "FINALIZED":
        existing = db.scalars(select(AttendanceRecord).where(AttendanceRecord.attendance_session_id == session.id)).all()
        return {"session_id": str(session.id), "status": "FINALIZED", "records_created": len(existing), "idempotent_replay": True}
    if session.status not in {"REVIEW", "REOPENED"}:
        raise error("SESSION_NOT_IN_REVIEW", "Open review before final submission.", 409)
    roster = db.scalars(select(StudentClassEnrollment).where(
        StudentClassEnrollment.class_id == session.class_id,
        StudentClassEnrollment.enrollment_status == "ACTIVE",
    )).all()
    marks = db.scalars(select(AttendanceSessionMark).where(
        AttendanceSessionMark.session_id == session.id
    ).with_for_update()).all()
    by_id = {mark.enrollment_id: mark for mark in marks}
    missing = [str(item.id) for item in roster if item.id not in by_id or not by_id[item.id].is_confirmed]
    if missing:
        raise error("ATTENDANCE_REVIEW_INCOMPLETE", f"Confirm the status for all {len(missing)} remaining student(s) before finalizing.", 409)
    for mark in marks:
        db.add(AttendanceRecord(
            attendance_session_id=session.id,
            student_enrollment_id=mark.enrollment_id,
            status=mark.status,
            identification_method="FACE_MATCH" if mark.source == "FACE" and mark.status in {"PRESENT", "LATE"} else ("ADMIN" if mark.source == "ADMIN" else "MANUAL"),
            confirmed_by_user_id=teacher_user_id,
            notes=mark.notes,
        ))
    session.status = "FINALIZED"
    session.finalized_by_user_id = teacher_user_id
    from app.core.security import utcnow
    session.finalized_at = utcnow()
    session.present_count = sum(mark.status in {"PRESENT", "LATE"} for mark in marks)
    session.absent_count = sum(mark.status == "ABSENT" for mark in marks)
    add_audit(db, actor_user_id=teacher_user_id, action="ATTENDANCE_FINALIZED", entity_type="attendance_session", entity_id=session.id,
              metadata={"present_count": session.present_count, "absent_count": session.absent_count})
    db.flush()
    return {"session_id": str(session.id), "status": "FINALIZED", "records_created": len(marks), "present_count": session.present_count,
            "absent_count": session.absent_count, "idempotent_replay": False}
