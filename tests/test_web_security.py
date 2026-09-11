"""Unit tests for local admin security primitives."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from argon2 import PasswordHasher

from kalki_market_intelligence.web.contracts import AuditEventType
from kalki_market_intelligence.web.security import (
    AdminAuthenticator,
    LoginNonceStore,
    LoginRateLimiter,
    RequestRateLimiter,
    SecurityAuditLog,
    SessionStore,
    client_fingerprint,
)


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 24, 12, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value

    def advance(self, **kwargs: float) -> None:
        self.value += timedelta(**kwargs)


def test_argon2_authenticator_checks_password_and_identity() -> None:
    hasher = PasswordHasher(time_cost=1, memory_cost=1_024, parallelism=1)
    authenticator = AdminAuthenticator(
        username="admin",
        password_hash=hasher.hash("synthetic-secure-password"),
        hasher=hasher,
    )

    assert authenticator.verify("admin", "synthetic-secure-password") is True
    assert authenticator.verify("wrong", "synthetic-secure-password") is False
    assert authenticator.verify("admin", "wrong-password") is False
    assert authenticator.verify("admin", "x" * 1_025) is False


def test_session_is_client_bound_csrf_protected_and_expires() -> None:
    clock = Clock()
    tokens = iter(("s" * 43, "c" * 43))
    store = SessionStore(
        idle_minutes=5,
        absolute_hours=1,
        now=clock.now,
        token_factory=lambda: next(tokens),
    )
    token, issued = store.issue("admin", "a" * 64)

    assert store.authenticate(token, "a" * 64) is issued
    assert store.authenticate(token, "b" * 64) is None

    tokens = iter(("t" * 43, "d" * 43))
    store = SessionStore(
        idle_minutes=5,
        absolute_hours=1,
        now=clock.now,
        token_factory=lambda: next(tokens),
    )
    token, issued = store.issue("admin", "a" * 64)
    assert store.verify_csrf(issued, "wrong") is False
    assert store.verify_csrf(issued, issued.csrf_token) is True
    clock.advance(minutes=5)
    assert store.authenticate(token, "a" * 64) is None


def test_login_nonce_is_one_time_client_bound_and_short_lived() -> None:
    clock = Clock()
    store = LoginNonceStore(now=clock.now, token_factory=lambda: "n" * 43)

    token = store.issue("a" * 64)

    assert store.consume(token, "b" * 64) is False
    assert store.consume(token, "a" * 64) is False
    token = store.issue("a" * 64)
    clock.advance(minutes=10)
    assert store.consume(token, "a" * 64) is False


def test_login_rate_limit_slides_and_can_be_cleared() -> None:
    clock = Clock()
    limiter = LoginRateLimiter(maximum_attempts=3, window_seconds=60, now=clock.now)

    assert limiter.allow_attempt("a" * 64) == (True, 0)
    assert limiter.allow_attempt("a" * 64) == (True, 0)
    assert limiter.allow_attempt("a" * 64) == (True, 0)
    allowed, retry_after = limiter.allow_attempt("a" * 64)
    assert allowed is False
    assert retry_after == 60
    clock.advance(seconds=60)
    assert limiter.allow_attempt("a" * 64) == (True, 0)
    limiter.clear("a" * 64)
    assert limiter.allow_attempt("a" * 64) == (True, 0)


def test_request_rate_limit_slides_independently() -> None:
    clock = Clock()
    limiter = RequestRateLimiter(maximum_requests=10, window_seconds=10, now=clock.now)

    for _ in range(10):
        assert limiter.allow_request("a" * 64) == (True, 0)
    assert limiter.allow_request("a" * 64) == (False, 10)
    assert limiter.allow_request("b" * 64) == (True, 0)
    clock.advance(seconds=10)
    assert limiter.allow_request("a" * 64) == (True, 0)


def test_audit_log_is_append_only_closed_and_hashes_client_metadata() -> None:
    clock = Clock()
    audit = SecurityAuditLog(
        now=clock.now,
        id_factory=lambda: UUID("90000000-0000-4000-8000-000000000001"),
    )
    fingerprint = client_fingerprint("127.0.0.1", "synthetic-browser")
    event = audit.append(
        AuditEventType.LOGIN_SUCCEEDED,
        actor="admin",
        client_sha256=fingerprint,
        detail="admin session issued",
    )

    assert audit.events == (event,)
    assert "127.0.0.1" not in event.model_dump_json()
    assert "synthetic-browser" not in event.model_dump_json()
