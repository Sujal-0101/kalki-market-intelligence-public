"""Contract tests for swappable market-data providers and explicit data quality."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from threading import Barrier, Event, Lock
from uuid import UUID

import pytest
from pydantic import ValidationError

from kalki_market_intelligence.contracts.domain import CurrencyCode
from kalki_market_intelligence.providers.market_data.contracts import (
    BarRequest,
    BarSeries,
    CorporateActionRequest,
    CorporateActionSeries,
    DailyBar,
    FreshnessStatus,
    InstrumentKind,
    MarketInstrument,
    PriceAdjustment,
    ProviderAccessMode,
    ProviderCapabilities,
    VolumeAdjustment,
)
from kalki_market_intelligence.providers.market_data.offline import (
    CsvFixtureMarketDataProvider,
    MemoryMarketDataProvider,
)
from kalki_market_intelligence.providers.market_data.provider import (
    MarketDataProvider,
    MemoryCachingMarketDataProvider,
)

FIXTURE_ROOT = Path(__file__).parents[1] / "data/fixtures/market_data"
US_ID = UUID("11111111-1111-4111-8111-111111111111")
CA_ID = UUID("22222222-2222-4222-8222-222222222222")
BENCHMARK_ID = UUID("33333333-3333-4333-8333-333333333333")
CUTOFF = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def bar_request(
    instrument_id: UUID = US_ID,
    *,
    currency: CurrencyCode = CurrencyCode.US_DOLLAR,
    adjustment: PriceAdjustment = PriceAdjustment.UNADJUSTED,
    cutoff: datetime = CUTOFF,
    start: date = date(2026, 8, 17),
    end: date = date(2026, 8, 20),
    maximum_age: int = 172_800,
    volume_adjustment: VolumeAdjustment = VolumeAdjustment.UNADJUSTED,
) -> BarRequest:
    return BarRequest(
        instrument_id=instrument_id,
        start_date=start,
        end_date=end,
        currency=currency,
        adjustment=adjustment,
        volume_adjustment=volume_adjustment,
        knowledge_cutoff_at=cutoff,
        freshness_max_age_seconds=maximum_age,
    )


def memory_provider_from_fixture() -> MemoryMarketDataProvider:
    fixture = CsvFixtureMarketDataProvider(FIXTURE_ROOT)
    instruments = tuple(fixture.get_instrument(item) for item in (US_ID, CA_ID, BENCHMARK_ID))
    bars = (
        *fixture.get_daily_bars(bar_request()).bars,
        *fixture.get_daily_bars(bar_request(CA_ID, currency=CurrencyCode.CANADIAN_DOLLAR)).bars,
        *fixture.get_daily_bars(
            bar_request(
                CA_ID,
                currency=CurrencyCode.CANADIAN_DOLLAR,
                adjustment=PriceAdjustment.SPLIT_ADJUSTED,
                volume_adjustment=VolumeAdjustment.SPLIT_ADJUSTED,
            )
        ).bars,
        *fixture.get_daily_bars(bar_request(BENCHMARK_ID)).bars,
    )
    actions = (
        *fixture.get_corporate_actions(_action_request(US_ID)).actions,
        *fixture.get_corporate_actions(_action_request(CA_ID)).actions,
    )
    return MemoryMarketDataProvider(
        capabilities=fixture.capabilities,
        instruments=instruments,
        bars=bars,
        corporate_actions=actions,
    )


def _action_request(instrument_id: UUID) -> CorporateActionRequest:
    return CorporateActionRequest(
        instrument_id=instrument_id,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        knowledge_cutoff_at=CUTOFF,
    )


@pytest.fixture(params=["csv", "memory"])
def provider(request: pytest.FixtureRequest) -> MarketDataProvider:
    if request.param == "csv":
        return CsvFixtureMarketDataProvider(FIXTURE_ROOT)
    return memory_provider_from_fixture()


def test_swappable_providers_return_identical_canonical_bars(
    provider: MarketDataProvider,
) -> None:
    series = provider.get_daily_bars(bar_request())

    assert len(series.bars) == 4
    assert series.bars[0].open == Decimal("20.00")
    assert series.bars[-1].close == Decimal("22.80")
    assert series.quality.freshness_status is FreshnessStatus.CURRENT
    assert series.quality.row_count == 4
    assert all(bar.currency is CurrencyCode.US_DOLLAR for bar in series.bars)
    assert all(bar.adjustment is PriceAdjustment.UNADJUSTED for bar in series.bars)


def test_reference_and_benchmark_capabilities_are_explicit(
    provider: MarketDataProvider,
) -> None:
    benchmark = provider.get_instrument(BENCHMARK_ID)

    assert benchmark.kind is InstrumentKind.BENCHMARK
    assert provider.capabilities.supports_benchmarks is True
    assert provider.capabilities.requests_per_period is None
    assert provider.capabilities.request_period_seconds is None
    assert "synthetic" in provider.capabilities.license_reference.lower()


def test_raw_and_split_adjusted_series_never_mix(provider: MarketDataProvider) -> None:
    raw = provider.get_daily_bars(bar_request(CA_ID, currency=CurrencyCode.CANADIAN_DOLLAR))
    adjusted = provider.get_daily_bars(
        bar_request(
            CA_ID,
            currency=CurrencyCode.CANADIAN_DOLLAR,
            adjustment=PriceAdjustment.SPLIT_ADJUSTED,
            volume_adjustment=VolumeAdjustment.SPLIT_ADJUSTED,
        )
    )

    assert raw.bars[0].close == Decimal("10.20")
    assert adjusted.bars[0].close == Decimal("5.10")
    assert {bar.adjustment for bar in raw.bars} == {PriceAdjustment.UNADJUSTED}
    assert {bar.adjustment for bar in adjusted.bars} == {PriceAdjustment.SPLIT_ADJUSTED}
    assert {bar.volume_adjustment for bar in raw.bars} == {VolumeAdjustment.UNADJUSTED}
    assert {bar.volume_adjustment for bar in adjusted.bars} == {VolumeAdjustment.SPLIT_ADJUSTED}


def test_wrong_currency_fails_instead_of_converting(provider: MarketDataProvider) -> None:
    with pytest.raises(ValueError, match="currency"):
        provider.get_daily_bars(bar_request(CA_ID, currency=CurrencyCode.US_DOLLAR))


def test_knowledge_cutoff_excludes_future_available_rows(provider: MarketDataProvider) -> None:
    series = provider.get_daily_bars(bar_request(cutoff=datetime(2026, 8, 19, 12, 0, tzinfo=UTC)))

    assert [bar.session_date for bar in series.bars] == [
        date(2026, 8, 17),
        date(2026, 8, 18),
    ]
    assert all(bar.available_at <= series.request.knowledge_cutoff_at for bar in series.bars)


def test_stale_and_missing_data_are_explicit(provider: MarketDataProvider) -> None:
    stale = provider.get_daily_bars(
        bar_request(cutoff=datetime(2026, 8, 30, tzinfo=UTC), maximum_age=86_400)
    )
    missing = provider.get_daily_bars(bar_request(start=date(2025, 1, 1), end=date(2025, 1, 31)))

    assert stale.quality.freshness_status is FreshnessStatus.STALE
    assert [issue.code.value for issue in stale.quality.issues] == ["stale"]
    assert missing.quality.freshness_status is FreshnessStatus.NO_DATA
    assert missing.bars == ()
    assert [issue.code.value for issue in missing.quality.issues] == ["no_data"]


def test_corporate_actions_respect_availability_cutoff(provider: MarketDataProvider) -> None:
    available = provider.get_corporate_actions(_action_request(CA_ID))
    early_request = _action_request(CA_ID).model_copy(
        update={"knowledge_cutoff_at": datetime(2026, 8, 1, tzinfo=UTC)}
    )
    unavailable = provider.get_corporate_actions(early_request)

    assert len(available.actions) == 1
    assert available.actions[0].action_type == "split"
    assert unavailable.actions == ()


class CountingProvider:
    def __init__(self, wrapped: MarketDataProvider) -> None:
        self.wrapped = wrapped
        self.bar_calls = 0

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self.wrapped.capabilities

    def get_instrument(self, instrument_id: UUID) -> MarketInstrument:
        return self.wrapped.get_instrument(instrument_id)

    def get_daily_bars(self, request: BarRequest) -> BarSeries:
        self.bar_calls += 1
        return self.wrapped.get_daily_bars(request)

    def get_corporate_actions(self, request: CorporateActionRequest) -> CorporateActionSeries:
        return self.wrapped.get_corporate_actions(request)


def test_cache_reuses_until_ttl_then_refreshes() -> None:
    clock = [10.0]
    counted = CountingProvider(CsvFixtureMarketDataProvider(FIXTURE_ROOT))
    cached = MemoryCachingMarketDataProvider(
        counted,
        ttl_seconds=60,
        monotonic=lambda: clock[0],
    )

    first = cached.get_daily_bars(bar_request())
    second = cached.get_daily_bars(bar_request())
    clock[0] = 71.0
    third = cached.get_daily_bars(bar_request())

    assert first is second
    assert third == first
    assert counted.bar_calls == 2


class ConcurrentInstrumentProvider(CountingProvider):
    def __init__(self, wrapped: MarketDataProvider, barrier: Barrier | None = None) -> None:
        super().__init__(wrapped)
        self.barrier = barrier
        self.instrument_calls = 0
        self.started = Event()
        self.release = Event()
        self.lock = Lock()

    def get_instrument(self, instrument_id: UUID) -> MarketInstrument:
        with self.lock:
            self.instrument_calls += 1
        self.started.set()
        if self.barrier is not None:
            self.barrier.wait(timeout=2)
        else:
            assert self.release.wait(timeout=2)
        return self.wrapped.get_instrument(instrument_id)


def test_cache_allows_unrelated_provider_keys_to_load_concurrently() -> None:
    wrapped = ConcurrentInstrumentProvider(CsvFixtureMarketDataProvider(FIXTURE_ROOT), Barrier(2))
    cached = MemoryCachingMarketDataProvider(wrapped)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(cached.get_instrument, (US_ID, CA_ID)))
    assert tuple(item.instrument_id for item in results) == (US_ID, CA_ID)
    assert wrapped.instrument_calls == 2


def test_cache_single_flight_calls_provider_once_for_same_key() -> None:
    wrapped = ConcurrentInstrumentProvider(CsvFixtureMarketDataProvider(FIXTURE_ROOT))
    cached = MemoryCachingMarketDataProvider(wrapped)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = tuple(pool.submit(cached.get_instrument, US_ID) for _ in range(2))
        assert wrapped.started.wait(timeout=2)
        wrapped.release.set()
        results = tuple(future.result(timeout=2) for future in futures)
    assert results[0] is results[1]
    assert wrapped.instrument_calls == 1


def test_capability_rate_limit_fields_are_all_or_nothing() -> None:
    with pytest.raises(ValidationError, match="rate limit"):
        ProviderCapabilities(
            provider_name="invalid",
            access_mode=ProviderAccessMode.LIVE,
            license_reference="synthetic test",
            supported_adjustments=(PriceAdjustment.UNADJUSTED,),
            supported_volume_adjustments=(VolumeAdjustment.UNADJUSTED,),
            supports_corporate_actions=False,
            supports_benchmarks=False,
            requests_per_period=10,
        )


def test_invalid_ohlc_relationship_is_rejected() -> None:
    base = CsvFixtureMarketDataProvider(FIXTURE_ROOT).get_daily_bars(bar_request()).bars[0]

    with pytest.raises(ValidationError, match="high"):
        DailyBar.model_validate({**base.model_dump(), "high": Decimal("19.00")})
