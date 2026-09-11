"""Tests for validated local configuration."""

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from kalki_market_intelligence.config import LogLevel, RuntimeEnvironment, Settings

SYNTHETIC_WEBHOOK_ID = "123456789012345678"
SYNTHETIC_WEBHOOK_TOKEN = "synthetic_test_token_12345"


def test_settings_have_safe_local_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KALKI_ENVIRONMENT", raising=False)
    monkeypatch.delenv("KALKI_LOG_LEVEL", raising=False)
    monkeypatch.delenv("KALKI_DATA_DIR", raising=False)
    monkeypatch.delenv("KALKI_TIMEZONE", raising=False)
    monkeypatch.delenv("KALKI_SEC_USER_AGENT", raising=False)
    monkeypatch.delenv("KALKI_SEC_REQUESTS_PER_SECOND", raising=False)
    monkeypatch.delenv("KALKI_SEC_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("KALKI_SEC_MAXIMUM_RESPONSE_BYTES", raising=False)
    monkeypatch.delenv("KALKI_DISCORD_ENABLED", raising=False)
    monkeypatch.delenv("KALKI_DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("KALKI_WEB_ENABLED", raising=False)
    monkeypatch.delenv("KALKI_ADMIN_PASSWORD_HASH", raising=False)
    monkeypatch.delenv("KALKI_ADMIN_PASSWORD_HASH_FILE", raising=False)
    monkeypatch.delenv("KALKI_DATABASE_ENABLED", raising=False)
    monkeypatch.delenv("KALKI_DATABASE_PASSWORD_FILE", raising=False)
    monkeypatch.delenv("KALKI_WEB_PUBLIC_ENABLED", raising=False)
    monkeypatch.delenv("KALKI_PROSPECTIVE_OUTCOMES_ENABLED", raising=False)
    monkeypatch.delenv("KALKI_TWELVE_DATA_API_KEY_FILE", raising=False)

    settings = Settings(_env_file=None)

    assert settings.environment is RuntimeEnvironment.DEVELOPMENT
    assert settings.log_level is LogLevel.INFO
    assert settings.data_dir == Path("data")
    assert settings.timezone == "UTC"
    assert settings.sec_user_agent is None
    assert settings.sec_requests_per_second == 2.0
    assert settings.discord_enabled is False
    assert settings.discord_webhook_url is None
    assert settings.web_enabled is False
    assert settings.web_host == "127.0.0.1"
    assert settings.admin_password_hash is None
    assert settings.database_enabled is False
    assert settings.web_public_enabled is False
    assert settings.prospective_outcomes_enabled is False
    assert settings.twelve_data_api_key_file is None


def test_settings_accept_prefixed_environment_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KALKI_ENVIRONMENT", "test")
    monkeypatch.setenv("KALKI_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("KALKI_DATA_DIR", "data/fixtures")

    settings = Settings(_env_file=None)

    assert settings.environment is RuntimeEnvironment.TEST
    assert settings.log_level is LogLevel.DEBUG
    assert settings.data_dir == Path("data/fixtures")


def test_non_utc_internal_timezone_is_rejected() -> None:
    with pytest.raises(ValidationError, match="UTC"):
        Settings(timezone="America/Toronto", _env_file=None)  # type: ignore[arg-type]


@pytest.mark.parametrize("unsafe_path", ["", "/"])
def test_unsafe_data_roots_are_rejected(unsafe_path: str) -> None:
    with pytest.raises(ValidationError, match="filesystem root"):
        Settings(data_dir=Path(unsafe_path), _env_file=None)


def test_configuration_schema_is_exportable() -> None:
    schema = Settings.model_json_schema()

    assert set(schema["properties"]) == {
        "data_dir",
        "discord_enabled",
        "discord_intake_allowlist",
        "discord_intake_bot_token_file",
        "discord_intake_channel_id",
        "discord_intake_results_channel_id",
        "discord_intake_enabled",
        "discord_maximum_attempts",
        "discord_maximum_response_bytes",
        "discord_requests_per_second",
        "discord_timeout_seconds",
        "discord_webhook_url",
        "environment",
        "log_level",
        "local_settings_file",
        "ollama_base_url",
        "ollama_bin",
        "ollama_home",
        "ollama_lib",
        "ownership_worker_batch_size",
        "ownership_worker_enabled",
        "ownership_worker_maximum_backlog",
        "ownership_worker_poll_seconds",
        "financing_worker_batch_size",
        "financing_worker_enabled",
        "financing_worker_maximum_backlog",
        "financing_worker_poll_seconds",
        "accounting_worker_batch_size",
        "accounting_worker_enabled",
        "accounting_worker_maximum_backlog",
        "accounting_worker_poll_seconds",
        "prospective_outcomes_batch_size",
        "prospective_outcomes_enabled",
        "prospective_outcomes_poll_seconds",
        "admin_password_hash",
        "admin_password_hash_file",
        "admin_username",
        "containerized",
        "database_enabled",
        "database_host",
        "database_name",
        "database_password_file",
        "database_pool_maximum",
        "database_pool_minimum",
        "database_port",
        "database_user",
        "sec_maximum_response_bytes",
        "sec_requests_per_second",
        "sec_timeout_seconds",
        "sec_user_agent",
        "timezone",
        "twelve_data_api_key_file",
        "worker_batch_size",
        "worker_enabled",
        "worker_model",
        "worker_model_digest",
        "worker_poll_seconds",
        "worker_verifier_enabled",
        "worker_verifier_model",
        "worker_verifier_model_digest",
        "web_enabled",
        "web_host",
        "web_login_attempts",
        "web_login_window_seconds",
        "web_port",
        "web_public_enabled",
        "web_public_host",
        "web_public_hostname",
        "web_public_port",
        "web_request_limit",
        "web_request_window_seconds",
        "web_secure_cookies",
        "web_session_absolute_hours",
        "web_session_idle_minutes",
    }


@pytest.mark.parametrize("user_agent", ["anonymous bot", "@@@@@@@@@@", "Kalki a@b.test\nX: y"])
def test_sec_configuration_requires_identified_contact(user_agent: str) -> None:
    with pytest.raises(ValidationError, match="contact email"):
        Settings(sec_user_agent=user_agent, _env_file=None)


def test_sec_configuration_never_exceeds_official_rate_ceiling() -> None:
    with pytest.raises(ValidationError, match="less than or equal to 10"):
        Settings(sec_requests_per_second=10.1, _env_file=None)


def test_ownership_worker_requires_private_database_persistence(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="ownership worker requires PostgreSQL"):
        Settings(ownership_worker_enabled=True, _env_file=None)
    settings = Settings(
        ownership_worker_enabled=True,
        database_enabled=True,
        database_password_file=tmp_path / "database-password",
        _env_file=None,
    )
    assert settings.ownership_worker_enabled


def test_financing_worker_requires_private_database_persistence(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="financing worker requires PostgreSQL"):
        Settings(financing_worker_enabled=True, _env_file=None)
    settings = Settings(
        financing_worker_enabled=True,
        database_enabled=True,
        database_password_file=tmp_path / "database-password",
        _env_file=None,
    )
    assert settings.financing_worker_enabled


def test_accounting_worker_requires_private_database_persistence(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="accounting worker requires PostgreSQL"):
        Settings(accounting_worker_enabled=True, _env_file=None)
    settings = Settings(
        accounting_worker_enabled=True,
        database_enabled=True,
        database_password_file=tmp_path / "database-password",
        _env_file=None,
    )
    assert settings.accounting_worker_enabled


def test_discord_requires_secret_only_when_explicitly_enabled() -> None:
    with pytest.raises(ValidationError, match="require a webhook secret"):
        Settings(discord_enabled=True, _env_file=None)


def test_discord_intake_requires_private_bot_contract_when_enabled(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="bot token file"):
        Settings(discord_intake_enabled=True, _env_file=None)
    settings = Settings(
        discord_intake_enabled=True,
        discord_intake_bot_token_file=tmp_path / "discord-bot-token",
        discord_intake_channel_id="323456789012345678",
        discord_intake_results_channel_id="222222222222222222",
        discord_intake_allowlist=("223456789012345678",),
        _env_file=None,
    )
    assert settings.discord_intake_enabled
    assert settings.discord_intake_allowlist == ("223456789012345678",)


def test_discord_intake_rejects_invalid_allowlist_ids() -> None:
    with pytest.raises(ValidationError, match="stable snowflake"):
        Settings(discord_intake_allowlist=("display-name",), _env_file=None)


def test_discord_intake_requires_results_channel_and_normalizes_empty_values(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError, match="results channel ID"):
        Settings(
            discord_intake_enabled=True,
            discord_intake_bot_token_file=tmp_path / "discord-bot-token",
            discord_intake_channel_id="111111111111111111",
            discord_intake_allowlist=("222222222222222222",),
            _env_file=None,
        )

    settings = Settings(
        discord_intake_channel_id="",
        discord_intake_results_channel_id=" ",
        _env_file=None,
    )
    assert settings.discord_intake_channel_id is None
    assert settings.discord_intake_results_channel_id is None


def test_discord_webhook_is_validated_and_remains_redacted() -> None:
    token = "synthetic_test_token_1234567890"
    settings = Settings(
        discord_enabled=True,
        discord_webhook_url=SecretStr(
            f"https://discord.com/api/webhooks/123456789012345678/{token}"
        ),
        _env_file=None,
    )

    assert settings.discord_webhook_url is not None
    assert token not in repr(settings)
    assert token not in settings.model_dump_json()
    assert "**********" in settings.model_dump_json()


@pytest.mark.parametrize(
    "url",
    [
        f"http://discord.com/api/webhooks/{SYNTHETIC_WEBHOOK_ID}/{SYNTHETIC_WEBHOOK_TOKEN}",
        f"https://example.com/api/webhooks/{SYNTHETIC_WEBHOOK_ID}/{SYNTHETIC_WEBHOOK_TOKEN}",
        f"https://discord.com/api/webhooks/not-a-snowflake/{SYNTHETIC_WEBHOOK_TOKEN}",
        "https://discord.com/api/webhooks/123456789012345678/short",
        (
            f"https://discord.com/api/webhooks/{SYNTHETIC_WEBHOOK_ID}/"
            f"{SYNTHETIC_WEBHOOK_TOKEN}?wait=false"
        ),
    ],
)
def test_discord_rejects_unapproved_or_malformed_webhook_urls(url: str) -> None:
    with pytest.raises(ValidationError, match="approved Discord HTTPS endpoint"):
        Settings(discord_webhook_url=SecretStr(url), _env_file=None)


def test_web_interface_requires_argon2id_hash_only_when_enabled() -> None:
    with pytest.raises(ValidationError, match="requires one admin Argon2id hash source"):
        Settings(web_enabled=True, _env_file=None)
    with pytest.raises(ValidationError, match="must be an Argon2id encoded hash"):
        Settings(admin_password_hash=SecretStr("plaintext-password"), _env_file=None)


def test_web_configuration_is_loopback_only_and_redacts_password_hash() -> None:
    encoded = "$argon2id$v=19$m=1024,t=1,p=1$c2FsdHNhbHQ$hashvalue"
    settings = Settings(
        web_enabled=True,
        web_host="::1",
        admin_username="local-admin",
        admin_password_hash=SecretStr(encoded),
        _env_file=None,
    )

    assert settings.web_host == "::1"
    assert encoded not in repr(settings)
    assert encoded not in settings.model_dump_json()
    with pytest.raises(ValidationError, match="loopback"):
        Settings(web_host="0.0.0.0", _env_file=None)


def test_production_services_require_persistence_and_explicit_container_mode(
    tmp_path: Path,
) -> None:
    password_file = tmp_path / "database-password"
    password_file.write_text("synthetic-database-password", encoding="utf-8")

    with pytest.raises(ValidationError, match="PostgreSQL persistence"):
        Settings(
            environment=RuntimeEnvironment.PRODUCTION,
            web_enabled=True,
            admin_password_hash_file=tmp_path / "admin-hash",
            _env_file=None,
        )
    with pytest.raises(ValidationError, match="container-only"):
        Settings(web_host="0.0.0.0", _env_file=None)

    settings = Settings(
        environment=RuntimeEnvironment.PRODUCTION,
        containerized=True,
        web_enabled=True,
        web_host="0.0.0.0",
        web_public_enabled=True,
        web_public_host="0.0.0.0",
        admin_password_hash_file=tmp_path / "admin-hash",
        database_enabled=True,
        database_host="postgres",
        database_password_file=password_file,
        _env_file=None,
    )

    assert settings.web_public_hostname == "localhost"
    assert settings.database_host == "postgres"


@pytest.mark.parametrize(
    "hostname",
    ["*", "https://public.example", "user@public.example", "public.example/path"],
)
def test_public_hostname_rejects_broad_or_url_values(hostname: str) -> None:
    with pytest.raises(ValidationError, match="explicit DNS hostname"):
        Settings(web_public_hostname=hostname, _env_file=None)


def test_database_secret_source_and_pool_bounds_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="password secret file"):
        Settings(database_enabled=True, _env_file=None)
    with pytest.raises(ValidationError, match="must be absolute"):
        Settings(database_password_file=Path("relative-secret"), _env_file=None)
    with pytest.raises(ValidationError, match="minimum cannot exceed"):
        Settings(
            database_pool_minimum=5,
            database_pool_maximum=2,
            _env_file=None,
        )


def test_prospective_outcomes_require_private_persistence_and_api_key(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="PostgreSQL persistence"):
        Settings(prospective_outcomes_enabled=True, _env_file=None)
    with pytest.raises(ValidationError, match="Twelve Data API key"):
        Settings(
            prospective_outcomes_enabled=True,
            database_enabled=True,
            database_password_file=tmp_path / "database-password",
            _env_file=None,
        )
    settings = Settings(
        prospective_outcomes_enabled=True,
        twelve_data_api_key_file=tmp_path / "twelve-data-key",
        database_enabled=True,
        database_password_file=tmp_path / "database-password",
        _env_file=None,
    )
    assert settings.prospective_outcomes_enabled


@pytest.mark.parametrize("username", ["ab", "admin user", "admin\nheader", "x" * 65])
def test_admin_username_rejects_unsafe_values(username: str) -> None:
    with pytest.raises(ValidationError, match="safe identifier"):
        Settings(admin_username=username, _env_file=None)
