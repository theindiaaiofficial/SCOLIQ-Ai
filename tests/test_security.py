from __future__ import annotations

import base64

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.security import digest_token, hash_password, new_token, verify_password
from app.face.encryption import FaceTemplateCipher
from app.face.image_validation import InvalidFaceImage, validate_image_bytes
from app.face.opencv_provider import OpenCVYuNetSFaceProvider, cosine_similarity
from app.face.provider import FakeFaceProvider, ProviderUnavailable
from app.core.middleware import InProcessRateLimiter


def test_password_hash_is_argon2_and_verifies() -> None:
    password = "Correct!HorseBatteryStaple123"
    stored = hash_password(password)
    assert stored.startswith("$argon2id$")
    assert stored != password
    assert verify_password(stored, password)
    assert not verify_password(stored, "incorrect-password")


def test_password_minimum_length() -> None:
    with pytest.raises(ValueError):
        hash_password("too-short")


def test_random_tokens_and_keyed_digest() -> None:
    first = new_token(32)
    second = new_token(32)
    assert first != second
    assert len(first) >= 40
    assert digest_token(first, "server-secret-1") != digest_token(first, "server-secret-2")
    assert digest_token(first, "server-secret-1") == digest_token(first, "server-secret-1")


def test_face_template_encryption_is_authenticated_and_student_bound() -> None:
    cipher = FaceTemplateCipher(b"k" * 32)
    template = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    encrypted = cipher.encrypt_embeddings(template, student_id="student-a")
    assert encrypted != str(template).encode()
    assert cipher.decrypt_embeddings(encrypted, student_id="student-a") == template
    with pytest.raises(Exception):
        cipher.decrypt_embeddings(encrypted, student_id="student-b")
    tampered = encrypted[:-1] + bytes([encrypted[-1] ^ 0x01])
    with pytest.raises(Exception):
        cipher.decrypt_embeddings(tampered, student_id="student-a")


def test_image_validation_checks_real_content(sample_jpeg: bytes) -> None:
    mime, width, height = validate_image_bytes(
        sample_jpeg, max_bytes=100_000, max_width=1000, max_height=1000
    )
    assert (mime, width, height) == ("image/jpeg", 320, 320)
    with pytest.raises(InvalidFaceImage):
        validate_image_bytes(b"not an image", max_bytes=1000, max_width=1000, max_height=1000)
    with pytest.raises(InvalidFaceImage):
        validate_image_bytes(sample_jpeg, max_bytes=10, max_width=1000, max_height=1000)


def test_fake_face_provider_is_repeatable_and_marked_nonproduction(sample_jpeg: bytes) -> None:
    provider = FakeFaceProvider()
    left = provider.create_embedding(sample_jpeg)
    right = provider.create_embedding(sample_jpeg)
    assert left.vector == right.vector
    assert left.provider == "fake-test-only"
    assert cosine_similarity(left.vector, right.vector) == pytest.approx(1.0)


def test_opencv_provider_fails_closed_without_model_files(tmp_path) -> None:
    with pytest.raises(ProviderUnavailable):
        OpenCVYuNetSFaceProvider(
            str(tmp_path / "missing-detection.onnx"),
            str(tmp_path / "missing-recognition.onnx"),
            "YuNet+SFace",
            "test",
        )


def test_cosine_similarity_rejects_mismatched_vectors() -> None:
    with pytest.raises(ValueError):
        cosine_similarity([1.0, 0.0], [1.0])


def test_production_settings_reject_fake_provider_and_placeholder_secrets() -> None:
    common = {
        "app_env": "production",
        "database_url": "postgresql+psycopg://user:pass@host:5432/db?sslmode=require",
        "session_secret": "s" * 48,
        "initial_admin_setup_token": "t" * 48,
        "cookie_secure": True,
        "cors_allowed_origins": ["https://school.example.edu"],
        "webauthn_rp_id": "school.example.edu",
        "webauthn_origin": "https://school.example.edu",
        "face_provider": "fake",
    }
    with pytest.raises(ValidationError):
        Settings(**common)
    common["face_provider"] = "manual"
    common["session_secret"] = "REPLACE_" + "s" * 48
    with pytest.raises(ValidationError):
        Settings(**common)


def test_rate_limiter_enforces_sliding_window() -> None:
    limiter = InProcessRateLimiter(limit=2, window_seconds=60)
    assert limiter.allow("ip:path")
    assert limiter.allow("ip:path")
    assert not limiter.allow("ip:path")


def test_frontend_and_documentation_csp_remain_separated(client) -> None:
    docs = client.get("/api/v1/docs")
    assert docs.status_code == 200
    docs_csp = docs.headers.get("content-security-policy", "")
    assert "https://cdn.jsdelivr.net" in docs_csp

    api = client.get("/health/live")
    assert api.status_code == 200
    api_csp = api.headers.get("content-security-policy", "")
    assert api_csp == "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"

    # A source checkout without a frontend build still receives the same
    # dedicated restrictive SPA policy on the portal paths.
    portal = client.get("/admin/login")
    portal_csp = portal.headers.get("content-security-policy", "")
    assert "script-src 'self'" in portal_csp
    assert "https://cdn.jsdelivr.net" not in portal_csp
