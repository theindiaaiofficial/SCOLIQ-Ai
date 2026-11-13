from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import Identity, require_admin
from app.auth.sessions import issue_session, revoke_all_user_sessions, revoke_session
from app.core.errors import error
from app.core.security import constant_time_secret_match, digest_token, hash_password, new_token, utcnow, verify_password
from app.database import get_db
from app.models import (
    AdminCredential,
    AuditLog,
    AppSession,
    AttendanceRecord,
    AttendanceScanEvent,
    AttendanceSession,
    AttendanceSessionMark,
    BootstrapState,
    ClassRecord,
    GuardianConsentRecord,
    PasskeyCredential,
    SchoolProfile,
    Student,
    StudentClassEnrollment,
    StudentFaceTemplate,
    TeacherAccessRequest,
    TeacherActivationToken,
    TeacherClassAssignment,
    User,
    WebAuthnChallenge,
)
from app.schemas import (
    AdminLoginRequest,
    PasswordChangeRequest,
    ApproveRequest,
    BootstrapRequest,
    ConsentGrantRequest,
    RejectRequest,
    ReopenRequest,
    SchoolProfileUpdate,
    SchoolDataResetRequest,
    DEFAULT_BRANDING,
    BrandingConfig,
    TeacherStatusRequest,
    TeacherConsentPermissionRequest,
)
from app.services.common import add_audit, clear_auth_cookies, local_today, set_auth_cookies

router = APIRouter(prefix="/admin", tags=["Principal administration"])


def settings_from(request: Request):
    return request.app.state.settings


def ensure_school_profile(db: Session) -> SchoolProfile:
    profile = db.get(SchoolProfile, 1)
    if profile is not None:
        return profile
    profile = SchoolProfile(id=1, branding=dict(DEFAULT_BRANDING))
    db.add(profile)
    try:
        db.flush()
    except IntegrityError:
        # Concurrent first access may race on the singleton primary key. Roll
        # back only this request's uncommitted transaction and reload the row.
        db.rollback()
        profile = db.get(SchoolProfile, 1)
        if profile is None:
            raise
    return profile


def school_profile_payload(profile: SchoolProfile) -> dict:
    branding = BrandingConfig.model_validate({**DEFAULT_BRANDING, **(profile.branding or {})})
    return {
        "school_name": profile.school_name,
        "school_code": profile.school_code,
        "timezone": profile.timezone,
        "current_academic_year": profile.current_academic_year,
        "logo_url": profile.logo_url,
        "branding": branding.model_dump(),
        "settings": profile.settings,
    }


@router.get("/bootstrap/status")
def bootstrap_status(db: Session = Depends(get_db)):
    state = db.get(BootstrapState, 1)
    exists = db.scalar(select(User.id).where(User.role == "PRINCIPAL")) is not None
    return {"available": state is None or state.completed_at is None, "principal_exists": exists}


@router.post("/bootstrap", status_code=201)
def bootstrap(payload: BootstrapRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    settings = settings_from(request)
    if not settings.initial_admin_setup_token or not constant_time_secret_match(settings.initial_admin_setup_token, payload.setup_token):
        raise error("BOOTSTRAP_TOKEN_INVALID", "Bootstrap authorization failed.", 403)
    state = db.get(BootstrapState, 1)
    if (state and state.completed_at) or db.scalar(select(User.id).where(User.role == "PRINCIPAL")):
        raise error("BOOTSTRAP_ALREADY_COMPLETED", "Principal bootstrap has already been completed.", 409)
    try:
        user = User(full_name=payload.full_name, email=str(payload.email).lower(), role="PRINCIPAL", status="ACTIVE")
        db.add(user)
        db.flush()
        db.add(AdminCredential(user_id=user.id, password_hash=hash_password(payload.password)))
        if state is None:
            state = BootstrapState(id=1)
            db.add(state)
        state.completed_at = utcnow()
        state.completed_by_user_id = user.id
        ensure_school_profile(db)
        raw, csrf, _ = issue_session(db, user.id, settings)
        add_audit(db, actor_user_id=user.id, action="PRINCIPAL_BOOTSTRAPPED", entity_type="user", entity_id=user.id)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise error("BOOTSTRAP_CONFLICT", "A Principal account already exists or the supplied email is already used.", 409) from exc
    set_auth_cookies(response, raw, csrf, settings)
    return {"message": "Initial Principal account created.", "csrf_token": csrf}


@router.post("/auth/login")
def admin_login(payload: AdminLoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.role == "PRINCIPAL", User.email == str(payload.email).lower(), User.status == "ACTIVE"))
    credential = db.get(AdminCredential, user.id) if user else None
    if not credential or not verify_password(credential.password_hash, payload.password):
        raise error("INVALID_CREDENTIALS", "Email or password is incorrect.", 401)
    raw, csrf, _ = issue_session(db, user.id, settings_from(request))
    add_audit(db, actor_user_id=user.id, action="PRINCIPAL_LOGIN", entity_type="user", entity_id=user.id)
    db.commit()
    set_auth_cookies(response, raw, csrf, settings_from(request))
    return {"message": "Signed in successfully.", "csrf_token": csrf}


