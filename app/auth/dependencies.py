from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import error
from app.core.security import digest_token, utcnow
from app.database import get_db
from app.models import AppSession, User


@dataclass(frozen=True)
class Identity:
    user: User
    session: AppSession


def current_identity(request: Request, db: Session = Depends(get_db)) -> Identity:
    token = request.cookies.get("smartattend_session")
    if not token:
        raise error("AUTHENTICATION_REQUIRED", "Please sign in.", 401)
    record = db.scalar(select(AppSession).where(
        AppSession.token_hash == digest_token(token, request.app.state.settings.session_secret or None),
        AppSession.revoked_at.is_(None),
        AppSession.expires_at > utcnow(),
    ))
    if record is None:
        raise error("SESSION_INVALID", "Your session is invalid or expired. Please sign in again.", 401)
    if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
        csrf = request.headers.get("X-CSRF-Token", "")
        if not csrf or digest_token(csrf, request.app.state.settings.session_secret or None) != record.csrf_token_hash:
            raise error("CSRF_VALIDATION_FAILED", "A valid CSRF token is required.", 403)
    user = db.get(User, record.user_id)
    if user is None:
        raise error("SESSION_INVALID", "Your account is unavailable.", 401)
    if user.status != "ACTIVE" and record.purpose != "ACTIVATION":
        raise error("ACCOUNT_INACTIVE", "This account is not active.", 403)
    return Identity(user=user, session=record)


def require_admin(identity: Identity = Depends(current_identity)) -> Identity:
    if identity.user.role != "PRINCIPAL" or identity.session.purpose != "AUTHENTICATED":
        raise error("FORBIDDEN", "Principal access is required.", 403)
    return identity


def require_teacher(identity: Identity = Depends(current_identity)) -> Identity:
    if identity.user.role != "TEACHER" or identity.user.status != "ACTIVE" or identity.session.purpose != "AUTHENTICATED":
        raise error("FORBIDDEN", "An active teacher session is required.", 403)
    return identity


def require_activation_teacher(identity: Identity = Depends(current_identity)) -> Identity:
    if identity.user.role != "TEACHER" or identity.user.status != "PENDING" or identity.session.purpose != "ACTIVATION":
        raise error("FORBIDDEN", "A valid teacher activation session is required.", 403)
    return identity
