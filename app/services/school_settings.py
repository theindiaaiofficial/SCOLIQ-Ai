from __future__ import annotations

from app.models import SchoolProfile

DEFAULT_SCHOOL_SETTINGS: dict[str, object] = {
    "student_information_enabled": False,
    "face_verification_attempt_limit": 5,
}


def get_school_operations_settings(db) -> dict[str, object]:
    profile = db.get(SchoolProfile, 1)
    stored = profile.settings if profile and isinstance(profile.settings, dict) else {}
    result = {**DEFAULT_SCHOOL_SETTINGS, **stored}
    if result.get("face_verification_attempt_limit") not in {3, 5}:
        result["face_verification_attempt_limit"] = 5
    result["student_information_enabled"] = bool(result.get("student_information_enabled", False))
    return result