@router.post("/auth/logout")
def admin_logout(request: Request, response: Response, identity: Identity = Depends(require_admin), db: Session = Depends(get_db)):
    revoke_session(db, identity.session)
    db.commit()
    clear_auth_cookies(response, settings_from(request))
    return {"message": "Signed out."}


@router.get("/me")
def admin_me(identity: Identity = Depends(require_admin)):
    return {"id": str(identity.user.id), "full_name": identity.user.full_name, "email": identity.user.email, "role": identity.user.role}


@router.post("/auth/password")
def change_admin_password(payload: PasswordChangeRequest, request: Request, response: Response,
                          identity: Identity = Depends(require_admin), db: Session = Depends(get_db)):
    credential = db.get(AdminCredential, identity.user.id)
    if credential is None or not verify_password(credential.password_hash, payload.current_password):
        raise error("CURRENT_PASSWORD_INVALID", "The current password is incorrect.", 401)
    if payload.current_password == payload.new_password:
        raise error("PASSWORD_UNCHANGED", "The new password must be different from the current password.", 400)
    credential.password_hash = hash_password(payload.new_password)
    credential.password_changed_at = utcnow()
    revoke_all_user_sessions(db, identity.user.id)
    raw, csrf, _ = issue_session(db, identity.user.id, settings_from(request))
    add_audit(db, actor_user_id=identity.user.id, action="PRINCIPAL_PASSWORD_CHANGED", entity_type="user", entity_id=identity.user.id)
    db.commit()
    set_auth_cookies(response, raw, csrf, settings_from(request))
    return {"message": "Password changed successfully. Other sessions have been revoked.", "csrf_token": csrf}


@router.get("/dashboard")
def dashboard(request: Request, identity: Identity = Depends(require_admin), db: Session = Depends(get_db)):
    profile = ensure_school_profile(db)
    today = local_today(profile.timezone)
    total_students = db.scalar(select(func.count()).select_from(StudentClassEnrollment).where(StudentClassEnrollment.enrollment_status == "ACTIVE")) or 0
    total_teachers = db.scalar(select(func.count()).select_from(User).where(User.role == "TEACHER", User.status == "ACTIVE")) or 0
    total_classes = db.scalar(select(func.count()).select_from(ClassRecord).where(ClassRecord.status == "ACTIVE")) or 0
    sessions = db.execute(select(AttendanceSession, ClassRecord).join(ClassRecord, ClassRecord.id == AttendanceSession.class_id).where(AttendanceSession.attendance_date == today)).all()
    finalized_present = sum(s.present_count for s, _ in sessions if s.status == "FINALIZED")
    finalized_absent = sum(s.absent_count for s, _ in sessions if s.status == "FINALIZED")
    return {
        "school": {"name": profile.school_name, "timezone": profile.timezone, "academic_year": profile.current_academic_year},
        "total_students": total_students,
        "total_teachers": total_teachers,
        "total_classes_sections": total_classes,
        "present_today_finalized": finalized_present,
        "absent_today_finalized": finalized_absent,
        "classes_in_progress": sum(s.status in {"OPEN", "REVIEW", "REOPENED"} for s, _ in sessions),
        "attendance_completion": {"sessions_today": len(sessions), "finalized": sum(s.status == "FINALIZED" for s, _ in sessions)},
        "session_states": [{"session_id": str(s.id), "class_id": str(c.id), "class": c.grade_label, "section": c.section_label,
                            "status": s.status, "provisional_present_count": s.present_count if s.status != "FINALIZED" else None,
                            "final_present_count": s.present_count if s.status == "FINALIZED" else None,
                            "final_absent_count": s.absent_count if s.status == "FINALIZED" else None} for s, c in sessions],
    }


