"""Immutability, temporal-integrity, and outcome evaluation tests."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from kalki_market_intelligence.contracts.domain import CurrencyCode
from kalki_market_intelligence.notifications.templates import ResearchNotification
from kalki_market_intelligence.predictions.contracts import (
    CorporateActionRecord,
    EvaluationRule,
    JobStatus,
    ObservationOrigin,
    OutcomeAssessment,
    OutcomeEvaluationInput,
    PredictionCorrection,
    PredictionEvidence,
    PredictionRecord,
    PredictionScores,
    ReturnObservation,
    SecurityOutcomeStatus,
    VersionManifest,
)
from kalki_market_intelligence.predictions.engine import OutcomeEvaluator
from kalki_market_intelligence.predictions.ledger import (
    DuplicateRecordError,
    ImmutableRecordError,
    MemoryPredictionLedger,
    UnknownPredictionError,
)
from kalki_market_intelligence.quantitative.algorithms import CALCULATION_CONTEXT
from kalki_market_intelligence.signals.contracts import (
    HeuristicScore,
    RiskProfile,
    RuleTrace,
    ScoreDimension,
    SignalLabel,
    SignalResult,
)

FIXTURE_PATH = Path(__file__).parents[1] / "data/fixtures/predictions/reference-outcomes.json"
REFERENCE = cast(dict[str, str], json.loads(FIXTURE_PATH.read_text(encoding="utf-8")))
PREDICTION_ID = UUID("10000000-0000-4000-8000-000000000001")
SUBJECT_ID = UUID("20000000-0000-4000-8000-000000000001")
INSTRUMENT_ID = UUID("30000000-0000-4000-8000-000000000001")
BENCHMARK_ID = UUID("40000000-0000-4000-8000-000000000001")
AS_OF = date(2026, 1, 1)
PREDICTION_CUTOFF = datetime(2026, 1, 1, 21, tzinfo=UTC)
EVALUATED_AT = datetime(2026, 4, 2, 21, tzinfo=UTC)
EVALUATION_CUTOFF = datetime(2026, 4, 2, 22, tzinfo=UTC)
EVALUATOR = OutcomeEvaluator()
EVIDENCE_ID = UUID("60000000-0000-4000-8000-000000000001")


def signal() -> SignalResult:
    return SignalResult(
        signal_fingerprint="d" * 64,
        research_subject_id=SUBJECT_ID,
        as_of_date=AS_OF,
        knowledge_cutoff_at=PREDICTION_CUTOFF,
        horizon_days=90,
        opportunity=HeuristicScore(points=68),
        risk=HeuristicScore(points=80),
        research_confidence=HeuristicScore(points=82),
        label=SignalLabel.SPECULATIVE_OPPORTUNITY,
        risk_profile=RiskProfile.AGGRESSIVE_SPECULATIVE,
        traces=(
            RuleTrace(
                rule_id="synthetic.opportunity",
                dimension=ScoreDimension.OPPORTUNITY,
                points=68,
                explanation="Synthetic opportunity contribution for contract testing.",
                evidence_ids=(EVIDENCE_ID,),
                input_hashes=("b" * 64,),
            ),
            RuleTrace(
                rule_id="synthetic.risk",
                dimension=ScoreDimension.RISK,
                points=80,
                explanation="Synthetic risk contribution for contract testing.",
                input_hashes=("c" * 64,),
            ),
            RuleTrace(
                rule_id="synthetic.confidence",
                dimension=ScoreDimension.RESEARCH_CONFIDENCE,
                points=82,
                explanation="Synthetic research-confidence contribution for contract testing.",
            ),
        ),
        missing_inputs=(),
    )


def prediction() -> PredictionRecord:
    return PredictionRecord(
        prediction_id=PREDICTION_ID,
        research_subject_id=SUBJECT_ID,
        instrument_id=INSTRUMENT_ID,
        benchmark_instrument_id=BENCHMARK_ID,
        currency=CurrencyCode.US_DOLLAR,
        as_of_date=AS_OF,
        knowledge_cutoff_at=PREDICTION_CUTOFF,
        published_at=PREDICTION_CUTOFF + timedelta(hours=1),
        horizon_days=90,
        evaluation_due_on=date(2026, 4, 1),
        evaluation_rule=EvaluationRule.TOTAL_RETURN_AND_BENCHMARK,
        thesis="Synthetic prediction thesis used only to test immutable contracts.",
        label=SignalLabel.SPECULATIVE_OPPORTUNITY,
        risk_profile=RiskProfile.AGGRESSIVE_SPECULATIVE,
        scores=PredictionScores(
            opportunity_points=68,
            risk_points=80,
            research_confidence_points=82,
        ),
        signal=signal(),
        evidence=(
            PredictionEvidence(
                evidence_id=EVIDENCE_ID,
                content_sha256="a" * 64,
                available_at=PREDICTION_CUTOFF - timedelta(hours=2),
                retrieved_at=PREDICTION_CUTOFF - timedelta(hours=1),
            ),
        ),
        metric_input_hashes=("b" * 64,),
        analysis_input_hashes=("c" * 64,),
        versions=VersionManifest(
            signal_ruleset_version="1.0.0",
            signal_fingerprint="d" * 64,
            calculation_versions=("1.0.0",),
            analysis_prompt_versions=("analyst-v1",),
            analysis_model_versions=("synthetic-no-model",),
        ),
        published_by="synthetic-test-publisher",
    )


def observation(
    instrument_id: UUID,
    effective_date: date,
    price_key: str,
    *,
    start: bool,
    cash_key: str | None = None,
) -> ReturnObservation:
    available = (
        PREDICTION_CUTOFF - timedelta(hours=2) if start else EVALUATED_AT - timedelta(hours=1)
    )
    return ReturnObservation(
        instrument_id=instrument_id,
        effective_date=effective_date,
        price=Decimal(REFERENCE[price_key]),
        cash_distributions_per_share=(Decimal(REFERENCE[cash_key]) if cash_key else Decimal(0)),
        currency=CurrencyCode.US_DOLLAR,
        available_at=available,
        retrieved_at=available + timedelta(minutes=30),
        source_record_id=f"synthetic-{price_key}",
        source_content_sha256=price_key.encode().hex().ljust(64, "0")[:64],
    )


def evaluation_input(
    *,
    status: SecurityOutcomeStatus = SecurityOutcomeStatus.DELISTED,
    complete: bool = True,
) -> OutcomeEvaluationInput:
    if not complete:
        return OutcomeEvaluationInput(
            prediction=prediction(),
            evaluated_at=EVALUATED_AT,
            knowledge_cutoff_at=EVALUATION_CUTOFF,
            security_status=status,
            asset_start=None,
            asset_end=None,
            benchmark_start=None,
            benchmark_end=None,
            limitations=("Synthetic missing-data case.",),
        )
    return OutcomeEvaluationInput(
        prediction=prediction(),
        evaluated_at=EVALUATED_AT,
        knowledge_cutoff_at=EVALUATION_CUTOFF,
        security_status=status,
        asset_start=observation(INSTRUMENT_ID, AS_OF, "asset_start", start=True),
        asset_end=observation(
            INSTRUMENT_ID,
            date(2026, 4, 1),
            "asset_end",
            start=False,
            cash_key="asset_cash_distribution",
        ),
        benchmark_start=observation(BENCHMARK_ID, AS_OF, "benchmark_start", start=True),
        benchmark_end=observation(
            BENCHMARK_ID,
            date(2026, 4, 1),
            "benchmark_end",
            start=False,
            cash_key="benchmark_cash_distribution",
        ),
        corporate_actions=(
            CorporateActionRecord(
                action_id=UUID("70000000-0000-4000-8000-000000000001"),
                instrument_id=INSTRUMENT_ID,
                action_type="delisting",
                effective_date=date(2026, 3, 31),
                description="Wholly synthetic delisting marker retained for testing.",
                available_at=EVALUATED_AT - timedelta(days=1),
                retrieved_at=EVALUATED_AT - timedelta(hours=1),
                source_content_sha256="e" * 64,
            ),
        ),
    )


def test_reference_outcome_is_exact_reproducible_and_corporate_action_aware() -> None:
    first = EVALUATOR.evaluate(evaluation_input())
    second = EVALUATOR.evaluate(evaluation_input())

    assert "not market evidence" in REFERENCE["description"]
    assert first == second
    assert first.asset_return == Decimal(REFERENCE["expected_asset_total_return"])
    assert first.benchmark_return == Decimal(REFERENCE["expected_benchmark_total_return"])
    assert first.benchmark_relative_return == Decimal(
        REFERENCE["expected_benchmark_relative_return"]
    )
    assert first.assessment is OutcomeAssessment.POSITIVE_ABSOLUTE_AND_RELATIVE
    assert first.security_status is SecurityOutcomeStatus.DELISTED
    assert len(first.corporate_action_ids) == len(first.corporate_action_hashes) == 1


def test_outcome_decimal_math_ignores_callers_context() -> None:
    expected = EVALUATOR.evaluate(evaluation_input())
    with localcontext() as context:
        context.prec = 3
        actual = EVALUATOR.evaluate(evaluation_input())
    assert actual == expected
    assert CALCULATION_CONTEXT.prec == 34


def test_prediction_is_frozen_and_ledger_rejects_update_delete_duplicates() -> None:
    record = prediction()
    ledger = MemoryPredictionLedger()
    first_hash = ledger.append_prediction(record)

    with pytest.raises(ValidationError):
        record.thesis = "Changed"  # type: ignore[misc]
    with pytest.raises(ImmutableRecordError, match="cannot be updated"):
        ledger.update_prediction(record.prediction_id, thesis="Changed")
    with pytest.raises(ImmutableRecordError, match="cannot be deleted"):
        ledger.delete_prediction(record.prediction_id)
    with pytest.raises(DuplicateRecordError):
        ledger.append_prediction(record)
    assert ledger.predictions == (record,)
    assert ledger.chain_head == first_hash


def test_corrections_and_outcomes_append_without_rewriting_prediction() -> None:
    record = prediction()
    outcome = EVALUATOR.evaluate(evaluation_input())
    correction = PredictionCorrection(
        correction_id=UUID("80000000-0000-4000-8000-000000000001"),
        prediction_id=record.prediction_id,
        appended_at=record.published_at + timedelta(minutes=1),
        reason="Synthetic visible wording correction.",
        replacement_text="Synthetic corrected display text.",
        appended_by="synthetic-test-publisher",
    )
    ledger = MemoryPredictionLedger()
    ledger.append_prediction(record)
    ledger.append_correction(correction)
    ledger.append_outcome(outcome)

    assert ledger.predictions == (record,)
    assert ledger.corrections == (correction,)
    assert ledger.outcomes == (outcome,)
    assert ledger.chain_head is not None

    empty = MemoryPredictionLedger()
    with pytest.raises(UnknownPredictionError):
        empty.append_outcome(outcome)


def test_evaluation_rejects_look_ahead_and_wrong_subject_data() -> None:
    valid = evaluation_input()
    assert valid.asset_start is not None
    assert valid.asset_end is not None
    with pytest.raises(ValidationError, match="before its declared horizon"):
        OutcomeEvaluationInput(
            **{**valid.model_dump(), "evaluated_at": datetime(2026, 3, 1, tzinfo=UTC)}
        )

    leaked_start = valid.asset_start.model_copy(
        update={
            "available_at": PREDICTION_CUTOFF + timedelta(minutes=1),
            "retrieved_at": PREDICTION_CUTOFF + timedelta(minutes=2),
        }
    )
    with pytest.raises(ValidationError, match="post-prediction knowledge"):
        OutcomeEvaluationInput(**{**valid.model_dump(), "asset_start": leaked_start})

    wrong_end = valid.asset_end.model_copy(update={"instrument_id": BENCHMARK_ID})
    with pytest.raises(ValidationError, match="asset end observation"):
        OutcomeEvaluationInput(**{**valid.model_dump(), "asset_end": wrong_end})


def test_jobs_obey_horizon_and_completed_outcomes() -> None:
    record = prediction()
    before = EVALUATOR.job_for(record, datetime(2026, 3, 31, tzinfo=UTC))
    ready = EVALUATOR.job_for(record, EVALUATED_AT)
    outcome = EVALUATOR.evaluate(evaluation_input())
    completed = EVALUATOR.job_for(record, EVALUATED_AT, (outcome,))

    assert before.status is JobStatus.NOT_DUE
    assert ready.status is JobStatus.READY
    assert completed.status is JobStatus.COMPLETED
    assert completed.outcome_id == outcome.outcome_id


def test_report_retains_delisted_and_unavailable_predictions() -> None:
    available = EVALUATOR.evaluate(evaluation_input())
    unavailable_prediction = prediction().model_copy(
        update={"prediction_id": UUID("10000000-0000-4000-8000-000000000002")}
    )
    missing_inputs = evaluation_input(complete=False).model_copy(
        update={"prediction": unavailable_prediction}
    )
    unavailable = EVALUATOR.evaluate(missing_inputs)
    report = EVALUATOR.report(
        (prediction(), unavailable_prediction),
        (available, unavailable),
        EVALUATION_CUTOFF,
    )

    assert report.prediction_count == report.evaluated_count == 2
    assert report.status_counts[SecurityOutcomeStatus.DELISTED] == 2
    assert report.unavailable_count == 1
    assert report.mean_asset_return == Decimal("0.25")
    assert report.mean_benchmark_relative_return == Decimal("0.19")


def test_report_keeps_reconstructed_observations_out_of_forward_statistics() -> None:
    reconstructed_prediction = prediction().model_copy(
        update={"prediction_id": UUID("10000000-0000-0000-8000-000000000003")}
    )
    reconstructed = EVALUATOR.evaluate(
        evaluation_input().model_copy(
            update={
                "prediction": reconstructed_prediction,
                "observation_origin": ObservationOrigin.RECONSTRUCTED,
            }
        )
    )
    forward = EVALUATOR.evaluate(evaluation_input())
    report = EVALUATOR.report(
        (prediction(), reconstructed_prediction),
        (forward, reconstructed),
        EVALUATION_CUTOFF,
    )

    assert report.evaluated_count == 2
    assert report.forward_observation_count == 1
    assert report.reconstructed_observation_count == 1
    assert report.mean_asset_return == Decimal("0.25")
    assert report.calibration is not None
    assert report.calibration.sample_size == 1
    assert report.inference_status == "inconclusive"


def test_prediction_and_outcome_schemas_are_closed() -> None:
    assert PredictionRecord.model_json_schema()["additionalProperties"] is False
    assert OutcomeEvaluationInput.model_json_schema()["additionalProperties"] is False


def test_published_prediction_maps_exactly_to_notification_metadata() -> None:
    record = prediction()
    notification = ResearchNotification.from_prediction(record)

    assert notification.prediction_id == record.prediction_id
    assert notification.published_at == record.published_at
    assert notification.label is record.label
    assert notification.risk_profile is record.risk_profile
    assert notification.opportunity_points == record.scores.opportunity_points
    assert notification.risk_points == record.scores.risk_points
    assert notification.research_confidence_points == record.scores.research_confidence_points
    assert notification.evidence_count == len(record.evidence)
    assert notification.signal_fingerprint == record.versions.signal_fingerprint
