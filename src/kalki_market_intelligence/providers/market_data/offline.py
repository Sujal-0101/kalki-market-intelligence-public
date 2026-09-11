"""Zero-cost offline market-data providers for deterministic development."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Literal
from uuid import UUID

from kalki_market_intelligence.contracts.common import ContractModel
from kalki_market_intelligence.providers.market_data.contracts import (
    BarRequest,
    BarSeries,
    CorporateAction,
    CorporateActionRequest,
    CorporateActionSeries,
    DailyBar,
    FreshnessStatus,
    MarketInstrument,
    ProviderAccessMode,
    ProviderCapabilities,
    QualityIssue,
    QualityIssueCode,
    QualityMetadata,
)
from kalki_market_intelligence.providers.market_data.provider import MarketDataNotFound

EXPECTED_BAR_COLUMNS = {
    "instrument_id",
    "session_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "currency",
    "adjustment",
    "volume_adjustment",
    "available_at",
    "retrieved_at",
    "source_record_id",
    "source_content_sha256",
}


class FixtureManifest(ContractModel):
    schema_version: Literal["1"]
    bars_file: Literal["daily-bars.csv"]
    capabilities: ProviderCapabilities
    instruments: tuple[MarketInstrument, ...]
    corporate_actions: tuple[CorporateAction, ...]


class MemoryMarketDataProvider:
    """Immutable in-memory implementation useful for adapters and contract tests."""

    def __init__(
        self,
        *,
        capabilities: ProviderCapabilities,
        instruments: Iterable[MarketInstrument],
        bars: Iterable[DailyBar],
        corporate_actions: Iterable[CorporateAction] = (),
    ) -> None:
        self._capabilities = capabilities
        instrument_records = tuple(instruments)
        self._instruments = {item.instrument_id: item for item in instrument_records}
        self._bars = tuple(bars)
        self._actions = tuple(corporate_actions)
        if len(self._instruments) != len(instrument_records):
            raise ValueError("instrument IDs must be unique")
        bar_keys: set[tuple[UUID, date, object, object, object]] = set()
        for bar in self._bars:
            if bar.instrument_id not in self._instruments:
                raise ValueError("bar references an unknown instrument")
            instrument = self._instruments[bar.instrument_id]
            if bar.currency is not instrument.currency:
                raise ValueError("bar currency does not match instrument currency")
            if not instrument.active_from <= bar.session_date <= (instrument.active_to or date.max):
                raise ValueError("bar session is outside instrument active dates")
            key = (
                bar.instrument_id,
                bar.session_date,
                bar.currency,
                bar.adjustment,
                bar.volume_adjustment,
            )
            if key in bar_keys:
                raise ValueError("bar keys must be unique")
            bar_keys.add(key)
        for action in self._actions:
            if action.instrument_id not in self._instruments:
                raise ValueError("corporate action references an unknown instrument")
            instrument = self._instruments[action.instrument_id]
            if (
                not instrument.active_from
                <= action.effective_date
                <= (instrument.active_to or date.max)
            ):
                raise ValueError("corporate action is outside instrument active dates")

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def get_instrument(self, instrument_id: UUID) -> MarketInstrument:
        try:
            return self._instruments[instrument_id]
        except KeyError as error:
            raise MarketDataNotFound(f"instrument not found: {instrument_id}") from error

    def get_daily_bars(self, request: BarRequest) -> BarSeries:
        instrument = self.get_instrument(request.instrument_id)
        if instrument.currency is not request.currency:
            raise ValueError("requested currency does not match instrument currency")
        if request.adjustment not in self.capabilities.supported_adjustments:
            raise ValueError("requested adjustment is not supported by provider")
        if request.volume_adjustment not in self.capabilities.supported_volume_adjustments:
            raise ValueError("requested volume adjustment is not supported by provider")
        bars = tuple(
            sorted(
                (
                    bar
                    for bar in self._bars
                    if bar.instrument_id == request.instrument_id
                    and request.start_date <= bar.session_date <= request.end_date
                    and bar.currency is request.currency
                    and bar.adjustment is request.adjustment
                    and bar.volume_adjustment is request.volume_adjustment
                    and bar.available_at <= request.knowledge_cutoff_at
                    and bar.retrieved_at <= request.knowledge_cutoff_at
                ),
                key=lambda item: item.session_date,
            )
        )
        return BarSeries(
            request=request,
            bars=bars,
            quality=_quality_for_bars(self.capabilities, request, bars),
        )

    def get_corporate_actions(self, request: CorporateActionRequest) -> CorporateActionSeries:
        self.get_instrument(request.instrument_id)
        if not self.capabilities.supports_corporate_actions:
            raise ValueError("provider does not support corporate actions")
        actions = tuple(
            sorted(
                (
                    action
                    for action in self._actions
                    if action.instrument_id == request.instrument_id
                    and request.start_date <= action.effective_date <= request.end_date
                    and action.available_at <= request.knowledge_cutoff_at
                    and action.retrieved_at <= request.knowledge_cutoff_at
                ),
                key=lambda item: (item.effective_date, item.action_id),
            )
        )
        return CorporateActionSeries(
            request=request,
            actions=actions,
            quality=_quality_for_actions(self.capabilities, request, actions),
        )


class CsvFixtureMarketDataProvider(MemoryMarketDataProvider):
    """Read a closed manifest plus exact-decimal CSV bars from local fixtures."""

    def __init__(self, fixture_root: Path) -> None:
        manifest = FixtureManifest.model_validate_json(
            (fixture_root / "manifest.json").read_text(encoding="utf-8")
        )
        if manifest.capabilities.access_mode is not ProviderAccessMode.OFFLINE_FIXTURE:
            raise ValueError("CSV fixture provider requires offline_fixture access mode")
        bars_path = fixture_root / manifest.bars_file
        with bars_path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if set(reader.fieldnames or ()) != EXPECTED_BAR_COLUMNS:
                raise ValueError("daily bar CSV columns do not match the canonical fixture schema")
            bars = tuple(DailyBar.model_validate(row) for row in reader)
        super().__init__(
            capabilities=manifest.capabilities,
            instruments=manifest.instruments,
            bars=bars,
            corporate_actions=manifest.corporate_actions,
        )


def _quality_for_bars(
    capabilities: ProviderCapabilities,
    request: BarRequest,
    bars: tuple[DailyBar, ...],
) -> QualityMetadata:
    if not bars:
        return QualityMetadata(
            provider_name=capabilities.provider_name,
            license_reference=capabilities.license_reference,
            evaluated_at=request.knowledge_cutoff_at,
            freshness_status=FreshnessStatus.NO_DATA,
            row_count=0,
            coverage_start=None,
            coverage_end=None,
            latest_available_at=None,
            issues=(QualityIssue(code=QualityIssueCode.NO_DATA, detail="no matching bars"),),
        )
    latest_available = max(bar.available_at for bar in bars)
    age_seconds = (request.knowledge_cutoff_at - latest_available).total_seconds()
    stale = age_seconds > request.freshness_max_age_seconds
    issues = (
        (QualityIssue(code=QualityIssueCode.STALE, detail="latest bar exceeds freshness limit"),)
        if stale
        else ()
    )
    return QualityMetadata(
        provider_name=capabilities.provider_name,
        license_reference=capabilities.license_reference,
        evaluated_at=request.knowledge_cutoff_at,
        freshness_status=FreshnessStatus.STALE if stale else FreshnessStatus.CURRENT,
        row_count=len(bars),
        coverage_start=bars[0].session_date,
        coverage_end=bars[-1].session_date,
        latest_available_at=latest_available,
        issues=issues,
    )


def _quality_for_actions(
    capabilities: ProviderCapabilities,
    request: CorporateActionRequest,
    actions: tuple[CorporateAction, ...],
) -> QualityMetadata:
    latest_available = max((action.available_at for action in actions), default=None)
    return QualityMetadata(
        provider_name=capabilities.provider_name,
        license_reference=capabilities.license_reference,
        evaluated_at=request.knowledge_cutoff_at,
        freshness_status=FreshnessStatus.CURRENT,
        row_count=len(actions),
        coverage_start=min((action.effective_date for action in actions), default=None),
        coverage_end=max((action.effective_date for action in actions), default=None),
        latest_available_at=latest_available,
        issues=(),
    )
