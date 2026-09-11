"""Tests for the private llama.cpp model-serving lab boundary."""

from __future__ import annotations

import json
from typing import Any

import pytest

from kalki_market_intelligence.analysis.contracts import ModelRequest
from kalki_market_intelligence.analysis.llama_cpp import (
    LlamaCppModelProvider,
    LlamaCppProviderError,
    build_llama_cpp_payload,
    validate_llama_cpp_base_url,
)


def request() -> ModelRequest:
    return ModelRequest(
        system_prompt="Return JSON.",
        user_prompt="Use the supplied evidence only.",
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["status"],
            "properties": {"status": {"type": "string", "enum": ["ok"]}},
        },
    )


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("http://127.0.0.1:18082/", "http://127.0.0.1:18082"),
        ("http://localhost:8080", "http://localhost:8080"),
        ("http://[::1]:18082", "http://[::1]:18082"),
        ("http://llama-server:8080", "http://llama-server:8080"),
    ],
)
def test_base_url_accepts_only_loopback_or_private_service(base_url: str, expected: str) -> None:
    assert validate_llama_cpp_base_url(base_url) == expected


@pytest.mark.parametrize(
    "base_url",
    [
        "https://127.0.0.1:8080",
        "http://example.com:8080",
        "http://127.0.0.1:8080/v1",
        "http://user:secret@127.0.0.1:8080",
        "http://llama-server:8081",
        "http://127.0.0.1:not-a-port",
    ],
)
def test_base_url_rejects_public_credentialed_or_ambiguous_origins(base_url: str) -> None:
    with pytest.raises(ValueError, match="llama.cpp base URL"):
        validate_llama_cpp_base_url(base_url)


def test_payload_is_no_tools_schema_constrained_and_requests_no_thinking() -> None:
    payload = build_llama_cpp_payload("/models/qwen3-4b.gguf", request())

    assert payload["model"] == "/models/qwen3-4b.gguf"
    assert payload["messages"] == [
        {"role": "system", "content": "Return JSON."},
        {"role": "user", "content": "Use the supplied evidence only."},
    ]
    assert payload["stream"] is False
    assert payload["temperature"] == 0
    assert payload["seed"] == 42
    assert payload["max_tokens"] == 768
    assert payload["response_format"] == {
        "type": "json_schema",
        "schema": request().output_schema,
    }
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert payload["reasoning_effort"] == "none"
    assert "tools" not in payload


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._body = json.dumps(payload).encode()
        self.headers = {"Content-Length": str(len(self._body))}

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, maximum_bytes: int) -> bytes:
        return self._body[:maximum_bytes]


def provider() -> LlamaCppModelProvider:
    return LlamaCppModelProvider(
        logical_model="qwen3:4b",
        server_model="/models/qwen3-4b.gguf",
        model_blob_sha256="a" * 64,
        expected_system_fingerprint="b10689-test",
        base_url="http://llama-server:8080",
    )


def response_payload(*, fingerprint: str = "b10689-test") -> dict[str, Any]:
    return {
        "model": "/models/qwen3-4b.gguf",
        "system_fingerprint": fingerprint,
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": '{"status":"ok"}',
                    "reasoning_content": "discard this private reasoning",
                },
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3},
        "timings": {
            "prompt_ms": 1_000,
            "prompt_per_second": 10,
            "predicted_ms": 600,
            "predicted_per_second": 5,
        },
    }


def test_provider_returns_only_final_content_and_records_timing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "kalki_market_intelligence.analysis.llama_cpp.urlopen",
        lambda *_args, **_kwargs: FakeResponse(response_payload()),
    )
    model_provider = provider()

    response = model_provider.generate(request())

    assert response.content == '{"status":"ok"}'
    assert "reasoning" not in response.content
    assert response.model_digest == "a" * 64
    assert response.prompt_tokens == 10
    assert response.generated_tokens == 3
    assert model_provider.performance_samples[0].total_seconds == 1.6
    assert model_provider.performance_samples[0].generated_tokens_per_second == 5


def test_provider_fails_closed_on_runtime_fingerprint_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "kalki_market_intelligence.analysis.llama_cpp.urlopen",
        lambda *_args, **_kwargs: FakeResponse(response_payload(fingerprint="wrong-runtime")),
    )

    with pytest.raises(LlamaCppProviderError, match="local llama.cpp request failed"):
        provider().generate(request())
