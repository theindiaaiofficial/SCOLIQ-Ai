from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import digest_token, new_token, utcnow
from app.models import AppSession

SESSION_COOKIE = "smartattend_session"
CSRF_COOKIE = "smartattend_csrf"


def issue_session(db: Session, user_id, settings, *, purpose: str = "AUTHENTICATED", ttl_minutes: int | None = None) -> tuple[str, str, AppSession]:
    raw_token = new_token(48)
    csrf_token = new_token(32)
    lifetime = timedelta(minutes=ttl_minutes) if ttl_minutes else timedelta(hours=settings.session_ttl_hours)
    record = AppSession(
        user_id=user_id,
        token_hash=digest_token(raw_token, settings.session_secret or None),
        csrf_token_hash=digest_token(csrf_token, settings.session_secret or None),
        purpose=purpose,
        expires_at=utcnow() + lifetime,
    )
    db.add(record)
    db.flush()
    return raw_token, csrf_token, record


def revoke_session(db: Session, session: AppSession) -> None:
    session.revoked_at = utcnow()
    db.add(session)


def revoke_all_user_sessions(db: Session, user_id) -> int:
    sessions = db.scalars(select(AppSession).where(AppSession.user_id == user_id, AppSession.revoked_at.is_(None))).all()
    for item in sessions:
        item.revoked_at = utcnow()
    return len(sessions)
