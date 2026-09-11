"""Real exchange-session planning for prospective event-study horizons."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import exchange_calendars  # type: ignore[import-untyped]

from kalki_market_intelligence.contracts.domain import CurrencyCode
from kalki_market_intelligence.prospective.contracts import (
    MarketIdentifierCode,
    OutcomeHorizon,
    OutcomeOrigin,
    ProspectiveOutcomePlan,
)


class ExchangeSessionPlanner:
    """Bind publication time to the first exchange close at or after publication."""

    def plan(
        self,
        *,
        publication_id: object,
        published_at: datetime,
        asset_symbol: str,
        asset_mic: MarketIdentifierCode,
        benchmark_symbol: str,
        benchmark_mic: MarketIdentifierCode,
        calendar_name: MarketIdentifierCode,
        currency: CurrencyCode,
        enrolled_at: datetime,
        horizon: OutcomeHorizon,
    ) -> ProspectiveOutcomePlan:
        from uuid import UUID

        if not isinstance(publication_id, UUID):
            raise TypeError("publication_id must be a UUID")
        published_utc = _utc(published_at)
        enrolled_utc = _utc(enrolled_at)
        start = published_utc.date() - timedelta(days=7)
        end = published_utc.date() + timedelta(days=60)
        calendar = exchange_calendars.get_calendar(calendar_name, start=start, end=end)
        minute = published_utc.replace(second=0, microsecond=0)
        if published_utc > minute:
            minute += timedelta(minutes=1)
        reference_session = calendar.minute_to_session(minute, direction="next")
        reference_date = reference_session.date()
        reference_close = calendar.session_close(reference_session).to_pydatetime().astimezone(UTC)
        # The library includes the reference session in a positive window. Add
        # one so T+N means N complete exchange sessions after that reference.
        sessions = calendar.sessions_window(reference_session, int(horizon) + 1)
        target_session = sessions[-1]
        target_date = target_session.date()
        target_close = calendar.session_close(target_session).to_pydatetime().astimezone(UTC)
        try:
            publication_session = calendar.minute_to_session(minute, direction="previous").date()
        except ValueError:
            publication_session = reference_date
        origin = (
            OutcomeOrigin.GENUINE_FORWARD
            if enrolled_utc < target_close
            else OutcomeOrigin.RECONSTRUCTED
        )
        return ProspectiveOutcomePlan(
            publication_id=publication_id,
            published_at=published_utc,
            asset_symbol=asset_symbol,
            asset_mic=asset_mic,
            benchmark_symbol=benchmark_symbol,
            benchmark_mic=benchmark_mic,
            calendar_name=calendar_name,
            currency=currency,
            enrolled_at=enrolled_utc,
            publication_session_date=publication_session,
            reference_session_date=reference_date,
            reference_session_close_at=reference_close,
            horizon=horizon,
            target_session_date=target_date,
            target_session_close_at=target_close,
            origin=origin,
        )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("session planning timestamps must be timezone-aware")
    return value.astimezone(UTC)


def supported_calendar(name: str) -> bool:
    """Expose a small deterministic predicate without constructing a schedule."""

    return name in {"XNYS", "XTSE"}
