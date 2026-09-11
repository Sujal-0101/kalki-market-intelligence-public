"""Deterministic walk-forward evaluation over immutable historical snapshots."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from decimal import Decimal, localcontext
from pathlib import Path

from kalki_market_intelligence.backtesting.contracts import (
    BacktestReport,
    CalibrationRow,
    CaseEvaluation,
    ErrorCategory,
    HistoricalDataset,
)
from kalki_market_intelligence.predictions.contracts import SecurityOutcomeStatus
from kalki_market_intelligence.quantitative.algorithms import CALCULATION_CONTEXT
from kalki_market_intelligence.signals.contracts import SignalLabel


def load_dataset(path: Path) -> HistoricalDataset:
    return HistoricalDataset.model_validate_json(path.read_text(encoding="utf-8"))


def _fingerprint(dataset: HistoricalDataset) -> str:
    payload = dataset.model_dump(mode="json")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _wilson(favorable: int, total: int) -> tuple[Decimal | None, Decimal | None]:
    if total == 0:
        return None, None
    with localcontext(CALCULATION_CONTEXT):
        n = Decimal(total)
        proportion = Decimal(favorable) / n
        z = Decimal("1.959963984540054")
        denominator = Decimal(1) + z * z / n
        center = (proportion + z * z / (Decimal(2) * n)) / denominator
        margin = (
            z
            * ((proportion * (Decimal(1) - proportion) / n + z * z / (Decimal(4) * n * n)).sqrt())
            / denominator
        )
        return center - margin, center + margin


def evaluate_dataset(dataset: HistoricalDataset) -> BacktestReport:
    predictions = {item.case_id: item for item in dataset.predictions}
    outcomes = {item.case_id: item for item in dataset.outcomes}
    cost = dataset.round_trip_cost_bps / Decimal(10_000)
    cases: list[CaseEvaluation] = []
    for case_id in sorted(predictions, key=str):
        prediction = predictions[case_id]
        outcome = outcomes[case_id]
        relative: Decimal | None = None
        if outcome.asset_return is None:
            category = ErrorCategory.OUTCOME_DATA_UNAVAILABLE
        else:
            assert outcome.benchmark_return is not None
            relative = outcome.asset_return - outcome.benchmark_return - cost
            if relative > 0:
                category = ErrorCategory.FAVORABLE
            elif outcome.security_status in {
                SecurityOutcomeStatus.DELISTED,
                SecurityOutcomeStatus.BANKRUPT,
            }:
                category = ErrorCategory.DELISTED_OR_BANKRUPT_ADVERSE
            else:
                category = ErrorCategory.ADVERSE_OUTCOME
        cases.append(
            CaseEvaluation(
                case_id=case_id,
                split=prediction.split,
                label=prediction.label,
                security_status=outcome.security_status,
                category=category,
                asset_return=outcome.asset_return,
                benchmark_return=outcome.benchmark_return,
                net_benchmark_relative_return=relative,
            )
        )
    calibration: list[CalibrationRow] = []
    for label in SignalLabel:
        selected = [item for item in cases if item.label is label]
        available = [
            item for item in selected if item.category is not ErrorCategory.OUTCOME_DATA_UNAVAILABLE
        ]
        favorable = sum(item.category is ErrorCategory.FAVORABLE for item in available)
        low, high = _wilson(favorable, len(available))
        rate = Decimal(favorable) / Decimal(len(available)) if available else None
        calibration.append(
            CalibrationRow(
                label=label,
                sample_count=len(selected),
                available_count=len(available),
                favorable_count=favorable,
                observed_favorable_rate=rate,
                wilson_low=low,
                wilson_high=high,
            )
        )
    unavailable = sum(item.category is ErrorCategory.OUTCOME_DATA_UNAVAILABLE for item in cases)
    total = len(cases)
    return BacktestReport(
        dataset_name=dataset.dataset_name,
        dataset_fingerprint=_fingerprint(dataset),
        generated_at=dataset.snapshot_at,
        policy_locked_at=dataset.policy_locked_at,
        round_trip_cost_bps=dataset.round_trip_cost_bps,
        universe_count=total,
        retained_delisted_or_bankrupt_count=sum(
            item.security_status
            in {
                SecurityOutcomeStatus.DELISTED,
                SecurityOutcomeStatus.BANKRUPT,
            }
            for item in cases
        ),
        split_counts=dict(Counter(item.split for item in cases)),
        available_count=total - unavailable,
        unavailable_count=unavailable,
        coverage_rate=Decimal(total - unavailable) / Decimal(total),
        cases=tuple(cases),
        calibration=tuple(calibration),
        error_counts=dict(Counter(item.category for item in cases)),
        limitations=(
            dataset.disclosure,
            "Small-sample Wilson intervals are descriptive, not calibrated probabilities.",
            "Round-trip cost is a transparent sensitivity assumption, not simulated execution.",
            "Unavailable outcomes remain in the universe and coverage denominator.",
            "No tuning decision may use validation or held-out outcomes.",
        ),
    )
