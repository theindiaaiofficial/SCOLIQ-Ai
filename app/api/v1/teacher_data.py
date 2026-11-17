from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import Identity, require_teacher
from app.core.errors import error
from app.database import get_db
from app.models import (
    ClassRecord,
    GuardianConsentRecord,
    Student,
    StudentClassEnrollment,
    StudentFaceTemplate,
    TeacherClassAssignment,
    SchoolProfile,
)
from app.schemas import ClassSetupRequest, ConsentGrantRequest, StudentCreateRequest, StudentUpdateRequest
from app.services.common import add_audit, selected_teacher_class
from app.services.school_settings import get_school_operations_settings

router = APIRouter(prefix="/teacher", tags=["Teacher class and students"])


@router.get("/student-form-settings")
def student_form_settings(identity: Identity = Depends(require_teacher), db: Session = Depends(get_db)):
    settings = get_school_operations_settings(db)
    return {"student_information_enabled": bool(settings["student_information_enabled"])}


@router.post("/class-setup", status_code=201)
def class_setup(payload: ClassSetupRequest, identity: Identity = Depends(require_teacher), db: Session = Depends(get_db)):
    from app.models import SchoolProfile
    profile = db.get(SchoolProfile, 1)
    if profile and payload.academic_year != profile.current_academic_year:
        raise error("ACADEMIC_YEAR_NOT_ALLOWED", "Class setup must use the school's currently configured academic year.", 409)
    class_record = db.scalar(select(ClassRecord).where(
        ClassRecord.grade_label == payload.grade_label,
        ClassRecord.section_label == payload.section_label,
        ClassRecord.academic_year == payload.academic_year,
    ))
    if class_record is None:
        class_record = ClassRecord(
            grade_label=payload.grade_label,
            section_label=payload.section_label,
            academic_year=payload.academic_year,
            created_by_user_id=identity.user.id,
        )
        db.add(class_record)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            class_record = db.scalar(select(ClassRecord).where(
                ClassRecord.grade_label == payload.grade_label,
                ClassRecord.section_label == payload.section_label,
                ClassRecord.academic_year == payload.academic_year,
            ))
            if class_record is None:
                raise error("CLASS_SETUP_CONFLICT", "The class could not be created due to a concurrent update.", 409)
    owner = db.scalar(select(TeacherClassAssignment).where(
        TeacherClassAssignment.class_id == class_record.id,
        TeacherClassAssignment.active_slot == "CLASS_TEACHER",
    ))
    if owner and owner.teacher_user_id != identity.user.id:
        db.rollback()
        raise error("CLASS_ALREADY_ASSIGNED", "This class already has an active class teacher. Contact the Principal for resolution.", 409)
    assignment = db.scalar(select(TeacherClassAssignment).where(
        TeacherClassAssignment.teacher_user_id == identity.user.id,
        TeacherClassAssignment.class_id == class_record.id,
    ))
    if assignment is None:
        assignment = TeacherClassAssignment(
            teacher_user_id=identity.user.id,
            class_id=class_record.id,
            is_class_teacher=True,
            status="ACTIVE",
            active_slot="CLASS_TEACHER",
        )
        db.add(assignment)
    else:
        assignment.status = "ACTIVE"
        assignment.active_slot = "CLASS_TEACHER"
        assignment.ended_at = None
    add_audit(db, actor_user_id=identity.user.id, action="CLASS_SETUP_COMPLETED", entity_type="class", entity_id=class_record.id,
              metadata={"grade": payload.grade_label, "section": payload.section_label, "academic_year": payload.academic_year})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise error("CLASS_ALREADY_ASSIGNED", "Another teacher has claimed this class. Ask the Principal to resolve the assignment.", 409) from exc
    return {"class_id": str(class_record.id), "grade": class_record.grade_label, "section": class_record.section_label,
            "academic_year": class_record.academic_year, "assignment_id": str(assignment.id)}


