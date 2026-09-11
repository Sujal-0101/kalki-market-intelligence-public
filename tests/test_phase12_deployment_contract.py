"""Static safety contract for the production and deferred exposure manifests."""

from __future__ import annotations

from pathlib import Path

import pytest

from kalki_market_intelligence.database import read_secret_file

ROOT = Path(__file__).parents[1]


def test_production_manifest_keeps_private_services_private() -> None:
    manifest = (ROOT / "compose.production.yaml").read_text(encoding="utf-8")
    assert "127.0.0.1:8000:8000" in manifest
    assert "127.0.0.1:8001:8001" in manifest
    postgres_block = manifest.split("  postgres:", 1)[1].split("  admin:", 1)[0]
    assert "ports:" not in postgres_block
    admin_block = manifest.split("  admin:", 1)[1].split("  public:", 1)[0]
    assert "read_only: true" in admin_block
    assert "cap_drop: [ALL]" in admin_block
    public_block = manifest.split("  public:", 1)[1].split("\nnetworks:", 1)[0]
    assert "admin_password_hash" not in public_block
    assert "command: [kalki-serve-public]" in public_block
    assert 'KALKI_WEB_PUBLIC_HOSTNAME: "${KALKI_WEB_PUBLIC_HOSTNAME:-localhost}"' in public_block
    assert "read_only: true" in public_block
    assert "cap_drop: [ALL]" in public_block


def test_cloudflare_manifest_is_pinned_guarded_and_public_only() -> None:
    manifest = (ROOT / "compose.cloudflare.yaml").read_text(encoding="utf-8")
    assert "cloudflare/cloudflared:2026.7.2@sha256:" in manifest
    assert "profiles: [exposure]" in manifest
    assert "--token-file" in manifest
    assert "/run/secrets/cloudflare_tunnel_token" in manifest
    assert "- public_connector" in manifest
    assert "database" not in manifest
    assert "admin" not in manifest
    assert "ports:" not in manifest
    assert "127.0.0.1:20241" in manifest
    assert "- ready" in manifest


def test_container_build_is_digest_pinned_and_non_root() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert dockerfile.count("@sha256:") == 2
    assert "USER 10001:10001" in dockerfile


def test_live_worker_and_local_model_have_no_public_network_surface() -> None:
    manifest = (ROOT / "compose.production.yaml").read_text(encoding="utf-8")
    ollama_block = manifest.split("  ollama:", 1)[1].split("  worker:", 1)[0]
    worker_block = manifest.split("  worker:", 1)[1].split("  ownership-worker:", 1)[0]

    assert "ports:" not in ollama_block
    assert "ports:" not in worker_block
    assert 'OLLAMA_NO_CLOUD: "1"' in ollama_block
    assert 'OLLAMA_NUM_PARALLEL: "1"' in ollama_block
    assert "OLLAMA_LIBRARY_PATH: /usr/local/lib/ollama" in ollama_block
    assert "KALKI_OLLAMA_LIB" in ollama_block
    assert "cpus: 6.0" in ollama_block
    assert "user:" in ollama_block
    assert "- analyst" in ollama_block
    assert "- database" in worker_block
    assert "- analyst" in worker_block
    assert "- research_egress" in worker_block
    assert "local_environment" in worker_block
    assert 'KALKI_WORKER_VERIFIER_ENABLED: "false"' in worker_block
    assert "public_connector" not in worker_block


def test_discord_intake_is_private_non_root_and_capability_free() -> None:
    manifest = (ROOT / "compose.production.yaml").read_text(encoding="utf-8")
    block = manifest.split("  discord-intake:", 1)[1].split("\nnetworks:", 1)[0]
    assert 'user: "1000:1000"' in block
    assert "read_only: true" in block
    assert "cap_drop: [ALL]" in block
    assert "no-new-privileges:true" in block
    assert "healthcheck:" in block
    assert "ports:" not in block
    assert "public_connector" not in block
    assert "analyst" not in block
    assert "profiles: [discord]" in block
    assert "${KALKI_DISCORD_INTAKE_CHANNEL_ID:-}" in block
    assert "KALKI_DISCORD_INTAKE_RESULTS_CHANNEL_ID:" in block
    assert "${KALKI_DISCORD_INTAKE_ALLOWLIST:-[]}" in block


def test_ownership_worker_is_private_bounded_and_model_free() -> None:
    manifest = (ROOT / "compose.production.yaml").read_text(encoding="utf-8")
    block = manifest.split("  ownership-worker:", 1)[1].split("  financing-worker:", 1)[0]
    assert "command: [kalki-ownership-worker]" in block
    assert 'KALKI_OWNERSHIP_WORKER_BATCH_SIZE: "2"' in block
    assert 'KALKI_OWNERSHIP_WORKER_MAXIMUM_BACKLOG: "250"' in block
    assert "- database" in block and "- research_egress" in block
    assert "analyst" not in block
    assert "public_connector" not in block
    assert "discord" not in block.casefold()
    assert "ports:" not in block


def test_secret_reader_accepts_only_bounded_absolute_regular_file(
    tmp_path: Path,
) -> None:
    secret = tmp_path / "secret"
    secret.write_text("valid-secret\n", encoding="utf-8")
    assert read_secret_file(secret, label="test") == "valid-secret"

    with pytest.raises(ValueError, match="absolute"):
        read_secret_file(Path("relative"), label="test")

    link = tmp_path / "link"
    link.symlink_to(secret)
    with pytest.raises(ValueError, match="non-symlink"):
        read_secret_file(link, label="test")

    secret.write_text("first\nsecond\n", encoding="utf-8")
    with pytest.raises(ValueError, match="one non-empty line"):
        read_secret_file(secret, label="test")

    secret.write_text("x" * 4_097, encoding="utf-8")
    with pytest.raises(ValueError, match="4096"):
        read_secret_file(secret, label="test")
