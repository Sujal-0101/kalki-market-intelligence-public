"""Phase 44 outcome science stays prospective, stratified, and descriptive."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from kalki_market_intelligence.contracts.domain import CurrencyCode
from kalki_market_intelligence.prospective.calendar import ExchangeSessionPlanner
from kalki_market_intelligence.prospective.contracts import (
    AttemptStatus,
    OutcomeHorizon,
    OutcomeObservationSet,
    OutcomeOrigin,
    OutcomeStatus,
    ProspectiveOutcome,
    ProspectiveOutcomeAttempt,
    ProspectiveOutcomePlan,
    SupportingDailyBar,
)
from kalki_market_intelligence.prospective.engine import ProspectiveOutcomeEvaluator
from kalki_market_intelligence.prospective.science import (
    MINIMUM_CALIBRATION_SAMPLE,
    OUTCOME_SCIENCE_PROTOCOL_LOCKED_AT,
    OutcomePublicationVersion,
    OutcomeScienceCase,
    OutcomeScienceDisposition,
    OutcomeScienceProtocol,
    OutcomeScienceReport,
    OutcomeScienceSnapshot,
    OutcomeScienceStratum,
    PowerSufficiency,
    build_outcome_science_report,
    build_outcome_science_snapshot,
    required_power_sample,
)
from kalki_market_intelligence.prospective.science_store import (
    build_outcome_science_population,
)
from kalki_market_intelligence.radar.contracts import (
    BriefEvidence,
    PublicationGateMode,
    PublicPublicationGateReceipt,
    RadarClassification,
    ResearchBrief,
)
from kalki_market_intelligence.web.operations import outcome_science_operations

GENERATED_AT = datetime(2026, 10, 15, 12, tzinfo=UTC)
FORWARD_PUBLISHED_AT = datetime(2026, 9, 8, 14, tzinfo=UTC)
RECONSTRUCTED_PUBLISHED_AT = datetime(2026, 8, 25, 14, tzinfo=UTC)


def _sha(marker: str) -> str:
    return hashlib.sha256(marker.encode("utf-8")).hexdigest()


def _publication_id(index: int) -> UUID:
    return UUID(f"10000000-0000-0000-0000-{index:012d}")


def _plan(index: int, *, origin: OutcomeOrigin) -> ProspectiveOutcomePlan:
    published_at = (
        FORWARD_PUBLISHED_AT
        if origin is OutcomeOrigin.GENUINE_FORWARD
        else RECONSTRUCTED_PUBLISHED_AT
    )
    enrolled_at = (
        FORWARD_PUBLISHED_AT + timedelta(minutes=1)
        if origin is OutcomeOrigin.GENUINE_FORWARD
        else datetime(2026, 9, 1, 12, tzinfo=UTC)
    )
    return ExchangeSessionPlanner().plan(
        publication_id=_publication_id(index),
        published_at=published_at,
        asset_symbol="AAPL",
        asset_mic="XNAS",
        benchmark_symbol="SPY",
        benchmark_mic="ARCX",
        calendar_name="XNYS",
        currency=CurrencyCode.US_DOLLAR,
        enrolled_at=enrolled_at,
        horizon=OutcomeHorizon.T1,
    )


def _bar(
    plan: ProspectiveOutcomePlan,
    *,
    benchmark: bool,
    target: bool,
    close: str,
    marker: str,
) -> SupportingDailyBar:
    value = Decimal(close)
    return SupportingDailyBar(
        symbol=plan.benchmark_symbol if benchmark else plan.asset_symbol,
        mic=plan.benchmark_mic if benchmark else plan.asset_mic,
        provider_mic=plan.benchmark_mic if benchmark else plan.asset_mic,
        session_date=plan.target_session_date if target else plan.reference_session_date,
        open=value,
        high=value + Decimal("1"),
        low=value - Decimal("1"),
        close=value,
        volume=100,
        currency=plan.currency,
        source_record_id=f"fixture:{marker}",
        source_content_sha256=_sha(marker),
        available_at=GENERATED_AT - timedelta(days=1),
        retrieved_at=GENERATED_AT - timedelta(days=1),
    )


def _attempt(
    plan: ProspectiveOutcomePlan,
    index: int,
    *,
    status: AttemptStatus,
) -> ProspectiveOutcomeAttempt:
    return ProspectiveOutcomeAttempt(
        attempt_id=UUID(f"20000000-0000-0000-0000-{index:012d}"),
        publication_id=plan.publication_id,
        horizon=plan.horizon,
        attempt_number=1,
        started_at=GENERATED_AT - timedelta(minutes=2),
        completed_at=GENERATED_AT - timedelta(minutes=1),
        status=status,
        response_sha256=(_sha(f"response-{index}"),),
        response_row_count=4,
        error_code=None if status is AttemptStatus.SUCCEEDED else "data_unavailable",
    )


def _case(
    index: int,
    *,
    origin: OutcomeOrigin = OutcomeOrigin.GENUINE_FORWARD,
    result: str = "favorable",
    classification: RadarClassification = RadarClassification.OPPORTUNITY,
    prompt_version: str = "analyst-v2",
) -> OutcomeScienceCase:
    plan = _plan(index, origin=origin)
    attempt_status = (
        AttemptStatus.TERMINAL_FAILURE if result == "unavailable" else AttemptStatus.SUCCEEDED
    )
    observations = (
        OutcomeObservationSet(
            asset_reference=None,
            asset_target=None,
            benchmark_reference=None,
            benchmark_target=None,
        )
        if result == "unavailable"
        else OutcomeObservationSet(
            asset_reference=_bar(
                plan, benchmark=False, target=False, close="100", marker=f"{index}-a0"
            ),
            asset_target=_bar(
                plan,
                benchmark=False,
                target=True,
                close="110" if result == "favorable" else "100",
                marker=f"{index}-a1",
            ),
            benchmark_reference=_bar(
                plan, benchmark=True, target=False, close="100", marker=f"{index}-b0"
            ),
            benchmark_target=_bar(
                plan, benchmark=True, target=True, close="100", marker=f"{index}-b1"
            ),
        )
    )
    outcome = ProspectiveOutcomeEvaluator().evaluate(
        plan=plan,
        observations=observations,
        attempts=(_attempt(plan, index, status=attempt_status),),
        evaluated_at=GENERATED_AT,
        appended_at=GENERATED_AT,
    )
    return OutcomeScienceCase(
        outcome=outcome,
        publication_version=OutcomePublicationVersion(
            publication_id=plan.publication_id,
            published_at=plan.published_at,
            accession_number=f"0000000001-26-{index:06d}",
            asset_symbol=plan.asset_symbol,
            source_document_sha256=_sha(f"source-{index}"),
            publication_schema_version="3.0.0",
            signal_ruleset_version="filing-radar-v1",
            signal_classification=classification,
            analysis_model_name="qwen3:4b",
            analysis_model_digest=_sha("qwen3:4b"),
            analysis_prompt_version=prompt_version,
        ),
    )


def _brief(
    case: OutcomeScienceCase,
    *,
    plan_override: ProspectiveOutcomePlan | None = None,
    version_override: OutcomePublicationVersion | None = None,
) -> ResearchBrief:
    plan = plan_override or case.outcome.plan
    version = version_override or case.publication_version
    retrieved_at = plan.published_at - timedelta(minutes=1)
    source_url = (
        f"https://www.sec.gov/Archives/edgar/data/1/{version.accession_number.replace('-', '')}.txt"
    )
    return ResearchBrief(
        brief_id=plan.publication_id,
        schema_version="3.0.0",
        accession_number=version.accession_number,
        cik="1",
        company_name="Synthetic issuer",
        ticker=plan.asset_symbol,
        exchange="Nasdaq",
        filing_form="8-K",
        filed_at=plan.published_at - timedelta(days=1),
        retrieved_at=retrieved_at,
        published_at=plan.published_at,
        source_url=source_url,
        source_document_sha256=version.source_document_sha256,
        classification=version.signal_classification,
        attention_points=10,
        risk_points=10,
        evidence_strength_points=10,
        headline="Synthetic contract fixture",
        summary="Synthetic report used only to exercise immutable lineage.",
        why_it_matters="It verifies that outcome science joins the exact publication.",
        evidence=(
            BriefEvidence(
                evidence_id=UUID(
                    f"30000000-0000-0000-0000-{int(str(plan.publication_id)[-12:]):012d}"
                ),
                quote="Synthetic evidence for contract validation only.",
                excerpt_sha256=_sha(f"excerpt-{plan.publication_id}"),
                source_url=source_url,
                source_document_sha256=version.source_document_sha256,
                available_at=retrieved_at,
                retrieved_at=retrieved_at,
            ),
        ),
        model_name=version.analysis_model_name,
        model_digest=version.analysis_model_digest,
        prompt_version=(
            "analyst-v1" if version.analysis_prompt_version == "analyst-v1" else "analyst-v2"
        ),
        scoring_version="filing-radar-v1",
        publication_gate=PublicPublicationGateReceipt(
            mode=PublicationGateMode.DETERMINISTIC_ONLY,
            validated_at=plan.published_at - timedelta(seconds=1),
            independent_verifier_status="disabled",
        ),
        limitations=("Synthetic fixture; never production evidence.",),
    )


def test_protocol_is_locked_before_any_forward_observation_and_power_is_fixed() -> None:
    protocol = OutcomeScienceProtocol()
    assert protocol.locked_at == OUTCOME_SCIENCE_PROTOCOL_LOCKED_AT
    assert protocol.minimum_calibration_sample == MINIMUM_CALIBRATION_SAMPLE == 30
    assert required_power_sample() == protocol.power_required_sample == 194
    assert protocol.calibration_origin is OutcomeOrigin.GENUINE_FORWARD
    assert OutcomeScienceProtocol.model_json_schema()["additionalProperties"] is False

    with pytest.raises(ValidationError, match="power design"):
        OutcomeScienceProtocol(power_target=Decimal("0.90"))


def test_outcome_plan_cannot_enroll_before_immutable_publication() -> None:
    valid = _plan(1, origin=OutcomeOrigin.GENUINE_FORWARD)
    payload = valid.model_dump()
    payload["enrolled_at"] = valid.published_at - timedelta(seconds=1)
    with pytest.raises(ValidationError, match="enrollment cannot precede publication"):
        ProspectiveOutcomePlan.model_validate(payload)


def test_completed_outcome_recomputes_identity_time_and_decimal_returns() -> None:
    case = _case(2)
    payload = case.outcome.model_dump()
    payload["benchmark_relative_return"] = Decimal("0.999")
    with pytest.raises(ValidationError, match="returns do not match"):
        ProspectiveOutcome.model_validate(payload)

    payload = case.outcome.model_dump()
    payload["observations"]["asset_target"]["session_date"] = date(2026, 9, 30)
    with pytest.raises(ValidationError, match="identity or time"):
        ProspectiveOutcome.model_validate(payload)

    payload = case.outcome.model_dump()
    payload["observations"]["asset_target"]["retrieved_at"] = GENERATED_AT + timedelta(seconds=1)
    with pytest.raises(ValidationError, match="identity or time"):
        ProspectiveOutcome.model_validate(payload)


def test_unavailable_outcome_requires_a_reason_and_preserves_no_returns() -> None:
    case = _case(3, result="unavailable")
    assert case.outcome.status is OutcomeStatus.DATA_UNAVAILABLE
    assert case.outcome.benchmark_relative_return is None
    payload = case.outcome.model_dump()
    payload["limitations"] = ()
    with pytest.raises(ValidationError, match="explicit limitation"):
        ProspectiveOutcome.model_validate(payload)


def test_empty_report_is_honest_and_reproducible() -> None:
    report = build_outcome_science_report((), generated_at=GENERATED_AT)
    assert report.sample_size == 0
    assert report.strata == ()
    assert report.disposition is OutcomeScienceDisposition.INSUFFICIENT_SAMPLE
    assert report.case_set_sha256 == _sha("[]")


def test_forward_and_reconstructed_history_are_never_calibrated_together() -> None:
    cases = (
        _case(10, result="favorable"),
        _case(11, result="adverse"),
        _case(12, result="unavailable"),
        _case(13, origin=OutcomeOrigin.RECONSTRUCTED, result="favorable"),
    )
    report = build_outcome_science_report(cases, generated_at=GENERATED_AT)
    assert report.genuine_forward_count == 3
    assert report.genuine_forward_completed_count == 2
    assert report.genuine_forward_favorable_count == 1
    assert report.genuine_forward_adverse_count == 1
    assert report.genuine_forward_unavailable_count == 1
    assert report.reconstructed_count == 1
    assert report.reconstructed_favorable_count == 1
    assert len(report.strata) == 2
    reconstructed = next(
        item for item in report.strata if item.origin is OutcomeOrigin.RECONSTRUCTED
    )
    assert reconstructed.observed_favorable_rate is None
    assert reconstructed.wilson_lower is None
    assert reconstructed.power_sufficiency is PowerSufficiency.NOT_ASSESSED_RECONSTRUCTED


def test_non_positive_forward_outcomes_are_adverse_and_uncertainty_is_visible() -> None:
    report = build_outcome_science_report(
        (_case(20, result="favorable"), _case(21, result="adverse")),
        generated_at=GENERATED_AT,
    )
    stratum = report.strata[0]
    assert stratum.favorable_count == 1
    assert stratum.adverse_count == 1
    assert stratum.observed_favorable_rate == Decimal("0.5")
    assert stratum.wilson_lower is not None
    assert stratum.wilson_upper is not None
    assert stratum.wilson_lower < Decimal("0.5") < stratum.wilson_upper
    assert stratum.disposition is OutcomeScienceDisposition.INSUFFICIENT_SAMPLE


def test_report_does_not_pool_small_version_cohorts_to_claim_sample_sufficiency() -> None:
    first = tuple(_case(100 + index) for index in range(15))
    second = tuple(_case(200 + index, prompt_version="analyst-v1") for index in range(15))
    report = build_outcome_science_report(first + second, generated_at=GENERATED_AT)
    assert report.genuine_forward_completed_count == 30
    assert len(report.strata) == 2
    assert all(
        item.disposition is OutcomeScienceDisposition.INSUFFICIENT_SAMPLE for item in report.strata
    )
    assert report.disposition is OutcomeScienceDisposition.INSUFFICIENT_SAMPLE


def test_one_complete_forward_cohort_at_30_is_still_only_inconclusive() -> None:
    report = build_outcome_science_report(
        tuple(_case(300 + index) for index in range(30)),
        generated_at=GENERATED_AT,
    )
    assert len(report.strata) == 1
    assert report.strata[0].disposition is OutcomeScienceDisposition.INCONCLUSIVE
    assert report.strata[0].power_sufficiency is PowerSufficiency.INSUFFICIENT_SAMPLE
    assert report.disposition is OutcomeScienceDisposition.INCONCLUSIVE


def test_case_order_does_not_change_hash_or_strata() -> None:
    cases = (_case(30), _case(31, result="adverse"))
    forward = build_outcome_science_report(cases, generated_at=GENERATED_AT)
    reverse = build_outcome_science_report(tuple(reversed(cases)), generated_at=GENERATED_AT)
    assert forward.case_set_sha256 == reverse.case_set_sha256
    assert forward.strata == reverse.strata


def test_forward_enrollment_before_protocol_lock_and_mismatched_publication_fail() -> None:
    case = _case(40)
    plan_payload = case.outcome.plan.model_dump()
    plan_payload["published_at"] = OUTCOME_SCIENCE_PROTOCOL_LOCKED_AT - timedelta(days=1)
    plan_payload["enrolled_at"] = OUTCOME_SCIENCE_PROTOCOL_LOCKED_AT - timedelta(minutes=1)
    old_plan = ProspectiveOutcomePlan.model_validate(plan_payload)
    outcome_payload = case.outcome.model_dump()
    outcome_payload["plan"] = old_plan.model_dump()
    old_outcome = ProspectiveOutcome.model_validate(outcome_payload)
    old_case = OutcomeScienceCase(
        outcome=old_outcome,
        publication_version=case.publication_version.model_copy(
            update={"published_at": old_plan.published_at}
        ),
    )
    with pytest.raises(ValueError, match="predates the science protocol lock"):
        build_outcome_science_report((old_case,), generated_at=GENERATED_AT)

    with pytest.raises(ValidationError, match="publication lineage"):
        OutcomeScienceCase(
            outcome=case.outcome,
            publication_version=case.publication_version.model_copy(
                update={"asset_symbol": "MSFT"}
            ),
        )


def test_contracts_reject_forged_statistics_and_origin_totals() -> None:
    report = build_outcome_science_report((_case(50),), generated_at=GENERATED_AT)
    stratum_payload = report.strata[0].model_dump()
    stratum_payload["observed_favorable_rate"] = Decimal("0.2")
    with pytest.raises(ValidationError, match="statistics do not match"):
        OutcomeScienceStratum.model_validate(stratum_payload)

    report_payload = report.model_dump()
    report_payload["genuine_forward_favorable_count"] = 0
    with pytest.raises(ValidationError, match="origin totals"):
        OutcomeScienceReport.model_validate(report_payload)


def test_private_population_accounts_for_terminal_future_and_due_plans() -> None:
    terminal = _case(60)
    due = _case(61, origin=OutcomeOrigin.RECONSTRUCTED)
    future_plan = ExchangeSessionPlanner().plan(
        publication_id=_publication_id(62),
        published_at=GENERATED_AT - timedelta(minutes=2),
        asset_symbol="AAPL",
        asset_mic="XNAS",
        benchmark_symbol="SPY",
        benchmark_mic="ARCX",
        calendar_name="XNYS",
        currency=CurrencyCode.US_DOLLAR,
        enrolled_at=GENERATED_AT - timedelta(minutes=1),
        horizon=OutcomeHorizon.T1,
    )
    future_version = terminal.publication_version.model_copy(
        update={
            "publication_id": future_plan.publication_id,
            "published_at": future_plan.published_at,
            "accession_number": "0000000001-26-000062",
            "source_document_sha256": _sha("source-62"),
        }
    )
    rows = (
        {
            "plan_record": terminal.outcome.plan.model_dump(mode="json"),
            "outcome_record": terminal.outcome.model_dump(mode="json"),
            "publication_record": _brief(terminal).model_dump(mode="json"),
        },
        {
            "plan_record": due.outcome.plan.model_dump(mode="json"),
            "outcome_record": None,
            "publication_record": _brief(due).model_dump(mode="json"),
        },
        {
            "plan_record": future_plan.model_dump(mode="json"),
            "outcome_record": None,
            "publication_record": _brief(
                terminal,
                plan_override=future_plan,
                version_override=future_version,
            ).model_dump(mode="json"),
        },
    )
    population = build_outcome_science_population(
        rows,
        knowledge_cutoff_at=GENERATED_AT,
    )
    assert population.enrolled_plan_count == 3
    assert population.terminal_outcome_count == 1
    assert population.due_without_outcome_count == 1
    assert population.not_yet_due_plan_count == 1
    snapshot = build_outcome_science_snapshot(population)
    operations = outcome_science_operations(snapshot)
    assert snapshot.report.sample_size == 1
    assert operations.enrolled_plan_count == 3
    assert operations.terminal_outcome_count == 1
    assert operations.due_without_outcome_count == 1
    assert len(operations.strata) == 1
    assert len(operations.strata[0].cohort_sha256) == 64
    assert not hasattr(operations, "cases")
    assert not hasattr(operations, "case_set_sha256")
    assert (
        snapshot.report.case_set_sha256
        == build_outcome_science_report(
            population.cases,
            generated_at=GENERATED_AT,
        ).case_set_sha256
    )


def test_private_population_rejects_orphan_and_conflicting_immutable_records() -> None:
    first = _case(70)
    second = _case(71)
    with pytest.raises(ValueError, match="no immutable publication"):
        build_outcome_science_population(
            (
                {
                    "plan_record": first.outcome.plan.model_dump(mode="json"),
                    "outcome_record": first.outcome.model_dump(mode="json"),
                    "publication_record": None,
                },
            ),
            knowledge_cutoff_at=GENERATED_AT,
        )
    with pytest.raises(ValueError, match="does not match its stored plan"):
        build_outcome_science_population(
            (
                {
                    "plan_record": first.outcome.plan.model_dump(mode="json"),
                    "outcome_record": second.outcome.model_dump(mode="json"),
                    "publication_record": _brief(first).model_dump(mode="json"),
                },
            ),
            knowledge_cutoff_at=GENERATED_AT,
        )


def test_empty_private_population_builds_the_truthful_production_shape() -> None:
    population = build_outcome_science_population((), knowledge_cutoff_at=GENERATED_AT)
    snapshot = build_outcome_science_snapshot(population)
    operations = outcome_science_operations(snapshot)
    assert population.enrolled_plan_count == 0
    assert snapshot.report.disposition is OutcomeScienceDisposition.INSUFFICIENT_SAMPLE
    assert snapshot.report.sample_size == 0
    assert operations.strata == ()
    assert operations.disposition == "INSUFFICIENT_SAMPLE"
    assert OutcomeScienceSnapshot.model_json_schema()["additionalProperties"] is False
