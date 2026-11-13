from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import error
from app.core.security import digest_token, new_token
from app.database import get_db
from app.models import SchoolProfile, TeacherAccessRequest
from app.schemas import BrandingConfig, DEFAULT_BRANDING, TeacherRequestCreate, TeacherRequestStatus

router = APIRouter(tags=["Public teacher onboarding"])


@router.post("/teacher-requests", status_code=201)
def create_teacher_request(payload: TeacherRequestCreate, request: Request, db: Session = Depends(get_db)):
    if db.scalar(select(TeacherAccessRequest.id).where(
        TeacherAccessRequest.phone == payload.phone,
        TeacherAccessRequest.status.in_(["PENDING", "APPROVED_PENDING_PASSKEY", "ACTIVE"]),
    )):
        raise error("REQUEST_ALREADY_EXISTS", "A request for this phone number is already on file.", 409)
    reference = new_token(32)
    item = TeacherAccessRequest(
        full_name=payload.full_name,
        phone=payload.phone,
        email=str(payload.email).lower() if payload.email else None,
        staff_identifier=payload.staff_identifier,
        public_reference_hash=digest_token(reference, request.app.state.settings.session_secret or None),
    )
    db.add(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise error("REQUEST_ALREADY_EXISTS", "A request for this phone number is already on file.", 409) from exc
    return {
        "message": "Your request is waiting for Principal approval.",
        "public_reference": reference,
        "status": "PENDING",
        "status_check_path": f"/api/v1/teacher-requests/{reference}/status",
    }


@router.get("/teacher-requests/{public_reference}/status", response_model=TeacherRequestStatus)
def get_request_status(public_reference: str, request: Request, db: Session = Depends(get_db)):
    if len(public_reference) < 32 or len(public_reference) > 256:
        raise error("REQUEST_NOT_FOUND", "Request status could not be found.", 404)
    item = db.scalar(select(TeacherAccessRequest).where(TeacherAccessRequest.public_reference_hash == digest_token(public_reference, request.app.state.settings.session_secret or None)))
    if item is None:
        # Identical response avoids confirming whether a request record exists.
        raise error("REQUEST_NOT_FOUND", "Request status could not be found.", 404)
    return TeacherRequestStatus(status=item.status, requested_at=item.requested_at, reviewed_at=item.reviewed_at)


@router.get("/public/school-branding")
def get_public_school_branding(db: Session = Depends(get_db)):
    """Public school identity only; intentionally excludes operational/private settings."""
    profile = db.get(SchoolProfile, 1)
    if profile is None:
        profile = SchoolProfile(id=1, branding=dict(DEFAULT_BRANDING))
        db.add(profile)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            profile = db.get(SchoolProfile, 1)
    branding = BrandingConfig.model_validate({**DEFAULT_BRANDING, **((profile.branding or {}) if profile else {})})
    return {
        "school_name": profile.school_name if profile else "My School",
        "logo_url": profile.logo_url if profile else None,
        "branding": branding.model_dump(),
    }
