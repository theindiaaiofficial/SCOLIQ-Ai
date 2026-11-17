from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class BootstrapRequest(APIModel):
    setup_token: str = Field(min_length=24, max_length=512)
    full_name: str = Field(min_length=2, max_length=180)
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)


class AdminLoginRequest(APIModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class PasswordResetRequest(APIModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> EmailStr:
        return str(value).lower()


class PasswordResetConfirmRequest(APIModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    new_password: str = Field(min_length=12, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> EmailStr:
        return str(value).lower()


class PasswordChangeRequest(APIModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class SchoolDataResetRequest(APIModel):
    current_password: str = Field(min_length=1, max_length=256)
    confirmation: Literal["RESET SCHOOL DATA"]


class TeacherRequestCreate(APIModel):
    full_name: str = Field(min_length=2, max_length=180)
    phone: str = Field(min_length=7, max_length=32)
    email: EmailStr | None = None
    staff_identifier: str | None = Field(default=None, max_length=80)

    @field_validator("phone")
    @classmethod
    def clean_phone(cls, value: str) -> str:
        digits = "".join(c for c in value if c.isdigit())
        if len(digits) < 7 or len(digits) > 15:
            raise ValueError("Phone number must contain 7 to 15 digits")
        return "+" + digits if value.strip().startswith("+") else digits


class TeacherRequestStatus(APIModel):
    status: str
    requested_at: datetime
    reviewed_at: datetime | None = None


class ApproveRequest(APIModel):
    review_note: str | None = Field(default=None, max_length=500)


class RejectRequest(APIModel):
    review_note: str = Field(min_length=2, max_length=500)


class ActivationRedeemRequest(APIModel):
    activation_code: str = Field(min_length=20, max_length=256)


class WebAuthnOptionsRequest(APIModel):
    identifier: str = Field(min_length=3, max_length=254)


class WebAuthnVerifyRequest(APIModel):
    identifier: str | None = Field(default=None, max_length=254)
    credential: dict


class ClassSetupRequest(APIModel):
    grade_label: str = Field(min_length=1, max_length=32)
    section_label: str = Field(min_length=1, max_length=32)
    academic_year: str = Field(min_length=4, max_length=32)


class StudentCreateRequest(APIModel):
    full_name: str = Field(min_length=2, max_length=180)
    roll_number: str = Field(min_length=1, max_length=32)
    school_student_code: str | None = Field(default=None, max_length=64)
    father_name: str | None = Field(default=None, max_length=180)
    mother_name: str | None = Field(default=None, max_length=180)
    guardian_phone: str | None = Field(default=None, max_length=32)
    alternate_guardian_phone: str | None = Field(default=None, max_length=32)
    consent_status: Literal["PENDING"] = "PENDING"

    @field_validator("guardian_phone", "alternate_guardian_phone")
    @classmethod
    def clean_guardian_phone(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        digits = "".join(char for char in value if char.isdigit())
        if not 7 <= len(digits) <= 15:
            raise ValueError("Guardian phone must contain 7 to 15 digits")
        return ("+" if value.strip().startswith("+") else "") + digits


class StudentUpdateRequest(APIModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=180)
    roll_number: str | None = Field(default=None, min_length=1, max_length=32)
    status: Literal["ACTIVE", "TRANSFERRED", "INACTIVE"] | None = None
    father_name: str | None = Field(default=None, max_length=180)
    mother_name: str | None = Field(default=None, max_length=180)
    guardian_phone: str | None = Field(default=None, max_length=32)
    alternate_guardian_phone: str | None = Field(default=None, max_length=32)

    @field_validator("guardian_phone", "alternate_guardian_phone")
    @classmethod
    def clean_guardian_phone(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        digits = "".join(char for char in value if char.isdigit())
        if not 7 <= len(digits) <= 15:
            raise ValueError("Guardian phone must contain 7 to 15 digits")
        return ("+" if value.strip().startswith("+") else "") + digits


class ConsentGrantRequest(APIModel):
    consent_status: Literal["GRANTED", "WITHDRAWN"]
    consent_method: str = Field(min_length=3, max_length=80)
    consent_record_reference: str = Field(min_length=3, max_length=255)


class MarkUpdateRequest(APIModel):
    status: Literal["PRESENT", "ABSENT", "LATE", "EXCUSED"]
    notes: str | None = Field(default=None, max_length=300)


class FinalizeRequest(APIModel):
    confirmation: Literal["CONFIRM_ALL_STATUSES"]


class ReopenRequest(APIModel):
    reason: str = Field(min_length=5, max_length=500)


class TeacherConsentPermissionRequest(APIModel):
    can_record_guardian_consent: bool
    reason: str = Field(min_length=5, max_length=500)


class TeacherStatusRequest(APIModel):
    status: Literal["ACTIVE", "SUSPENDED", "REVOKED"]
    reason: str = Field(min_length=3, max_length=500)


class BrandingConfig(APIModel):
    design_profile: Literal["basic", "clean", "premium"] = "clean"
    appearance: Literal["light", "dark", "system"] = "light"
    primary_color: str = Field(default="#3157D5", pattern=r"^#[0-9A-Fa-f]{6}$")
    accent_color: str = Field(default="#148A78", pattern=r"^#[0-9A-Fa-f]{6}$")
    sidebar_appearance: Literal["solid", "subtle", "brand-tinted"] = "subtle"
    sidebar_collapsed: bool = False
    card_appearance: Literal["flat", "outlined", "elevated"] = "outlined"
    corner_radius: Literal["sharp", "balanced", "soft"] = "balanced"
    density: Literal["comfortable", "compact"] = "comfortable"
    heading_style: Literal["modern", "editorial"] = "modern"
    masthead_style: Literal["prominent", "compact"] = "prominent"
    motion: Literal["off", "subtle", "expressive"] = "subtle"
    page_background: Literal["plain", "soft-tint", "gradient"] = "soft-tint"
    logo_size: Literal["small", "medium", "large"] = "medium"
    logo_placement: Literal["beside", "above"] = "beside"
    logo_with_school_name: bool = True


DEFAULT_BRANDING = BrandingConfig().model_dump()


def validate_school_logo_url(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if len(value) > 2048:
        raise ValueError("Logo URL must be at most 2048 characters")
    parsed = urlsplit(value)
    local_dev = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
    hosted = parsed.scheme == "https" and bool(parsed.hostname)
    if not (local_dev or hosted) or parsed.username or parsed.password:
        raise ValueError("Logo URL must be an HTTPS URL (localhost is allowed for development)")
    if parsed.path.lower().endswith((".svg", ".svgz")):
        raise ValueError("SVG logo URLs are not accepted; use a raster image such as PNG or WebP")
    return value


class SchoolOperationsSettings(APIModel):
    student_information_enabled: bool | None = None
    face_verification_attempt_limit: Literal[3, 5] | None = None


class SchoolProfileUpdate(APIModel):
    school_name: str | None = Field(default=None, min_length=2, max_length=180)
    school_code: str | None = Field(default=None, max_length=64)
    timezone: str | None = Field(default=None, max_length=64)
    current_academic_year: str | None = Field(default=None, min_length=4, max_length=32)
    logo_url: str | None = None
    branding: BrandingConfig | None = None
    settings: SchoolOperationsSettings | None = None

    @field_validator("logo_url")
    @classmethod
    def validate_logo(cls, value: str | None) -> str | None:
        return validate_school_logo_url(value)


class ManualAttendanceConfirmRequest(APIModel):
    status: Literal["PRESENT", "LATE", "ABSENT"] = "PRESENT"


class PaginatedParams(APIModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)


class AttendanceDateFilter(APIModel):
    from_date: date | None = None
    to_date: date | None = None
