from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import error
from app.models import AuditLog, ClassRecord, TeacherClassAssignment


def add_audit(
    db: Session,
    *,
    actor_user_id,
    action: str,
    entity_type: str,
    entity_id: str | UUID | None = None,
    metadata: dict | None = None,
) -> None:
    db.add(AuditLog(
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        metadata_json=metadata or {},
    ))


def selected_teacher_class(db: Session, user_id, request: Request) -> tuple[TeacherClassAssignment, ClassRecord]:
    query = select(TeacherClassAssignment, ClassRecord).join(
        ClassRecord, ClassRecord.id == TeacherClassAssignment.class_id
    ).where(
        TeacherClassAssignment.teacher_user_id == user_id,
        TeacherClassAssignment.status == "ACTIVE",
        TeacherClassAssignment.is_class_teacher.is_(True),
        ClassRecord.status == "ACTIVE",
    )
    class_header = request.headers.get("X-Class-ID")
    if class_header:
        try:
            class_id = UUID(class_header)
        except ValueError as exc:
            raise error("INVALID_CLASS_ID", "X-Class-ID must be a valid UUID.") from exc
        query = query.where(ClassRecord.id == class_id)
    rows = db.execute(query.order_by(ClassRecord.academic_year.desc(), ClassRecord.grade_label, ClassRecord.section_label)).all()
    if not rows:
        raise error("CLASS_NOT_ASSIGNED", "No active class is assigned to this teacher.", 409)
    if len(rows) > 1 and not class_header:
        raise error("CLASS_SELECTION_REQUIRED", "Select one of your assigned classes using the X-Class-ID header.", 409)
    return rows[0][0], rows[0][1]


def cookie_options(request: Request, settings) -> dict:
    return {
        "secure": settings.cookie_secure,
        "httponly": True,
        "samesite": settings.cookie_samesite,
        "path": "/",
    }


def set_auth_cookies(response, raw_token: str, csrf_token: str, settings, *, max_age: int | None = None) -> None:
    opts = cookie_options(None, settings)
    response.set_cookie("smartattend_session", raw_token, max_age=max_age or settings.session_ttl_hours * 3600, **opts)
    response.set_cookie(
        "smartattend_csrf", csrf_token,
        max_age=max_age or settings.session_ttl_hours * 3600,
        secure=settings.cookie_secure,
        httponly=False,
        samesite=settings.cookie_samesite,
        path="/",
    )


def clear_auth_cookies(response, settings) -> None:
    response.delete_cookie("smartattend_session", path="/", secure=settings.cookie_secure, httponly=True, samesite=settings.cookie_samesite)
    response.delete_cookie("smartattend_csrf", path="/", secure=settings.cookie_secure, httponly=False, samesite=settings.cookie_samesite)


def local_today(timezone_name: str):
    from zoneinfo import ZoneInfo

    return datetime.now(UTC).astimezone(ZoneInfo(timezone_name)).date()