@router.get("/teacher-requests")
def list_teacher_requests(status: str | None = Query(default="PENDING"), page: int = 1, page_size: int = 50,
                          identity: Identity = Depends(require_admin), db: Session = Depends(get_db)):
    page = max(page, 1)
    page_size = min(max(page_size, 1), 200)
    query = select(TeacherAccessRequest)
    count_query = select(func.count()).select_from(TeacherAccessRequest)
    if status:
        query = query.where(TeacherAccessRequest.status == status)
        count_query = count_query.where(TeacherAccessRequest.status == status)
    total = db.scalar(count_query) or 0
    items = db.scalars(query.order_by(TeacherAccessRequest.requested_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [{"id": str(i.id), "full_name": i.full_name, "phone": i.phone, "email": i.email, "staff_identifier": i.staff_identifier,
                       "status": i.status, "requested_at": i.requested_at} for i in items], "page": page, "page_size": page_size, "total": total}


@router.post("/teacher-requests/{request_id}/approve")
def approve_teacher(request_id: UUID, payload: ApproveRequest, request: Request, identity: Identity = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.scalar(select(TeacherAccessRequest).where(TeacherAccessRequest.id == request_id).with_for_update())
    if item is None:
        raise error("REQUEST_NOT_FOUND", "Teacher access request was not found.", 404)
    if item.status != "PENDING":
        raise error("REQUEST_NOT_PENDING", "Only pending requests can be approved.", 409)
    code = new_token(32)
    try:
        teacher = User(full_name=item.full_name, phone=item.phone, email=item.email, role="TEACHER", status="PENDING")
        db.add(teacher)
        db.flush()
        item.teacher_user_id = teacher.id
        item.status = "APPROVED_PENDING_PASSKEY"
        item.reviewed_by_user_id = identity.user.id
        item.reviewed_at = utcnow()
        item.review_note = payload.review_note
        db.add(TeacherActivationToken(request_id=item.id, teacher_user_id=teacher.id, token_hash=digest_token(code, request.app.state.settings.session_secret or None), expires_at=utcnow() + timedelta(hours=24)))
        add_audit(db, actor_user_id=identity.user.id, action="TEACHER_REQUEST_APPROVED", entity_type="teacher_access_request", entity_id=item.id)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise error("TEACHER_IDENTITY_CONFLICT", "A teacher with this email or phone already exists.", 409) from exc
    return {"request_id": str(item.id), "teacher_id": str(teacher.id), "status": item.status,
            "activation_code": code, "activation_expires_at": utcnow() + timedelta(hours=24),
            "one_time_notice": "Copy this code now and hand it to the verified teacher through a trusted channel. It will not be shown again."}


@router.post("/teacher-requests/{request_id}/reject")
def reject_teacher(request_id: UUID, payload: RejectRequest, identity: Identity = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.scalar(select(TeacherAccessRequest).where(TeacherAccessRequest.id == request_id).with_for_update())
    if item is None:
        raise error("REQUEST_NOT_FOUND", "Teacher access request was not found.", 404)
    if item.status != "PENDING":
        raise error("REQUEST_NOT_PENDING", "Only pending requests can be rejected.", 409)
    item.status = "REJECTED"
    item.reviewed_by_user_id = identity.user.id
    item.reviewed_at = utcnow()
    item.review_note = payload.review_note
    add_audit(db, actor_user_id=identity.user.id, action="TEACHER_REQUEST_REJECTED", entity_type="teacher_access_request", entity_id=item.id)
    db.commit()
    return {"request_id": str(item.id), "status": item.status}


@router.get("/teachers")
def list_teachers(page: int = 1, page_size: int = 50, identity: Identity = Depends(require_admin), db: Session = Depends(get_db)):
    page = max(page, 1)
    page_size = min(max(page_size, 1), 200)
    query = select(User).where(User.role == "TEACHER").order_by(User.created_at.desc())
    items = db.scalars(query.offset((page - 1) * page_size).limit(page_size)).all()
    total = db.scalar(select(func.count()).select_from(User).where(User.role == "TEACHER")) or 0
    return {"items": [{"id": str(u.id), "full_name": u.full_name, "phone": u.phone, "email": u.email, "status": u.status, "can_record_guardian_consent": bool(u.can_record_guardian_consent), "created_at": u.created_at} for u in items],
            "page": page, "page_size": page_size, "total": total}


@router.get("/teachers/{teacher_id}")
def teacher_detail(teacher_id: UUID, identity: Identity = Depends(require_admin), db: Session = Depends(get_db)):
    teacher = db.get(User, teacher_id)
    if teacher is None or teacher.role != "TEACHER":
        raise error("TEACHER_NOT_FOUND", "Teacher was not found.", 404)
    assignments = db.execute(select(TeacherClassAssignment, ClassRecord).join(ClassRecord, ClassRecord.id == TeacherClassAssignment.class_id).where(TeacherClassAssignment.teacher_user_id == teacher_id)).all()
    return {"id": str(teacher.id), "full_name": teacher.full_name, "phone": teacher.phone, "email": teacher.email, "status": teacher.status,
            "can_record_guardian_consent": bool(teacher.can_record_guardian_consent),
            "assignments": [{"assignment_id": str(a.id), "class_id": str(c.id), "grade": c.grade_label, "section": c.section_label,
                             "academic_year": c.academic_year, "status": a.status} for a, c in assignments]}


@router.patch("/teachers/{teacher_id}/consent-permission")
def set_teacher_consent_permission(teacher_id: UUID, payload: TeacherConsentPermissionRequest, identity: Identity = Depends(require_admin), db: Session = Depends(get_db)):
    teacher = db.get(User, teacher_id)
    if teacher is None or teacher.role != "TEACHER":
        raise error("TEACHER_NOT_FOUND", "Teacher was not found.", 404)
    if payload.can_record_guardian_consent and teacher.status != "ACTIVE":
        raise error("TEACHER_NOT_ACTIVE", "Only an active teacher can receive this permission.", 409)
    teacher.can_record_guardian_consent = payload.can_record_guardian_consent
    add_audit(
        db, actor_user_id=identity.user.id, action="TEACHER_GUARDIAN_CONSENT_PERMISSION_CHANGED",
        entity_type="user", entity_id=teacher.id,
        metadata={"enabled": payload.can_record_guardian_consent, "reason": payload.reason},
    )
    db.commit()
    return {"teacher_id": str(teacher.id), "can_record_guardian_consent": teacher.can_record_guardian_consent}


@router.patch("/teachers/{teacher_id}/status")
def change_teacher_status(teacher_id: UUID, payload: TeacherStatusRequest, identity: Identity = Depends(require_admin), db: Session = Depends(get_db)):
    teacher = db.get(User, teacher_id)
    if teacher is None or teacher.role != "TEACHER":
        raise error("TEACHER_NOT_FOUND", "Teacher was not found.", 404)
    teacher.status = payload.status
    if payload.status in {"SUSPENDED", "REVOKED"}:
        teacher.can_record_guardian_consent = False
        revoke_all_user_sessions(db, teacher.id)
        for item in db.scalars(select(TeacherActivationToken).where(TeacherActivationToken.teacher_user_id == teacher.id, TeacherActivationToken.redeemed_at.is_(None))).all():
            item.redeemed_at = utcnow()
        if payload.status == "REVOKED":
            for credential in db.scalars(select(PasskeyCredential).where(PasskeyCredential.user_id == teacher.id, PasskeyCredential.revoked_at.is_(None))).all():
                credential.revoked_at = utcnow()
    add_audit(db, actor_user_id=identity.user.id, action="TEACHER_STATUS_CHANGED", entity_type="user", entity_id=teacher.id,
              metadata={"status": payload.status, "reason": payload.reason, "consent_permission_disabled": payload.status in {"SUSPENDED", "REVOKED"}})
    db.commit()
    return {"teacher_id": str(teacher.id), "status": teacher.status}


@router.post("/teachers/{teacher_id}/revoke-passkeys")
def revoke_teacher_passkeys(teacher_id: UUID, request: Request, identity: Identity = Depends(require_admin), db: Session = Depends(get_db)):
    teacher = db.get(User, teacher_id)
    if teacher is None or teacher.role != "TEACHER":
        raise error("TEACHER_NOT_FOUND", "Teacher was not found.", 404)
    access_request = db.scalar(select(TeacherAccessRequest).where(TeacherAccessRequest.teacher_user_id == teacher_id))
    if access_request is None:
        raise error("TEACHER_RECOVERY_UNAVAILABLE", "Teacher access request history is missing; Principal-assisted recovery cannot be started.", 409)
    for previous_code in db.scalars(select(TeacherActivationToken).where(
        TeacherActivationToken.teacher_user_id == teacher_id, TeacherActivationToken.redeemed_at.is_(None)
    )).all():
        previous_code.redeemed_at = utcnow()
    credentials = db.scalars(select(PasskeyCredential).where(PasskeyCredential.user_id == teacher_id, PasskeyCredential.revoked_at.is_(None))).all()
    for credential in credentials:
        credential.revoked_at = utcnow()
    revoke_all_user_sessions(db, teacher_id)
    teacher.status = "PENDING"
    access_request.status = "APPROVED_PENDING_PASSKEY"
    code = new_token(32)
    expiry = utcnow() + timedelta(hours=24)
    db.add(TeacherActivationToken(
        request_id=access_request.id,
        teacher_user_id=teacher_id,
        token_hash=digest_token(code, request.app.state.settings.session_secret or None),
        expires_at=expiry,
    ))
    add_audit(db, actor_user_id=identity.user.id, action="TEACHER_PASSKEYS_REVOKED_RECOVERY_ISSUED", entity_type="user", entity_id=teacher_id,
              metadata={"revoked_count": len(credentials)})
    db.commit()
    return {"teacher_id": str(teacher_id), "revoked_count": len(credentials), "status": teacher.status,
            "recovery_activation_code": code, "expires_at": expiry,
            "one_time_notice": "Deliver this one-time recovery code to the verified teacher through a trusted channel. It will not be shown again."}


@router.get("/classes")
def list_classes(identity: Identity = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.execute(select(ClassRecord, TeacherClassAssignment, User).outerjoin(
        TeacherClassAssignment, (TeacherClassAssignment.class_id == ClassRecord.id) & (TeacherClassAssignment.status == "ACTIVE")
    ).outerjoin(User, User.id == TeacherClassAssignment.teacher_user_id).order_by(ClassRecord.academic_year.desc(), ClassRecord.grade_label, ClassRecord.section_label)).all()
    return [{"class_id": str(c.id), "grade": c.grade_label, "section": c.section_label, "academic_year": c.academic_year,
             "status": c.status, "teacher_id": str(t.id) if t else None, "teacher_name": t.full_name if t else None} for c, _, t in rows]


@router.post("/classes/{class_id}/assignments/{teacher_id}")
def admin_assign_teacher(class_id: UUID, teacher_id: UUID, identity: Identity = Depends(require_admin), db: Session = Depends(get_db)):
    class_record = db.get(ClassRecord, class_id)
    teacher = db.get(User, teacher_id)
    if class_record is None or teacher is None or teacher.role != "TEACHER" or teacher.status != "ACTIVE":
        raise error("INVALID_ASSIGNMENT", "Active class and teacher records are required.", 404)
    existing = db.scalar(select(TeacherClassAssignment).where(TeacherClassAssignment.class_id == class_id, TeacherClassAssignment.active_slot == "CLASS_TEACHER"))
    if existing and existing.teacher_user_id != teacher_id:
        raise error("CLASS_ALREADY_ASSIGNED", "Another active class teacher owns this class. End that assignment before replacement.", 409)
    assignment = db.scalar(select(TeacherClassAssignment).where(TeacherClassAssignment.teacher_user_id == teacher_id, TeacherClassAssignment.class_id == class_id))
    if assignment is None:
        assignment = TeacherClassAssignment(teacher_user_id=teacher_id, class_id=class_id, status="ACTIVE", active_slot="CLASS_TEACHER")
        db.add(assignment)
    else:
        assignment.status = "ACTIVE"
        assignment.active_slot = "CLASS_TEACHER"
        assignment.ended_at = None
    add_audit(db, actor_user_id=identity.user.id, action="CLASS_TEACHER_ASSIGNED", entity_type="class", entity_id=class_id, metadata={"teacher_id": str(teacher_id)})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise error("CLASS_ALREADY_ASSIGNED", "Another active class teacher owns this class.", 409) from exc
    return {"assignment_id": str(assignment.id), "class_id": str(class_id), "teacher_id": str(teacher_id), "status": "ACTIVE"}


@router.delete("/classes/{class_id}/assignments/{teacher_id}")
def admin_unassign_teacher(class_id: UUID, teacher_id: UUID, identity: Identity = Depends(require_admin), db: Session = Depends(get_db)):
    assignment = db.scalar(select(TeacherClassAssignment).where(TeacherClassAssignment.class_id == class_id, TeacherClassAssignment.teacher_user_id == teacher_id, TeacherClassAssignment.status == "ACTIVE"))
    if assignment is None:
        raise error("ASSIGNMENT_NOT_FOUND", "Active assignment was not found.", 404)
    assignment.status = "INACTIVE"
    assignment.active_slot = None
    assignment.ended_at = utcnow()
    add_audit(db, actor_user_id=identity.user.id, action="CLASS_TEACHER_UNASSIGNED", entity_type="class", entity_id=class_id, metadata={"teacher_id": str(teacher_id)})
    db.commit()
    return {"message": "Teacher assignment ended."}


@router.get("/students")
def admin_students(page: int = 1, page_size: int = 50, q: str | None = None, identity: Identity = Depends(require_admin), db: Session = Depends(get_db)):
    page = max(page, 1)
    page_size = min(max(page_size, 1), 200)
    latest_consent = (select(GuardianConsentRecord.consent_status)
                      .where(GuardianConsentRecord.student_id == Student.id)
                      .order_by(GuardianConsentRecord.recorded_at.desc())
                      .limit(1).correlate(Student).scalar_subquery())
    has_face_template = select(StudentFaceTemplate.id).where(
        StudentFaceTemplate.student_id == Student.id, StudentFaceTemplate.is_active.is_(True)
    ).exists()
    query = select(Student, StudentClassEnrollment, ClassRecord, latest_consent, has_face_template).join(
        StudentClassEnrollment, StudentClassEnrollment.student_id == Student.id
    ).join(ClassRecord, ClassRecord.id == StudentClassEnrollment.class_id)
    if q:
        query = query.where(or_(Student.full_name.ilike(f"%{q}%"), Student.school_student_code.ilike(f"%{q}%"), StudentClassEnrollment.roll_number.ilike(f"%{q}%")))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(query.order_by(Student.full_name).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [{"student_id": str(s.id), "full_name": s.full_name, "school_student_code": s.school_student_code,
                       "roll_number": e.roll_number, "class": c.grade_label, "section": c.section_label, "academic_year": e.academic_year,
                       "status": s.status, "consent_status": consent_status or "PENDING", "face_enrolled": bool(face_enrolled)}
                      for s, e, c, consent_status, face_enrolled in rows], "page": page, "page_size": page_size, "total": total}


@router.post("/students/{student_id}/consent")
def update_student_consent(student_id: UUID, payload: ConsentGrantRequest, identity: Identity = Depends(require_admin), db: Session = Depends(get_db)):
    student = db.scalar(select(Student).where(Student.id == student_id).with_for_update())
    if student is None:
        raise error("STUDENT_NOT_FOUND", "Student was not found.", 404)
    record = GuardianConsentRecord(
        student_id=student_id, consent_status=payload.consent_status, consent_method=payload.consent_method,
        consent_record_reference=payload.consent_record_reference, recorded_by_user_id=identity.user.id,
    )
    db.add(record)
    if payload.consent_status == "WITHDRAWN":
        templates = db.scalars(select(StudentFaceTemplate).where(StudentFaceTemplate.student_id == student_id, StudentFaceTemplate.is_active.is_(True))).all()
        for template in templates:
            db.delete(template)
        add_audit(db, actor_user_id=identity.user.id, action="FACE_CONSENT_WITHDRAWN", entity_type="student", entity_id=student_id,
                  metadata={"deactivated_templates": len(templates)})
    else:
        add_audit(db, actor_user_id=identity.user.id, action="FACE_CONSENT_GRANTED", entity_type="student", entity_id=student_id,
                  metadata={"consent_method": payload.consent_method})
    db.commit()
    return {"student_id": str(student_id), "consent_status": payload.consent_status, "record_id": str(record.id)}


@router.get("/attendance/live")
def attendance_live(identity: Identity = Depends(require_admin), db: Session = Depends(get_db)):
    profile = ensure_school_profile(db)
    today = local_today(profile.timezone)
    rows = db.execute(select(AttendanceSession, ClassRecord).join(ClassRecord, ClassRecord.id == AttendanceSession.class_id).where(AttendanceSession.attendance_date == today).order_by(ClassRecord.grade_label, ClassRecord.section_label)).all()
    return [{"session_id": str(s.id), "class_id": str(c.id), "class": c.grade_label, "section": c.section_label,
             "status": s.status, "provisional_present_count": s.present_count if s.status != "FINALIZED" else None,
             "final_present_count": s.present_count if s.status == "FINALIZED" else None,
             "final_absent_count": s.absent_count if s.status == "FINALIZED" else None,
             "opened_at": s.opened_at, "finalized_at": s.finalized_at} for s, c in rows]


@router.get("/attendance/reports")
def attendance_reports(from_date: date | None = None, to_date: date | None = None, class_id: UUID | None = None, page: int = 1, page_size: int = 100,
                       identity: Identity = Depends(require_admin), db: Session = Depends(get_db)):
    page = max(page, 1)
    page_size = min(max(page_size, 1), 200)
    if from_date and to_date and from_date > to_date:
        raise error("INVALID_DATE_RANGE", "from_date must not be later than to_date.", 422)
    query = select(AttendanceSession, ClassRecord).join(ClassRecord, ClassRecord.id == AttendanceSession.class_id).where(AttendanceSession.status == "FINALIZED")
    if from_date:
        query = query.where(AttendanceSession.attendance_date >= from_date)
    if to_date:
        query = query.where(AttendanceSession.attendance_date <= to_date)
    if class_id:
        query = query.where(AttendanceSession.class_id == class_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(query.order_by(AttendanceSession.attendance_date.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [{"session_id": str(s.id), "date": s.attendance_date, "class_id": str(c.id), "class": c.grade_label,
                       "section": c.section_label, "present_count": s.present_count, "absent_count": s.absent_count,
                       "submitted_by": str(s.finalized_by_user_id), "submitted_at": s.finalized_at} for s, c in rows],
            "page": page, "page_size": page_size, "total": total}


@router.post("/attendance/sessions/{session_id}/reopen")
def reopen_attendance(session_id: UUID, payload: ReopenRequest, identity: Identity = Depends(require_admin), db: Session = Depends(get_db)):
    session = db.scalar(select(AttendanceSession).where(AttendanceSession.id == session_id).with_for_update())
    if session is None:
        raise error("SESSION_NOT_FOUND", "Attendance session was not found.", 404)
    if session.status != "FINALIZED":
        raise error("SESSION_NOT_FINALIZED", "Only finalized sessions can be reopened.", 409)
    records = db.scalars(select(AttendanceRecord).where(AttendanceRecord.attendance_session_id == session.id)).all()
    marks = {mark.enrollment_id: mark for mark in db.scalars(
        select(AttendanceSessionMark).where(AttendanceSessionMark.session_id == session.id).with_for_update()
    ).all()}
    for record in records:
        mark = marks.get(record.student_enrollment_id)
        if mark is None:
            mark = AttendanceSessionMark(
                session_id=session.id,
                enrollment_id=record.student_enrollment_id,
                status=record.status,
                source="ADMIN",
                is_confirmed=True,
                updated_by_user_id=identity.user.id,
                notes=record.notes,
            )
            db.add(mark)
        else:
            mark.status = record.status
            mark.source = "ADMIN"
            mark.is_confirmed = True
            mark.updated_by_user_id = identity.user.id
            mark.notes = record.notes
        db.delete(record)
    session.present_count = sum(record.status in {"PRESENT", "LATE"} for record in records)
    session.absent_count = sum(record.status == "ABSENT" for record in records)
    session.status = "REOPENED"
    session.finalized_at = None
    session.finalized_by_user_id = None
    add_audit(db, actor_user_id=identity.user.id, action="ATTENDANCE_SESSION_REOPENED", entity_type="attendance_session", entity_id=session.id,
              metadata={"reason": payload.reason, "record_count": len(records)})
    db.commit()
    return {"session_id": str(session.id), "status": session.status, "message": "Session reopened; teacher must review and submit again."}


@router.post("/system/reset-school-data")
def reset_school_data(
    payload: SchoolDataResetRequest,
    identity: Identity = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Delete operational school data while preserving the Principal and school identity."""
    credential = db.get(AdminCredential, identity.user.id)
    if credential is None or not verify_password(credential.password_hash, payload.current_password):
        raise error("CURRENT_PASSWORD_INVALID", "The current Principal password is incorrect.", 401)

    teacher_ids = list(db.scalars(select(User.id).where(User.role == "TEACHER")).all())
    counts: dict[str, int] = {}

    def remove(label: str, statement) -> None:
        result = db.execute(statement)
        counts[label] = int(result.rowcount or 0)

    try:
        # Remove dependent attendance rows before their sessions/enrollments/classes.
        remove("attendance_scan_events", delete(AttendanceScanEvent))
        remove("attendance_session_marks", delete(AttendanceSessionMark))
        remove("attendance_records", delete(AttendanceRecord))
        remove("attendance_sessions", delete(AttendanceSession))

        # Remove all student-linked records, including encrypted biometric templates.
        remove("student_face_templates", delete(StudentFaceTemplate))
        remove("guardian_consent_records", delete(GuardianConsentRecord))
        remove("student_class_enrollments", delete(StudentClassEnrollment))
        remove("students", delete(Student))

        # Remove all class and teacher operational data.
        remove("teacher_class_assignments", delete(TeacherClassAssignment))
        remove("classes", delete(ClassRecord))
        remove("teacher_activation_tokens", delete(TeacherActivationToken))
        remove("teacher_access_requests", delete(TeacherAccessRequest))

        # Revoke/delete every teacher credential and session, leaving Principal sessions intact.
        if teacher_ids:
            remove("teacher_passkeys", delete(PasskeyCredential).where(PasskeyCredential.user_id.in_(teacher_ids)))
            remove("teacher_webauthn_challenges", delete(WebAuthnChallenge).where(WebAuthnChallenge.user_id.in_(teacher_ids)))
            remove("teacher_sessions", delete(AppSession).where(AppSession.user_id.in_(teacher_ids)))
        else:
            counts.update({"teacher_passkeys": 0, "teacher_webauthn_challenges": 0, "teacher_sessions": 0})

        # Historical audit metadata may contain staff/student identifiers. Clear it,
        # then write one minimal reset event containing counts only.
        remove("previous_audit_logs", delete(AuditLog))
        remove("teacher_accounts", delete(User).where(User.role == "TEACHER"))

        add_audit(
            db,
            actor_user_id=identity.user.id,
            action="SCHOOL_DATA_RESET",
            entity_type="school",
            entity_id="1",
            metadata={"deleted_counts": counts, "preserved": ["principal_account", "school_profile", "branding", "school_settings"]},
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "message": "School operational data was reset. Principal login and school identity were preserved.",
        "deleted_counts": counts,
        "preserved": ["principal_account", "principal_credentials", "principal_sessions", "school_profile", "branding", "school_settings", "bootstrap_state"],
    }


@router.get("/settings/profile")
def get_school_profile(identity: Identity = Depends(require_admin), db: Session = Depends(get_db)):
    return school_profile_payload(ensure_school_profile(db))


@router.patch("/settings/profile")
def update_school_profile(payload: SchoolProfileUpdate, identity: Identity = Depends(require_admin), db: Session = Depends(get_db)):
    profile = ensure_school_profile(db)
    updates = payload.model_dump(exclude_unset=True)
    if updates.get("timezone"):
        try:
            ZoneInfo(updates["timezone"])
        except ZoneInfoNotFoundError as exc:
            raise error("INVALID_TIMEZONE", "Timezone must be a valid IANA timezone.") from exc
    for key in ("school_name", "school_code", "timezone", "current_academic_year"):
        if key in updates and updates[key] is not None:
            setattr(profile, key, updates[key])
    if "logo_url" in updates:
        profile.logo_url = updates["logo_url"]
    if updates.get("branding") is not None:
        profile.branding = BrandingConfig.model_validate(updates["branding"]).model_dump()
    profile.updated_at = utcnow()
    changed_fields = list(updates)
    add_audit(db, actor_user_id=identity.user.id, action="SCHOOL_PROFILE_UPDATED", entity_type="school_profile", entity_id="1", metadata={"fields": changed_fields})
    db.commit()
    db.refresh(profile)
    return school_profile_payload(profile)


@router.get("/audit-log")
def audit_log(page: int = 1, page_size: int = 100, identity: Identity = Depends(require_admin), db: Session = Depends(get_db)):
    from app.models import AuditLog
    page = max(page, 1)
    page_size = min(max(page_size, 1), 200)
    rows = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return [{"id": str(a.id), "actor_user_id": str(a.actor_user_id) if a.actor_user_id else None, "action": a.action,
             "entity_type": a.entity_type, "entity_id": a.entity_id, "created_at": a.created_at, "metadata": a.metadata_json} for a in rows]
