"""Private llama.cpp adapter used only by the isolated model-serving lab."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field

from kalki_market_intelligence.analysis.contracts import ModelRequest, ModelResponse
from kalki_market_intelligence.analysis.ollama import OllamaPerformanceSample


class LlamaCppProviderError(RuntimeError):
    """The isolated llama.cpp server could not produce a usable response."""


class _LlamaCppMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    content: str


class _LlamaCppChoice(BaseModel):
    model_config = ConfigDict(extra="ignore")
    finish_reason: str
    message: _LlamaCppMessage


class _LlamaCppUsage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)


class _LlamaCppTimings(BaseModel):
    model_config = ConfigDict(extra="ignore")
    prompt_ms: float = Field(default=0, ge=0)
    prompt_per_second: float | None = Field(default=None, ge=0)
    predicted_ms: float = Field(default=0, ge=0)
    predicted_per_second: float | None = Field(default=None, ge=0)


class _LlamaCppChatResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    model: str
    system_fingerprint: str
    choices: tuple[_LlamaCppChoice, ...] = Field(min_length=1, max_length=1)
    usage: _LlamaCppUsage
    timings: _LlamaCppTimings


def validate_llama_cpp_base_url(base_url: str) -> str:
    """Allow only loopback or the named, private benchmark container."""

    normalized = base_url.rstrip("/")
    parsed = urlsplit(normalized)
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("llama.cpp base URL has an invalid port") from error
    is_loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    is_private_service = parsed.hostname == "llama-server"
    if (
        parsed.scheme != "http"
        or not (is_loopback or is_private_service)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path
        or port is None
        or not 1_024 <= port <= 65_535
        or (is_private_service and port != 8_080)
    ):
        raise ValueError("llama.cpp base URL must use loopback or the private benchmark service")
    return normalized


def build_llama_cpp_payload(server_model: str, request: ModelRequest) -> dict[str, object]:
    """Build one no-tools, schema-constrained, non-streaming lab request."""

    return {
        "model": server_model,
        "messages": [
            {"role": "system", "content": request.system_prompt},
            {"role": "user", "content": request.user_prompt},
        ],
        "stream": False,
        "temperature": request.temperature,
        "seed": request.seed,
        "max_tokens": request.maximum_output_tokens,
        "response_format": {
            "type": "json_schema",
            "schema": request.output_schema,
        },
        # Current llama.cpp exposes both controls. The lab records a runtime as
        # incompatible if the model/template still spends the output budget on
        # reasoning instead of returning the required JSON contract.
        "chat_template_kwargs": {"enable_thinking": False},
        "reasoning_effort": "none",
        "reasoning_format": "deepseek",
    }


class LlamaCppModelProvider:
    """Benchmark-only provider for one digest-pinned private llama-server."""

    def __init__(
        self,
        *,
        logical_model: str,
        server_model: str,
        model_blob_sha256: str,
        expected_system_fingerprint: str,
        base_url: str = "http://127.0.0.1:8080",
        timeout_seconds: float = 300,
        maximum_response_bytes: int = 2_000_000,
    ) -> None:
        if not logical_model.strip() or len(logical_model) > 255:
            raise ValueError("llama.cpp logical model name must be non-empty and bounded")
        if not server_model.strip() or len(server_model) > 1_024:
            raise ValueError("llama.cpp server model name must be non-empty and bounded")
        if re.fullmatch(r"[0-9a-f]{64}", model_blob_sha256) is None:
            raise ValueError("llama.cpp model blob digest must be lowercase SHA-256")
        if re.fullmatch(r"[A-Za-z0-9._-]{3,128}", expected_system_fingerprint) is None:
            raise ValueError("llama.cpp system fingerprint must be a bounded safe identifier")
        if timeout_seconds <= 0 or timeout_seconds > 1_200:
            raise ValueError("llama.cpp timeout must be between 0 and 1200 seconds")
        if maximum_response_bytes < 1_000 or maximum_response_bytes > 10_000_000:
            raise ValueError("llama.cpp response limit is outside the permitted range")
        self._logical_model = logical_model.strip()
        self._server_model = server_model.strip()
        self._model_blob_sha256 = model_blob_sha256
        self._expected_system_fingerprint = expected_system_fingerprint
        self._base_url = validate_llama_cpp_base_url(base_url)
        self._timeout = timeout_seconds
        self._maximum_response_bytes = maximum_response_bytes
        self._performance_samples: list[OllamaPerformanceSample] = []

    @property
    def performance_samples(self) -> tuple[OllamaPerformanceSample, ...]:
        """Return content-free timing samples using the existing local-model receipt."""

        return tuple(self._performance_samples)

    def generate(self, request: ModelRequest) -> ModelResponse:
        payload = build_llama_cpp_payload(self._server_model, request)
        try:
            raw = self._request_json("POST", "/v1/chat/completions", payload=payload)
            response = _LlamaCppChatResponse.model_validate(raw)
            if response.model != self._server_model:
                raise ValueError("llama.cpp response model does not match the mounted model")
            if response.system_fingerprint != self._expected_system_fingerprint:
                raise ValueError("llama.cpp server fingerprint does not match the pinned runtime")
            choice = response.choices[0]
            if choice.finish_reason not in {"stop", "length"}:
                raise ValueError("llama.cpp returned an unsupported finish reason")
            timings = response.timings
            self._performance_samples.append(
                OllamaPerformanceSample(
                    total_seconds=(timings.prompt_ms + timings.predicted_ms) / 1_000,
                    load_seconds=0,
                    prompt_tokens=response.usage.prompt_tokens,
                    generated_tokens=response.usage.completion_tokens,
                    prompt_tokens_per_second=timings.prompt_per_second,
                    generated_tokens_per_second=timings.predicted_per_second,
                )
            )
            return ModelResponse(
                provider_name="llama.cpp-loopback",
                model_name=self._logical_model,
                model_digest=self._model_blob_sha256,
                content=choice.message.content,
                prompt_tokens=response.usage.prompt_tokens,
                generated_tokens=response.usage.completion_tokens,
            )
        except (HTTPError, URLError, TimeoutError, ValueError) as error:
            raise LlamaCppProviderError(
                f"local llama.cpp request failed: {type(error).__name__}"
            ) from error

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        encoded = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(  # noqa: S310 - constructor accepts private origins only
            f"{self._base_url}{path}",
            data=encoded,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=self._timeout) as response:  # noqa: S310
            content_length = response.headers.get("Content-Length")
            if content_length is not None and int(content_length) > self._maximum_response_bytes:
                raise ValueError("llama.cpp response exceeds declared size limit")
            body = response.read(self._maximum_response_bytes + 1)
        if len(body) > self._maximum_response_bytes:
            raise ValueError("llama.cpp response exceeds declared size limit")
        decoded: object = json.loads(body.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("llama.cpp returned a non-object response")
        return cast(dict[str, Any], decoded)
