"""Deterministic price-return evaluation over supporting provider bars."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, localcontext
from uuid import NAMESPACE_URL, uuid5

from kalki_market_intelligence.prospective.contracts import (
    OutcomeObservationSet,
    OutcomeStatus,
    ProspectiveOutcome,
    ProspectiveOutcomeAttempt,
    ProspectiveOutcomePlan,
    SupportingDailyBar,
)


class ProspectiveOutcomeEvaluator:
    def evaluate(
        self,
        *,
        plan: ProspectiveOutcomePlan,
        observations: OutcomeObservationSet,
        attempts: tuple[ProspectiveOutcomeAttempt, ...],
        evaluated_at: datetime,
        appended_at: datetime,
    ) -> ProspectiveOutcome:
        bars = (
            observations.asset_reference,
            observations.asset_target,
            observations.benchmark_reference,
            observations.benchmark_target,
        )
        present = tuple(bar for bar in bars if bar is not None)
        self._validate_bars(plan, observations, present)
        hashes = tuple(sorted(bar.source_content_sha256 for bar in present))
        outcome_id = uuid5(
            NAMESPACE_URL,
            f"prospective:{plan.publication_id}:{int(plan.horizon)}:{plan.provider_name}",
        )
        if len(present) != 4:
            missing = _missing_observations(observations)
            return ProspectiveOutcome(
                outcome_id=outcome_id,
                plan=plan,
                status=OutcomeStatus.DATA_UNAVAILABLE,
                evaluated_at=evaluated_at,
                appended_at=appended_at,
                observations=observations,
                asset_return=None,
                benchmark_return=None,
                benchmark_relative_return=None,
                observation_hashes=hashes,
                attempts=attempts,
                limitations=(f"missing provider observations: {', '.join(missing)}",),
            )
        assert observations.asset_reference is not None
        assert observations.asset_target is not None
        assert observations.benchmark_reference is not None
        assert observations.benchmark_target is not None
        asset_return = _price_return(
            observations.asset_reference.close, observations.asset_target.close
        )
        benchmark_return = _price_return(
            observations.benchmark_reference.close, observations.benchmark_target.close
        )
        with localcontext() as context:
            context.prec = 34
            relative = asset_return - benchmark_return
        return ProspectiveOutcome(
            outcome_id=outcome_id,
            plan=plan,
            status=OutcomeStatus.COMPLETED,
            evaluated_at=evaluated_at,
            appended_at=appended_at,
            observations=observations,
            asset_return=asset_return,
            benchmark_return=benchmark_return,
            benchmark_relative_return=relative,
            observation_hashes=hashes,
            attempts=attempts,
            limitations=(),
        )

    @staticmethod
    def _validate_bars(
        plan: ProspectiveOutcomePlan,
        observations: OutcomeObservationSet,
        bars: tuple[SupportingDailyBar, ...],
    ) -> None:
        if any(bar.provider_name != plan.provider_name for bar in bars):
            raise ValueError("observation provider does not match plan")
        if any(bar.currency is not plan.currency for bar in bars):
            raise ValueError("observation currency does not match plan")
        expected = (
            (
                observations.asset_reference,
                plan.asset_symbol,
                plan.asset_mic,
                plan.reference_session_date,
            ),
            (
                observations.asset_target,
                plan.asset_symbol,
                plan.asset_mic,
                plan.target_session_date,
            ),
            (
                observations.benchmark_reference,
                plan.benchmark_symbol,
                plan.benchmark_mic,
                plan.reference_session_date,
            ),
            (
                observations.benchmark_target,
                plan.benchmark_symbol,
                plan.benchmark_mic,
                plan.target_session_date,
            ),
        )
        for bar, symbol, mic, session_date in expected:
            if bar is not None and (
                bar.symbol != symbol or bar.mic != mic or bar.session_date != session_date
            ):
                raise ValueError("provider observation identity does not match plan")


def _price_return(start: Decimal, end: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 34
        return (end - start) / start


def _missing_observations(observations: OutcomeObservationSet) -> tuple[str, ...]:
    return tuple(
        name
        for name, value in (
            ("asset_reference", observations.asset_reference),
            ("asset_target", observations.asset_target),
            ("benchmark_reference", observations.benchmark_reference),
            ("benchmark_target", observations.benchmark_target),
        )
        if value is None
    )
