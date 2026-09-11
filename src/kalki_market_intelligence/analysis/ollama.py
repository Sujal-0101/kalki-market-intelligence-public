"""Loopback-only Ollama adapter for schema-constrained analyst output."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict

from kalki_market_intelligence.analysis.contracts import ModelRequest, ModelResponse


class ModelProviderError(RuntimeError):
    """The configured local model provider could not produce a usable response."""


class _OllamaMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    content: str


class _OllamaChatResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    model: str
    message: _OllamaMessage
    total_duration: int = 0
    load_duration: int = 0
    prompt_eval_count: int = 0
    prompt_eval_duration: int = 0
    eval_count: int = 0
    eval_duration: int = 0


class OllamaPerformanceSample(BaseModel):
    """One provider-call performance receipt reported by local Ollama."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    total_seconds: float
    load_seconds: float
    prompt_tokens: int
    generated_tokens: int
    prompt_tokens_per_second: float | None
    generated_tokens_per_second: float | None


class OllamaModelProvider:
    """Minimal no-tools adapter restricted to an uncredentialed loopback origin."""

    def __init__(
        self,
        *,
        model: str = "qwen3:4b",
        base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: float = 240,
        maximum_response_bytes: int = 2_000_000,
        expected_digest: str | None = None,
        keep_alive: str = "10m",
    ) -> None:
        normalized_model = model.strip()
        if not normalized_model or len(normalized_model) > 255:
            raise ValueError("Ollama model name must be non-empty and bounded")
        if timeout_seconds <= 0 or timeout_seconds > 1_200:
            raise ValueError("Ollama timeout must be between 0 and 1200 seconds")
        if maximum_response_bytes < 1_000 or maximum_response_bytes > 10_000_000:
            raise ValueError("Ollama response limit is outside the permitted range")
        if expected_digest is not None and re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None:
            raise ValueError("Ollama expected digest must be lowercase SHA-256")
        if re.fullmatch(r"(?:0|[1-9][0-9]{0,3}[smh])", keep_alive) is None:
            raise ValueError("Ollama keep-alive must be zero or a bounded duration")
        self._model = normalized_model
        self._base_url = _validate_private_base_url(base_url)
        self._timeout = timeout_seconds
        self._maximum_response_bytes = maximum_response_bytes
        self._expected_digest = expected_digest
        self._keep_alive = keep_alive
        self._model_digest: str | None = None
        self._performance_samples: list[OllamaPerformanceSample] = []

    @property
    def performance_samples(self) -> tuple[OllamaPerformanceSample, ...]:
        """Return immutable timing samples without exposing prompts or generated text."""

        return tuple(self._performance_samples)

    def generate(self, request: ModelRequest) -> ModelResponse:
        if self._expected_digest is not None and self._model_digest is None:
            try:
                digest = self._load_model_digest()
            except (HTTPError, URLError, TimeoutError, ValueError) as error:
                raise ModelProviderError(
                    f"local Ollama digest check failed: {type(error).__name__}"
                ) from error
            if digest != self._expected_digest:
                raise ModelProviderError("configured Ollama tag does not match its pinned digest")
            self._model_digest = digest
        payload: dict[str, object] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "stream": False,
            "think": False,
            "format": request.output_schema,
            "keep_alive": self._keep_alive,
            "options": {
                "temperature": request.temperature,
                "seed": request.seed,
                "num_ctx": request.context_tokens,
                "num_predict": request.maximum_output_tokens,
            },
        }
        try:
            raw = self._request_json("POST", "/api/chat", payload=payload)
            response = _OllamaChatResponse.model_validate(raw)
            if response.model not in {self._model, f"{self._model}:latest"}:
                raise ValueError("Ollama response model does not match the configured model")
            digest = self._model_digest or self._load_model_digest()
            self._model_digest = digest
            self._performance_samples.append(
                OllamaPerformanceSample(
                    total_seconds=response.total_duration / 1_000_000_000,
                    load_seconds=response.load_duration / 1_000_000_000,
                    prompt_tokens=response.prompt_eval_count,
                    generated_tokens=response.eval_count,
                    prompt_tokens_per_second=_token_rate(
                        response.prompt_eval_count, response.prompt_eval_duration
                    ),
                    generated_tokens_per_second=_token_rate(
                        response.eval_count, response.eval_duration
                    ),
                )
            )
            return ModelResponse(
                provider_name="ollama-loopback",
                model_name=response.model,
                model_digest=digest,
                content=response.message.content,
                prompt_tokens=response.prompt_eval_count,
                generated_tokens=response.eval_count,
            )
        except (HTTPError, URLError, TimeoutError, ValueError) as error:
            raise ModelProviderError(
                f"local Ollama request failed: {type(error).__name__}"
            ) from error

    def unload(self) -> None:
        """Ask private Ollama to release this model before loading another model."""

        try:
            self._request_json(
                "POST",
                "/api/generate",
                payload={"model": self._model, "keep_alive": 0},
            )
        except (HTTPError, URLError, TimeoutError, ValueError) as error:
            raise ModelProviderError(
                f"local Ollama unload failed: {type(error).__name__}"
            ) from error

    def _load_model_digest(self) -> str:
        tags = self._request_json("GET", "/api/tags")
        models = tags.get("models")
        if not isinstance(models, list):
            raise ValueError("Ollama tags response has no model list")
        selected = next(
            (
                item
                for item in models
                if isinstance(item, dict)
                and item.get("name") in {self._model, f"{self._model}:latest"}
            ),
            None,
        )
        if selected is None or not isinstance(selected.get("digest"), str):
            raise ValueError("configured Ollama model digest is unavailable")
        return cast(str, selected["digest"])

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        encoded = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(  # noqa: S310 - constructor accepts loopback origins only
            f"{self._base_url}{path}",
            data=encoded,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=self._timeout) as response:  # noqa: S310 - loopback only
            content_length = response.headers.get("Content-Length")
            if content_length is not None and int(content_length) > self._maximum_response_bytes:
                raise ValueError("Ollama response exceeds declared size limit")
            body = response.read(self._maximum_response_bytes + 1)
        if len(body) > self._maximum_response_bytes:
            raise ValueError("Ollama response exceeds declared size limit")
        decoded: object = json.loads(body.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("Ollama returned a non-object response")
        return cast(dict[str, Any], decoded)


def _validate_private_base_url(base_url: str) -> str:
    """Allow only loopback or the named private Compose model service."""

    normalized = base_url.rstrip("/")
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
        or parsed.query
        or parsed.fragment
        or parsed.path
        or port not in {None, 11434}
    ):
        raise ValueError("Ollama base URL must use loopback or the private Compose model service")
    return normalized


def _token_rate(tokens: int, duration_nanoseconds: int) -> float | None:
    if tokens <= 0 or duration_nanoseconds <= 0:
        return None
    return tokens / (duration_nanoseconds / 1_000_000_000)