@router.get("/classes")
def teacher_classes(identity: Identity = Depends(require_teacher), db: Session = Depends(get_db)):
    rows = db.execute(select(TeacherClassAssignment, ClassRecord).join(ClassRecord, ClassRecord.id == TeacherClassAssignment.class_id).where(
        TeacherClassAssignment.teacher_user_id == identity.user.id,
        TeacherClassAssignment.status == "ACTIVE",
        ClassRecord.status == "ACTIVE",
    )).all()
    return [{"class_id": str(c.id), "grade": c.grade_label, "section": c.section_label, "academic_year": c.academic_year} for _, c in rows]


@router.get("/class")
def teacher_class(request: Request, identity: Identity = Depends(require_teacher), db: Session = Depends(get_db)):
    assignment, class_record = selected_teacher_class(db, identity.user.id, request)
    total = db.scalar(select(func.count()).select_from(StudentClassEnrollment).where(
        StudentClassEnrollment.class_id == class_record.id, StudentClassEnrollment.enrollment_status == "ACTIVE"
    )) or 0
    return {"class_id": str(class_record.id), "grade": class_record.grade_label, "section": class_record.section_label,
            "academic_year": class_record.academic_year, "total_enrolled_students": total}


@router.post("/students", status_code=201)
def create_student(payload: StudentCreateRequest, request: Request, identity: Identity = Depends(require_teacher), db: Session = Depends(get_db)):
    _, class_record = selected_teacher_class(db, identity.user.id, request)
    school_settings = get_school_operations_settings(db)
    student_information_enabled = bool(school_settings["student_information_enabled"])
    extra_fields = (payload.father_name, payload.mother_name, payload.guardian_phone, payload.alternate_guardian_phone)
    if not student_information_enabled and any(value is not None for value in extra_fields):
        raise error("STUDENT_INFORMATION_DISABLED", "Detailed student information is currently disabled by the Principal.", 403)
    student = db.scalar(select(Student).where(Student.school_student_code == payload.school_student_code)) if payload.school_student_code else None
    if student and db.scalar(select(StudentClassEnrollment.id).where(
        StudentClassEnrollment.student_id == student.id,
        StudentClassEnrollment.academic_year == class_record.academic_year,
    )):
        raise error("STUDENT_ALREADY_ENROLLED", "This student already has an enrollment for the current academic year.", 409)
    created_new_student = student is None
    if student is None:
        student = Student(
            full_name=payload.full_name,
            school_student_code=payload.school_student_code,
            father_name=payload.father_name if student_information_enabled else None,
            mother_name=payload.mother_name if student_information_enabled else None,
            guardian_phone=payload.guardian_phone if student_information_enabled else None,
            alternate_guardian_phone=payload.alternate_guardian_phone if student_information_enabled else None,
        )
        db.add(student)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise error("ENROLLMENT_CONFLICT", "The student code was enrolled by another request. Refresh the roster and retry.", 409) from exc
    else:
        student.full_name = payload.full_name
        if student_information_enabled:
            for field in ("father_name", "mother_name", "guardian_phone", "alternate_guardian_phone"):
                value = getattr(payload, field)
                if value is not None:
                    setattr(student, field, value)
    enrollment = StudentClassEnrollment(
        student_id=student.id,
        class_id=class_record.id,
        roll_number=payload.roll_number,
        academic_year=class_record.academic_year,
        enrolled_by_user_id=identity.user.id,
    )
    db.add(enrollment)
    db.add(GuardianConsentRecord(student_id=student.id, consent_status="PENDING", recorded_by_user_id=identity.user.id))
    add_audit(db, actor_user_id=identity.user.id, action="STUDENT_ENROLLED", entity_type="student", entity_id=student.id,
              metadata={"enrollment_id": str(enrollment.id), "class_id": str(class_record.id), "consent_status": "PENDING"})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise error("ENROLLMENT_CONFLICT", "Duplicate roll number, school code, or academic-year enrollment.", 409) from exc
    return {"student_id": str(student.id), "enrollment_id": str(enrollment.id), "full_name": student.full_name,
            "roll_number": enrollment.roll_number, "class_id": str(class_record.id), "consent_status": "PENDING",
            "new_student_record": created_new_student}


