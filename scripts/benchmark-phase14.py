#!/usr/bin/env python3
"""Repeatable offline microbenchmarks used for Phase 14 optimization evidence."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import median
from time import perf_counter, sleep
from uuid import UUID

from kalki_market_intelligence.backtesting import evaluate_dataset, load_dataset
from kalki_market_intelligence.providers.market_data.contracts import (
    BarRequest,
    BarSeries,
    CorporateActionRequest,
    CorporateActionSeries,
    MarketInstrument,
    ProviderCapabilities,
)
from kalki_market_intelligence.providers.market_data.offline import CsvFixtureMarketDataProvider
from kalki_market_intelligence.providers.market_data.provider import (
    MemoryCachingMarketDataProvider,
)

ROOT = Path(__file__).parents[1]


class DelayedFixtureProvider:
    """Controlled latency around wholly synthetic offline data."""

    def __init__(self, delay_seconds: float) -> None:
        self._wrapped = CsvFixtureMarketDataProvider(ROOT / "data/fixtures/market_data")
        self._delay_seconds = delay_seconds

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._wrapped.capabilities

    def get_instrument(self, instrument_id: UUID) -> MarketInstrument:
        sleep(self._delay_seconds)
        return self._wrapped.get_instrument(instrument_id)

    def get_daily_bars(self, request: BarRequest) -> BarSeries:
        sleep(self._delay_seconds)
        return self._wrapped.get_daily_bars(request)

    def get_corporate_actions(self, request: CorporateActionRequest) -> CorporateActionSeries:
        sleep(self._delay_seconds)
        return self._wrapped.get_corporate_actions(request)


def run(repetitions: int) -> dict[str, object]:
    manifest = json.loads(
        (ROOT / "data/fixtures/market_data/manifest.json").read_text(encoding="utf-8")
    )
    instrument_ids = tuple(UUID(item["instrument_id"]) for item in manifest["instruments"])
    provider = DelayedFixtureProvider(0.02)
    cache_seconds: list[float] = []
    for _ in range(repetitions):
        cache = MemoryCachingMarketDataProvider(provider)
        started = perf_counter()
        with ThreadPoolExecutor(max_workers=len(instrument_ids)) as pool:
            tuple(pool.map(cache.get_instrument, instrument_ids))
        cache_seconds.append(perf_counter() - started)

    dataset = load_dataset(ROOT / "data/fixtures/backtesting/phase13_synthetic.json")
    started = perf_counter()
    for _ in range(100):
        evaluate_dataset(dataset)
    backtest_seconds = perf_counter() - started
    return {
        "schema_version": "1.0.0",
        "fixture_only": True,
        "cache": {
            "independent_requests": len(instrument_ids),
            "provider_delay_seconds_each": 0.02,
            "repetitions": repetitions,
            "median_wall_seconds": median(cache_seconds),
            "all_wall_seconds": cache_seconds,
        },
        "backtest_100_reports_wall_seconds": backtest_seconds,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=5, choices=range(3, 31))
    args = parser.parse_args()
    print(json.dumps(run(args.repetitions), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
