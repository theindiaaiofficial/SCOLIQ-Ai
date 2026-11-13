from __future__ import annotations

from fastapi.testclient import TestClient


def test_public_branding_is_safe_and_has_defaults(client: TestClient):
    response = client.get("/api/v1/public/school-branding")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["school_name"] == "My School"
    assert payload["logo_url"] is None
    assert payload["branding"]["design_profile"] == "clean"
    assert payload["branding"]["appearance"] == "light"
    assert set(payload) == {"school_name", "logo_url", "branding"}
    assert "settings" not in payload
    assert "timezone" not in payload
    assert "database_url" not in payload


def test_principal_can_persist_branding_and_public_portal_reads_it(client: TestClient, principal, auth_headers):
    headers = auth_headers(client, principal)
    payload = {
        "school_name": "Northfield Academy",
        "logo_url": "https://assets.example.edu/brand/logo.png",
        "timezone": "Asia/Kolkata",
        "current_academic_year": "2026-27",
        "branding": {
            "design_profile": "premium",
            "appearance": "system",
            "primary_color": "#153E75",
            "accent_color": "#159A82",
            "sidebar_appearance": "brand-tinted",
            "sidebar_collapsed": False,
            "card_appearance": "elevated",
            "corner_radius": "soft",
            "density": "comfortable",
            "heading_style": "editorial",
            "masthead_style": "prominent",
            "motion": "subtle",
            "page_background": "gradient",
            "logo_size": "large",
            "logo_placement": "beside",
            "logo_with_school_name": True,
        },
    }
    update = client.patch("/api/v1/admin/settings/profile", json=payload, headers=headers)
    assert update.status_code == 200, update.text
    assert update.json()["branding"]["design_profile"] == "premium"
    assert update.json()["logo_url"] == payload["logo_url"]

    # A separate public read (as the Teacher portal would make) sees the same persisted identity.
    public = client.get("/api/v1/public/school-branding")
    assert public.status_code == 200
    assert public.json()["school_name"] == "Northfield Academy"
    assert public.json()["branding"]["primary_color"] == "#153E75"
    # A fresh protected profile read returns the complete saved configuration.
    fresh = client.get("/api/v1/admin/settings/profile", headers=headers)
    assert fresh.status_code == 200
    assert fresh.json()["branding"] == payload["branding"]


def test_logo_can_be_cleared_without_erasing_branding(client: TestClient, principal, auth_headers):
    headers = auth_headers(client, principal)
    initial = client.patch(
        "/api/v1/admin/settings/profile",
        json={"logo_url": "https://assets.example.edu/logo.png", "branding": {"primary_color": "#123456"}},
        headers=headers,
    )
    assert initial.status_code == 200, initial.text
    clear = client.patch("/api/v1/admin/settings/profile", json={"logo_url": None}, headers=headers)
    assert clear.status_code == 200, clear.text
    assert clear.json()["logo_url"] is None
    assert clear.json()["branding"]["primary_color"] == "#123456"


def test_branding_payload_and_logo_url_are_strictly_validated(client: TestClient, principal, auth_headers):
    headers = auth_headers(client, principal)
    invalid_color = client.patch(
        "/api/v1/admin/settings/profile",
        json={"branding": {"primary_color": "red"}},
        headers=headers,
    )
    assert invalid_color.status_code == 422
    invalid_extra = client.patch(
        "/api/v1/admin/settings/profile",
        json={"branding": {"custom_css": "body{display:none}"}},
        headers=headers,
    )
    assert invalid_extra.status_code == 422
    unsafe_logo = client.patch(
        "/api/v1/admin/settings/profile",
        json={"logo_url": "javascript:alert(1)"},
        headers=headers,
    )
    assert unsafe_logo.status_code == 422
    unsafe_data_url = client.patch(
        "/api/v1/admin/settings/profile",
        json={"logo_url": "data:image/svg+xml,<svg/>"},
        headers=headers,
    )
    assert unsafe_data_url.status_code == 422
    svg_url = client.patch(
        "/api/v1/admin/settings/profile",
        json={"logo_url": "https://assets.example.edu/school-mark.svg"},
        headers=headers,
    )
    assert svg_url.status_code == 422


def test_teacher_cannot_modify_branding(client: TestClient, active_teacher, auth_headers):
    headers = auth_headers(client, active_teacher)
    response = client.patch(
        "/api/v1/admin/settings/profile",
        json={"school_name": "Not Allowed"},
        headers=headers,
    )
    assert response.status_code == 403
