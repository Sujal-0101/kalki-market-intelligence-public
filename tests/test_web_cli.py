"""Command tests for local-only web setup and serving."""

from __future__ import annotations

import pytest
from argon2 import PasswordHasher
from fastapi import FastAPI
from pydantic import SecretStr

from kalki_market_intelligence.config import Settings
from kalki_market_intelligence.web import cli


def test_password_hash_command_rejects_arguments_without_prompting(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "kalki_market_intelligence.web.cli.getpass.getpass",
        lambda _prompt: (_ for _ in ()).throw(AssertionError),
    )

    assert cli.hash_password_main(("plaintext-must-not-be-an-argument",)) == 2
    assert "accepts no password arguments" in capsys.readouterr().err


def test_password_hash_command_prints_only_an_argon2id_env_value(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    password = "synthetic-local-password"
    answers = iter((password, password))
    monkeypatch.setattr(
        "kalki_market_intelligence.web.cli.getpass.getpass", lambda _prompt: next(answers)
    )

    assert cli.hash_password_main(()) == 0
    output = capsys.readouterr().out.strip()

    assert output.startswith("KALKI_ADMIN_PASSWORD_HASH='$argon2id$v=19$")
    assert password not in output


def test_serve_command_passes_only_validated_loopback_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hasher = PasswordHasher(time_cost=1, memory_cost=1_024, parallelism=1)
    settings = Settings(
        web_enabled=True,
        web_host="127.0.0.1",
        web_port=8_765,
        admin_password_hash=SecretStr(hasher.hash("synthetic-local-password")),
        _env_file=None,
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "kalki_market_intelligence.web.cli.Settings.load", staticmethod(lambda: settings)
    )

    def fake_run(app: object, **kwargs: object) -> None:
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr("kalki_market_intelligence.web.cli.uvicorn.run", fake_run)

    assert cli.serve_main() == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8_765
    assert captured["proxy_headers"] is False
    assert captured["forwarded_allow_ips"] == ""
    assert captured["server_header"] is False


def test_public_runner_trusts_proxy_headers_only_on_its_private_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(app: object, **kwargs: object) -> None:
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr("kalki_market_intelligence.web.cli.uvicorn.run", fake_run)
    app = FastAPI()
    cli._run(app, host="0.0.0.0", port=8_001, trust_proxy_headers=True)

    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 8_001
    assert captured["proxy_headers"] is True
    assert captured["forwarded_allow_ips"] == "*"
    assert captured["server_header"] is False
