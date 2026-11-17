from __future__ import annotations

from datetime import date
import time
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import Identity, require_teacher
from app.core.errors import error
from app.core.security import utcnow
from app.database import get_db
from app.face.encryption import FaceTemplateCipher
from app.face.diagnostics import log_face_event
from app.face.image_validation import InvalidFaceImage, validate_image_bytes
from app.face.opencv_provider import cosine_similarity
from app.face.provider import (
    FaceProviderError,
    MultipleFacesDetected,
    NoFaceDetected,
    PoorFaceQuality,
    ProviderUnavailable,
)
from app.models import (
    AttendanceRecord,
    AttendanceScanEvent,
    AttendanceSession,
    AttendanceSessionMark,
    AttendanceVerificationAttempt,
    ClassRecord,
    GuardianConsentRecord,
    SchoolProfile,
    Student,
    StudentClassEnrollment,
    StudentFaceTemplate,
    TeacherClassAssignment,
)
from app.schemas import FinalizeRequest, ManualAttendanceConfirmRequest, MarkUpdateRequest
from app.services.attendance import finalize_session, record_scan, review_payload
from app.services.common import add_audit, local_today, selected_teacher_class
from app.services.school_settings import get_school_operations_settings

router = APIRouter(prefix="/teacher", tags=["Teacher attendance and face enrollment"])


def _get_session_for_teacher(
    db: Session, session_id: UUID, teacher_user_id, *, lock: bool = False
) -> AttendanceSession:
    statement = select(AttendanceSession).where(AttendanceSession.id == session_id)
    if lock:
        statement = statement.with_for_update()
    session = db.scalar(statement)
    if session is None:
        raise error("SESSION_NOT_FOUND", "Attendance session was not found.", 404)
    assigned = db.scalar(select(TeacherClassAssignment.id).where(
        TeacherClassAssignment.teacher_user_id == teacher_user_id,
        TeacherClassAssignment.class_id == session.class_id,
        TeacherClassAssignment.status == "ACTIVE",
    ).limit(1))
    if assigned is None:
        raise error("FORBIDDEN_CLASS_ACCESS", "This session is not part of your assigned classes.", 403)
    return session


def _cipher(request: Request) -> FaceTemplateCipher:
    try:
        return FaceTemplateCipher(request.app.state.settings.face_encryption_key())
    except Exception as exc:
        raise error("FACE_ENCRYPTION_NOT_CONFIGURED", "Face template encryption is not configured. Manual attendance remains available.", 503) from exc


def _provider(request: Request):
    provider = getattr(request.app.state, "face_provider", None)
    if provider is None:
        raise error("FACE_PROVIDER_UNAVAILABLE", "Face processing is not configured. Use manual attendance.", 503)
    return provider


def _read_and_validate_upload(file: UploadFile, request: Request) -> bytes:
    settings = request.app.state.settings
    max_bytes = settings.max_face_upload_mb * 1024 * 1024
    content = file.file.read(max_bytes + 1)
    log_face_event(
        "upload.received",
        upload_bytes=len(content),
        content_type_header=file.content_type,
        configured_max_bytes=max_bytes,
        configured_max_width=settings.max_face_image_width,
        configured_max_height=settings.max_face_image_height,
    )
    try:
        content_type, width, height = validate_image_bytes(
            content,
            max_bytes=max_bytes,
            max_width=settings.max_face_image_width,
            max_height=settings.max_face_image_height,
        )
    except InvalidFaceImage as exc:
        log_face_event(
            "upload.rejected",
            reason=str(exc),
            upload_bytes=len(content),
            content_type_header=file.content_type,
        )
        raise error("INVALID_FACE_IMAGE", str(exc), 422) from exc
    log_face_event(
        "upload.validated",
        image_content_type=content_type,
        image_width=width,
        image_height=height,
        upload_bytes=len(content),
        result="success",
    )
    return content


def _attempt_count(db: Session, session_id: UUID, enrollment_id: UUID, *, increment: bool = False) -> int:
    row = db.scalar(select(AttendanceVerificationAttempt).where(
        AttendanceVerificationAttempt.session_id == session_id,
        AttendanceVerificationAttempt.enrollment_id == enrollment_id,
    ).with_for_update())
    if row is None:
        if not increment:
            return 0
        row = AttendanceVerificationAttempt(session_id=session_id, enrollment_id=enrollment_id, attempt_count=0)
        db.add(row)
        db.flush()
    if increment:
        row.attempt_count += 1
        row.updated_at = utcnow()
    return row.attempt_count


def _attempt_limit(db: Session) -> int:
    return int(get_school_operations_settings(db)["face_verification_attempt_limit"])


