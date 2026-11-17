from __future__ import annotations

import base64
import binascii
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "SCOLIQ AI Backend"
    app_env: Literal["development", "test", "production"] = "development"
    app_base_url: str = "http://localhost:8000"
    api_v1_prefix: str = "/api/v1"
    school_timezone: str = "Asia/Kolkata"

    database_url: str = ""
    migration_database_url: str | None = None

    session_secret: str = ""
    session_ttl_hours: int = Field(default=12, ge=1, le=168)
    initial_admin_setup_token: str = ""
    resend_api_key: str = ""
    resend_from_email: str = ""
    cors_allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    webauthn_rp_id: str = "localhost"
    webauthn_origin: str = "http://localhost:5173"
    webauthn_rp_name: str = "SCOLIQ AI"
    webauthn_challenge_ttl_seconds: int = Field(default=300, ge=60, le=900)

    face_provider: Literal["opencv_sface", "mobilefacenet", "manual", "fake"] = "manual"
    face_model_name: str = "YuNet+SFace"
    face_model_version: str = "2023mar+2021dec"
    face_detector_model_path: str = "./models/face/face_detection_yunet_2023mar.onnx"
    face_recognizer_model_path: str = "./models/face/face_recognition_sface_2021dec.onnx"
    face_mobilefacenet_model_path: str = "./models/face/mobile_facenet.onnx"
    face_mobilefacenet_metadata_path: str = "./models/face/metadata.json"
    face_mobilefacenet_external_data_path: str = "./models/face/mobile_facenet.data"
    face_mobilefacenet_model_name: str = "MobileFaceNet"
    face_mobilefacenet_model_version: str = "qaihub-v0.66.0-float-onnx-ort-1.30.0"
    face_mobilefacenet_input_size: int = Field(default=112, ge=64, le=256)
    face_mobilefacenet_embedding_size: int = Field(default=128, ge=1, le=4096)
    face_mobilefacenet_input_name_1: str = "img1"
    face_mobilefacenet_input_name_2: str = "img2"
    face_mobilefacenet_output_name: str = "embeddings"
    face_mobilefacenet_match_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    face_mobilefacenet_ambiguity_margin: float | None = Field(default=None, ge=0.0, le=1.0)
    face_detector_score_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    face_detector_nms_threshold: float = Field(default=0.30, ge=0.0, le=1.0)
    face_min_face_size: int = Field(default=64, ge=16, le=2048)
    face_template_encryption_key: str = ""
    face_match_threshold: float = Field(default=0.363, ge=0.0, le=1.0)
    face_ambiguity_margin: float = Field(default=0.035, ge=0.0, le=1.0)
    max_face_upload_mb: int = Field(default=5, ge=1, le=15)
    max_face_image_width: int = Field(default=4096, ge=320, le=8192)
    max_face_image_height: int = Field(default=4096, ge=320, le=8192)

    face_diagnostics_enabled: bool = False

    log_level: str = "INFO"
    rate_limit_requests: int = Field(default=20, ge=1, le=1000)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)

    @field_validator("school_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("SCHOOL_TIMEZONE must be a valid IANA timezone") from exc
        return value

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @model_validator(mode="after")
    def validate_security_configuration(self) -> "Settings":
        if self.app_env == "production":
            if len(self.session_secret.encode()) < 32:
                raise ValueError("SESSION_SECRET must contain at least 32 bytes in production")
            if len(self.initial_admin_setup_token) < 32 or self.initial_admin_setup_token.startswith("REPLACE_"):
                raise ValueError("INITIAL_ADMIN_SETUP_TOKEN must be a generated secret of at least 32 characters in production")
            if self.session_secret.startswith("REPLACE_"):
                raise ValueError("SESSION_SECRET must be replaced with a generated secret in production")
            if not self.database_url.startswith("postgresql+psycopg://") or "sslmode=require" not in self.database_url:
                raise ValueError("Production DATABASE_URL must use PostgreSQL via psycopg with sslmode=require")
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be true in production")
            if self.cookie_samesite == "none" and not self.cookie_secure:
                raise ValueError("SameSite=None requires Secure cookies")
            if "*" in self.cors_allowed_origins:
                raise ValueError("Wildcard CORS is forbidden in production")
            if self.face_provider == "fake":
                raise ValueError("The fake face provider is forbidden in production")
            if self.face_diagnostics_enabled:
                raise ValueError("FACE_DIAGNOSTICS_ENABLED must be false in production")
            from urllib.parse import urlparse
            parsed_origin = urlparse(self.webauthn_origin)
            if parsed_origin.scheme != "https" or parsed_origin.hostname != self.webauthn_rp_id or parsed_origin.path not in {"", "/"}:
                raise ValueError("WEBAUTHN_ORIGIN must be an HTTPS origin whose hostname exactly matches WEBAUTHN_RP_ID")
        if self.face_provider == "mobilefacenet":
            if self.face_mobilefacenet_match_threshold is None or self.face_mobilefacenet_ambiguity_margin is None:
                raise ValueError(
                    "MobileFaceNet requires FACE_MOBILEFACENET_MATCH_THRESHOLD and "
                    "FACE_MOBILEFACENET_AMBIGUITY_MARGIN calibrated for the exact ONNX model"
                )
            # The matching service consumes the existing generic fields. Map
            # only explicitly calibrated MobileFaceNet values into them.
            self.face_match_threshold = self.face_mobilefacenet_match_threshold
            self.face_ambiguity_margin = self.face_mobilefacenet_ambiguity_margin
        return self

    def face_encryption_key(self) -> bytes:
        if not self.face_template_encryption_key:
            raise ValueError("FACE_TEMPLATE_ENCRYPTION_KEY is required for face template storage")
        try:
            key = base64.b64decode(self.face_template_encryption_key, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("FACE_TEMPLATE_ENCRYPTION_KEY must be base64 encoded") from exc
        if len(key) != 32:
            raise ValueError("FACE_TEMPLATE_ENCRYPTION_KEY must decode to exactly 32 bytes")
        return key


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
