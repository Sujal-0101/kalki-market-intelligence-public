"""Typed API, responsive HTML, authentication, and authorization flow tests."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest
from argon2 import PasswordHasher
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response
from test_live_radar import brief
from test_prediction_outcomes import prediction

from kalki_market_intelligence.web.app import (
    SESSION_COOKIE,
    WebSecurityOptions,
    create_public_web_app,
    create_web_app,
)
from kalki_market_intelligence.web.contracts import PUBLIC_RESEARCH_DISCLAIMER
from kalki_market_intelligence.web.repository import MemoryResearchRepository

ADMIN_PASSWORD = "synthetic-secure-password"


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 24, 12, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value

    def advance(self, **kwargs: float) -> None:
        self.value += timedelta(**kwargs)


def build_client(
    *,
    with_prediction: bool = True,
    secure_cookies: bool = False,
    login_attempts: int = 5,
    request_limit: int = 120,
    clock: Clock | None = None,
) -> tuple[TestClient, FastAPI]:
    hasher = PasswordHasher(time_cost=1, memory_cost=1_024, parallelism=1)
    selected_clock = clock or Clock()
    repository = MemoryResearchRepository((prediction(),) if with_prediction else ())
    app = create_web_app(
        repository,
        WebSecurityOptions(
            admin_username="admin",
            admin_password_hash=hasher.hash(ADMIN_PASSWORD),
            secure_cookies=secure_cookies,
            session_idle_minutes=5,
            session_absolute_hours=1,
            login_attempts=login_attempts,
            login_window_seconds=60,
            request_limit=request_limit,
            request_window_seconds=60,
        ),
        now=selected_clock.now,
        password_hasher=hasher,
    )
    return TestClient(app, base_url="http://testserver"), app


def login_token(client: TestClient) -> str:
    response = client.get("/admin/login")
    match = re.search(r'name="login_csrf" value="([^"]+)"', response.text)
    assert response.status_code == 200
    assert match is not None
    return match.group(1)


def login(client: TestClient) -> Response:
    return client.post(
        "/admin/login",
        data={
            "username": "admin",
            "password": ADMIN_PASSWORD,
            "login_csrf": login_token(client),
        },
        follow_redirects=False,
    )


def test_public_typed_api_exposes_only_reviewed_projection() -> None:
    client, _ = build_client()
    record = prediction()

    listed = client.get("/api/v1/research")
    invalid_page = client.get("/api/v1/research?limit=501")
    detailed = client.get(f"/api/v1/research/{record.prediction_id}")
    missing = client.get("/api/v1/research/10000000-0000-4000-8000-000000000099")
    mutation = client.post("/api/v1/research", json={})

    assert listed.status_code == 200
    assert invalid_page.status_code == 422
    assert len(listed.json()) == 1
    assert listed.json()[0]["disclaimer"] == PUBLIC_RESEARCH_DISCLAIMER
    assert "thesis" not in listed.json()[0]
    assert "published_by" not in listed.json()[0]
    assert detailed.status_code == 200
    assert detailed.json()["thesis"] == record.thesis
    assert detailed.json()["scores"]["interpretation"] == "heuristic_points_not_probability"
    assert detailed.json()["evidence"][0]["available_at"].endswith("Z")
    assert missing.status_code == 404
    assert mutation.status_code == 405

    openapi = client.get("/api/openapi.json").json()
    assert "/api/v1/research" in openapi["paths"]
    assert openapi["components"]["schemas"]["PublicResearchDetail"]["additionalProperties"] is False
    assert openapi["paths"]["/api/v1/admin/audit"]["get"]["security"] == [{"APIKeyCookie": []}]


def test_public_pages_are_accessible_responsive_and_escape_untrusted_text() -> None:
    record = prediction().model_copy(update={"thesis": "<script>alert('x')</script>"})
    hasher = PasswordHasher(time_cost=1, memory_cost=1_024, parallelism=1)
    app = create_web_app(
        MemoryResearchRepository((record,)),
        WebSecurityOptions(
            admin_username="admin",
            admin_password_hash=hasher.hash(ADMIN_PASSWORD),
        ),
        password_hasher=hasher,
    )
    client = TestClient(app)

    listing = client.get("/research")
    detail = client.get(f"/research/{record.prediction_id}")
    css = client.get("/static/app.css")

    assert listing.status_code == detail.status_code == css.status_code == 200
    assert '<meta name="viewport"' in listing.text
    assert 'class="skip-link"' in listing.text
    assert '<nav aria-label="Primary navigation">' in listing.text
    assert PUBLIC_RESEARCH_DISCLAIMER in detail.text
    assert "<script>alert" not in detail.text
    assert "&lt;script&gt;alert" in detail.text
    assert '<th scope="col">Evidence ID</th>' in detail.text
    assert "@media (max-width: 48rem)" in css.text
    assert ":focus-visible" in css.text
    assert "prefers-reduced-motion" in css.text


def test_physically_separate_public_app_contains_no_admin_or_operational_routes() -> None:
    record = prediction()
    app = create_public_web_app(
        MemoryResearchRepository((record,)),
        allowed_hosts=("public.example", "testserver"),
    )
    client = TestClient(app, base_url="https://public.example")

    public_listing = client.get("/research")
    assert public_listing.status_code == 200
    assert public_listing.headers["strict-transport-security"] == "max-age=31536000"
    assert client.get("/api/v1/research").status_code == 200
    assert client.get(f"/research/{record.prediction_id}").status_code == 200
    assert client.get("/static/app.css").status_code == 200
    for private_path in (
        "/admin",
        "/admin/login",
        "/api/v1/admin/audit",
        "/health",
        "/api/openapi.json",
        "/docs",
    ):
        assert client.get(private_path, follow_redirects=False).status_code == 404

    rejected = client.get(
        "/research",
        headers={"host": "attacker.example"},
        follow_redirects=False,
    )
    assert rejected.status_code == 400


def test_trusted_host_configuration_rejects_wildcards_and_duplicates() -> None:
    repository = MemoryResearchRepository()

    with pytest.raises(ValueError, match="explicit"):
        create_public_web_app(repository, allowed_hosts=("*",))
    with pytest.raises(ValueError, match="unique"):
        create_public_web_app(repository, allowed_hosts=("localhost", "localhost"))


def test_empty_page_discloses_absence_instead_of_fabricating_content() -> None:
    client, _ = build_client(with_prediction=False)
    response = client.get("/research")

    assert response.status_code == 200
    assert "The public research library is empty" in response.text
    assert "Nothing is fabricated for display" in response.text


def test_public_library_lists_each_dossier_and_forecast_once_with_explicit_types() -> None:
    dossier = brief()
    forecast = prediction()
    app = create_public_web_app(
        MemoryResearchRepository((forecast,), briefs=(dossier,)),
        allowed_hosts=("testserver",),
    )
    client = TestClient(app)

    response = client.get("/api/v1/research")
    page = client.get("/research")

    assert response.status_code == page.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["prediction_id"] == str(forecast.prediction_id)
    assert "record_type" not in response.json()[0]
    assert page.text.count(">Filing dossier<") == 1
    assert page.text.count(">Forecast record<") == 1
    assert "Explicit 90-day forecast" in page.text
    assert "SEC filing evidence" in page.text


def test_security_headers_and_trusted_host_apply_without_public_exposure() -> None:
    client, _ = build_client()
    response = client.get("/research")
    rejected_host = client.get("/research", headers={"host": "public.example"})

    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "script-src 'none'" in response.headers["content-security-policy"]
    assert rejected_host.status_code == 400


def test_admin_and_operational_api_require_authentication() -> None:
    client, _ = build_client()

    page = client.get("/admin", follow_redirects=False)
    detail = client.get(f"/admin/research/{prediction().prediction_id}", follow_redirects=False)
    audit = client.get("/api/v1/admin/audit")

    assert page.status_code == detail.status_code == 303
    assert page.headers["location"] == detail.headers["location"] == "/admin/login"
    assert audit.status_code == 401
    assert audit.headers["www-authenticate"] == "Session"
    assert "no-store" in audit.headers["cache-control"]


def test_login_is_csrf_protected_generic_audited_and_issues_safe_cookie() -> None:
    client, app = build_client()
    token = login_token(client)
    rejected = client.post(
        "/admin/login",
        data={"username": "admin", "password": "wrong-password", "login_csrf": token},
        follow_redirects=False,
    )
    reused = client.post(
        "/admin/login",
        data={"username": "admin", "password": ADMIN_PASSWORD, "login_csrf": token},
        follow_redirects=False,
    )
    accepted = login(client)

    assert rejected.status_code == 401
    assert "Invalid username or password" in rejected.text
    assert ADMIN_PASSWORD not in rejected.text
    assert reused.status_code == 403
    assert accepted.status_code == 303
    assert accepted.headers["location"] == "/admin"
    cookie = accepted.headers["set-cookie"]
    assert f"{SESSION_COOKIE}=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Path=/" in cookie
    assert "Secure" not in cookie
    audit_types = tuple(item.event_type.value for item in app.state.kalki.audit_log.events)
    assert "login_failed" in audit_types
    assert "csrf_rejected" in audit_types
    assert "login_succeeded" in audit_types


def test_authenticated_workspace_and_audit_api_are_available() -> None:
    client, _ = build_client()
    assert login(client).status_code == 303

    dashboard = client.get("/admin")
    operations = client.get("/admin/operations")
    detail = client.get(f"/admin/research/{prediction().prediction_id}")
    audit = client.get("/api/v1/admin/audit")

    assert (
        dashboard.status_code
        == operations.status_code
        == detail.status_code
        == audit.status_code
        == 200
    )
    assert "Publication records remain immutable" in dashboard.text
    assert "Mission Control" in operations.text
    assert "Host envelope" in operations.text
    assert "GPU" in operations.text
    assert "Freshness and performance measurements" in operations.text
    assert "Deterministic convergence receipts" in operations.text
    assert "Prospective outcome science" in operations.text
    assert "UNAVAILABLE" in operations.text
    assert "Viewing only" in detail.text
    assert "login_succeeded" in tuple(item["event_type"] for item in audit.json())
    assert "password" not in audit.text.lower()
    assert "no-store" in dashboard.headers["cache-control"]


def test_session_is_bound_to_client_and_expires_after_idle_limit() -> None:
    clock = Clock()
    client, _ = build_client(clock=clock)
    client.headers["user-agent"] = "browser-a"
    assert login(client).status_code == 303

    changed_client = client.get(
        "/admin", headers={"user-agent": "browser-b"}, follow_redirects=False
    )
    assert changed_client.status_code == 303

    client, _ = build_client(clock=clock)
    assert login(client).status_code == 303
    clock.advance(minutes=5)
    expired = client.get("/admin", follow_redirects=False)
    assert expired.status_code == 303
    assert expired.headers["location"] == "/admin/login"


def test_logout_requires_csrf_and_revokes_session() -> None:
    client, _ = build_client()
    assert login(client).status_code == 303
    dashboard = client.get("/admin")
    match = re.search(r'name="csrf_token" value="([^"]+)"', dashboard.text)
    assert match is not None

    rejected = client.post("/admin/logout", data={"csrf_token": "wrong"}, follow_redirects=False)
    accepted = client.post(
        "/admin/logout", data={"csrf_token": match.group(1)}, follow_redirects=False
    )
    protected = client.get("/admin", follow_redirects=False)

    assert rejected.status_code == 403
    assert accepted.status_code == 303
    assert accepted.headers["location"] == "/admin/login"
    assert protected.status_code == 303


def test_login_rate_limit_returns_retry_after_and_does_not_set_session() -> None:
    client, _ = build_client(login_attempts=3)

    statuses = []
    for _ in range(4):
        response = client.post(
            "/admin/login",
            data={
                "username": "admin",
                "password": "wrong-password",
                "login_csrf": login_token(client),
            },
            follow_redirects=False,
        )
        statuses.append(response.status_code)

    assert statuses == [401, 401, 401, 429]
    assert response.headers["retry-after"] == "60"
    assert SESSION_COOKIE not in client.cookies


def test_secure_cookie_mode_is_available_for_later_tls_deployment() -> None:
    client, _ = build_client(secure_cookies=True)
    response = login(client)

    assert "Secure" in response.headers["set-cookie"]


def test_general_request_limit_and_body_ceiling_fail_closed() -> None:
    client, app = build_client(request_limit=10)

    for _ in range(10):
        assert client.get("/health").status_code == 200
    limited = client.get("/health")

    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"
    assert limited.json() == {"detail": "request rate limit exceeded"}

    fresh_client, _ = build_client()
    oversized = fresh_client.post(
        "/admin/login",
        content=b"x" * 16_385,
        headers={"content-type": "application/octet-stream"},
    )
    assert oversized.status_code == 413
    assert oversized.json() == {"detail": "request body too large"}
    assert not app.state.kalki.audit_log.events


def test_primary_palette_has_wcag_aa_contrast() -> None:
    assert _contrast_ratio("#f4f7f2", "#07110f") >= 7
    assert _contrast_ratio("#73f2b3", "#032117") >= 4.5


def _contrast_ratio(foreground: str, background: str) -> float:
    lighter, darker = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _luminance(color: str) -> float:
    channels = tuple(int(color[index : index + 2], 16) / 255 for index in (1, 3, 5))
    linear = tuple(
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in channels
    )
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
