"""Single-admin authentication, session, CSRF, rate-limit, and audit controls."""

from __future__ import annotations

import hmac
import math
import secrets
import threading
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Protocol
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from psycopg import sql

from kalki_market_intelligence.database import ConnectionFactory
from kalki_market_intelligence.web.contracts import AuditEventType, SecurityAuditEvent


def require_utc(value: datetime) -> datetime:
    """Normalize an aware security timestamp and reject naive clocks."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("security clock must return a timezone-aware timestamp")
    return value.astimezone(UTC)


def client_fingerprint(client_host: str, user_agent: str) -> str:
    """Hash bounded request metadata so raw network identifiers are not audited."""

    host = client_host[:255]
    agent = user_agent[:512]
    return sha256(f"{host}\n{agent}".encode()).hexdigest()


class AdminAuthenticator:
    """Verify one configured identity with Argon2id and bounded inputs."""

    def __init__(
        self,
        *,
        username: str,
        password_hash: str,
        hasher: PasswordHasher | None = None,
    ) -> None:
        if not password_hash.startswith("$argon2id$v=19$"):
            raise ValueError("admin password must use an Argon2id encoded hash")
        self._username = username
        self._password_hash = password_hash
        self._hasher = hasher or PasswordHasher()

    @property
    def username(self) -> str:
        return self._username

    def verify(self, username: str, password: str) -> bool:
        """Always run Argon2 verification and then compare the configured identity."""

        bounded_password = password if len(password) <= 1_024 else password[:1_024]
        password_matches: bool
        try:
            password_matches = self._hasher.verify(self._password_hash, bounded_password)
        except VerificationError:
            password_matches = False
        username_matches = hmac.compare_digest(username, self._username)
        return bool(password_matches and username_matches and len(password) <= 1_024)


@dataclass(slots=True)
class AdminSession:
    """Server-side state; only its random bearer token reaches the browser."""

    username: str
    client_sha256: str
    csrf_token: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime


class SessionBackend(Protocol):
    def issue(self, username: str, client_sha256: str) -> tuple[str, AdminSession]: ...

    def authenticate(self, token: str | None, client_sha256: str) -> AdminSession | None: ...

    def verify_csrf(self, session: AdminSession, supplied: str | None) -> bool: ...

    def revoke(self, token: str | None) -> None: ...


class LoginRateLimiterBackend(Protocol):
    def allow_attempt(self, client_sha256: str) -> tuple[bool, int]: ...

    def clear(self, client_sha256: str) -> None: ...


class RequestRateLimiterBackend(Protocol):
    def allow_request(self, client_sha256: str) -> tuple[bool, int]: ...


class SecurityAuditBackend(Protocol):
    def append(
        self,
        event_type: AuditEventType,
        *,
        actor: str | None,
        client_sha256: str,
        detail: str,
    ) -> SecurityAuditEvent: ...

    @property
    def events(self) -> tuple[SecurityAuditEvent, ...]: ...


class SessionStore:
    """Thread-safe in-memory sessions with idle and absolute expiry."""

    def __init__(
        self,
        *,
        idle_minutes: int = 30,
        absolute_hours: int = 8,
        now: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        if not 5 <= idle_minutes <= 120:
            raise ValueError("session idle lifetime must be between 5 and 120 minutes")
        if not 1 <= absolute_hours <= 24:
            raise ValueError("session absolute lifetime must be between 1 and 24 hours")
        self._idle = timedelta(minutes=idle_minutes)
        self._absolute = timedelta(hours=absolute_hours)
        self._now = now or (lambda: datetime.now(UTC))
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._sessions: dict[str, AdminSession] = {}
        self._lock = threading.Lock()

    def issue(self, username: str, client_sha256: str) -> tuple[str, AdminSession]:
        now = require_utc(self._now())
        token = self._token_factory()
        csrf_token = self._token_factory()
        if len(token) < 32 or len(csrf_token) < 32:
            raise ValueError("session token factory returned insufficient entropy")
        session = AdminSession(
            username=username,
            client_sha256=client_sha256,
            csrf_token=csrf_token,
            created_at=now,
            last_seen_at=now,
            expires_at=now + self._absolute,
        )
        with self._lock:
            self._sessions[_token_digest(token)] = session
        return token, session

    def authenticate(self, token: str | None, client_sha256: str) -> AdminSession | None:
        if token is None or len(token) > 256:
            return None
        key = _token_digest(token)
        now = require_utc(self._now())
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                return None
            idle_expiry = session.last_seen_at + self._idle
            if (
                now >= session.expires_at
                or now >= idle_expiry
                or not hmac.compare_digest(session.client_sha256, client_sha256)
            ):
                self._sessions.pop(key, None)
                return None
            session.last_seen_at = now
            return session

    def verify_csrf(self, session: AdminSession, supplied: str | None) -> bool:
        return supplied is not None and hmac.compare_digest(session.csrf_token, supplied)

    def revoke(self, token: str | None) -> None:
        if token is None or len(token) > 256:
            return
        with self._lock:
            self._sessions.pop(_token_digest(token), None)


class PostgresSessionStore:
    """Durable opaque sessions; bearer tokens are persisted only as digests."""

    def __init__(
        self,
        connection: ConnectionFactory,
        *,
        idle_minutes: int = 30,
        absolute_hours: int = 8,
        now: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        if not 5 <= idle_minutes <= 120:
            raise ValueError("session idle lifetime must be between 5 and 120 minutes")
        if not 1 <= absolute_hours <= 24:
            raise ValueError("session absolute lifetime must be between 1 and 24 hours")
        self._connection = connection
        self._idle = timedelta(minutes=idle_minutes)
        self._absolute = timedelta(hours=absolute_hours)
        self._now = now or (lambda: datetime.now(UTC))
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))

    def issue(self, username: str, client_sha256: str) -> tuple[str, AdminSession]:
        now = require_utc(self._now())
        token = self._token_factory()
        csrf_token = self._token_factory()
        if len(token) < 32 or len(csrf_token) < 32:
            raise ValueError("session token factory returned insufficient entropy")
        session = AdminSession(
            username=username,
            client_sha256=client_sha256,
            csrf_token=csrf_token,
            created_at=now,
            last_seen_at=now,
            expires_at=now + self._absolute,
        )
        with self._connection() as connection:
            connection.execute(
                "DELETE FROM web_admin_sessions WHERE expires_at <= %s OR revoked_at IS NOT NULL",
                (now,),
            )
            connection.execute(
                """
                INSERT INTO web_admin_sessions (
                    token_sha256, username, client_sha256, csrf_token,
                    created_at, last_seen_at, expires_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    _token_digest(token),
                    username,
                    client_sha256,
                    csrf_token,
                    session.created_at,
                    session.last_seen_at,
                    session.expires_at,
                ),
            )
        return token, session

    def authenticate(self, token: str | None, client_sha256: str) -> AdminSession | None:
        if token is None or len(token) > 256:
            return None
        key = _token_digest(token)
        now = require_utc(self._now())
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT username, client_sha256, csrf_token, created_at, last_seen_at, expires_at,
                       revoked_at
                FROM web_admin_sessions
                WHERE token_sha256 = %s
                FOR UPDATE
                """,
                (key,),
            ).fetchone()
            if row is None or row["revoked_at"] is not None:
                return None
            session = AdminSession(
                username=row["username"],
                client_sha256=row["client_sha256"],
                csrf_token=row["csrf_token"],
                created_at=require_utc(row["created_at"]),
                last_seen_at=require_utc(row["last_seen_at"]),
                expires_at=require_utc(row["expires_at"]),
            )
            invalid = (
                now >= session.expires_at
                or now >= session.last_seen_at + self._idle
                or not hmac.compare_digest(session.client_sha256, client_sha256)
            )
            if invalid:
                connection.execute(
                    "UPDATE web_admin_sessions SET revoked_at = %s WHERE token_sha256 = %s",
                    (now, key),
                )
                return None
            connection.execute(
                "UPDATE web_admin_sessions SET last_seen_at = %s WHERE token_sha256 = %s",
                (now, key),
            )
            session.last_seen_at = now
            return session

    def verify_csrf(self, session: AdminSession, supplied: str | None) -> bool:
        return supplied is not None and hmac.compare_digest(session.csrf_token, supplied)

    def revoke(self, token: str | None) -> None:
        if token is None or len(token) > 256:
            return
        now = require_utc(self._now())
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE web_admin_sessions
                SET revoked_at = COALESCE(revoked_at, %s)
                WHERE token_sha256 = %s
                """,
                (now, _token_digest(token)),
            )


