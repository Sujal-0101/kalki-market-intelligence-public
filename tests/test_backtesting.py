"""Phase 13 temporal integrity, survivorship, and reproducibility gates."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from kalki_market_intelligence.backtesting.contracts import (
    DatasetSplit,
    ErrorCategory,
    HistoricalDataset,
)
from kalki_market_intelligence.backtesting.engine import evaluate_dataset, load_dataset
from kalki_market_intelligence.predictions.contracts import SecurityOutcomeStatus
from kalki_market_intelligence.signals.contracts import SignalLabel

FIXTURE = Path("data/fixtures/backtesting/phase13_synthetic.json")


def dataset() -> HistoricalDataset:
    return load_dataset(FIXTURE)


def replace_section(value: HistoricalDataset, **changes: object) -> HistoricalDataset:
    return HistoricalDataset.model_validate(value.model_dump() | changes)


def test_reference_report_is_reproducible_and_discloses_small_synthetic_sample() -> None:
    first = evaluate_dataset(dataset())
    assert first == evaluate_dataset(dataset())
    assert (
        first.dataset_fingerprint
        == "ae880df670ae3741fe9ede35cbac68282a08cd3f3111e18e318e0e6ab050e277"
    )
    assert first.generated_at == dataset().snapshot_at
    assert (first.universe_count, first.available_count, first.unavailable_count) == (6, 5, 1)
    assert first.coverage_rate == Decimal(5) / Decimal(6)
    assert any("synthetic" in item.lower() for item in first.limitations)
    assert any("Small-sample" in item for item in first.limitations)


def test_walk_forward_splits_are_chronological_and_policy_is_prelocked() -> None:
    value = dataset()
    by_split = {
        split: [p.published_at for p in value.predictions if p.split is split]
        for split in DatasetSplit
    }
    assert max(by_split[DatasetSplit.TUNING]) < min(by_split[DatasetSplit.VALIDATION])
    assert max(by_split[DatasetSplit.VALIDATION]) < min(by_split[DatasetSplit.HELD_OUT])
    with pytest.raises(ValidationError, match="policy was not locked"):
        replace_section(
            value, policy_locked_at=max(by_split[DatasetSplit.HELD_OUT]) + timedelta(days=1)
        )


def test_future_universe_knowledge_is_rejected() -> None:
    value = dataset()
    future = value.predictions[0].knowledge_cutoff_at + timedelta(seconds=1)
    first = value.universe[0].model_copy(update={"available_at": future, "retrieved_at": future})
    with pytest.raises(ValidationError, match="leaks knowledge"):
        replace_section(value, universe=(first, *value.universe[1:]))


def test_pre_horizon_outcome_is_rejected_as_look_ahead() -> None:
    value = dataset()
    first = value.outcomes[0].model_copy(
        update={"available_at": value.predictions[0].knowledge_cutoff_at}
    )
    with pytest.raises(ValidationError, match="endpoint predates"):
        replace_section(value, outcomes=(first, *value.outcomes[1:]))


def test_survivorship_guard_requires_every_original_member_and_expected_count() -> None:
    value = dataset()
    with pytest.raises(ValidationError, match="possible survivorship bias"):
        replace_section(value, universe=value.universe[:-1])
    with pytest.raises(ValidationError, match="must retain prediction and outcome"):
        replace_section(value, outcomes=value.outcomes[:-1])


def test_delisted_bankrupt_and_unavailable_cases_remain_in_counts() -> None:
    report = evaluate_dataset(dataset())
    assert report.retained_delisted_or_bankrupt_count == 2
    assert report.error_counts[ErrorCategory.DELISTED_OR_BANKRUPT_ADVERSE] == 2
    assert report.error_counts[ErrorCategory.OUTCOME_DATA_UNAVAILABLE] == 1
    statuses = {item.security_status for item in report.cases}
    assert {SecurityOutcomeStatus.DELISTED, SecurityOutcomeStatus.BANKRUPT} <= statuses
    row = next(
        item for item in report.calibration if item.label is SignalLabel.INSUFFICIENT_EVIDENCE
    )
    assert (row.sample_count, row.available_count, row.observed_favorable_rate) == (1, 0, None)


def test_cost_and_wilson_uncertainty_are_deterministic() -> None:
    report = evaluate_dataset(dataset())
    case = next(item for item in report.cases if item.asset_return == Decimal("0.10"))
    assert case.net_benchmark_relative_return == Decimal("0.068")
    row = next(item for item in report.calibration if item.label is SignalLabel.STRONG_OPPORTUNITY)
    assert (row.sample_count, row.available_count, row.favorable_count) == (2, 2, 2)
    assert row.observed_favorable_rate == Decimal(1)
    assert row.wilson_low is not None and Decimal(0) < row.wilson_low < Decimal(1)
    assert row.wilson_high is not None and row.wilson_high <= Decimal(1)


def test_contracts_are_closed() -> None:
    payload = dataset().model_dump(mode="json")
    payload["fabricated_field"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        HistoricalDataset.model_validate(payload)
