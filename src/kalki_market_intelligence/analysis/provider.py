"""Replaceable model-provider interface and deterministic test implementation."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from kalki_market_intelligence.analysis.contracts import ModelRequest, ModelResponse


class ModelProvider(Protocol):
    def generate(self, request: ModelRequest) -> ModelResponse: ...


class SequenceModelProvider:
    """Return predeclared raw responses in order for deterministic pipeline tests."""

    def __init__(
        self,
        responses: Iterable[str],
        *,
        model_name: str = "fixture-model",
        model_digest: str | None = None,
    ) -> None:
        self._responses = iter(responses)
        self._model_name = model_name
        self._model_digest = model_digest
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        try:
            content = next(self._responses)
        except StopIteration as error:
            raise RuntimeError("fake model provider has no response remaining") from error
        return ModelResponse(
            provider_name="deterministic-sequence",
            model_name=self._model_name,
            model_digest=self._model_digest,
            content=content,
        )
