"""Bounded PostgreSQL connection runtime with file-injected credentials."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from psycopg import Connection, conninfo
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

type DatabaseRow = dict[str, Any]
type DatabaseConnection = Connection[DatabaseRow]
type ConnectionFactory = Callable[[], AbstractContextManager[DatabaseConnection]]


@dataclass(frozen=True, slots=True)
class DatabaseOptions:
    """Non-secret connection fields plus a mounted password-file reference."""

    host: str
    port: int
    name: str
    user: str
    password_file: Path
    minimum_pool_size: int = 1
    maximum_pool_size: int = 5
    connect_timeout_seconds: int = 5


class DatabaseRuntime:
    """Own one small thread-safe pool and never expose its credential string."""

    def __init__(self, options: DatabaseOptions) -> None:
        password = read_secret_file(options.password_file, label="database password")
        connection_info = conninfo.make_conninfo(
            host=options.host,
            port=options.port,
            dbname=options.name,
            user=options.user,
            password=password,
            connect_timeout=options.connect_timeout_seconds,
            application_name="kalki-web",
        )
        raw_pool = ConnectionPool(
            connection_info,
            kwargs={"row_factory": dict_row},
            min_size=options.minimum_pool_size,
            max_size=options.maximum_pool_size,
            timeout=options.connect_timeout_seconds,
            open=False,
            name="kalki-web",
            check=ConnectionPool.check_connection,
        )
        self._pool = cast(ConnectionPool[DatabaseConnection], raw_pool)

    @property
    def connection(self) -> ConnectionFactory:
        return self._pool.connection

    def open(self) -> None:
        self._pool.open(wait=True)

    def close(self) -> None:
        self._pool.close()


def read_secret_file(path: Path, *, label: str) -> str:
    """Read one bounded single-line secret without ever including it in errors."""

    if not path.is_absolute():
        raise ValueError(f"{label} file path must be absolute")
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} file must be a regular non-symlink file")
    if path.stat().st_size > 4_096:
        raise ValueError(f"{label} file exceeds 4096 bytes")
    value = path.read_text(encoding="utf-8").rstrip("\r\n")
    if not value or "\n" in value or "\r" in value or "\x00" in value:
        raise ValueError(f"{label} file must contain one non-empty line")
    return value