@router.get("/students")
def list_students(request: Request, page: int = 1, page_size: int = 50, q: str | None = None,
                 identity: Identity = Depends(require_teacher), db: Session = Depends(get_db)):
    _, class_record = selected_teacher_class(db, identity.user.id, request)
    page = max(page, 1)
    page_size = min(max(page_size, 1), 200)
    latest_consent = (select(GuardianConsentRecord.consent_status)
                      .where(GuardianConsentRecord.student_id == Student.id)
                      .order_by(GuardianConsentRecord.recorded_at.desc())
                      .limit(1).correlate(Student).scalar_subquery())
    has_face_template = select(StudentFaceTemplate.id).where(
        StudentFaceTemplate.student_id == Student.id, StudentFaceTemplate.is_active.is_(True)
    ).exists()
    query = select(Student, StudentClassEnrollment, latest_consent, has_face_template).join(
        StudentClassEnrollment, StudentClassEnrollment.student_id == Student.id
    ).where(
        StudentClassEnrollment.class_id == class_record.id,
        StudentClassEnrollment.enrollment_status == "ACTIVE",
        Student.status == "ACTIVE",
    )
    if q:
        query = query.where(Student.full_name.ilike(f"%{q}%") | StudentClassEnrollment.roll_number.ilike(f"%{q}%"))
    count_query = select(func.count()).select_from(query.subquery())
    total = db.scalar(count_query) or 0
    rows = db.execute(query.order_by(StudentClassEnrollment.roll_number).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [{"student_id": str(s.id), "enrollment_id": str(e.id), "full_name": s.full_name,
                       "roll_number": e.roll_number, "school_student_code": s.school_student_code, "status": s.status,
                       "consent_status": consent_status or "PENDING", "face_enrolled": bool(face_enrolled)}
                      for s, e, consent_status, face_enrolled in rows],
            "page": page, "page_size": page_size, "total": total}


@router.get("/students/{student_id}")
def get_student(student_id: UUID, request: Request, identity: Identity = Depends(require_teacher), db: Session = Depends(get_db)):
    _, class_record = selected_teacher_class(db, identity.user.id, request)
    row = db.execute(select(Student, StudentClassEnrollment).join(StudentClassEnrollment, StudentClassEnrollment.student_id == Student.id).where(
        Student.id == student_id, StudentClassEnrollment.class_id == class_record.id,
    )).first()
    if row is None:
        raise error("STUDENT_NOT_FOUND", "Student was not found in your assigned class.", 404)
    student, enrollment = row
    consent = db.scalar(select(GuardianConsentRecord).where(GuardianConsentRecord.student_id == student.id).order_by(GuardianConsentRecord.recorded_at.desc()))
    settings = get_school_operations_settings(db)
    include_details = bool(settings["student_information_enabled"])
    return {"student_id": str(student.id), "enrollment_id": str(enrollment.id), "full_name": student.full_name,
            "roll_number": enrollment.roll_number, "school_student_code": student.school_student_code,
            "status": student.status, "consent_status": consent.consent_status if consent else "PENDING",
            "father_name": student.father_name if include_details else None,
            "mother_name": student.mother_name if include_details else None,
            "guardian_phone": student.guardian_phone if include_details else None,
            "alternate_guardian_phone": student.alternate_guardian_phone if include_details else None}


