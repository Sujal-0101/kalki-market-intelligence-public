"""Replaceable market-data provider protocol and cache decorator."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast
from uuid import UUID

from kalki_market_intelligence.providers.market_data.contracts import (
    BarRequest,
    BarSeries,
    CorporateActionRequest,
    CorporateActionSeries,
    MarketInstrument,
    ProviderCapabilities,
)


class MarketDataNotFound(LookupError):
    """The provider has no record for the requested instrument or series."""


class MarketDataProvider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...

    def get_instrument(self, instrument_id: UUID) -> MarketInstrument: ...

    def get_daily_bars(self, request: BarRequest) -> BarSeries: ...

    def get_corporate_actions(self, request: CorporateActionRequest) -> CorporateActionSeries: ...


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    expires_at: float
    value: object


class MemoryCachingMarketDataProvider:
    """Bounded-time process-local cache that never changes provider semantics."""

    def __init__(
        self,
        provider: MarketDataProvider,
        *,
        ttl_seconds: float = 60.0,
        maximum_entries: int = 1_024,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("cache TTL must be positive")
        if maximum_entries < 1:
            raise ValueError("cache maximum entries must be positive")
        self._provider = provider
        self._ttl_seconds = ttl_seconds
        self._maximum_entries = maximum_entries
        self._monotonic = monotonic
        self._cache: dict[str, _CacheEntry] = {}
        self._inflight: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._provider.capabilities

    def get_instrument(self, instrument_id: UUID) -> MarketInstrument:
        return self._get_or_load(
            f"instrument:{instrument_id}",
            lambda: self._provider.get_instrument(instrument_id),
            MarketInstrument,
        )

    def get_daily_bars(self, request: BarRequest) -> BarSeries:
        return self._get_or_load(
            f"bars:{request.model_dump_json()}",
            lambda: self._provider.get_daily_bars(request),
            BarSeries,
        )

    def get_corporate_actions(self, request: CorporateActionRequest) -> CorporateActionSeries:
        return self._get_or_load(
            f"actions:{request.model_dump_json()}",
            lambda: self._provider.get_corporate_actions(request),
            CorporateActionSeries,
        )

    def _get_or_load[ValueT: (MarketInstrument, BarSeries, CorporateActionSeries)](
        self,
        key: str,
        loader: Callable[[], ValueT],
        expected_type: type[ValueT],
    ) -> ValueT:
        while True:
            with self._lock:
                now = self._monotonic()
                cached = self._cache.get(key)
                if cached is not None and cached.expires_at > now:
                    return cast(ValueT, cached.value)
                waiting = self._inflight.get(key)
                if waiting is None:
                    waiting = threading.Event()
                    self._inflight[key] = waiting
                    break
            waiting.wait()
        try:
            value = loader()
            if not isinstance(value, expected_type):
                raise TypeError("market-data provider returned an unexpected contract")
            with self._lock:
                now = self._monotonic()
                expired = tuple(
                    cached_key
                    for cached_key, entry in self._cache.items()
                    if entry.expires_at <= now
                )
                for cached_key in expired:
                    self._cache.pop(cached_key)
                if len(self._cache) >= self._maximum_entries:
                    self._cache.pop(next(iter(self._cache)))
                self._cache[key] = _CacheEntry(now + self._ttl_seconds, value)
            return value
        finally:
            with self._lock:
                completed = self._inflight.pop(key)
                completed.set()