@router.post("/face-capture-guidance")
async def face_capture_guidance(
    request: Request,
    file: UploadFile = File(...),
    identity: Identity = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """Analyze one transient preview frame for pose/quality guidance only."""
    selected_teacher_class(db, identity.user.id, request)
    provider = _provider(request)
    analyzer = getattr(provider, "analyze_capture_guidance", None)
    if not callable(analyzer):
        raise error("FACE_GUIDANCE_UNAVAILABLE", "The configured face provider does not support live pose guidance.", 503)
    raw = _read_and_validate_upload(file, request)
    try:
        import anyio
        result = await anyio.to_thread.run_sync(analyzer, raw)
        log_face_event(
            "capture_guidance.completed",
            face_detected=bool(result.get("face_detected")),
            pose_bucket=result.get("pose_bucket"),
            quality_grade=result.get("quality_grade"),
            result="success",
        )
        return result
    finally:
        raw = b""


@router.post("/students/{student_id}/face-enrollment")
async def enroll_student_face(student_id: UUID, request: Request, files: list[UploadFile] = File(...),
                              identity: Identity = Depends(require_teacher), db: Session = Depends(get_db)):
    _, class_record = selected_teacher_class(db, identity.user.id, request)
    student_record = db.scalar(select(Student).where(Student.id == student_id).with_for_update())
    if student_record is None:
        raise error("STUDENT_NOT_FOUND", "Student is not enrolled in your assigned class.", 404)
    enrollment = db.scalar(select(StudentClassEnrollment).where(
        StudentClassEnrollment.student_id == student_id,
        StudentClassEnrollment.class_id == class_record.id,
        StudentClassEnrollment.enrollment_status == "ACTIVE",
    ))
    if enrollment is None:
        raise error("STUDENT_NOT_FOUND", "Student is not enrolled in your assigned class.", 404)
    consent = db.scalar(select(GuardianConsentRecord).where(GuardianConsentRecord.student_id == student_id).order_by(GuardianConsentRecord.recorded_at.desc()))
    if consent is None or consent.consent_status != "GRANTED" or not consent.consent_method or not consent.consent_record_reference:
        raise error("GUARDIAN_CONSENT_REQUIRED", "A verified guardian consent record from the Principal or a Principal-authorized teacher is required before face processing.", 403)
    if not 1 <= len(files) <= 3:
        raise error("INVALID_CAPTURE_COUNT", "Upload one to three guided still images.", 422)
    provider = _provider(request)
    log_face_event(
        "enrollment.started",
        capture_count=len(files),
        provider=getattr(provider, "provider_name", "unknown"),
        model_name=getattr(provider, "model_name", "unknown"),
        model_version=getattr(provider, "model_version", "unknown"),
    )
    embeddings: list[list[float]] = []
    for capture_index, file in enumerate(files, start=1):
        raw = _read_and_validate_upload(file, request)
        capture_started = time.perf_counter()
        try:
            # CPU inference runs outside the event loop; raw bytes remain in memory only.
            import anyio
            result = await anyio.to_thread.run_sync(provider.create_embedding, raw)
            vector_norm = sum(float(value) * float(value) for value in result.vector) ** 0.5
            log_face_event(
                "enrollment.capture_embedding_created",
                capture_index=capture_index,
                embedding_dimensions=len(result.vector),
                embedding_norm=round(vector_norm, 7),
                provider=result.provider,
                model_name=result.model_name,
                model_version=result.model_version,
                elapsed_ms=round((time.perf_counter() - capture_started) * 1000, 2),
            )
            embeddings.append(result.vector)
        except (NoFaceDetected, MultipleFacesDetected, PoorFaceQuality, ProviderUnavailable, FaceProviderError) as exc:
            log_face_event(
                "enrollment.capture_rejected",
                capture_index=capture_index,
                exception_type=type(exc).__name__,
                reason=str(exc),
                elapsed_ms=round((time.perf_counter() - capture_started) * 1000, 2),
            )
            raise error("FACE_ENROLLMENT_REJECTED", str(exc), 422 if not isinstance(exc, ProviderUnavailable) else 503) from exc
        finally:
            raw = b""
    cipher = _cipher(request)
    encrypted = cipher.encrypt_embeddings(embeddings, student_id=str(student_id))
    log_face_event(
        "enrollment.templates_encrypted",
        capture_count=len(embeddings),
        encrypted_bytes=len(encrypted),
        encryption_key_id=cipher.key_id,
    )
    old = db.scalars(select(StudentFaceTemplate).where(StudentFaceTemplate.student_id == student_id, StudentFaceTemplate.is_active.is_(True))).all()
    for template in old:
        db.delete(template)
    first = provider.create_embedding.__self__ if hasattr(provider.create_embedding, "__self__") else provider
    template = StudentFaceTemplate(
        student_id=student_id,
        ciphertext=encrypted,
        key_id=cipher.key_id,
        model_provider=first.provider_name,
        model_name=first.model_name,
        model_version=first.model_version,
        is_active=True,
    )
    db.add(template)
    add_audit(db, actor_user_id=identity.user.id, action="STUDENT_FACE_TEMPLATE_CREATED", entity_type="student", entity_id=student_id,
              metadata={"capture_count": len(embeddings), "model_provider": first.provider_name, "model_version": first.model_version})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise error("FACE_ENROLLMENT_CONFLICT", "A face template was enrolled by another request. Refresh and retry.", 409) from exc
    log_face_event(
        "enrollment.completed",
        capture_count=len(embeddings),
        provider=first.provider_name,
        model_name=first.model_name,
        model_version=first.model_version,
        result="success",
    )
    return {"student_id": str(student_id), "template_id": str(template.id), "status": "ENROLLED", "raw_images_retained": False}


@router.delete("/students/{student_id}/face-template")
def delete_student_face(student_id: UUID, request: Request, identity: Identity = Depends(require_teacher), db: Session = Depends(get_db)):
    _, class_record = selected_teacher_class(db, identity.user.id, request)
    student_record = db.scalar(select(Student).where(Student.id == student_id).with_for_update())
    if student_record is None:
        raise error("STUDENT_NOT_FOUND", "Student is not enrolled in your assigned class.", 404)
    enrollment = db.scalar(select(StudentClassEnrollment).where(StudentClassEnrollment.student_id == student_id, StudentClassEnrollment.class_id == class_record.id))
    if enrollment is None:
        raise error("STUDENT_NOT_FOUND", "Student is not enrolled in your assigned class.", 404)
    templates = db.scalars(select(StudentFaceTemplate).where(StudentFaceTemplate.student_id == student_id, StudentFaceTemplate.is_active.is_(True))).all()
    for template in templates:
        db.delete(template)
    add_audit(db, actor_user_id=identity.user.id, action="STUDENT_FACE_TEMPLATE_DELETED", entity_type="student", entity_id=student_id,
              metadata={"deactivated_templates": len(templates)})
    db.commit()
    return {"student_id": str(student_id), "deleted_templates": len(templates), "manual_attendance_available": True}


@router.post("/attendance/sessions", status_code=201)
def open_attendance_session(request: Request, identity: Identity = Depends(require_teacher), db: Session = Depends(get_db)):
    _, class_record = selected_teacher_class(db, identity.user.id, request)
    profile = db.get(SchoolProfile, 1)
    timezone_name = profile.timezone if profile else request.app.state.settings.school_timezone
    today = local_today(timezone_name)
    session = db.scalar(select(AttendanceSession).where(AttendanceSession.class_id == class_record.id, AttendanceSession.attendance_date == today))
    if session is None:
        session = AttendanceSession(class_id=class_record.id, attendance_date=today, opened_by_user_id=identity.user.id, status="OPEN")
        db.add(session)
        add_audit(db, actor_user_id=identity.user.id, action="ATTENDANCE_SESSION_OPENED", entity_type="attendance_session", entity_id="pending",
                  metadata={"class_id": str(class_record.id), "attendance_date": str(today)})
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            session = db.scalar(select(AttendanceSession).where(AttendanceSession.class_id == class_record.id, AttendanceSession.attendance_date == today))
    return {"session_id": str(session.id), "class_id": str(class_record.id), "attendance_date": today, "status": session.status,
            "existing_session": session.opened_by_user_id != identity.user.id}


@router.get("/attendance/sessions/{session_id}")
def attendance_session_detail(session_id: UUID, identity: Identity = Depends(require_teacher), db: Session = Depends(get_db)):
    session = _get_session_for_teacher(db, session_id, identity.user.id)
    total = db.scalar(select(func.count()).select_from(StudentClassEnrollment).where(
        StudentClassEnrollment.class_id == session.class_id, StudentClassEnrollment.enrollment_status == "ACTIVE")) or 0
    marks = db.scalars(select(AttendanceSessionMark).where(AttendanceSessionMark.session_id == session.id)).all()
    return {"session_id": str(session.id), "attendance_date": session.attendance_date, "status": session.status,
            "total_enrolled": total, "provisional_present_count": session.present_count if session.status != "FINALIZED" else None,
            "final_present_count": session.present_count if session.status == "FINALIZED" else None,
            "final_absent_count": session.absent_count if session.status == "FINALIZED" else None,
            "identified_unique": sum(m.status in {"PRESENT", "LATE"} for m in marks)}


@router.post("/attendance/sessions/{session_id}/identify")
async def identify_student(
    session_id: UUID,
    request: Request,
    file: UploadFile | None = File(default=None),
    files: list[UploadFile] | None = File(default=None),
    expected_enrollment_id: UUID | None = Form(default=None),
    identity: Identity = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    session = _get_session_for_teacher(db, session_id, identity.user.id, lock=True)
    if session.status not in {"OPEN", "REOPENED"}:
        raise error("SESSION_NOT_OPEN", "This attendance session is not accepting scans.", 409)
    uploads = files or ([file] if file is not None else [])
    if not 1 <= len(uploads) <= 3:
        raise error("INVALID_CAPTURE_COUNT", "Send one to three live face captures.", 422)

    attempt_limit = _attempt_limit(db)
    expected_enrollment = None
    if expected_enrollment_id is not None:
        if len(uploads) != 1:
            raise error("INVALID_CAPTURE_COUNT", "Attendance verification uses one front-facing capture per attempt.", 422)
        expected_enrollment = db.scalar(select(StudentClassEnrollment).where(
            StudentClassEnrollment.id == expected_enrollment_id,
            StudentClassEnrollment.class_id == session.class_id,
            StudentClassEnrollment.enrollment_status == "ACTIVE",
        ))
        if expected_enrollment is None:
            raise error("ENROLLMENT_NOT_FOUND", "The current student is not enrolled in this attendance class.", 404)
        current_attempts = _attempt_count(db, session.id, expected_enrollment.id)
        if current_attempts >= attempt_limit:
            raise error("FACE_ATTEMPT_LIMIT_REACHED", "The verification limit has been reached. Continue with manual student verification.", 409)
        existing_mark = db.scalar(select(AttendanceSessionMark).where(
            AttendanceSessionMark.session_id == session.id,
            AttendanceSessionMark.enrollment_id == expected_enrollment.id,
            AttendanceSessionMark.is_confirmed.is_(True),
        ))
        if existing_mark:
            raise error("STUDENT_ALREADY_CONFIRMED", "This student's attendance has already been confirmed.", 409)

    log_face_event("identification.started", session_status=session.status, capture_count=len(uploads))
    provider = _provider(request)
    captured_frames = []
    for capture_index, upload in enumerate(uploads, start=1):
        raw = _read_and_validate_upload(upload, request)
        embedding_started = time.perf_counter()
        try:
            import anyio
            captured = await anyio.to_thread.run_sync(provider.create_embedding, raw)
            captured_frames.append(captured)
            log_face_event(
                "identification.capture_embedding_created",
                capture_index=capture_index,
                capture_count=len(uploads),
                embedding_dimensions=len(captured.vector),
                embedding_norm=round(sum(float(value) * float(value) for value in captured.vector) ** 0.5, 7),
                provider=captured.provider,
                model_name=captured.model_name,
                model_version=captured.model_version,
                elapsed_ms=round((time.perf_counter() - embedding_started) * 1000, 2),
            )
        except NoFaceDetected as exc:
            log_face_event("identification.capture_rejected", capture_index=capture_index, stage="face_detection", exception_type=type(exc).__name__, reason=str(exc))
            event, _ = record_scan(db, session=session, teacher_user_id=identity.user.id, status="NO_MATCH")
            attempt_count = _attempt_count(db, session.id, expected_enrollment.id, increment=True) if expected_enrollment else None
            db.commit()
            suffix = f" Verification attempt {attempt_count} of {attempt_limit}." if attempt_count is not None else ""
            raise error("NO_FACE_DETECTED", f"{exc}{suffix}", 422) from exc
        except (MultipleFacesDetected, PoorFaceQuality) as exc:
            log_face_event("identification.capture_rejected", capture_index=capture_index, stage="face_quality", exception_type=type(exc).__name__, reason=str(exc))
            record_scan(db, session=session, teacher_user_id=identity.user.id, status="POOR_QUALITY")
            attempt_count = _attempt_count(db, session.id, expected_enrollment.id, increment=True) if expected_enrollment else None
            db.commit()
            suffix = f" Verification attempt {attempt_count} of {attempt_limit}." if attempt_count is not None else ""
            raise error("POOR_FACE_QUALITY", f"{exc}{suffix}", 422) from exc
        except ProviderUnavailable as exc:
            log_face_event("identification.capture_rejected", capture_index=capture_index, stage="provider", exception_type=type(exc).__name__, reason=str(exc))
            record_scan(db, session=session, teacher_user_id=identity.user.id, status="PROVIDER_UNAVAILABLE")
            db.commit()
            raise error("FACE_PROVIDER_UNAVAILABLE", str(exc), 503) from exc
        except FaceProviderError as exc:
            log_face_event("identification.capture_rejected", capture_index=capture_index, stage="embedding", exception_type=type(exc).__name__, reason=str(exc))
            record_scan(db, session=session, teacher_user_id=identity.user.id, status="POOR_QUALITY")
            attempt_count = _attempt_count(db, session.id, expected_enrollment.id, increment=True) if expected_enrollment else None
            db.commit()
            suffix = f" Verification attempt {attempt_count} of {attempt_limit}." if attempt_count is not None else ""
            raise error("FACE_PROCESSING_FAILED", f"The capture could not be processed. Retake a front-facing image.{suffix}", 422) from exc
        finally:
            raw = b""

    cipher = _cipher(request)
    rows = db.execute(select(StudentClassEnrollment, Student, StudentFaceTemplate).join(
        Student, Student.id == StudentClassEnrollment.student_id
    ).join(StudentFaceTemplate, StudentFaceTemplate.student_id == Student.id).where(
        StudentClassEnrollment.class_id == session.class_id,
        StudentClassEnrollment.enrollment_status == "ACTIVE",
        Student.status == "ACTIVE",
        StudentFaceTemplate.is_active.is_(True),
        StudentFaceTemplate.model_provider == provider.provider_name,
        StudentFaceTemplate.model_name == provider.model_name,
        StudentFaceTemplate.model_version == provider.model_version,
    )).all()
    if expected_enrollment is not None:
        rows = [row for row in rows if row[0].id == expected_enrollment.id]

    # Each live pose is scored against the student's enrolled templates. The final
    # per-student score is the mean of the best two pose scores (or the only score
    # for legacy single-image clients), matching the Lab's top-k aggregation idea.
    scores_by_frame: list[dict[UUID, float]] = [dict() for _ in captured_frames]
    template_vector_count = 0
    max_templates_per_student = 0
    scoring_started = time.perf_counter()
    try:
        for enrollment, student, template in rows:
            vectors = cipher.decrypt_embeddings(template.ciphertext, student_id=str(student.id))
            template_vector_count += len(vectors)
            max_templates_per_student = max(max_templates_per_student, len(vectors))
            for frame_index, captured in enumerate(captured_frames):
                frame_score = max(cosine_similarity(captured.vector, vec) for vec in vectors)
                scores_by_frame[frame_index][enrollment.id] = max(
                    frame_score, scores_by_frame[frame_index].get(enrollment.id, -1.0)
                )
    except Exception as exc:
        log_face_event("identification.template_read_failed", exception_type=type(exc).__name__, template_rows=len(rows))
        raise error("FACE_TEMPLATE_UNAVAILABLE", "A protected face template could not be read. Contact the Principal.", 503) from exc

    aggregate_top_k = min(2, len(captured_frames))
    best_by_enrollment: dict[UUID, float] = {}
    aggregate_inputs: dict[UUID, list[float]] = {}
    for frame_scores in scores_by_frame:
        for enrollment_id, frame_score in frame_scores.items():
            aggregate_inputs.setdefault(enrollment_id, []).append(frame_score)
    for enrollment_id, frame_scores in aggregate_inputs.items():
        selected_scores = sorted(frame_scores, reverse=True)[:aggregate_top_k]
        best_by_enrollment[enrollment_id] = sum(selected_scores) / len(selected_scores)

    scoring_ms = round((time.perf_counter() - scoring_started) * 1000, 2)
    log_face_event(
        "identification.template_scoring_complete",
        capture_count=len(captured_frames),
        aggregation_method="mean_of_best_two_capture_scores",
        template_rows=len(rows),
        template_embedding_count=template_vector_count,
        candidate_enrollments=len(best_by_enrollment),
        max_templates_per_student=max_templates_per_student,
        elapsed_ms=scoring_ms,
    )
    ranked = sorted(best_by_enrollment.items(), key=lambda item: item[1], reverse=True)
    status = "NO_MATCH"
    matched_enrollment = None
    score = ranked[0][1] if ranked else None
    settings = request.app.state.settings
    second_score = ranked[1][1] if len(ranked) > 1 else None
    score_gap = (ranked[0][1] - second_score) if ranked and second_score is not None else None
    if ranked and ranked[0][1] >= settings.face_match_threshold:
        if score_gap is not None and score_gap < settings.face_ambiguity_margin:
            status = "AMBIGUOUS"
        else:
            status = "MATCHED"
            matched_enrollment = db.get(StudentClassEnrollment, ranked[0][0])
    log_face_event(
        "identification.match_decision",
        capture_count=len(captured_frames),
        aggregation_method="mean_of_best_two_capture_scores",
        enrolled_template_rows=len(rows),
        candidate_enrollments=len(ranked),
        best_score=round(float(ranked[0][1]), 6) if ranked else None,
        second_best_score=round(float(second_score), 6) if second_score is not None else None,
        score_gap=round(float(score_gap), 6) if score_gap is not None else None,
        match_threshold=settings.face_match_threshold,
        ambiguity_margin=settings.face_ambiguity_margin,
        decision=status,
    )
    event, new_mark = record_scan(db, session=session, teacher_user_id=identity.user.id, status=status,
                                  enrollment=matched_enrollment, score=score)
    attempt_count = None
    manual_required = False
    if expected_enrollment is not None and status in {"NO_MATCH", "AMBIGUOUS"}:
        attempt_count = _attempt_count(db, session.id, expected_enrollment.id, increment=True)
        manual_required = attempt_count >= attempt_limit
    elif expected_enrollment is not None:
        attempt_count = _attempt_count(db, session.id, expected_enrollment.id)
    db.commit()
    log_face_event("identification.completed", result_status=event.result_status, capture_count=len(captured_frames), scan_event_created=True, new_mark=bool(new_mark))
    candidate = None
    if matched_enrollment and status in {"MATCHED", "DUPLICATE"}:
        student = db.get(Student, matched_enrollment.student_id)
        candidate = {"student_id": str(student.id), "enrollment_id": str(matched_enrollment.id),
                     "name": student.full_name, "roll_number": matched_enrollment.roll_number}
    result_status = event.result_status
    message = {
        "MATCHED": "Candidate identified. Teacher must confirm the displayed identity.",
        "DUPLICATE": "Already marked present in this session.",
        "AMBIGUOUS": "More than one candidate is too close to call. Use manual review.",
        "NO_MATCH": "No sufficiently reliable candidate was found. Use manual review.",
    }.get(result_status, result_status)
    return {
        "scan_event_id": str(event.id), "status": result_status, "candidate": candidate,
        "score": round(score, 5) if score is not None else None,
        "capture_count": len(captured_frames),
        "score_aggregation": "mean_of_best_two_capture_scores",
        "provisional_present_count": session.present_count, "new_unique_mark": new_mark,
        "teacher_confirmation_required": True, "message": message,
        "attempt_count": attempt_count, "attempt_limit": attempt_limit if expected_enrollment is not None else None,
        "manual_required": manual_required,
    }



def _current_unconfirmed_enrollment_id(db: Session, session: AttendanceSession) -> UUID | None:
    has_confirmed_mark = select(AttendanceSessionMark.id).where(
        AttendanceSessionMark.session_id == session.id,
        AttendanceSessionMark.enrollment_id == StudentClassEnrollment.id,
        AttendanceSessionMark.is_confirmed.is_(True),
    ).exists()
    return db.scalar(
        select(StudentClassEnrollment.id)
        .join(Student, Student.id == StudentClassEnrollment.student_id)
        .where(
            StudentClassEnrollment.class_id == session.class_id,
            StudentClassEnrollment.enrollment_status == "ACTIVE",
            Student.status == "ACTIVE",
            ~has_confirmed_mark,
        )
        .order_by(StudentClassEnrollment.roll_number)
        .limit(1)
    )

@router.get("/attendance/sessions/{session_id}/verification-progress")
def attendance_verification_progress(session_id: UUID, identity: Identity = Depends(require_teacher), db: Session = Depends(get_db)):
    session = _get_session_for_teacher(db, session_id, identity.user.id)
    settings = get_school_operations_settings(db)
    attempt_limit = int(settings["face_verification_attempt_limit"])
    include_details = bool(settings["student_information_enabled"])
    active_template = select(StudentFaceTemplate.id).where(
        StudentFaceTemplate.student_id == Student.id,
        StudentFaceTemplate.is_active.is_(True),
    ).exists()
    rows = db.execute(
        select(StudentClassEnrollment, Student, AttendanceSessionMark, AttendanceVerificationAttempt, active_template)
        .join(Student, Student.id == StudentClassEnrollment.student_id)
        .outerjoin(AttendanceSessionMark, (AttendanceSessionMark.session_id == session.id) & (AttendanceSessionMark.enrollment_id == StudentClassEnrollment.id))
        .outerjoin(AttendanceVerificationAttempt, (AttendanceVerificationAttempt.session_id == session.id) & (AttendanceVerificationAttempt.enrollment_id == StudentClassEnrollment.id))
        .where(
            StudentClassEnrollment.class_id == session.class_id,
            StudentClassEnrollment.enrollment_status == "ACTIVE",
            Student.status == "ACTIVE",
        )
        .order_by(StudentClassEnrollment.roll_number)
    ).all()
    students = []
    current = None
    for enrollment, student, mark, attempts, face_enrolled in rows:
        attempt_count = attempts.attempt_count if attempts else 0
        item = {
            "student_id": str(student.id), "enrollment_id": str(enrollment.id),
            "full_name": student.full_name, "roll_number": enrollment.roll_number,
            "face_enrolled": bool(face_enrolled), "attempt_count": attempt_count,
            "attempt_limit": attempt_limit, "attendance_status": mark.status if mark else None,
            "attendance_confirmed": bool(mark.is_confirmed) if mark else False,
            "attendance_source": mark.source if mark else None,
        }
        students.append(item)
        if current is None and not (mark and mark.is_confirmed):
            current = item
    manual_required = bool(current and (not current["face_enrolled"] or current["attempt_count"] >= attempt_limit))
    return {
        "session_id": str(session.id), "attempt_limit": attempt_limit,
        "student_information_enabled": include_details,
        "total_students": len(students),
        "confirmed_students": sum(1 for item in students if item["attendance_confirmed"]),
        "current_student": current,
        "manual_required": manual_required,
        "students": students,
    }


@router.get("/attendance/sessions/{session_id}/students/lookup")
def lookup_attendance_student(
    session_id: UUID, request: Request, q: str = Query(min_length=1, max_length=180),
    identity: Identity = Depends(require_teacher), db: Session = Depends(get_db),
):
    session = _get_session_for_teacher(db, session_id, identity.user.id)
    search = q.strip()
    if not search:
        return {"items": []}
    current_enrollment_id = _current_unconfirmed_enrollment_id(db, session)
    if current_enrollment_id is None:
        return {"items": []}
    rows = db.execute(
        select(Student, StudentClassEnrollment)
        .join(StudentClassEnrollment, StudentClassEnrollment.student_id == Student.id)
        .where(
            StudentClassEnrollment.class_id == session.class_id,
            StudentClassEnrollment.id == current_enrollment_id,
            StudentClassEnrollment.enrollment_status == "ACTIVE",
            Student.status == "ACTIVE",
            or_(Student.full_name.ilike(f"%{search}%"), StudentClassEnrollment.roll_number.ilike(f"%{search}%")),
        )
        .order_by(StudentClassEnrollment.roll_number)
        .limit(10)
    ).all()
    include_details = bool(get_school_operations_settings(db)["student_information_enabled"])
    items = []
    for student, enrollment in rows:
        item = {
            "student_id": str(student.id), "enrollment_id": str(enrollment.id),
            "full_name": student.full_name, "roll_number": enrollment.roll_number,
        }
        if include_details:
            item.update({
                "father_name": student.father_name,
                "mother_name": student.mother_name,
                "guardian_phone": student.guardian_phone,
                "alternate_guardian_phone": student.alternate_guardian_phone,
            })
        items.append(item)
    return {"items": items}


@router.post("/attendance/sessions/{session_id}/confirm-face/{enrollment_id}")
def confirm_face_attendance(
    session_id: UUID, enrollment_id: UUID, request: Request,
    identity: Identity = Depends(require_teacher), db: Session = Depends(get_db),
):
    session = _get_session_for_teacher(db, session_id, identity.user.id, lock=True)
    if session.status not in {"OPEN", "REOPENED"}:
        raise error("SESSION_NOT_OPEN", "Face confirmations are available only while scanning is open.", 409)
    if _current_unconfirmed_enrollment_id(db, session) != enrollment_id:
        raise error("NOT_CURRENT_STUDENT", "Confirm students in roll-number order. Only the current unconfirmed student can be confirmed here.", 409)
    mark = db.scalar(select(AttendanceSessionMark).where(
        AttendanceSessionMark.session_id == session.id,
        AttendanceSessionMark.enrollment_id == enrollment_id,
    ).with_for_update())
    if mark is None or mark.source != "FACE":
        raise error("FACE_CANDIDATE_NOT_FOUND", "No face candidate is waiting for confirmation.", 404)
    mark.is_confirmed = True
    mark.updated_by_user_id = identity.user.id
    mark.updated_at = utcnow()
    add_audit(db, actor_user_id=identity.user.id, action="FACE_ATTENDANCE_CONFIRMED", entity_type="attendance_session", entity_id=session.id,
              metadata={"enrollment_id": str(enrollment_id)})
    db.commit()
    return {"session_id": str(session.id), "enrollment_id": str(enrollment_id), "status": mark.status, "confirmed": True}


@router.post("/attendance/sessions/{session_id}/manual-confirm/{enrollment_id}")
def manual_confirm_attendance(
    session_id: UUID, enrollment_id: UUID, payload: ManualAttendanceConfirmRequest,
    identity: Identity = Depends(require_teacher), db: Session = Depends(get_db),
):
    session = _get_session_for_teacher(db, session_id, identity.user.id, lock=True)
    if session.status not in {"OPEN", "REOPENED"}:
        raise error("SESSION_NOT_OPEN", "Manual verification is available only while scanning is open.", 409)
    current_enrollment_id = _current_unconfirmed_enrollment_id(db, session)
    if current_enrollment_id != enrollment_id:
        raise error("NOT_CURRENT_STUDENT", "Verify students in roll-number order. Only the current unconfirmed student can be marked here.", 409)
    enrollment = db.scalar(select(StudentClassEnrollment).where(
        StudentClassEnrollment.id == enrollment_id,
        StudentClassEnrollment.class_id == session.class_id,
        StudentClassEnrollment.enrollment_status == "ACTIVE",
    ))
    if enrollment is None:
        raise error("ENROLLMENT_NOT_FOUND", "The selected student is not enrolled in this attendance class.", 404)
    mark = db.scalar(select(AttendanceSessionMark).where(
        AttendanceSessionMark.session_id == session.id,
        AttendanceSessionMark.enrollment_id == enrollment_id,
    ).with_for_update())
    if mark and mark.is_confirmed:
        raise error("STUDENT_ALREADY_CONFIRMED", "This student's attendance has already been confirmed.", 409)
    if mark is None:
        mark = AttendanceSessionMark(
            session_id=session.id, enrollment_id=enrollment_id, status=payload.status,
            source="MANUAL", is_confirmed=True, updated_by_user_id=identity.user.id,
        )
        db.add(mark)
    else:
        mark.status = payload.status
        mark.source = "MANUAL"
        mark.is_confirmed = True
        mark.updated_by_user_id = identity.user.id
        mark.updated_at = utcnow()
    session.present_count = db.scalar(select(func.count()).select_from(AttendanceSessionMark).where(
        AttendanceSessionMark.session_id == session.id,
        AttendanceSessionMark.status.in_(["PRESENT", "LATE"]),
    )) or 0
    add_audit(db, actor_user_id=identity.user.id, action="ATTENDANCE_MANUALLY_VERIFIED", entity_type="attendance_session", entity_id=session.id,
              metadata={"enrollment_id": str(enrollment_id), "status": payload.status})
    db.commit()
    return {"session_id": str(session.id), "enrollment_id": str(enrollment_id), "status": payload.status, "confirmed": True}


@router.get("/attendance/sessions/{session_id}/review")
def attendance_review(session_id: UUID, identity: Identity = Depends(require_teacher), db: Session = Depends(get_db)):
    session = _get_session_for_teacher(db, session_id, identity.user.id, lock=True)
    if session.status == "FINALIZED":
        raise error("SESSION_ALREADY_FINALIZED", "This session has already been finalized.", 409)
    if session.status == "CANCELLED":
        raise error("SESSION_CANCELLED", "This session has been cancelled.", 409)
    session.status = "REVIEW"
    db.commit()
    return review_payload(db, session)


@router.post("/attendance/sessions/{session_id}/resume-scanning")
def resume_attendance_scanning(session_id: UUID, identity: Identity = Depends(require_teacher), db: Session = Depends(get_db)):
    session = _get_session_for_teacher(db, session_id, identity.user.id, lock=True)
    if session.status != "REVIEW":
        raise error("SESSION_NOT_IN_REVIEW", "Only a session in review can return to scanning.", 409)
    session.status = "OPEN"
    add_audit(db, actor_user_id=identity.user.id, action="ATTENDANCE_REVIEW_RESUMED", entity_type="attendance_session", entity_id=session.id)
    db.commit()
    return {"session_id": str(session.id), "status": "OPEN", "message": "Scanning resumed. Existing provisional marks are preserved."}


@router.patch("/attendance/sessions/{session_id}/marks/{enrollment_id}")
def update_attendance_mark(session_id: UUID, enrollment_id: UUID, payload: MarkUpdateRequest,
                           identity: Identity = Depends(require_teacher), db: Session = Depends(get_db)):
    session = _get_session_for_teacher(db, session_id, identity.user.id, lock=True)
    if session.status not in {"REVIEW", "REOPENED"}:
        raise error("SESSION_NOT_IN_REVIEW", "Attendance changes are available only during review.", 409)
    enrollment = db.scalar(select(StudentClassEnrollment).where(
        StudentClassEnrollment.id == enrollment_id,
        StudentClassEnrollment.class_id == session.class_id,
        StudentClassEnrollment.enrollment_status == "ACTIVE",
    ))
    if enrollment is None:
        raise error("ENROLLMENT_NOT_FOUND", "Student enrollment was not found in this session's class.", 404)
    mark = db.scalar(select(AttendanceSessionMark).where(
        AttendanceSessionMark.session_id == session.id,
        AttendanceSessionMark.enrollment_id == enrollment_id,
    ).with_for_update())
    if mark is None:
        mark = AttendanceSessionMark(session_id=session.id, enrollment_id=enrollment_id,
                                     status=payload.status, source="MANUAL", is_confirmed=True,
                                     updated_by_user_id=identity.user.id)
        db.add(mark)
    else:
        previous_status = mark.status
        # Preserve FACE provenance when the teacher confirms the same candidate;
        # a changed status is an explicit manual correction. ADMIN marks remain ADMIN.
        if mark.source != "ADMIN" and not (mark.source == "FACE" and payload.status == previous_status):
            mark.source = "MANUAL"
        mark.status = payload.status
        mark.is_confirmed = True
        mark.updated_by_user_id = identity.user.id
        mark.updated_at = utcnow()
    mark.notes = payload.notes
    count = db.query(AttendanceSessionMark).filter(AttendanceSessionMark.session_id == session.id, AttendanceSessionMark.status.in_(["PRESENT", "LATE"])).count()
    session.present_count = count
    add_audit(db, actor_user_id=identity.user.id, action="ATTENDANCE_MARK_CORRECTED", entity_type="attendance_session", entity_id=session.id,
              metadata={"enrollment_id": str(enrollment_id), "status": payload.status, "source": "MANUAL"})
    db.commit()
    return {"session_id": str(session.id), "enrollment_id": str(enrollment_id), "status": payload.status, "confirmed": True}


@router.post("/attendance/sessions/{session_id}/finalize")
def submit_attendance(session_id: UUID, payload: FinalizeRequest,
                      identity: Identity = Depends(require_teacher), db: Session = Depends(get_db)):
    session = _get_session_for_teacher(db, session_id, identity.user.id, lock=True)
    try:
        result = finalize_session(db, session, identity.user.id)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


@router.get("/attendance/history")
def teacher_attendance_history(request: Request, from_date: date | None = None, to_date: date | None = None,
                               page: int = 1, page_size: int = 50,
                               identity: Identity = Depends(require_teacher), db: Session = Depends(get_db)):
    _, class_record = selected_teacher_class(db, identity.user.id, request)
    if from_date and to_date and from_date > to_date:
        raise error("INVALID_DATE_RANGE", "from_date must not be later than to_date.", 422)
    page = max(page, 1)
    page_size = min(max(page_size, 1), 200)
    query = select(AttendanceSession).where(AttendanceSession.class_id == class_record.id, AttendanceSession.status == "FINALIZED")
    if from_date:
        query = query.where(AttendanceSession.attendance_date >= from_date)
    if to_date:
        query = query.where(AttendanceSession.attendance_date <= to_date)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(AttendanceSession.attendance_date.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [{"session_id": str(s.id), "date": s.attendance_date, "present_count": s.present_count,
                       "absent_count": s.absent_count, "finalized_at": s.finalized_at} for s in rows],
            "page": page, "page_size": page_size, "total": total}