@router.patch("/students/{student_id}")
def update_student(student_id: UUID, payload: StudentUpdateRequest, request: Request,
                   identity: Identity = Depends(require_teacher), db: Session = Depends(get_db)):
    _, class_record = selected_teacher_class(db, identity.user.id, request)
    row = db.execute(select(Student, StudentClassEnrollment).join(StudentClassEnrollment, StudentClassEnrollment.student_id == Student.id).where(
        Student.id == student_id, StudentClassEnrollment.class_id == class_record.id,
    )).first()
    if row is None:
        raise error("STUDENT_NOT_FOUND", "Student was not found in your assigned class.", 404)
    student, enrollment = row
    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    profile_settings = get_school_operations_settings(db)
    detail_keys = {"father_name", "mother_name", "guardian_phone", "alternate_guardian_phone"}
    if not profile_settings["student_information_enabled"] and detail_keys.intersection(updates):
        raise error("STUDENT_INFORMATION_DISABLED", "Detailed student information is currently disabled by the Principal.", 403)
    if "full_name" in updates:
        student.full_name = updates["full_name"]
    if "roll_number" in updates:
        enrollment.roll_number = updates["roll_number"]
    for field in detail_keys.intersection(updates):
        setattr(student, field, updates[field])
    if "status" in updates:
        student.status = updates["status"]
        if updates["status"] == "TRANSFERRED":
            enrollment.enrollment_status = "TRANSFERRED"
        elif updates["status"] == "INACTIVE":
            enrollment.enrollment_status = "COMPLETED"
        elif updates["status"] == "ACTIVE":
            enrollment.enrollment_status = "ACTIVE"
    add_audit(db, actor_user_id=identity.user.id, action="STUDENT_UPDATED", entity_type="student", entity_id=student.id, metadata={"fields": list(updates)})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise error("STUDENT_UPDATE_CONFLICT", "The requested update conflicts with an existing student record.", 409) from exc
    return {"student_id": str(student.id), "enrollment_id": str(enrollment.id), "full_name": student.full_name,
            "roll_number": enrollment.roll_number, "status": student.status}


@router.post("/students/{student_id}/consent")
def teacher_record_student_consent(
    student_id: UUID, payload: ConsentGrantRequest, request: Request,
    identity: Identity = Depends(require_teacher), db: Session = Depends(get_db),
):
    """Record verified guardian consent only for a teacher explicitly authorized by the Principal."""
    if not identity.user.can_record_guardian_consent:
        raise error("CONSENT_RECORD_PERMISSION_REQUIRED", "The Principal has not enabled guardian-consent recording for your account.", 403)
    _, class_record = selected_teacher_class(db, identity.user.id, request)
    student = db.scalar(
        select(Student).join(StudentClassEnrollment, StudentClassEnrollment.student_id == Student.id).where(
            Student.id == student_id,
            StudentClassEnrollment.class_id == class_record.id,
            StudentClassEnrollment.enrollment_status == "ACTIVE",
        ).with_for_update()
    )
    if student is None:
        raise error("STUDENT_NOT_FOUND", "Student is not enrolled in your assigned class.", 404)

    record = GuardianConsentRecord(
        student_id=student_id, consent_status=payload.consent_status,
        consent_method=payload.consent_method, consent_record_reference=payload.consent_record_reference,
        recorded_by_user_id=identity.user.id,
    )
    db.add(record)
    removed_templates = 0
    if payload.consent_status == "WITHDRAWN":
        templates = db.scalars(select(StudentFaceTemplate).where(
            StudentFaceTemplate.student_id == student_id, StudentFaceTemplate.is_active.is_(True)
        )).all()
        removed_templates = len(templates)
        for template in templates:
            db.delete(template)
    add_audit(
        db, actor_user_id=identity.user.id,
        action="TEACHER_GUARDIAN_CONSENT_GRANTED" if payload.consent_status == "GRANTED" else "TEACHER_GUARDIAN_CONSENT_WITHDRAWN",
        entity_type="student", entity_id=student_id,
        metadata={
            "consent_method": payload.consent_method,
            "consent_record_reference": payload.consent_record_reference,
            "class_id": str(class_record.id),
            "removed_face_templates": removed_templates,
        },
    )
    db.commit()
    return {"student_id": str(student_id), "consent_status": payload.consent_status, "record_id": str(record.id), "recorded_by": str(identity.user.id)}
