"""FastAPI application factory for local research and single-admin workflows."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

from argon2 import PasswordHasher
from fastapi import FastAPI, Form, HTTPException, Query, Request, Security
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.security import APIKeyCookie
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape

from kalki_market_intelligence.radar.contracts import (
    RadarClassification,
    ResearchBrief,
    WorkerSnapshot,
)
from kalki_market_intelligence.web.contracts import (
    AuditEventType,
    PublicResearchDetail,
    PublicResearchSummary,
    PublicScreenedFiling,
    PublicScreeningActivity,
    SecurityAuditEvent,
    public_detail,
    public_index_item,
    public_summary,
)
from kalki_market_intelligence.web.operations import mission_control_snapshot
from kalki_market_intelligence.web.repository import ResearchRepository
from kalki_market_intelligence.web.security import (
    AdminAuthenticator,
    AdminSession,
    LoginNonceStore,
    LoginRateLimiter,
    LoginRateLimiterBackend,
    RequestRateLimiter,
    RequestRateLimiterBackend,
    SecurityAuditBackend,
    SecurityAuditLog,
    SessionBackend,
    SessionStore,
    client_fingerprint,
)

SESSION_COOKIE = "kalki_session"
ADMIN_SESSION_COOKIE = APIKeyCookie(name=SESSION_COOKIE, auto_error=False)
MAX_REQUEST_BODY_BYTES = 16_384
PACKAGE_DIR = Path(__file__).parent


@dataclass(frozen=True, slots=True)
class WebSecurityOptions:
    """Validated factory inputs for the local administration boundary."""

    admin_username: str
    admin_password_hash: str
    secure_cookies: bool = False
    session_idle_minutes: int = 30
    session_absolute_hours: int = 8
    login_attempts: int = 5
    login_window_seconds: int = 300
    request_limit: int = 120
    request_window_seconds: int = 60


@dataclass(slots=True)
class WebApplicationState:
    """Explicit process-local dependencies, inspectable in security tests."""

    repository: ResearchRepository
    authenticator: AdminAuthenticator
    sessions: SessionBackend
    login_nonces: LoginNonceStore
    login_limiter: LoginRateLimiterBackend
    request_limiter: RequestRateLimiterBackend
    audit_log: SecurityAuditBackend
    templates: Jinja2Templates
    secure_cookies: bool
    session_max_age_seconds: int


def create_web_app(
    repository: ResearchRepository,
    security: WebSecurityOptions,
    *,
    now: Callable[[], datetime] | None = None,
    password_hasher: PasswordHasher | None = None,
    sessions: SessionBackend | None = None,
    login_limiter: LoginRateLimiterBackend | None = None,
    request_limiter: RequestRateLimiterBackend | None = None,
    audit_log: SecurityAuditBackend | None = None,
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost", "[::1]", "testserver"),
) -> FastAPI:
    """Build a local-only app with no global database, server, or secret loading."""

    selected_now = now or (lambda: datetime.now(UTC))
    environment = Environment(
        loader=FileSystemLoader(PACKAGE_DIR / "templates"),
        autoescape=select_autoescape(enabled_extensions=("html", "xml"), default=True),
        enable_async=False,
    )
    templates = Jinja2Templates(env=environment)
    state = WebApplicationState(
        repository=repository,
        authenticator=AdminAuthenticator(
            username=security.admin_username,
            password_hash=security.admin_password_hash,
            hasher=password_hasher,
        ),
        sessions=sessions
        or SessionStore(
            idle_minutes=security.session_idle_minutes,
            absolute_hours=security.session_absolute_hours,
            now=selected_now,
        ),
        login_nonces=LoginNonceStore(now=selected_now),
        login_limiter=login_limiter
        or LoginRateLimiter(
            maximum_attempts=security.login_attempts,
            window_seconds=security.login_window_seconds,
            now=selected_now,
        ),
        request_limiter=request_limiter
        or RequestRateLimiter(
            maximum_requests=security.request_limit,
            window_seconds=security.request_window_seconds,
            now=selected_now,
        ),
        audit_log=audit_log or SecurityAuditLog(now=selected_now),
        templates=templates,
        secure_cookies=security.secure_cookies,
        session_max_age_seconds=security.session_absolute_hours * 60 * 60,
    )
    app = FastAPI(
        title="Kalki Market Intelligence",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.kalki = state
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(_validated_hosts(allowed_hosts)),
    )
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")

    @app.middleware("http")
    async def security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        fingerprint = _request_fingerprint(request)
        is_static = request.url.path.startswith("/static/")
        allowed, retry_after = (
            (True, 0) if is_static else state.request_limiter.allow_request(fingerprint)
        )
        response: Response
        if not allowed:
            if request.url.path.startswith(("/admin", "/api/v1/admin")):
                state.audit_log.append(
                    AuditEventType.REQUEST_RATE_LIMITED,
                    actor=None,
                    client_sha256=fingerprint,
                    detail="admin request rate limited",
                )
            response = JSONResponse(
                {"detail": "request rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
        else:
            size_error = _request_size_error(request)
            response = size_error if size_error is not None else await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'none'; form-action 'self'; "
            "frame-ancestors 'none'; object-src 'none'; script-src 'none'; "
            "style-src 'self'; img-src 'self'; connect-src 'self'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path.startswith(("/admin", "/api/v1/admin")):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/radar", status_code=307)

    @app.get("/health", tags=["operations"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/radar", response_model=list[ResearchBrief], tags=["radar"])
    def radar_api(
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
        classification: RadarClassification | None = None,
        query: Annotated[str | None, Query(max_length=64)] = None,
    ) -> tuple[ResearchBrief, ...]:
        return state.repository.list_briefs(
            limit=limit, offset=offset, classification=classification, query=query
        )

    @app.get("/api/v1/radar/status", response_model=WorkerSnapshot, tags=["radar"])
    def radar_status() -> WorkerSnapshot:
        snapshot = state.repository.get_worker_snapshot()
        if snapshot is None:
            raise HTTPException(status_code=503, detail="research worker has not reported yet")
        return snapshot

    @app.get("/api/v1/radar/{brief_id}", response_model=ResearchBrief, tags=["radar"])
    def radar_detail_api(brief_id: UUID) -> ResearchBrief:
        brief = state.repository.get_brief(brief_id)
        if brief is None:
            raise HTTPException(status_code=404, detail="radar brief not found")
        return brief

    @app.get("/radar", response_class=HTMLResponse, include_in_schema=False)
    def radar_page(
        request: Request,
        page: Annotated[int, Query(ge=1, le=2_001)] = 1,
        classification: RadarClassification | None = None,
        query: Annotated[str | None, Query(max_length=64)] = None,
    ) -> Response:
        page_size = 24
        records = state.repository.list_briefs(
            limit=page_size + 1,
            offset=(page - 1) * page_size,
            classification=classification,
            query=query,
        )
        return state.templates.TemplateResponse(
            request=request,
            name="radar_list.html",
            context={
                "briefs": records[:page_size],
                "snapshot": state.repository.get_worker_snapshot(),
                "page": page,
                "has_older": len(records) > page_size,
                "selected_classification": classification,
                "query": query or "",
                "classifications": tuple(RadarClassification),
            },
        )

    @app.get("/radar/{brief_id}", response_class=HTMLResponse, include_in_schema=False)
    def radar_detail_page(request: Request, brief_id: UUID) -> Response:
        brief = state.repository.get_brief(brief_id)
        if brief is None:
            return state.templates.TemplateResponse(
                request=request, name="not_found.html", context={}, status_code=404
            )
        return state.templates.TemplateResponse(
            request=request,
            name="radar_detail.html",
            context={
                "brief": brief,
                "sec_links": state.repository.get_brief_sec_links(brief_id),
                "snapshot": state.repository.get_worker_snapshot(),
            },
        )

    @app.get(
        "/api/v1/research",
        response_model=list[PublicResearchSummary],
        tags=["research"],
    )
    def api_research_list(
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    ) -> tuple[PublicResearchSummary, ...]:
        return tuple(
            public_summary(item)
            for item in state.repository.list_predictions(limit=limit, offset=offset)
        )

    @app.get(
        "/api/v1/research/{prediction_id}",
        response_model=PublicResearchDetail,
        tags=["research"],
    )
    def api_research_detail(prediction_id: UUID) -> PublicResearchDetail:
        prediction = state.repository.get_prediction(prediction_id)
        if prediction is None:
            raise HTTPException(status_code=404, detail="research publication not found")
        return public_detail(prediction)

    @app.get("/research", response_class=HTMLResponse, include_in_schema=False)
    def research_list(
        request: Request, page: Annotated[int, Query(ge=1, le=2_001)] = 1
    ) -> Response:
        page_size = 50
        page_records = state.repository.list_publications(
            limit=page_size + 1, offset=(page - 1) * page_size
        )
        publications = tuple(public_index_item(item) for item in page_records[:page_size])
        return state.templates.TemplateResponse(
            request=request,
            name="research_list.html",
            context={
                "publications": publications,
                "page": page,
                "has_older": len(page_records) > page_size,
            },
        )

    @app.get(
        "/research/{prediction_id}",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def research_detail(request: Request, prediction_id: UUID) -> Response:
        prediction = state.repository.get_prediction(prediction_id)
        if prediction is None:
            return state.templates.TemplateResponse(
                request=request,
                name="not_found.html",
                context={},
                status_code=404,
            )
        return state.templates.TemplateResponse(
            request=request,
            name="research_detail.html",
            context={"publication": public_detail(prediction)},
        )

    @app.get("/api/v1/screened", response_model=list[PublicScreenedFiling], tags=["screening"])
    def screened_api(
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    ) -> tuple[PublicScreenedFiling, ...]:
        return state.repository.list_screened_filings(limit=limit, offset=offset)

    @app.get(
        "/api/v1/screened/activity",
        response_model=PublicScreeningActivity,
        tags=["screening"],
    )
    def screened_activity_api() -> PublicScreeningActivity:
        activity = state.repository.get_screening_activity()
        if activity is None:
            raise HTTPException(status_code=503, detail="screening activity is unavailable")
        return activity

    @app.get("/screened", response_class=HTMLResponse, include_in_schema=False)
    def screened_page(
        request: Request, page: Annotated[int, Query(ge=1, le=2_001)] = 1
    ) -> Response:
        page_size = 50
        records = state.repository.list_screened_filings(
            limit=page_size + 1, offset=(page - 1) * page_size
        )
        return state.templates.TemplateResponse(
            request=request,
            name="screened_list.html",
            context={
                "screened_filings": records[:page_size],
                "activity": state.repository.get_screening_activity(),
                "page": page,
                "has_older": len(records) > page_size,
            },
        )

    @app.get("/admin/login", response_class=HTMLResponse, include_in_schema=False)
    def login_form(request: Request) -> Response:
        fingerprint = _request_fingerprint(request)
        if _session_for(request, state, fingerprint) is not None:
            return RedirectResponse("/admin", status_code=303)
        return _login_response(request, state, fingerprint)

    @app.post("/admin/login", response_class=HTMLResponse, include_in_schema=False)
    def login(
        request: Request,
        username: str = Form(min_length=1, max_length=64),
        password: str = Form(min_length=1, max_length=1_024),
        login_csrf: str = Form(min_length=1, max_length=256),
    ) -> Response:
        fingerprint = _request_fingerprint(request)
        if not state.login_nonces.consume(login_csrf, fingerprint):
            state.audit_log.append(
                AuditEventType.CSRF_REJECTED,
                actor=None,
                client_sha256=fingerprint,
                detail="login form token rejected",
            )
            return _login_response(
                request,
                state,
                fingerprint,
                error="The login form expired. Please try again.",
                status_code=403,
            )
        allowed, retry_after = state.login_limiter.allow_attempt(fingerprint)
        if not allowed:
            state.audit_log.append(
                AuditEventType.LOGIN_RATE_LIMITED,
                actor=None,
                client_sha256=fingerprint,
                detail="login attempt rate limited",
            )
            response = _login_response(
                request,
                state,
                fingerprint,
                error="Too many attempts. Please wait before trying again.",
                status_code=429,
            )
            response.headers["Retry-After"] = str(retry_after)
            return response
        if not state.authenticator.verify(username, password):
            state.audit_log.append(
                AuditEventType.LOGIN_FAILED,
                actor=None,
                client_sha256=fingerprint,
                detail="credentials rejected",
            )
            return _login_response(
                request,
                state,
                fingerprint,
                error="Invalid username or password.",
                status_code=401,
            )
        state.login_limiter.clear(fingerprint)
        token, _ = state.sessions.issue(state.authenticator.username, fingerprint)
        state.audit_log.append(
            AuditEventType.LOGIN_SUCCEEDED,
            actor=state.authenticator.username,
            client_sha256=fingerprint,
            detail="admin session issued",
        )
        response = RedirectResponse("/admin", status_code=303)
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=state.session_max_age_seconds,
            httponly=True,
            secure=state.secure_cookies,
            samesite="strict",
            path="/",
        )
        return response

    @app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
    def admin_dashboard(request: Request) -> Response:
        fingerprint = _request_fingerprint(request)
        session = _session_for(request, state, fingerprint)
        if session is None:
            return _admin_login_redirect(state, fingerprint)
        state.audit_log.append(
            AuditEventType.ADMIN_VIEWED,
            actor=session.username,
            client_sha256=fingerprint,
            detail="admin dashboard viewed",
        )
        return state.templates.TemplateResponse(
            request=request,
            name="admin_dashboard.html",
            context={
                "session": session,
                "publications": tuple(
                    public_summary(item) for item in state.repository.list_predictions()
                ),
                "audit_events": tuple(reversed(state.audit_log.events[-50:])),
            },
        )

    @app.get("/admin/operations", response_class=HTMLResponse, include_in_schema=False)
    def admin_operations(request: Request) -> Response:
        """Render the private, secret-free Mission Control projection."""

        fingerprint = _request_fingerprint(request)
        session = _session_for(request, state, fingerprint)
        if session is None:
            return _admin_login_redirect(state, fingerprint)
        state.audit_log.append(
            AuditEventType.ADMIN_VIEWED,
            actor=session.username,
            client_sha256=fingerprint,
            detail="mission control viewed",
        )
        return state.templates.TemplateResponse(
            request=request,
            name="admin_operations.html",
            context={
                "session": session,
                "snapshot": mission_control_snapshot(
                    state.repository.get_worker_snapshot(),
                    funnel=state.repository.get_funnel_snapshot(),
                ),
                "screening": state.repository.get_screening_reconciliation(),
                "ownership": state.repository.get_ownership_operations(),
                "financing": state.repository.get_financing_operations(),
                "accounting": state.repository.get_accounting_operations(),
                "convergence": state.repository.get_convergence_operations(),
                "outcome_science": state.repository.get_outcome_science_operations(),
                "engineering": state.repository.get_engineering_measurements(),
            },
        )

    @app.get(
        "/admin/research/{prediction_id}",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def admin_research_detail(request: Request, prediction_id: UUID) -> Response:
        fingerprint = _request_fingerprint(request)
        session = _session_for(request, state, fingerprint)
        if session is None:
            return _admin_login_redirect(state, fingerprint)
        prediction = state.repository.get_prediction(prediction_id)
        if prediction is None:
            return state.templates.TemplateResponse(
                request=request,
                name="not_found.html",
                context={"session": session},
                status_code=404,
            )
        state.audit_log.append(
            AuditEventType.ADMIN_VIEWED,
            actor=session.username,
            client_sha256=fingerprint,
            detail="admin research detail viewed",
        )
        return state.templates.TemplateResponse(
            request=request,
            name="admin_research_detail.html",
            context={"session": session, "prediction": prediction},
        )

    @app.get(
        "/api/v1/admin/audit",
        response_model=list[SecurityAuditEvent],
        tags=["administration"],
    )
    def admin_audit_api(
        request: Request,
        token: Annotated[str | None, Security(ADMIN_SESSION_COOKIE)],
    ) -> tuple[SecurityAuditEvent, ...]:
        fingerprint = _request_fingerprint(request)
        session = state.sessions.authenticate(token, fingerprint)
        if session is None:
            state.audit_log.append(
                AuditEventType.SESSION_REJECTED,
                actor=None,
                client_sha256=fingerprint,
                detail="admin API session rejected",
            )
            raise HTTPException(
                status_code=401,
                detail="administrator authentication required",
                headers={"WWW-Authenticate": "Session"},
            )
        return state.audit_log.events

    @app.post("/admin/logout", include_in_schema=False)
    def logout(
        request: Request,
        csrf_token: str = Form(min_length=1, max_length=256),
    ) -> Response:
        fingerprint = _request_fingerprint(request)
        token = request.cookies.get(SESSION_COOKIE)
        session = state.sessions.authenticate(token, fingerprint)
        if session is None:
            return _admin_login_redirect(state, fingerprint)
        if not state.sessions.verify_csrf(session, csrf_token):
            state.audit_log.append(
                AuditEventType.CSRF_REJECTED,
                actor=session.username,
                client_sha256=fingerprint,
                detail="logout token rejected",
            )
            return HTMLResponse("CSRF validation failed", status_code=403)
        state.sessions.revoke(token)
        state.audit_log.append(
            AuditEventType.LOGOUT_SUCCEEDED,
            actor=session.username,
            client_sha256=fingerprint,
            detail="admin session revoked",
        )
        response = RedirectResponse("/admin/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    return app


@dataclass(slots=True)
class PublicWebApplicationState:
    """Dependencies for the physically separate anonymous research surface."""

    repository: ResearchRepository
    request_limiter: RequestRateLimiterBackend
    templates: Jinja2Templates


def create_public_web_app(
    repository: ResearchRepository,
    *,
    request_limiter: RequestRateLimiterBackend | None = None,
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost", "[::1]", "testserver"),
    now: Callable[[], datetime] | None = None,
) -> FastAPI:
    """Build a research-only process containing no admin or operational routes."""

    selected_now = now or (lambda: datetime.now(UTC))
    environment = Environment(
        loader=FileSystemLoader(PACKAGE_DIR / "templates"),
        autoescape=select_autoescape(enabled_extensions=("html", "xml"), default=True),
        enable_async=False,
    )
    state = PublicWebApplicationState(
        repository=repository,
        request_limiter=request_limiter
        or RequestRateLimiter(maximum_requests=120, window_seconds=60, now=selected_now),
        templates=Jinja2Templates(env=environment),
    )
    app = FastAPI(
        title="Kalki Public Research",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.kalki = state
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(_validated_hosts(allowed_hosts)))
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")

    @app.middleware("http")
    async def public_security_boundary(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        fingerprint = _request_fingerprint(request)
        is_static = request.url.path.startswith("/static/")
        allowed, retry_after = (
            (True, 0) if is_static else state.request_limiter.allow_request(fingerprint)
        )
        if allowed:
            response = await call_next(request)
        else:
            response = JSONResponse(
                {"detail": "request rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
        _set_security_headers(response)
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.get("/", include_in_schema=False)
    def public_root() -> RedirectResponse:
        return RedirectResponse("/radar", status_code=307)

    @app.get("/api/v1/radar", response_model=list[ResearchBrief])
    def public_radar_api(
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
        classification: RadarClassification | None = None,
        query: Annotated[str | None, Query(max_length=64)] = None,
    ) -> tuple[ResearchBrief, ...]:
        return state.repository.list_briefs(
            limit=limit,
            offset=offset,
            classification=classification,
            query=query,
        )

    @app.get("/api/v1/radar/status", response_model=WorkerSnapshot)
    def public_radar_status() -> WorkerSnapshot:
        snapshot = state.repository.get_worker_snapshot()
        if snapshot is None:
            raise HTTPException(status_code=503, detail="research worker has not reported yet")
        return snapshot

    @app.get("/api/v1/radar/{brief_id}", response_model=ResearchBrief)
    def public_radar_detail_api(brief_id: UUID) -> ResearchBrief:
        brief = state.repository.get_brief(brief_id)
        if brief is None:
            raise HTTPException(status_code=404, detail="radar brief not found")
        return brief

    @app.get("/radar", response_class=HTMLResponse, include_in_schema=False)
    def public_radar(
        request: Request,
        page: Annotated[int, Query(ge=1, le=2_001)] = 1,
        classification: RadarClassification | None = None,
        query: Annotated[str | None, Query(max_length=64)] = None,
    ) -> Response:
        page_size = 24
        records = state.repository.list_briefs(
            limit=page_size + 1,
            offset=(page - 1) * page_size,
            classification=classification,
            query=query,
        )
        return state.templates.TemplateResponse(
            request=request,
            name="radar_list.html",
            context={
                "briefs": records[:page_size],
                "snapshot": state.repository.get_worker_snapshot(),
                "page": page,
                "has_older": len(records) > page_size,
                "selected_classification": classification,
                "query": query or "",
                "classifications": tuple(RadarClassification),
            },
        )

    @app.get("/radar/{brief_id}", response_class=HTMLResponse, include_in_schema=False)
    def public_radar_detail(request: Request, brief_id: UUID) -> Response:
        brief = state.repository.get_brief(brief_id)
        if brief is None:
            return state.templates.TemplateResponse(
                request=request, name="not_found.html", context={}, status_code=404
            )
        return state.templates.TemplateResponse(
            request=request,
            name="radar_detail.html",
            context={
                "brief": brief,
                "sec_links": state.repository.get_brief_sec_links(brief_id),
                "snapshot": state.repository.get_worker_snapshot(),
            },
        )

    @app.get("/api/v1/research", response_model=list[PublicResearchSummary])
    def public_api_list(
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    ) -> tuple[PublicResearchSummary, ...]:
        return tuple(
            public_summary(item)
            for item in state.repository.list_predictions(limit=limit, offset=offset)
        )

    @app.get("/api/v1/research/{prediction_id}", response_model=PublicResearchDetail)
    def public_api_detail(prediction_id: UUID) -> PublicResearchDetail:
        prediction = state.repository.get_prediction(prediction_id)
        if prediction is None:
            raise HTTPException(status_code=404, detail="research publication not found")
        return public_detail(prediction)

    @app.get("/research", response_class=HTMLResponse, include_in_schema=False)
    def public_research_list(
        request: Request, page: Annotated[int, Query(ge=1, le=2_001)] = 1
    ) -> Response:
        page_size = 50
        page_records = state.repository.list_publications(
            limit=page_size + 1, offset=(page - 1) * page_size
        )
        publications = tuple(public_index_item(item) for item in page_records[:page_size])
        return state.templates.TemplateResponse(
            request=request,
            name="research_list.html",
            context={
                "publications": publications,
                "page": page,
                "has_older": len(page_records) > page_size,
            },
        )

    @app.get("/research/{prediction_id}", response_class=HTMLResponse, include_in_schema=False)
    def public_research_detail(request: Request, prediction_id: UUID) -> Response:
        prediction = state.repository.get_prediction(prediction_id)
        if prediction is None:
            return state.templates.TemplateResponse(
                request=request,
                name="not_found.html",
                context={},
                status_code=404,
            )
        return state.templates.TemplateResponse(
            request=request,
            name="research_detail.html",
            context={"publication": public_detail(prediction)},
        )

    @app.get("/api/v1/screened", response_model=list[PublicScreenedFiling])
    def public_screened_api(
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    ) -> tuple[PublicScreenedFiling, ...]:
        return state.repository.list_screened_filings(limit=limit, offset=offset)

    @app.get("/api/v1/screened/activity", response_model=PublicScreeningActivity)
    def public_screened_activity_api() -> PublicScreeningActivity:
        activity = state.repository.get_screening_activity()
        if activity is None:
            raise HTTPException(status_code=503, detail="screening activity is unavailable")
        return activity

    @app.get("/screened", response_class=HTMLResponse, include_in_schema=False)
    def public_screened_page(
        request: Request, page: Annotated[int, Query(ge=1, le=2_001)] = 1
    ) -> Response:
        page_size = 50
        records = state.repository.list_screened_filings(
            limit=page_size + 1, offset=(page - 1) * page_size
        )
        return state.templates.TemplateResponse(
            request=request,
            name="screened_list.html",
            context={
                "screened_filings": records[:page_size],
                "activity": state.repository.get_screening_activity(),
                "page": page,
                "has_older": len(records) > page_size,
            },
        )

    return app


def _login_response(
    request: Request,
    state: WebApplicationState,
    fingerprint: str,
    *,
    error: str | None = None,
    status_code: int = 200,
) -> Response:
    nonce = state.login_nonces.issue(fingerprint)
    return state.templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"login_csrf": nonce, "error": error},
        status_code=status_code,
    )


def _request_fingerprint(request: Request) -> str:
    host = request.client.host if request.client is not None else "unknown"
    return client_fingerprint(host, request.headers.get("user-agent", ""))


def _request_size_error(request: Request) -> Response | None:
    """Reject unbounded or oversized mutating requests before form parsing."""

    if request.method not in {"POST", "PUT", "PATCH"}:
        return None
    raw_length = request.headers.get("content-length")
    if raw_length is None:
        return JSONResponse({"detail": "content length required"}, status_code=411)
    try:
        length = int(raw_length)
    except ValueError:
        return JSONResponse({"detail": "invalid content length"}, status_code=400)
    if length < 0:
        return JSONResponse({"detail": "invalid content length"}, status_code=400)
    if length > MAX_REQUEST_BODY_BYTES:
        return JSONResponse({"detail": "request body too large"}, status_code=413)
    return None


def _set_security_headers(response: Response) -> None:
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; base-uri 'none'; form-action 'self'; "
        "frame-ancestors 'none'; object-src 'none'; script-src 'none'; "
        "style-src 'self'; img-src 'self'; connect-src 'self'"
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"


def _validated_hosts(hosts: tuple[str, ...]) -> tuple[str, ...]:
    if not hosts or any(not host or host == "*" or "/" in host for host in hosts):
        raise ValueError("trusted hosts must be explicit non-empty hostnames")
    if len(set(hosts)) != len(hosts):
        raise ValueError("trusted hosts must be unique")
    return hosts


def _session_for(
    request: Request,
    state: WebApplicationState,
    fingerprint: str,
) -> AdminSession | None:
    return state.sessions.authenticate(request.cookies.get(SESSION_COOKIE), fingerprint)


def _admin_login_redirect(
    state: WebApplicationState,
    fingerprint: str,
) -> RedirectResponse:
    state.audit_log.append(
        AuditEventType.SESSION_REJECTED,
        actor=None,
        client_sha256=fingerprint,
        detail="admin page session rejected",
    )
    return RedirectResponse("/admin/login", status_code=303)
