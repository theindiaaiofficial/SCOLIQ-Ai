from __future__ import annotations

import argparse
import base64
import getpass
import secrets
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.database import build_engine, build_session_factory
from app.models import (
    AdminCredential,
    BootstrapState,
    SchoolProfile,
    User,
)


def generate_secrets() -> None:
    print(
        "SESSION_SECRET="
        + base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("=")
    )
    print("INITIAL_ADMIN_SETUP_TOKEN=" + secrets.token_urlsafe(48))
    print(
        "FACE_TEMPLATE_ENCRYPTION_KEY="
        + base64.b64encode(secrets.token_bytes(32)).decode()
    )


def create_admin() -> None:
    settings = get_settings()

    if not settings.database_url:
        raise SystemExit("DATABASE_URL is required. Apply migrations first.")

    email = input("Principal email: ").strip().lower()
    full_name = input("Principal full name: ").strip()

    password = getpass.getpass("Principal password (12+ characters): ")
    confirmation = getpass.getpass("Confirm password: ")

    if password != confirmation:
        raise SystemExit("Passwords do not match.")

    try:
        password_hash = hash_password(password)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)

    try:
        with factory.begin() as db:
            state = db.get(BootstrapState, 1)

            exists = (
                db.scalar(select(User.id).where(User.role == "PRINCIPAL")) is not None
            )

            if exists or (state and state.completed_at):
                raise SystemExit("Principal bootstrap has already been completed.")

            user = User(
                full_name=full_name,
                email=email,
                role="PRINCIPAL",
                status="ACTIVE",
            )

            db.add(user)
            db.flush()

            db.add(
                AdminCredential(
                    user_id=user.id,
                    password_hash=password_hash,
                )
            )

            if state is None:
                state = BootstrapState(id=1)
                db.add(state)

            state.completed_at = datetime.now(UTC)
            state.completed_by_user_id = user.id

            if db.get(SchoolProfile, 1) is None:
                db.add(SchoolProfile(id=1))

    finally:
        engine.dispose()

    print("Principal account created successfully.")


def reset_admin_password() -> None:
    settings = get_settings()

    if not settings.database_url:
        raise SystemExit("DATABASE_URL is required.")

    email = input("Existing Principal email: ").strip().lower()

    password = getpass.getpass("New password (12+ characters): ")
    confirmation = getpass.getpass("Confirm new password: ")

    if password != confirmation:
        raise SystemExit("Passwords do not match.")

    try:
        password_hash = hash_password(password)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)

    try:
        with factory.begin() as db:
            user = db.scalar(
                select(User).where(
                    User.email == email,
                    User.role == "PRINCIPAL",
                    User.status == "ACTIVE",
                )
            )

            if user is None:
                raise SystemExit("Active Principal account not found.")

            credential = db.get(AdminCredential, user.id)

            if credential is None:
                raise SystemExit("Principal credential not found.")

            credential.password_hash = password_hash

    finally:
        engine.dispose()

    print("Principal password reset successfully.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")

    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    sub.add_parser(
        "generate-secrets",
        help="Generate secure local secret values",
    )

    sub.add_parser(
        "create-admin",
        help="Create the first Principal account after migrations",
    )

    sub.add_parser(
        "reset-admin-password",
        help="Reset existing Principal password",
    )

    args = parser.parse_args()

    if args.command == "generate-secrets":
        generate_secrets()

    elif args.command == "create-admin":
        create_admin()

    elif args.command == "reset-admin-password":
        reset_admin_password()


if __name__ == "__main__":
    main()
