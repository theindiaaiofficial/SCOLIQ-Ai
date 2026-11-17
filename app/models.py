from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from app.database import Base

JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


def now_utc() -> datetime:
    return datetime.now(UTC)


class SchoolProfile(Base):
    __tablename__ = "school_profile"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    school_name: Mapped[str] = mapped_column(String(180), nullable=False, default="My School")
    school_code: Mapped[str | None] = mapped_column(String(64), unique=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata")
    current_academic_year: Mapped[str] = mapped_column(String(32), nullable=False, default="2026-27")
    settings: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    logo_url: Mapped[str | None] = mapped_column(String(2048))
    branding: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)
    __table_args__ = (CheckConstraint("id = 1", name="ck_school_profile_singleton"),)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(String(180), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), unique=True)
    email: Mapped[str | None] = mapped_column(String(254), unique=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE")
    can_record_guardian_consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)
    __table_args__ = (
        CheckConstraint("role IN ('PRINCIPAL', 'TEACHER')", name="ck_users_role"),
        CheckConstraint("status IN ('ACTIVE', 'PENDING', 'SUSPENDED', 'REVOKED')", name="ck_users_status"),
        Index("ix_users_role_status", "role", "status"),
        Index("uq_single_principal_user", "role", unique=True, postgresql_where=text("role = 'PRINCIPAL'"), sqlite_where=text("role = 'PRINCIPAL'")),
    )


class AdminCredential(Base):
    __tablename__ = "admin_credentials"
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    password_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class BootstrapState(Base):
    __tablename__ = "bootstrap_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    __table_args__ = (CheckConstraint("id = 1", name="ck_bootstrap_state_singleton"),)


class TeacherAccessRequest(Base):
    __tablename__ = "teacher_access_requests"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(String(180), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    email: Mapped[str | None] = mapped_column(String(254))
    staff_identifier: Mapped[str | None] = mapped_column(String(80))
    public_reference_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(String(500))
    teacher_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), unique=True)
    __table_args__ = (
        CheckConstraint("status IN ('PENDING', 'APPROVED_PENDING_PASSKEY', 'ACTIVE', 'REJECTED', 'EXPIRED', 'REVOKED')", name="ck_teacher_request_status"),
        Index("ix_teacher_requests_status_requested", "status", "requested_at"),
        Index("uq_active_teacher_request_phone", "phone", unique=True, postgresql_where=text("status IN ('PENDING', 'APPROVED_PENDING_PASSKEY', 'ACTIVE')"), sqlite_where=text("status IN ('PENDING', 'APPROVED_PENDING_PASSKEY', 'ACTIVE')")),
    )


class TeacherActivationToken(Base):
    __tablename__ = "teacher_activation_tokens"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("teacher_access_requests.id", ondelete="CASCADE"), nullable=False)
    teacher_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    __table_args__ = (
        CheckConstraint("attempts >= 0 AND attempts <= 5", name="ck_activation_attempts"),
        Index("ix_activation_teacher_expiry", "teacher_user_id", "expires_at"),
    )


class PasskeyCredential(Base):
    __tablename__ = "passkey_credentials"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    credential_id: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False)
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sign_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    transports: Mapped[list[str] | None] = mapped_column(JSON_TYPE)
    device_type: Mapped[str | None] = mapped_column(String(64))
    backed_up: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_passkeys_user_active", "user_id", "revoked_at"),)


class WebAuthnChallenge(Base):
    __tablename__ = "webauthn_challenges"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    ceremony: Mapped[str] = mapped_column(String(24), nullable=False)
    challenge: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    __table_args__ = (
        CheckConstraint("ceremony IN ('REGISTRATION', 'AUTHENTICATION')", name="ck_webauthn_ceremony"),
        Index("ix_webauthn_user_ceremony_expiry", "user_id", "ceremony", "expires_at"),
    )


