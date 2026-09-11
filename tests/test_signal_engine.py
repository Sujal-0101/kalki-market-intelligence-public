"""Fixed-reference and safety tests for the versioned signal engine."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import UUID, uuid5

import pytest
from pydantic import ValidationError

from kalki_market_intelligence.analysis.contracts import (
    PROMPT_VERSION,
    VALIDATION_VERSION,
    AnalysisAudit,
    AnalystEvidence,
    AnalystFinding,
    AnalystReport,
    AnalystRole,
    Assessment,
    EvidenceCitation,
    FindingCategory,
    FindingKind,
    FindingPolarity,
    ValidatedAnalysis,
)
from kalki_market_intelligence.contracts.evidence import SourceClass
from kalki_market_intelligence.quantitative.contracts import (
    CalculationInput,
    InputValue,
    MetricPoint,
    MetricResult,
)
from kalki_market_intelligence.signals.contracts import (
    MissingSeverity,
    RiskProfile,
    RuleTrace,
    ScoreDimension,
    SignalLabel,
    SignalRequest,
    SignalResult,
)
from kalki_market_intelligence.signals.engine import SignalEngine

FIXTURE = Path(__file__).parents[1] / "data/fixtures/signals/reference-cases.json"
REFERENCE = cast(dict[str, object], json.loads(FIXTURE.read_text(encoding="utf-8")))
SUBJECT_ID = UUID("77777777-7777-4777-8777-777777777777")
NAMESPACE = UUID("11111111-1111-4111-8111-111111111111")
AS_OF = date(2026, 6, 30)
CUTOFF = datetime(2026, 6, 30, 23, tzinfo=UTC)
ENGINE = SignalEngine()


def stable_id(value: str) -> UUID:
    return uuid5(NAMESPACE, value)


def metric(name: str, value: str) -> MetricResult:
    return MetricResult(
        metric_name=name,
        as_of_date=AS_OF,
        knowledge_cutoff_at=CUTOFF,
        unit="synthetic_reference",
        points=(MetricPoint(effective_date=AS_OF, component="value", value=Decimal(value)),),
        inputs=(
            CalculationInput(
                input_id=f"synthetic-{name}",
                input_kind="synthetic_signal_fixture",
                subject_id=SUBJECT_ID,
                effective_date=AS_OF,
                values=(InputValue(name="fixture_value", value=Decimal(value), unit="pure"),),
                available_at=CUTOFF - timedelta(hours=2),
                retrieved_at=CUTOFF - timedelta(hours=1),
                source_record_id=f"synthetic-{name}",
                source_content_sha256="a" * 64,
            ),
        ),
    )


def analysis(
    case_name: str,
    role_name: str,
    category_name: str,
    source_name: str,
) -> tuple[ValidatedAnalysis, AnalystEvidence]:
    evidence_id = stable_id(f"{case_name}-{role_name}-evidence")
    quote = f"Synthetic {category_name.replace('_', ' ')} statement for contract testing."
    evidence = AnalystEvidence(
        evidence_id=evidence_id,
        subject_id=SUBJECT_ID,
        source_id=stable_id(f"{case_name}-{role_name}-source"),
        source_class=SourceClass(source_name),
        publisher="Synthetic fixture publisher",
        locator="synthetic fixture paragraph 1",
        text=quote,
        content_sha256=stable_id(quote).hex * 2,
        published_at=CUTOFF - timedelta(days=2),
        available_at=CUTOFF - timedelta(days=1),
        retrieved_at=CUTOFF - timedelta(hours=1),
    )
    role = AnalystRole(role_name)
    category = FindingCategory(category_name)
    report = AnalystReport(
        prompt_version=PROMPT_VERSION,
        role=role,
        assessment=Assessment.EVIDENCE_SUFFICIENT,
        findings=(
            AnalystFinding(
                kind=FindingKind.REPORTED_FACT,
                category=category,
                polarity=(
                    FindingPolarity.BEARISH
                    if category in {FindingCategory.RISK, FindingCategory.BEAR_CASE}
                    else FindingPolarity.BULLISH
                ),
                statement=quote,
                citations=(EvidenceCitation(evidence_id=evidence_id, quote=quote),),
            ),
        ),
        contradictions=(),
        limitations=("Wholly synthetic test input.",),
    )
    audit = AnalysisAudit(
        provider_name="synthetic-sequence",
        model_name="no-model",
        model_digest=None,
        prompt_version=PROMPT_VERSION,
        validation_version=VALIDATION_VERSION,
        knowledge_cutoff_at=CUTOFF,
        completed_at=CUTOFF + timedelta(seconds=1),
        attempts=1,
        evidence_ids=(evidence_id,),
        evidence_hashes=(evidence.content_sha256,),
    )
    return ValidatedAnalysis(report=report, audit=audit), evidence


def request_for(case: dict[str, object]) -> SignalRequest:
    metrics = tuple(
        metric(name, value) for name, value in cast(dict[str, str], case["metrics"]).items()
    )
    pairs = tuple(
        analysis(cast(str, case["name"]), *cast(tuple[str, str, str], item))
        for item in cast(list[list[str]], case["findings"])
    )
    return SignalRequest(
        research_subject_id=SUBJECT_ID,
        allowed_metric_subject_ids=(SUBJECT_ID,),
        as_of_date=AS_OF,
        knowledge_cutoff_at=CUTOFF,
        horizon_days=90,
        metrics=metrics,
        analyses=tuple(item[0] for item in pairs),
        evidence=tuple(item[1] for item in pairs),
    )


def cases() -> list[dict[str, object]]:
    return cast(list[dict[str, object]], REFERENCE["cases"])


@pytest.mark.parametrize("case", cases(), ids=lambda case: cast(dict[str, object], case)["name"])
def test_fixed_cases_are_exact_and_reproducible(case: dict[str, object]) -> None:
    request = request_for(case)
    first = ENGINE.evaluate(request)
    second = ENGINE.evaluate(request)
    expected = cast(list[object], case["expected"])

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    assert [
        first.opportunity.points,
        first.risk.points,
        first.research_confidence.points,
        first.label,
        first.risk_profile,
    ] == [expected[0], expected[1], expected[2], expected[3], expected[4]]


def test_fixture_is_explicitly_synthetic_and_rules_are_versioned() -> None:
    assert REFERENCE["schema_version"] == "1"
    assert "not market evidence" in cast(str, REFERENCE["description"])
    result = ENGINE.evaluate(request_for(cases()[0]))
    assert result.ruleset_version == "1.0.0"
    assert {trace.ruleset_version for trace in result.traces} == {"1.0.0"}
    assert result.opportunity.interpretation == "heuristic_points_not_probability"


def test_every_material_contribution_has_lineage() -> None:
    result = ENGINE.evaluate(request_for(cases()[0]))
    material = [trace for trace in result.traces if trace.points]

    assert material
    assert all(
        trace.metric_names or trace.analysis_roles or trace.evidence_ids for trace in material
    )
    assert all(trace.input_hashes for trace in material)
    assert set(ScoreDimension) == {trace.dimension for trace in result.traces}


def test_critical_missing_inputs_force_insufficient_evidence() -> None:
    result = ENGINE.evaluate(request_for(cases()[-1]))

    assert result.label is SignalLabel.INSUFFICIENT_EVIDENCE
    assert result.risk_profile is RiskProfile.UNCLASSIFIED
    assert {
        item.slot for item in result.missing_inputs if item.severity is MissingSeverity.CRITICAL
    } == {
        "risk_metrics",
        "qualitative_analysis",
        "cited_evidence",
    }


def test_request_rejects_future_and_wrong_subject_inputs() -> None:
    valid = request_for(cases()[0])
    future_metric = valid.metrics[0].model_copy(
        update={
            "as_of_date": AS_OF + timedelta(days=1),
            "knowledge_cutoff_at": CUTOFF + timedelta(days=1),
        }
    )
    with pytest.raises(ValidationError, match="later than the signal"):
        SignalRequest(**{**valid.model_dump(), "metrics": (future_metric, *valid.metrics[1:])})

    wrong = valid.evidence[0].model_copy(update={"subject_id": stable_id("wrong")})
    with pytest.raises(ValidationError, match="different research subject"):
        SignalRequest(**{**valid.model_dump(), "evidence": (wrong, *valid.evidence[1:])})


def test_result_rejects_unexplained_score_and_recommendation_language() -> None:
    valid = ENGINE.evaluate(request_for(cases()[0]))
    with pytest.raises(ValidationError, match="score does not equal"):
        SignalResult(**{**valid.model_dump(), "opportunity": {"points": 1}})

    bad_trace = RuleTrace(
        rule_id="bad.wording",
        dimension=ScoreDimension.OPPORTUNITY,
        points=0,
        explanation="Buy based on this input.",
    )
    with pytest.raises(ValidationError, match="prohibited recommendation"):
        SignalResult(**{**valid.model_dump(), "traces": (*valid.traces, bad_trace)})


def test_signal_contract_schemas_are_closed() -> None:
    assert SignalRequest.model_json_schema()["additionalProperties"] is False
    assert SignalResult.model_json_schema()["additionalProperties"] is False
