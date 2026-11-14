from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import b64url, utcnow
from app.models import PasskeyCredential, WebAuthnChallenge


def _webauthn_imports():
    try:
        from webauthn import (
            base64url_to_bytes,
            generate_authentication_options,
            generate_registration_options,
            options_to_json,
            verify_authentication_response,
            verify_registration_response,
        )
        from webauthn.helpers.structs import (
            AuthenticatorSelectionCriteria,
            PublicKeyCredentialDescriptor,
            ResidentKeyRequirement,
            UserVerificationRequirement,
        )
    except ImportError as exc:
        raise RuntimeError("Install the pinned WebAuthn dependency from requirements.txt") from exc
    return (base64url_to_bytes, generate_authentication_options, generate_registration_options,
            options_to_json, verify_authentication_response, verify_registration_response,
            AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
            ResidentKeyRequirement, UserVerificationRequirement)


def create_registration_options(db: Session, user_id, settings) -> str:
    (base64url_to_bytes, _, generate_registration_options, options_to_json, _, _,
     AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
     ResidentKeyRequirement, UserVerificationRequirement) = _webauthn_imports()
    credentials = db.scalars(select(PasskeyCredential).where(PasskeyCredential.user_id == user_id, PasskeyCredential.revoked_at.is_(None))).all()
    options = generate_registration_options(
        rp_id=settings.webauthn_rp_id,
        rp_name=settings.webauthn_rp_name,
        user_id=user_id.bytes,
        user_name=str(user_id),
        user_display_name="SCOLIQ AI Teacher",
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(c.credential_id)) for c in credentials],
        timeout=120000,
    )
    db.add(WebAuthnChallenge(user_id=user_id, ceremony="REGISTRATION", challenge=options.challenge,
                             expires_at=utcnow() + timedelta(seconds=settings.webauthn_challenge_ttl_seconds)))
    db.commit()
    return json.loads(options_to_json(options))


def verify_registration(db: Session, user_id, credential: dict[str, Any], settings) -> PasskeyCredential:
    (_, _, _, _, _, verify_registration_response, *_rest) = _webauthn_imports()
    challenge = db.scalar(select(WebAuthnChallenge).where(
        WebAuthnChallenge.user_id == user_id,
        WebAuthnChallenge.ceremony == "REGISTRATION",
        WebAuthnChallenge.used_at.is_(None),
        WebAuthnChallenge.expires_at > utcnow(),
    ).order_by(WebAuthnChallenge.created_at.desc()).with_for_update())
    if challenge is None:
        raise ValueError("No valid registration challenge is available")
    verification = verify_registration_response(
        credential=credential,
        expected_challenge=challenge.challenge,
        expected_rp_id=settings.webauthn_rp_id,
        expected_origin=settings.webauthn_origin,
        require_user_verification=True,
    )
    challenge.used_at = utcnow()
    item = PasskeyCredential(
        user_id=user_id,
        credential_id=b64url(verification.credential_id),
        public_key=verification.credential_public_key,
        sign_count=verification.sign_count,
        device_type=str(verification.credential_device_type),
        backed_up=verification.credential_backed_up,
        transports=credential.get("response", {}).get("transports", []),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def create_authentication_options(db: Session, user_id, settings) -> str:
    (base64url_to_bytes, generate_authentication_options, _, options_to_json, _, _, _,
     PublicKeyCredentialDescriptor, _, UserVerificationRequirement) = _webauthn_imports()
    credentials = db.scalars(select(PasskeyCredential).where(PasskeyCredential.user_id == user_id, PasskeyCredential.revoked_at.is_(None))).all()
    if not credentials:
        raise ValueError("No active passkeys are registered for this teacher")
    options = generate_authentication_options(
        rp_id=settings.webauthn_rp_id,
        allow_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(c.credential_id)) for c in credentials],
        user_verification=UserVerificationRequirement.REQUIRED,
        timeout=120000,
    )
    db.add(WebAuthnChallenge(user_id=user_id, ceremony="AUTHENTICATION", challenge=options.challenge,
                             expires_at=utcnow() + timedelta(seconds=settings.webauthn_challenge_ttl_seconds)))
    db.commit()
    return json.loads(options_to_json(options))


def verify_authentication(db: Session, user_id, credential: dict[str, Any], settings) -> PasskeyCredential:
    (_, _, _, _, verify_authentication_response, _, _, _, _, _) = _webauthn_imports()
    credential_id = credential.get("id") or credential.get("rawId")
    stored = db.scalar(select(PasskeyCredential).where(
        PasskeyCredential.credential_id == credential_id,
        PasskeyCredential.user_id == user_id,
        PasskeyCredential.revoked_at.is_(None),
    ).with_for_update())
    challenge = db.scalar(select(WebAuthnChallenge).where(
        WebAuthnChallenge.user_id == user_id,
        WebAuthnChallenge.ceremony == "AUTHENTICATION",
        WebAuthnChallenge.used_at.is_(None),
        WebAuthnChallenge.expires_at > utcnow(),
    ).order_by(WebAuthnChallenge.created_at.desc()).with_for_update())
    if stored is None or challenge is None:
        raise ValueError("No valid passkey or authentication challenge is available")
    verification = verify_authentication_response(
        credential=credential,
        expected_challenge=challenge.challenge,
        expected_rp_id=settings.webauthn_rp_id,
        expected_origin=settings.webauthn_origin,
        credential_public_key=stored.public_key,
        credential_current_sign_count=stored.sign_count,
        require_user_verification=True,
    )
    challenge.used_at = utcnow()
    stored.sign_count = verification.new_sign_count
    stored.last_used_at = utcnow()
    db.commit()
    return stored