class AppSession(Base):
    __tablename__ = "app_sessions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    csrf_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(24), nullable=False, default="AUTHENTICATED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rotated_from_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("app_sessions.id", ondelete="SET NULL"))
    __table_args__ = (
        CheckConstraint("purpose IN ('AUTHENTICATED', 'ACTIVATION')", name="ck_session_purpose"),
        Index("ix_sessions_user_expiry", "user_id", "expires_at"),
    )


class PrincipalPasswordResetCode(Base):
    __tablename__ = "principal_password_reset_codes"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    email_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ip_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("attempts >= 0 AND attempts <= 5", name="ck_password_reset_attempts"),
        Index("ix_password_reset_email_created", "email_hash", "created_at"),
        Index("ix_password_reset_ip_created", "ip_hash", "created_at"),
    )


class ClassRecord(Base):
    __tablename__ = "classes"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    grade_label: Mapped[str] = mapped_column(String(32), nullable=False)
    section_label: Mapped[str] = mapped_column(String(32), nullable=False)
    academic_year: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    __table_args__ = (
        UniqueConstraint("grade_label", "section_label", "academic_year", name="uq_class_grade_section_year"),
        CheckConstraint("status IN ('ACTIVE', 'ARCHIVED')", name="ck_classes_status"),
        Index("ix_classes_status_year", "status", "academic_year"),
    )


class TeacherClassAssignment(Base):
    __tablename__ = "teacher_class_assignments"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    teacher_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("classes.id", ondelete="CASCADE"), nullable=False)
    is_class_teacher: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    active_slot: Mapped[str | None] = mapped_column(String(24))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("class_id", "active_slot", name="uq_active_teacher_per_class"),
        UniqueConstraint("teacher_user_id", "class_id", name="uq_teacher_class_pair"),
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE', 'PENDING_ADMIN_REVIEW')", name="ck_assignment_status"),
        Index("ix_assignments_teacher_status", "teacher_user_id", "status"),
    )


class Student(Base):
    __tablename__ = "students"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    school_student_code: Mapped[str | None] = mapped_column(String(64), unique=True)
    full_name: Mapped[str] = mapped_column(String(180), nullable=False)
    father_name: Mapped[str | None] = mapped_column(String(180))
    mother_name: Mapped[str | None] = mapped_column(String(180))
    guardian_phone: Mapped[str | None] = mapped_column(String(32))
    alternate_guardian_phone: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)
    __table_args__ = (CheckConstraint("status IN ('ACTIVE', 'TRANSFERRED', 'INACTIVE')", name="ck_students_status"),)


class StudentClassEnrollment(Base):
    __tablename__ = "student_class_enrollments"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False)
    roll_number: Mapped[str] = mapped_column(String(32), nullable=False)
    academic_year: Mapped[str] = mapped_column(String(32), nullable=False)
    enrollment_status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    enrolled_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    __table_args__ = (
        UniqueConstraint("class_id", "roll_number", name="uq_enrollment_class_roll"),
        UniqueConstraint("student_id", "academic_year", name="uq_student_academic_year"),
        CheckConstraint("enrollment_status IN ('ACTIVE', 'COMPLETED', 'TRANSFERRED')", name="ck_enrollment_status"),
        Index("ix_enrollment_class_status", "class_id", "enrollment_status"),
    )


class GuardianConsentRecord(Base):
    __tablename__ = "guardian_consent_records"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    consent_status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    consent_method: Mapped[str | None] = mapped_column(String(80))
    consent_record_reference: Mapped[str | None] = mapped_column(String(255))
    recorded_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    __table_args__ = (
        CheckConstraint("consent_status IN ('GRANTED', 'WITHDRAWN', 'PENDING')", name="ck_consent_status"),
        Index("ix_consent_student_recorded", "student_id", "recorded_at"),
    )


class StudentFaceTemplate(Base):
    __tablename__ = "student_face_templates"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_id: Mapped[str] = mapped_column(String(32), nullable=False)
    model_provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_version: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        Index("ix_face_templates_student_active", "student_id", "is_active"),
        Index("uq_active_face_template_student", "student_id", unique=True, postgresql_where=text("is_active = true"), sqlite_where=text("is_active = 1")),
    )


