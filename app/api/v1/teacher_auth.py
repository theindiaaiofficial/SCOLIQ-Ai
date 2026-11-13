from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth.dependencies import Identity, require_activation_teacher, require_teacher
from app.auth.passkeys import (
    create_authentication_options,
    create_registration_options,
    verify_authentication,
    verify_registration,
)
from app.auth.sessions import issue_session, revoke_session
from app.core.config import Settings
from app.core.errors import error
from app.core.security import constant_time_secret_match, digest_token, is_expired, new_token, utcnow
from app.database import get_db
from app.models import (
    AppSession,
    PasskeyCredential,
    TeacherAccessRequest,
    TeacherActivationToken,
    User,
)
from app.schemas import ActivationRedeemRequest, WebAuthnOptionsRequest, WebAuthnVerifyRequest
from app.services.common import add_audit, clear_auth_cookies, set_auth_cookies

router = APIRouter(prefix="/teacher", tags=["Teacher authentication"])


def settings_from(request: Request) -> Settings:
    return request.app.state.settings


@router.post("/activation/redeem")
def redeem_activation(payload: ActivationRedeemRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    token = db.scalar(select(TeacherActivationToken).where(TeacherActivationToken.token_hash == digest_token(payload.activation_code, settings_from(request).session_secret or None)).with_for_update())
    if token is None or token.redeemed_at is not None or is_expired(token.expires_at) or token.attempts >= 5:
        raise error("ACTIVATION_CODE_INVALID", "The activation code is invalid or expired.", 400)
    user = db.get(User, token.teacher_user_id)
    if user is None or user.status != "PENDING":
        raise error("ACTIVATION_NOT_AVAILABLE", "Teacher activation is no longer available.", 409)
    token.attempts += 1
    token.redeemed_at = utcnow()
    raw, csrf, session = issue_session(db, user.id, settings_from(request), purpose="ACTIVATION", ttl_minutes=15)
    db.add(token)
    add_audit(db, actor_user_id=user.id, action="TEACHER_ACTIVATION_CODE_REDEEMED", entity_type="user", entity_id=user.id)
    db.commit()
    set_auth_cookies(response, raw, csrf, settings_from(request), max_age=900)
    return {"message": "Activation accepted. Register a passkey to activate your teacher account.", "registration_required": True, "csrf_token": csrf}


@router.get("/activation/status")
def activation_status(identity: Identity = Depends(require_activation_teacher)):
    """Allow a page refresh during the short-lived activation-only passkey setup."""
    return {"id": str(identity.user.id), "full_name": identity.user.full_name,
            "role": identity.user.role, "registration_required": True}


@router.post("/passkeys/register/options")
def registration_options(request: Request, identity: Identity = Depends(require_activation_teacher), db: Session = Depends(get_db)):
    try:
        return create_registration_options(db, identity.user.id, settings_from(request))
    except RuntimeError as exc:
        raise error("WEBAUTHN_UNAVAILABLE", "The WebAuthn verification dependency is unavailable. Install the pinned backend requirements.", 503) from exc
    except Exception as exc:
        raise error("PASSKEY_REGISTRATION_UNAVAILABLE", "Could not start passkey registration.", 503) from exc


@router.post("/passkeys/register/verify")
def registration_verify(payload: WebAuthnVerifyRequest, request: Request, response: Response,
                         identity: Identity = Depends(require_activation_teacher), db: Session = Depends(get_db)):
    try:
        verify_registration(db, identity.user.id, payload.credential, settings_from(request))
    except RuntimeError as exc:
        db.rollback()
        raise error("WEBAUTHN_UNAVAILABLE", "The WebAuthn verification dependency is unavailable. Install the pinned backend requirements.", 503) from exc
    except Exception as exc:
        db.rollback()
        raise error("PASSKEY_REGISTRATION_FAILED", "Passkey registration could not be verified. Start again with a fresh challenge.", 400) from exc
    user = db.get(User, identity.user.id)
    user.status = "ACTIVE"
    access_request = db.scalar(select(TeacherAccessRequest).where(TeacherAccessRequest.teacher_user_id == user.id))
    if access_request:
        access_request.status = "ACTIVE"
    revoke_session(db, identity.session)
    raw, csrf, _ = issue_session(db, user.id, settings_from(request))
    add_audit(db, actor_user_id=user.id, action="TEACHER_PASSKEY_REGISTERED", entity_type="user", entity_id=user.id)
    db.commit()
    set_auth_cookies(response, raw, csrf, settings_from(request))
    return {"message": "Passkey registered. Teacher account is now active.", "csrf_token": csrf}


@router.post("/passkeys/login/options")
def login_options(payload: WebAuthnOptionsRequest, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(
        User.role == "TEACHER", User.status == "ACTIVE",
        or_(User.email == payload.identifier, User.phone == payload.identifier),
    ))
    if user is None:
        raise error("PASSKEY_LOGIN_UNAVAILABLE", "Passkey sign-in could not be started for this account.", 400)
    try:
        return create_authentication_options(db, user.id, settings_from(request))
    except RuntimeError as exc:
        raise error("WEBAUTHN_UNAVAILABLE", "The WebAuthn verification dependency is unavailable. Install the pinned backend requirements.", 503) from exc
    except Exception as exc:
        raise error("PASSKEY_LOGIN_UNAVAILABLE", "Passkey sign-in could not be started for this account.", 400) from exc


@router.post("/passkeys/login/verify")
def login_verify(payload: WebAuthnVerifyRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    if not payload.identifier:
        raise error("IDENTIFIER_REQUIRED", "The teacher phone number or email used to start sign-in is required.")
    user = db.scalar(select(User).where(
        User.role == "TEACHER", User.status == "ACTIVE",
        or_(User.email == payload.identifier, User.phone == payload.identifier),
    ))
    if user is None:
        raise error("PASSKEY_LOGIN_FAILED", "Passkey sign-in could not be verified.", 401)
    try:
        credential = verify_authentication(db, user.id, payload.credential, settings_from(request))
    except RuntimeError as exc:
        db.rollback()
        raise error("WEBAUTHN_UNAVAILABLE", "The WebAuthn verification dependency is unavailable. Install the pinned backend requirements.", 503) from exc
    except Exception as exc:
        db.rollback()
        raise error("PASSKEY_LOGIN_FAILED", "Passkey sign-in could not be verified.", 401) from exc
    raw, csrf, _ = issue_session(db, user.id, settings_from(request))
    add_audit(db, actor_user_id=user.id, action="TEACHER_LOGIN", entity_type="user", entity_id=user.id)
    db.commit()
    set_auth_cookies(response, raw, csrf, settings_from(request))
    return {"message": "Signed in successfully.", "csrf_token": csrf}


@router.get("/me")
def teacher_me(identity: Identity = Depends(require_teacher), db: Session = Depends(get_db)):
    from app.models import TeacherClassAssignment, ClassRecord
    assignments = db.execute(select(TeacherClassAssignment, ClassRecord).join(
        ClassRecord, ClassRecord.id == TeacherClassAssignment.class_id
    ).where(TeacherClassAssignment.teacher_user_id == identity.user.id, TeacherClassAssignment.status == "ACTIVE")).all()
    return {
        "id": str(identity.user.id),
        "full_name": identity.user.full_name,
        "email": identity.user.email,
        "phone": identity.user.phone,
        "role": identity.user.role,
        "can_record_guardian_consent": bool(identity.user.can_record_guardian_consent),
        "classes": [{"id": str(c.id), "grade": c.grade_label, "section": c.section_label, "academic_year": c.academic_year} for _, c in assignments],
    }


@router.get("/passkeys")
def list_passkeys(identity: Identity = Depends(require_teacher), db: Session = Depends(get_db)):
    items = db.scalars(select(PasskeyCredential).where(PasskeyCredential.user_id == identity.user.id, PasskeyCredential.revoked_at.is_(None))).all()
    return [{"id": str(p.id), "created_at": p.created_at, "last_used_at": p.last_used_at, "device_type": p.device_type, "backed_up": p.backed_up, "transports": p.transports} for p in items]


@router.delete("/passkeys/{credential_id}")
def revoke_passkey(credential_id: UUID, identity: Identity = Depends(require_teacher), db: Session = Depends(get_db)):
    created_at = identity.session.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=utcnow().tzinfo)
    if (utcnow() - created_at) > timedelta(minutes=10):
        raise error("RECENT_AUTH_REQUIRED", "Sign in again with a passkey before revoking another credential.", 409)
    item = db.scalar(select(PasskeyCredential).where(
        PasskeyCredential.id == credential_id,
        PasskeyCredential.user_id == identity.user.id,
        PasskeyCredential.revoked_at.is_(None),
    ).with_for_update())
    if item is None:
        raise error("PASSKEY_NOT_FOUND", "Passkey was not found.", 404)
    active_count = db.scalar(select(func.count()).select_from(PasskeyCredential).where(
        PasskeyCredential.user_id == identity.user.id,
        PasskeyCredential.revoked_at.is_(None),
    )) or 0
    if active_count <= 1:
        raise error("LAST_PASSKEY_REQUIRES_ADMIN", "The final active passkey can only be removed through Principal-assisted recovery.", 409)
    item.revoked_at = utcnow()
    add_audit(db, actor_user_id=identity.user.id, action="TEACHER_PASSKEY_REVOKED", entity_type="passkey", entity_id=item.id)
    db.commit()
    return {"message": "Passkey revoked."}


@router.post("/logout")
def teacher_logout(request: Request, response: Response, identity: Identity = Depends(require_teacher), db: Session = Depends(get_db)):
    revoke_session(db, identity.session)
    db.commit()
    clear_auth_cookies(response, settings_from(request))
    return {"message": "Signed out."}
