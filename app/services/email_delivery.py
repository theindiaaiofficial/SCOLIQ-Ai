from __future__ import annotations

from html import escape

import httpx


def send_principal_password_reset_email(*, api_key: str, from_email: str, to_email: str, code: str) -> None:
    """Send a short-lived principal password reset code through Resend."""
    if not api_key or not from_email:
        raise RuntimeError("Resend email delivery is not configured")
    safe_code = escape(code)
    response = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "from": from_email,
            "to": [to_email],
            "subject": "Your SCOLIQ AI password reset code",
            "text": (
                f"Your SCOLIQ AI Principal password reset code is {code}. "
                "It expires in 10 minutes and can be used once. "
                "If you did not request this, you can ignore this email."
            ),
            "html": (
                "<div style='font-family:Arial,sans-serif;max-width:560px;margin:auto'>"
                "<h2>Reset your SCOLIQ AI password</h2>"
                "<p>Use this one-time verification code to reset your Principal password:</p>"
                f"<p style='font-size:30px;font-weight:700;letter-spacing:8px'>{safe_code}</p>"
                "<p>This code expires in <b>10 minutes</b> and can only be used once.</p>"
                "<p>If you did not request this, ignore this email. Your password will not change.</p>"
                "</div>"
            ),
        },
        timeout=10.0,
    )
    response.raise_for_status()