@dataclass(frozen=True, slots=True)
class LoginNonce:
    """One-time pre-authentication CSRF state."""

    client_sha256: str
    expires_at: datetime


class LoginNonceStore:
    """Issue and consume short-lived, one-time login form tokens."""

    def __init__(
        self,
        *,
        now: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._now = now or (lambda: datetime.now(UTC))
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._nonces: dict[str, LoginNonce] = {}
        self._lock = threading.Lock()

    def issue(self, client_sha256: str) -> str:
        token = self._token_factory()
        if len(token) < 32:
            raise ValueError("login nonce factory returned insufficient entropy")
        now = require_utc(self._now())
        with self._lock:
            self._purge(now)
            self._nonces[_token_digest(token)] = LoginNonce(
                client_sha256=client_sha256,
                expires_at=now + timedelta(minutes=10),
            )
        return token

    def consume(self, token: str | None, client_sha256: str) -> bool:
        if token is None or len(token) > 256:
            return False
        now = require_utc(self._now())
        with self._lock:
            self._purge(now)
            nonce = self._nonces.pop(_token_digest(token), None)
        return bool(
            nonce is not None
            and now < nonce.expires_at
            and hmac.compare_digest(nonce.client_sha256, client_sha256)
        )

    def _purge(self, now: datetime) -> None:
        expired = tuple(key for key, item in self._nonces.items() if now >= item.expires_at)
        for key in expired:
            self._nonces.pop(key, None)


class LoginRateLimiter:
    """Thread-safe sliding-window limiter keyed by hashed client metadata."""

    def __init__(
        self,
        *,
        maximum_attempts: int = 5,
        window_seconds: int = 300,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not 3 <= maximum_attempts <= 10:
            raise ValueError("login maximum attempts must be between 3 and 10")
        if not 60 <= window_seconds <= 900:
            raise ValueError("login rate window must be between 60 and 900 seconds")
        self._maximum = maximum_attempts
        self._window = timedelta(seconds=window_seconds)
        self._now = now or (lambda: datetime.now(UTC))
        self._attempts: defaultdict[str, deque[datetime]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow_attempt(self, client_sha256: str) -> tuple[bool, int]:
        now = require_utc(self._now())
        threshold = now - self._window
        with self._lock:
            attempts = self._attempts[client_sha256]
            while attempts and attempts[0] <= threshold:
                attempts.popleft()
            if len(attempts) >= self._maximum:
                remaining = max(1, int((attempts[0] + self._window - now).total_seconds()))
                return False, remaining
            attempts.append(now)
            return True, 0

    def clear(self, client_sha256: str) -> None:
        with self._lock:
            self._attempts.pop(client_sha256, None)


class RequestRateLimiter:
    """General local request ceiling separate from credential-attempt throttling."""

    def __init__(
        self,
        *,
        maximum_requests: int = 120,
        window_seconds: int = 60,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not 10 <= maximum_requests <= 600:
            raise ValueError("request limit must be between 10 and 600")
        if not 10 <= window_seconds <= 300:
            raise ValueError("request rate window must be between 10 and 300 seconds")
        self._maximum = maximum_requests
        self._window = timedelta(seconds=window_seconds)
        self._now = now or (lambda: datetime.now(UTC))
        self._requests: defaultdict[str, deque[datetime]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow_request(self, client_sha256: str) -> tuple[bool, int]:
        now = require_utc(self._now())
        threshold = now - self._window
        with self._lock:
            requests = self._requests[client_sha256]
            while requests and requests[0] <= threshold:
                requests.popleft()
            if len(requests) >= self._maximum:
                remaining = max(1, int((requests[0] + self._window - now).total_seconds()))
                return False, remaining
            requests.append(now)
            return True, 0


class _PostgresSlidingWindowLimiter:
    """Transactionally serialize one fingerprint's durable sliding window."""

    def __init__(
        self,
        connection: ConnectionFactory,
        *,
        table: str,
        timestamp_column: str,
        maximum: int,
        window_seconds: int,
        now: Callable[[], datetime] | None,
        advisory_seed: int,
    ) -> None:
        self._connection = connection
        self._table = sql.Identifier(table)
        self._timestamp_column = sql.Identifier(timestamp_column)
        self._maximum = maximum
        self._window = timedelta(seconds=window_seconds)
        self._now = now or (lambda: datetime.now(UTC))
        self._advisory_seed = advisory_seed

    def allow(self, client_sha256: str) -> tuple[bool, int]:
        now = require_utc(self._now())
        threshold = now - self._window
        with self._connection() as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, %s))",
                (client_sha256, self._advisory_seed),
            )
            connection.execute(
                sql.SQL("DELETE FROM {} WHERE {} <= %s").format(
                    self._table, self._timestamp_column
                ),
                (threshold,),
            )
            row = connection.execute(
                sql.SQL(
                    "SELECT count(*) AS event_count, min({}) AS oldest "
                    "FROM {} WHERE client_sha256 = %s"
                ).format(self._timestamp_column, self._table),
                (client_sha256,),
            ).fetchone()
            if row is None:
                raise RuntimeError("rate-limit aggregate unexpectedly returned no row")
            if row["event_count"] >= self._maximum:
                oldest = require_utc(row["oldest"])
                remaining = max(1, math.ceil((oldest + self._window - now).total_seconds()))
                return False, remaining
            connection.execute(
                sql.SQL("INSERT INTO {} (client_sha256, {}) VALUES (%s, %s)").format(
                    self._table, self._timestamp_column
                ),
                (client_sha256, now),
            )
            return True, 0

    def clear(self, client_sha256: str) -> None:
        with self._connection() as connection:
            connection.execute(
                sql.SQL("DELETE FROM {} WHERE client_sha256 = %s").format(self._table),
                (client_sha256,),
            )


class PostgresLoginRateLimiter:
    def __init__(
        self,
        connection: ConnectionFactory,
        *,
        maximum_attempts: int = 5,
        window_seconds: int = 300,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not 3 <= maximum_attempts <= 10:
            raise ValueError("login maximum attempts must be between 3 and 10")
        if not 60 <= window_seconds <= 900:
            raise ValueError("login rate window must be between 60 and 900 seconds")
        self._limiter = _PostgresSlidingWindowLimiter(
            connection,
            table="web_login_attempts",
            timestamp_column="attempted_at",
            maximum=maximum_attempts,
            window_seconds=window_seconds,
            now=now,
            advisory_seed=1,
        )

    def allow_attempt(self, client_sha256: str) -> tuple[bool, int]:
        return self._limiter.allow(client_sha256)

    def clear(self, client_sha256: str) -> None:
        self._limiter.clear(client_sha256)


class PostgresRequestRateLimiter:
    def __init__(
        self,
        connection: ConnectionFactory,
        *,
        maximum_requests: int = 120,
        window_seconds: int = 60,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not 10 <= maximum_requests <= 600:
            raise ValueError("request limit must be between 10 and 600")
        if not 10 <= window_seconds <= 300:
            raise ValueError("request rate window must be between 10 and 300 seconds")
        self._limiter = _PostgresSlidingWindowLimiter(
            connection,
            table="web_request_events",
            timestamp_column="requested_at",
            maximum=maximum_requests,
            window_seconds=window_seconds,
            now=now,
            advisory_seed=2,
        )

    def allow_request(self, client_sha256: str) -> tuple[bool, int]:
        return self._limiter.allow(client_sha256)


class SecurityAuditLog:
    """Append-only process-local security events with closed detail values."""

    def __init__(
        self,
        *,
        now: Callable[[], datetime] | None = None,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._now = now or (lambda: datetime.now(UTC))
        self._id_factory = id_factory
        self._events: list[SecurityAuditEvent] = []
        self._lock = threading.Lock()

    def append(
        self,
        event_type: AuditEventType,
        *,
        actor: str | None,
        client_sha256: str,
        detail: str,
    ) -> SecurityAuditEvent:
        event = SecurityAuditEvent(
            event_id=self._id_factory(),
            occurred_at=require_utc(self._now()),
            event_type=event_type,
            actor=actor,
            client_sha256=client_sha256,
            detail=detail,
        )
        with self._lock:
            self._events.append(event)
        return event

    @property
    def events(self) -> tuple[SecurityAuditEvent, ...]:
        with self._lock:
            return tuple(self._events)


class PostgresSecurityAuditLog:
    """Database-enforced append-only audit events with bounded reads."""

    def __init__(
        self,
        connection: ConnectionFactory,
        *,
        now: Callable[[], datetime] | None = None,
        id_factory: Callable[[], UUID] = uuid4,
        read_limit: int = 500,
    ) -> None:
        if not 1 <= read_limit <= 1_000:
            raise ValueError("audit read limit must be between 1 and 1000")
        self._connection = connection
        self._now = now or (lambda: datetime.now(UTC))
        self._id_factory = id_factory
        self._read_limit = read_limit

    def append(
        self,
        event_type: AuditEventType,
        *,
        actor: str | None,
        client_sha256: str,
        detail: str,
    ) -> SecurityAuditEvent:
        event = SecurityAuditEvent(
            event_id=self._id_factory(),
            occurred_at=require_utc(self._now()),
            event_type=event_type,
            actor=actor,
            client_sha256=client_sha256,
            detail=detail,
        )
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO web_security_audit_events (
                    event_id, occurred_at, event_type, actor, client_sha256, detail
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    event.event_id,
                    event.occurred_at,
                    event.event_type.value,
                    event.actor,
                    event.client_sha256,
                    event.detail,
                ),
            )
        return event

    @property
    def events(self) -> tuple[SecurityAuditEvent, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT event_id, occurred_at, event_type, actor, client_sha256, detail
                FROM (
                    SELECT event_id, occurred_at, event_type, actor, client_sha256, detail
                    FROM web_security_audit_events
                    ORDER BY occurred_at DESC, event_id DESC
                    LIMIT %s
                ) AS recent_events
                ORDER BY occurred_at, event_id
                """,
                (self._read_limit,),
            ).fetchall()
        return tuple(
            SecurityAuditEvent(
                event_id=row["event_id"],
                occurred_at=require_utc(row["occurred_at"]),
                event_type=AuditEventType(row["event_type"]),
                actor=row["actor"],
                client_sha256=row["client_sha256"],
                detail=row["detail"],
            )
            for row in rows
        )


def _token_digest(token: str) -> str:
    return sha256(token.encode()).hexdigest()
