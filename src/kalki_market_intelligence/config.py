"""Validated, environment-driven local configuration."""

import re
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from kalki_market_intelligence.notifications.webhook_url import validate_discord_webhook_url


class RuntimeEnvironment(StrEnum):
    """Supported execution contexts during local development."""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    """Allowed application log levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class Settings(BaseSettings):
    """Validated local settings loaded from ``KALKI_`` variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="KALKI_",
        case_sensitive=False,
        extra="forbid",
        frozen=True,
        validate_default=True,
    )

    environment: RuntimeEnvironment = RuntimeEnvironment.DEVELOPMENT
    log_level: LogLevel = LogLevel.INFO
    data_dir: Path = Path("data")
    timezone: Literal["UTC"] = "UTC"
    sec_user_agent: str | None = None
    sec_requests_per_second: float = Field(default=2.0, gt=0, le=10)
    sec_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    sec_maximum_response_bytes: int = Field(default=50_000_000, ge=1_000_000, le=250_000_000)
    discord_enabled: bool = False
    discord_webhook_url: SecretStr | None = None
    discord_requests_per_second: float = Field(default=0.5, gt=0, le=2)
    discord_timeout_seconds: float = Field(default=10.0, gt=0, le=30)
    discord_maximum_response_bytes: int = Field(default=100_000, ge=1_000, le=1_000_000)
    discord_maximum_attempts: int = Field(default=3, ge=1, le=3)
    discord_intake_enabled: bool = False
    discord_intake_bot_token_file: Path | None = None
    discord_intake_channel_id: str | None = None
    discord_intake_results_channel_id: str | None = None
    discord_intake_allowlist: tuple[str, ...] = ()
    web_enabled: bool = False
    containerized: bool = False
    web_host: str = "127.0.0.1"
    web_port: int = Field(default=8000, ge=1024, le=65_535)
    web_public_enabled: bool = False
    web_public_host: str = "127.0.0.1"
    web_public_port: int = Field(default=8001, ge=1024, le=65_535)
    web_public_hostname: str = "localhost"
    web_secure_cookies: bool = False
    web_session_idle_minutes: int = Field(default=30, ge=5, le=120)
    web_session_absolute_hours: int = Field(default=8, ge=1, le=24)
    web_login_attempts: int = Field(default=5, ge=3, le=10)
    web_login_window_seconds: int = Field(default=300, ge=60, le=900)
    web_request_limit: int = Field(default=120, ge=30, le=600)
    web_request_window_seconds: int = Field(default=60, ge=10, le=300)
    admin_username: str = "admin"
    admin_password_hash: SecretStr | None = None
    admin_password_hash_file: Path | None = None
    database_enabled: bool = False
    database_host: str = "127.0.0.1"
    database_port: int = Field(default=5432, ge=1024, le=65_535)
    database_name: str = "kalki"
    database_user: str = "kalki_app"
    database_password_file: Path | None = None
    database_pool_minimum: int = Field(default=1, ge=1, le=5)
    database_pool_maximum: int = Field(default=5, ge=1, le=20)
    local_settings_file: Path | None = None
    worker_enabled: bool = False
    worker_poll_seconds: int = Field(default=900, ge=60, le=86_400)
    worker_batch_size: int = Field(default=2, ge=1, le=8)
    worker_model: str = "qwen3:4b"
    worker_model_digest: str = "359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7"
    worker_verifier_enabled: bool = False
    worker_verifier_model: str = "gemma4:12b-it-q4_K_M"
    worker_verifier_model_digest: str = (
        "4eb23ef187e2c5462566d6a1d3bbbc2f1346d0b4327cbb66d58fffbcc9b2b05c"
    )
    ownership_worker_enabled: bool = False
    ownership_worker_poll_seconds: int = Field(default=900, ge=300, le=86_400)
    ownership_worker_batch_size: int = Field(default=2, ge=1, le=8)
    ownership_worker_maximum_backlog: int = Field(default=250, ge=1, le=1_000)
    financing_worker_enabled: bool = False
    financing_worker_poll_seconds: int = Field(default=900, ge=300, le=86_400)
    financing_worker_batch_size: int = Field(default=2, ge=1, le=8)
    financing_worker_maximum_backlog: int = Field(default=250, ge=1, le=1_000)
    accounting_worker_enabled: bool = False
    accounting_worker_poll_seconds: int = Field(default=900, ge=300, le=86_400)
    accounting_worker_batch_size: int = Field(default=2, ge=1, le=8)
    accounting_worker_maximum_backlog: int = Field(default=250, ge=1, le=1_000)
    prospective_outcomes_enabled: bool = False
    prospective_outcomes_poll_seconds: int = Field(default=3600, ge=300, le=86_400)
    prospective_outcomes_batch_size: int = Field(default=8, ge=1, le=50)
    twelve_data_api_key_file: Path | None = None
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_bin: Path = Path.home() / ".local/bin/ollama"
    ollama_lib: Path = Path.home() / ".local/lib/ollama"
    ollama_home: Path = Path.home() / ".ollama"

    @field_validator("data_dir")
    @classmethod
    def data_dir_must_not_be_empty(cls, value: Path) -> Path:
        """Reject an empty path while allowing local or later approved absolute paths."""

        if value in {Path("."), Path("/")}:
            raise ValueError("data_dir must not be empty or the filesystem root")
        return value

    @field_validator("sec_user_agent")
    @classmethod
    def sec_user_agent_identifies_contact(cls, value: str | None) -> str | None:
        """Require the application/contact form requested by SEC fair-access guidance."""

        if value is None:
            return None
        normalized = value.strip()
        if (
            len(normalized) < 10
            or len(normalized) > 255
            or "@" not in normalized
            or " " not in normalized
            or not normalized.isprintable()
        ):
            raise ValueError("sec_user_agent must identify the application and a contact email")
        return normalized

    @field_validator("discord_webhook_url")
    @classmethod
    def discord_webhook_is_secret_and_origin_restricted(
        cls, value: SecretStr | None
    ) -> SecretStr | None:
        """Validate a configured secret without storing a normalized plain string."""

        if value is not None:
            validate_discord_webhook_url(value.get_secret_value())
        return value

    @model_validator(mode="after")
    def enabled_discord_requires_webhook(self) -> Self:
        """Keep outbound notifications hard-disabled unless both controls are set."""

        if self.discord_enabled and self.discord_webhook_url is None:
            raise ValueError("enabled Discord notifications require a webhook secret")
        if self.discord_intake_enabled:
            if self.discord_intake_bot_token_file is None:
                raise ValueError("enabled Discord intake requires a bot token file")
            if self.discord_intake_channel_id is None:
                raise ValueError("enabled Discord intake requires a channel ID")
            if self.discord_intake_results_channel_id is None:
                raise ValueError("enabled Discord intake requires a results channel ID")
            if not self.discord_intake_allowlist:
                raise ValueError("enabled Discord intake requires a user allowlist")
        return self

    @field_validator("admin_username")
    @classmethod
    def admin_username_is_bounded(cls, value: str) -> str:
        """Allow one predictable local identity without control characters."""

        normalized = value.strip()
        if re.fullmatch(r"[A-Za-z0-9_.-]{3,64}", normalized) is None:
            raise ValueError("admin_username must be 3-64 safe identifier characters")
        return normalized

    @field_validator("admin_password_hash")
    @classmethod
    def admin_password_uses_argon2id(cls, value: SecretStr | None) -> SecretStr | None:
        """Reject plaintext and non-Argon2id values at the configuration boundary."""

        if value is not None and not value.get_secret_value().startswith("$argon2id$v=19$"):
            raise ValueError("admin_password_hash must be an Argon2id encoded hash")
        return value

    @field_validator("database_name", "database_user")
    @classmethod
    def database_identifiers_are_safe(cls, value: str) -> str:
        if re.fullmatch(r"[a-z][a-z0-9_]{2,62}", value) is None:
            raise ValueError("database identifiers must use 3-63 lowercase safe characters")
        return value

    @field_validator(
        "admin_password_hash_file",
        "database_password_file",
        "local_settings_file",
        "twelve_data_api_key_file",
    )
    @classmethod
    def secret_file_paths_are_absolute(cls, value: Path | None) -> Path | None:
        if value is not None and not value.is_absolute():
            raise ValueError("secret file paths must be absolute")
        return value

    @field_validator("discord_intake_bot_token_file")
    @classmethod
    def discord_bot_token_file_is_absolute(cls, value: Path | None) -> Path | None:
        if value is not None and not value.is_absolute():
            raise ValueError("Discord bot token file must be an absolute path")
        return value

    @field_validator(
        "discord_intake_channel_id",
        "discord_intake_results_channel_id",
        mode="before",
    )
    @classmethod
    def discord_channel_id_is_snowflake(cls, value: object) -> str | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if not isinstance(value, str):
            raise ValueError("Discord channel ID must be a stable snowflake ID")
        normalized = value.strip()
        if re.fullmatch(r"[0-9]{17,20}", normalized) is None:
            raise ValueError("Discord channel ID must be a stable snowflake ID")
        return normalized

    @field_validator("web_public_hostname")
    @classmethod
    def public_hostname_is_explicit(cls, value: str) -> str:
        """Accept one hostname, never a URL, wildcard, credential, or path."""

        normalized = value.strip().rstrip(".").lower()
        hostname_pattern = (
            r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)"
            r"(?:\.(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?))*"
        )
        if (
            not normalized
            or len(normalized) > 253
            or normalized == "*"
            or "://" in normalized
            or "/" in normalized
            or "@" in normalized
            or re.fullmatch(hostname_pattern, normalized) is None
        ):
            raise ValueError("public hostname must be one explicit DNS hostname")
        return normalized

    @field_validator("discord_intake_allowlist")
    @classmethod
    def discord_allowlist_contains_snowflakes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(re.fullmatch(r"[0-9]{17,20}", item) is None for item in value):
            raise ValueError("Discord allowlist entries must be stable snowflake IDs")
        if len(set(value)) != len(value):
            raise ValueError("Discord allowlist entries must be unique")
        return value

    @field_validator("ollama_bin", "ollama_lib", "ollama_home")
    @classmethod
    def ollama_host_paths_are_absolute(cls, value: Path) -> Path:
        if not value.is_absolute() or value == Path("/"):
            raise ValueError("Ollama host paths must be absolute and cannot be filesystem root")
        return value

    @field_validator("worker_model", "worker_verifier_model")
    @classmethod
    def worker_model_is_bounded(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 255 or not normalized.isprintable():
            raise ValueError("worker model must be non-empty and bounded")
        return normalized

    @field_validator("worker_model_digest", "worker_verifier_model_digest")
    @classmethod
    def worker_model_digest_is_sha256(cls, value: str) -> str:
        if re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("worker model digest must be lowercase SHA-256")
        return value

    @field_validator("ollama_base_url")
    @classmethod
    def ollama_origin_is_private(cls, value: str) -> str:
        normalized = value.rstrip("/")
        parsed = urlsplit(normalized)
        try:
            port = parsed.port
        except ValueError as error:
            raise ValueError("Ollama base URL has an invalid port") from error
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1", "ollama"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or port not in {None, 11434}
        ):
            raise ValueError("Ollama base URL must use the private local Ollama origin")
        return normalized

    @model_validator(mode="after")
    def network_bindings_are_private(self) -> Self:
        allowed_bindings = {"127.0.0.1", "::1"}
        if self.containerized:
            allowed_bindings.add("0.0.0.0")
        if self.web_host not in allowed_bindings or self.web_public_host not in allowed_bindings:
            raise ValueError("web bindings must be loopback or an explicit container-only bind")
        allowed_database_hosts = {"127.0.0.1", "::1"}
        if self.containerized:
            allowed_database_hosts.add("postgres")
        if self.database_host not in allowed_database_hosts:
            raise ValueError(
                "database host must remain loopback or on the private container network"
            )
        return self

    @model_validator(mode="after")
    def enabled_web_requires_admin_hash(self) -> Self:
        """Keep the web application off until its sole admin secret is configured."""

        configured_hashes = sum(
            value is not None for value in (self.admin_password_hash, self.admin_password_hash_file)
        )
        if configured_hashes > 1:
            raise ValueError("configure only one admin password hash source")
        if self.web_enabled and configured_hashes != 1:
            raise ValueError("enabled web interface requires one admin Argon2id hash source")
        if self.database_enabled and self.database_password_file is None:
            raise ValueError("enabled database requires a password secret file")
        if self.web_public_enabled and not self.database_enabled:
            raise ValueError("public research service requires PostgreSQL persistence")
        if self.environment is RuntimeEnvironment.PRODUCTION and (
            (self.web_enabled or self.web_public_enabled) and not self.database_enabled
        ):
            raise ValueError("production web services require PostgreSQL persistence")
        if self.database_pool_minimum > self.database_pool_maximum:
            raise ValueError("database pool minimum cannot exceed its maximum")
        if not self.containerized and urlsplit(self.ollama_base_url).hostname == "ollama":
            raise ValueError("the Ollama service hostname is permitted only inside containers")
        if self.worker_enabled and not self.database_enabled:
            raise ValueError("the research worker requires PostgreSQL persistence")
        if self.worker_verifier_enabled and not self.worker_enabled:
            raise ValueError("the publication verifier requires the research worker")
        if self.ownership_worker_enabled and not self.database_enabled:
            raise ValueError("the ownership worker requires PostgreSQL persistence")
        if self.financing_worker_enabled and not self.database_enabled:
            raise ValueError("the financing worker requires PostgreSQL persistence")
        if self.accounting_worker_enabled and not self.database_enabled:
            raise ValueError("the accounting worker requires PostgreSQL persistence")
        if self.prospective_outcomes_enabled and not self.database_enabled:
            raise ValueError("prospective outcomes require PostgreSQL persistence")
        if self.prospective_outcomes_enabled and self.twelve_data_api_key_file is None:
            raise ValueError("enabled prospective outcomes require a Twelve Data API key file")
        if self.worker_verifier_enabled and self.worker_verifier_model != ("gemma4:12b-it-q4_K_M"):
            raise ValueError("the approved verifier must use the pinned local Gemma 4 12B tag")
        if "gemma3" in self.worker_verifier_model.casefold() or "cloud" in (
            self.worker_verifier_model.casefold()
        ):
            raise ValueError("Gemma 3 and cloud-hosted verifier models are prohibited")
        return self

    @classmethod
    def load(cls) -> Self:
        """Load and validate settings from defaults, ``.env``, and the environment."""

        return cls()
