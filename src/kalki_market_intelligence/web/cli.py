"""Local-only web administration commands."""

from __future__ import annotations

import getpass
import sys
from collections.abc import Sequence

import uvicorn
from argon2 import PasswordHasher
from fastapi import FastAPI

from kalki_market_intelligence.config import Settings
from kalki_market_intelligence.database import DatabaseOptions, DatabaseRuntime, read_secret_file
from kalki_market_intelligence.web.app import (
    WebSecurityOptions,
    create_public_web_app,
    create_web_app,
)
from kalki_market_intelligence.web.repository import (
    MemoryResearchRepository,
    PostgresResearchRepository,
    ResearchRepository,
)
from kalki_market_intelligence.web.security import (
    PostgresLoginRateLimiter,
    PostgresRequestRateLimiter,
    PostgresSecurityAuditLog,
    PostgresSessionStore,
)


def hash_password_main(argv: Sequence[str] | None = None) -> int:
    """Prompt locally and print an Argon2id hash suitable for ignored `.env`."""

    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if arguments:
        print("This command accepts no password arguments.", file=sys.stderr)
        return 2
    password = getpass.getpass("New admin password: ")
    confirmation = getpass.getpass("Confirm admin password: ")
    if password != confirmation:
        print("Passwords did not match.", file=sys.stderr)
        return 1
    if not 14 <= len(password) <= 1_024:
        print("Password must contain between 14 and 1024 characters.", file=sys.stderr)
        return 1
    encoded = PasswordHasher().hash(password)
    print(f"KALKI_ADMIN_PASSWORD_HASH='{encoded}'")
    return 0


def serve_main() -> int:
    """Backward-compatible local admin entry point."""

    return serve_admin_main()


def serve_admin_main() -> int:
    """Serve the full workspace on its validated local/container boundary."""

    settings = Settings.load()
    if not settings.web_enabled:
        print("Web interface is disabled or its admin hash is absent.", file=sys.stderr)
        return 2
    password_hash = _admin_password_hash(settings)
    runtime = _database_runtime(settings)
    try:
        if runtime is None:
            repository: ResearchRepository = MemoryResearchRepository()
            app = create_web_app(
                repository,
                _security_options(settings, password_hash),
            )
        else:
            runtime.open()
            repository = PostgresResearchRepository(runtime.connection)
            app = create_web_app(
                repository,
                _security_options(settings, password_hash),
                sessions=PostgresSessionStore(
                    runtime.connection,
                    idle_minutes=settings.web_session_idle_minutes,
                    absolute_hours=settings.web_session_absolute_hours,
                ),
                login_limiter=PostgresLoginRateLimiter(
                    runtime.connection,
                    maximum_attempts=settings.web_login_attempts,
                    window_seconds=settings.web_login_window_seconds,
                ),
                request_limiter=PostgresRequestRateLimiter(
                    runtime.connection,
                    maximum_requests=settings.web_request_limit,
                    window_seconds=settings.web_request_window_seconds,
                ),
                audit_log=PostgresSecurityAuditLog(runtime.connection),
                allowed_hosts=("127.0.0.1", "localhost", "[::1]"),
            )
        _run(app, host=settings.web_host, port=settings.web_port, trust_proxy_headers=False)
        return 0
    finally:
        if runtime is not None:
            runtime.close()


def serve_public_main() -> int:
    """Serve only anonymous reviewed research; no admin routes exist here."""

    settings = Settings.load()
    if not settings.web_public_enabled:
        print("Public research service is disabled.", file=sys.stderr)
        return 2
    runtime = _database_runtime(settings)
    if runtime is None:
        print("Public research service requires PostgreSQL.", file=sys.stderr)
        return 2
    try:
        runtime.open()
        app = create_public_web_app(
            PostgresResearchRepository(runtime.connection),
            request_limiter=PostgresRequestRateLimiter(
                runtime.connection,
                maximum_requests=settings.web_request_limit,
                window_seconds=settings.web_request_window_seconds,
            ),
            allowed_hosts=(
                settings.web_public_hostname,
                "127.0.0.1",
                "localhost",
                "[::1]",
            ),
        )
        _run(
            app,
            host=settings.web_public_host,
            port=settings.web_public_port,
            trust_proxy_headers=True,
        )
        return 0
    finally:
        runtime.close()


def _admin_password_hash(settings: Settings) -> str:
    if settings.admin_password_hash is not None:
        return settings.admin_password_hash.get_secret_value()
    if settings.admin_password_hash_file is None:
        raise ValueError("admin password hash source is absent")
    encoded = read_secret_file(settings.admin_password_hash_file, label="admin password hash")
    if not encoded.startswith("$argon2id$v=19$"):
        raise ValueError("admin password hash file must contain an Argon2id encoded hash")
    return encoded


def _database_runtime(settings: Settings) -> DatabaseRuntime | None:
    if not settings.database_enabled:
        return None
    if settings.database_password_file is None:
        raise ValueError("database password file is absent")
    return DatabaseRuntime(
        DatabaseOptions(
            host=settings.database_host,
            port=settings.database_port,
            name=settings.database_name,
            user=settings.database_user,
            password_file=settings.database_password_file,
            minimum_pool_size=settings.database_pool_minimum,
            maximum_pool_size=settings.database_pool_maximum,
        )
    )


def _security_options(settings: Settings, password_hash: str) -> WebSecurityOptions:
    return WebSecurityOptions(
        admin_username=settings.admin_username,
        admin_password_hash=password_hash,
        secure_cookies=settings.web_secure_cookies,
        session_idle_minutes=settings.web_session_idle_minutes,
        session_absolute_hours=settings.web_session_absolute_hours,
        login_attempts=settings.web_login_attempts,
        login_window_seconds=settings.web_login_window_seconds,
        request_limit=settings.web_request_limit,
        request_window_seconds=settings.web_request_window_seconds,
    )


def _run(app: FastAPI, *, host: str, port: int, trust_proxy_headers: bool) -> None:
    uvicorn.run(
        app,
        host=host,
        port=port,
        proxy_headers=trust_proxy_headers,
        # The public process is reachable only from host loopback and its private
        # connector network, so forwarded client IPs are trusted there. The admin
        # process never trusts proxy headers.
        forwarded_allow_ips="*" if trust_proxy_headers else "",
        server_header=False,
    )