class AttendanceSession(Base):
    __tablename__ = "attendance_sessions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    class_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False)
    attendance_date: Mapped[Any] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    opened_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    finalized_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    present_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    absent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    __table_args__ = (
        UniqueConstraint("class_id", "attendance_date", name="uq_session_class_date"),
        CheckConstraint("status IN ('OPEN', 'REVIEW', 'FINALIZED', 'CANCELLED', 'REOPENED')", name="ck_attendance_session_status"),
        CheckConstraint("present_count >= 0 AND absent_count >= 0", name="ck_attendance_counts_nonnegative"),
        Index("ix_attendance_sessions_date_status", "attendance_date", "status"),
    )


class AttendanceScanEvent(Base):
    __tablename__ = "attendance_scan_events"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("attendance_sessions.id", ondelete="CASCADE"), nullable=False)
    matched_enrollment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("student_class_enrollments.id", ondelete="SET NULL"))
    result_status: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[float | None] = mapped_column()
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    __table_args__ = (
        CheckConstraint("result_status IN ('MATCHED', 'DUPLICATE', 'NO_MATCH', 'AMBIGUOUS', 'POOR_QUALITY', 'PROVIDER_UNAVAILABLE', 'ALREADY_REVIEWED')", name="ck_scan_event_status"),
        CheckConstraint("score IS NULL OR (score >= -1 AND score <= 1)", name="ck_scan_event_score_range"),
        Index("ix_scan_events_session_time", "session_id", "scanned_at"),
    )


class AttendanceVerificationAttempt(Base):
    __tablename__ = "attendance_verification_attempts"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("attendance_sessions.id", ondelete="CASCADE"), nullable=False)
    enrollment_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("student_class_enrollments.id", ondelete="CASCADE"), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)
    __table_args__ = (
        UniqueConstraint("session_id", "enrollment_id", name="uq_face_attempt_session_enrollment"),
        CheckConstraint("attempt_count >= 0 AND attempt_count <= 5", name="ck_face_attempt_count"),
        Index("ix_face_attempt_session", "session_id"),
    )


class AttendanceSessionMark(Base):
    __tablename__ = "attendance_session_marks"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("attendance_sessions.id", ondelete="CASCADE"), nullable=False)
    enrollment_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("student_class_enrollments.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    is_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(String(300))
    updated_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)
    __table_args__ = (
        UniqueConstraint("session_id", "enrollment_id", name="uq_session_mark_enrollment"),
        CheckConstraint("status IN ('PRESENT', 'ABSENT', 'LATE', 'EXCUSED')", name="ck_session_mark_status"),
        CheckConstraint("source IN ('FACE', 'MANUAL', 'ADMIN')", name="ck_session_mark_source"),
        Index("ix_session_marks_session_confirmed", "session_id", "is_confirmed"),
    )


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    attendance_session_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("attendance_sessions.id", ondelete="CASCADE"), nullable=False)
    student_enrollment_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("student_class_enrollments.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    identification_method: Mapped[str] = mapped_column(String(16), nullable=False)
    confirmed_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(300))
    __table_args__ = (
        UniqueConstraint("attendance_session_id", "student_enrollment_id", name="uq_attendance_record_session_enrollment"),
        CheckConstraint("status IN ('PRESENT', 'ABSENT', 'LATE', 'EXCUSED')", name="ck_attendance_record_status"),
        CheckConstraint("identification_method IN ('FACE_MATCH', 'MANUAL', 'ADMIN')", name="ck_attendance_identification_method"),
        Index("ix_attendance_records_session_status", "attendance_session_id", "status"),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON_TYPE, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    __table_args__ = (Index("ix_audit_created", "created_at"), Index("ix_audit_actor_action", "actor_user_id", "action"))
