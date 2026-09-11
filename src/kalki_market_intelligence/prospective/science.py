"""Pre-registered, version-stratified science over prospective supporting outcomes."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal, localcontext
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from kalki_market_intelligence.contracts.common import (
    ContractModel,
    Sha256Hex,
    ShortText,
    UtcDatetime,
)
from kalki_market_intelligence.prospective.contracts import (
    OutcomeHorizon,
    OutcomeOrigin,
    OutcomeStatus,
    ProspectiveOutcome,
)
from kalki_market_intelligence.quantitative.algorithms import CALCULATION_CONTEXT
from kalki_market_intelligence.radar.contracts import (
    AccessionNumber,
    RadarClassification,
    ResearchBrief,
    TickerText,
)

OUTCOME_SCIENCE_PROTOCOL_VERSION: Literal["outcome-science-v1"] = "outcome-science-v1"
OUTCOME_SCIENCE_PROTOCOL_LOCKED_AT = datetime(2026, 9, 8, 0, 17, tzinfo=UTC)
MINIMUM_CALIBRATION_SAMPLE = 30

# Fixed before any supporting market-data outcome existed. The one-sample design asks
# whether a homogeneous stratum's positive benchmark-relative rate differs from 0.50 by
# at least 0.10, using a two-sided 5% type-I error rate and 80% target power. The normal
# approximation produces 194. Power sufficiency is reported, never treated as proof of
# economic value or described as market alpha.
POWER_NULL_RATE = Decimal("0.50")
POWER_ALTERNATIVE_RATE = Decimal("0.60")
POWER_TWO_SIDED_TYPE_I_ERROR = Decimal("0.05")
POWER_TARGET = Decimal("0.80")
POWER_Z_ALPHA_OVER_TWO = Decimal("1.959963984540054")
POWER_Z_BETA = Decimal("0.841621233572914")

type OutcomeScienceStratumKey = tuple[
    OutcomeHorizon,
    OutcomeOrigin,
    str,
    str,
    RadarClassification,
    str,
    str,
    str,
    str,
    str,
    str,
    str,
    str,
]


class OutcomeScienceDisposition(StrEnum):
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    INCONCLUSIVE = "INCONCLUSIVE"


class PowerSufficiency(StrEnum):
    NOT_ASSESSED_RECONSTRUCTED = "NOT_ASSESSED_RECONSTRUCTED"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    SUFFICIENT_FOR_PREREGISTERED_DESIGN = "SUFFICIENT_FOR_PREREGISTERED_DESIGN"


class OutcomeScienceProtocol(ContractModel):
    """Immutable analysis choices locked before eligible forward enrollment."""

    protocol_version: Literal["outcome-science-v1"] = OUTCOME_SCIENCE_PROTOCOL_VERSION
    locked_at: UtcDatetime = OUTCOME_SCIENCE_PROTOCOL_LOCKED_AT
    horizons: tuple[OutcomeHorizon, ...] = (
        OutcomeHorizon.T1,
        OutcomeHorizon.T5,
        OutcomeHorizon.T20,
    )
    horizon_unit: Literal["complete_exchange_sessions_after_reference_close"] = (
        "complete_exchange_sessions_after_reference_close"
    )
    reference_definition: Literal["first_exchange_close_at_or_after_publication"] = (
        "first_exchange_close_at_or_after_publication"
    )
    return_definition: Literal[
        "split_adjusted_price_return_and_asset_minus_benchmark_price_return"
    ] = "split_adjusted_price_return_and_asset_minus_benchmark_price_return"
    favorable_definition: Literal["benchmark_relative_return_gt_zero"] = (
        "benchmark_relative_return_gt_zero"
    )
    non_positive_definition: Literal["adverse_including_zero"] = "adverse_including_zero"
    unavailable_policy: Literal["retain_in_sample_exclude_from_rate_denominator"] = (
        "retain_in_sample_exclude_from_rate_denominator"
    )
    calibration_origin: Literal[OutcomeOrigin.GENUINE_FORWARD] = OutcomeOrigin.GENUINE_FORWARD
    reconstructed_policy: Literal["report_separately_never_calibrate_or_assess_power"] = (
        "report_separately_never_calibrate_or_assess_power"
    )
    stratification_dimensions: tuple[
        Literal[
            "horizon",
            "origin",
            "publication_schema",
            "signal_ruleset",
            "signal_classification",
            "analysis_model",
            "analysis_prompt",
            "outcome_methodology",
            "outcome_calculation",
            "outcome_schema",
            "provider",
            "provider_terms",
        ],
        ...,
    ] = (
        "horizon",
        "origin",
        "publication_schema",
        "signal_ruleset",
        "signal_classification",
        "analysis_model",
        "analysis_prompt",
        "outcome_methodology",
        "outcome_calculation",
        "outcome_schema",
        "provider",
        "provider_terms",
    )
    benchmark_symbol: Literal["SPY"] = "SPY"
    benchmark_mic: Literal["ARCX"] = "ARCX"
    confidence_interval: Literal["two_sided_95_percent_wilson"] = "two_sided_95_percent_wilson"
    minimum_calibration_sample: Literal[30] = 30
    power_null_rate: Decimal = POWER_NULL_RATE
    power_alternative_rate: Decimal = POWER_ALTERNATIVE_RATE
    power_two_sided_type_i_error: Decimal = POWER_TWO_SIDED_TYPE_I_ERROR
    power_target: Decimal = POWER_TARGET
    power_required_sample: Literal[194] = 194
    inference_policy: Literal["descriptive_only_never_market_alpha_or_trading_claim"] = (
        "descriptive_only_never_market_alpha_or_trading_claim"
    )

    @model_validator(mode="after")
    def policy_is_exactly_preregistered(self) -> Self:
        if self.locked_at != OUTCOME_SCIENCE_PROTOCOL_LOCKED_AT:
            raise ValueError("outcome-science protocol lock cannot be changed")
        if self.horizons != (OutcomeHorizon.T1, OutcomeHorizon.T5, OutcomeHorizon.T20):
            raise ValueError("outcome-science horizons must remain T+1/T+5/T+20")
        if self.stratification_dimensions != (
            "horizon",
            "origin",
            "publication_schema",
            "signal_ruleset",
            "signal_classification",
            "analysis_model",
            "analysis_prompt",
            "outcome_methodology",
            "outcome_calculation",
            "outcome_schema",
            "provider",
            "provider_terms",
        ):
            raise ValueError("outcome-science version strata cannot be changed")
        power_values = (
            self.power_null_rate,
            self.power_alternative_rate,
            self.power_two_sided_type_i_error,
            self.power_target,
        )
        if power_values != (
            POWER_NULL_RATE,
            POWER_ALTERNATIVE_RATE,
            POWER_TWO_SIDED_TYPE_I_ERROR,
            POWER_TARGET,
        ):
            raise ValueError("outcome-science power design cannot be changed")
        if self.power_required_sample != required_power_sample():
            raise ValueError("outcome-science power sample is inconsistent")
        return self


class OutcomePublicationVersion(ContractModel):
    """The immutable publication lineage used to stratify an outcome."""

    publication_id: UUID
    published_at: UtcDatetime
    accession_number: AccessionNumber
    asset_symbol: TickerText
    source_document_sha256: Sha256Hex
    publication_schema_version: ShortText
    signal_ruleset_version: ShortText
    signal_classification: RadarClassification
    analysis_model_name: ShortText
    analysis_model_digest: Sha256Hex
    analysis_prompt_version: ShortText

    @classmethod
    def from_brief(cls, brief: ResearchBrief) -> OutcomePublicationVersion:
        if brief.ticker is None:
            raise ValueError("an outcome publication requires a resolved asset symbol")
        return cls(
            publication_id=brief.brief_id,
            published_at=brief.published_at,
            accession_number=brief.accession_number,
            asset_symbol=brief.ticker,
            source_document_sha256=brief.source_document_sha256,
            publication_schema_version=brief.schema_version,
            signal_ruleset_version=brief.scoring_version,
            signal_classification=brief.classification,
            analysis_model_name=brief.model_name,
            analysis_model_digest=brief.model_digest,
            analysis_prompt_version=brief.prompt_version,
        )


class OutcomeScienceCase(ContractModel):
    outcome: ProspectiveOutcome
    publication_version: OutcomePublicationVersion

    @model_validator(mode="after")
    def publication_matches_outcome(self) -> Self:
        if (
            self.outcome.plan.publication_id != self.publication_version.publication_id
            or self.outcome.plan.published_at != self.publication_version.published_at
            or self.outcome.plan.asset_symbol != self.publication_version.asset_symbol
        ):
            raise ValueError("outcome-science publication lineage does not match outcome")
        return self


class OutcomeSciencePopulation(ContractModel):
    """Point-in-time plan coverage and terminal cases available to science."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    knowledge_cutoff_at: UtcDatetime
    enrolled_plan_count: int = Field(ge=0)
    terminal_outcome_count: int = Field(ge=0)
    not_yet_due_plan_count: int = Field(ge=0)
    due_without_outcome_count: int = Field(ge=0)
    cases: tuple[OutcomeScienceCase, ...] = Field(max_length=100_000)

    @model_validator(mode="after")
    def point_in_time_coverage_is_complete(self) -> Self:
        if self.terminal_outcome_count != len(self.cases):
            raise ValueError("outcome-science terminal count does not match cases")
        if self.enrolled_plan_count != (
            self.terminal_outcome_count
            + self.not_yet_due_plan_count
            + self.due_without_outcome_count
        ):
            raise ValueError("outcome-science plan coverage counts do not reconcile")
        plan_keys = tuple(
            (
                item.outcome.plan.publication_id,
                item.outcome.plan.horizon,
                item.outcome.plan.provider_name,
            )
            for item in self.cases
        )
        if len(set(plan_keys)) != len(plan_keys):
            raise ValueError("outcome-science population contains duplicate plans")
        if any(
            item.outcome.plan.enrolled_at > self.knowledge_cutoff_at
            or item.outcome.appended_at > self.knowledge_cutoff_at
            for item in self.cases
        ):
            raise ValueError("outcome-science population leaks records after its cutoff")
        return self


class OutcomeScienceStratum(ContractModel):
    horizon: OutcomeHorizon
    origin: OutcomeOrigin
    publication_schema_version: ShortText
    signal_ruleset_version: ShortText
    signal_classification: RadarClassification
    analysis_model_name: ShortText
    analysis_model_digest: Sha256Hex
    analysis_prompt_version: ShortText
    outcome_methodology_version: ShortText
    outcome_calculation_version: ShortText
    outcome_schema_version: ShortText
    provider_name: ShortText
    provider_terms_version: ShortText
    sample_size: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    unavailable_count: int = Field(ge=0)
    favorable_count: int = Field(ge=0)
    adverse_count: int = Field(ge=0)
    observed_favorable_rate: Decimal | None
    wilson_lower: Decimal | None
    wilson_upper: Decimal | None
    power_sufficiency: PowerSufficiency
    disposition: OutcomeScienceDisposition

    @model_validator(mode="after")
    def counts_and_statistics_are_consistent(self) -> Self:
        if self.completed_count + self.unavailable_count != self.sample_size:
            raise ValueError("outcome-science availability counts do not equal sample size")
        if self.favorable_count + self.adverse_count != self.completed_count:
            raise ValueError("outcome-science result counts do not equal completed count")
        expected_rate = (
            Decimal(self.favorable_count) / Decimal(self.completed_count)
            if self.completed_count
            else None
        )
        expected_lower, expected_upper = _wilson(self.favorable_count, self.completed_count)
        statistics = (
            self.observed_favorable_rate,
            self.wilson_lower,
            self.wilson_upper,
        )
        if self.origin is OutcomeOrigin.RECONSTRUCTED:
            if any(value is not None for value in statistics):
                raise ValueError("reconstructed outcomes cannot emit calibration statistics")
            if self.power_sufficiency is not PowerSufficiency.NOT_ASSESSED_RECONSTRUCTED:
                raise ValueError("reconstructed outcome power must not be assessed")
            if self.disposition is not OutcomeScienceDisposition.INCONCLUSIVE:
                raise ValueError("reconstructed outcome strata must remain inconclusive")
            return self
        if statistics != (expected_rate, expected_lower, expected_upper):
            raise ValueError("forward calibration statistics do not match exact counts")
        expected_power = (
            PowerSufficiency.SUFFICIENT_FOR_PREREGISTERED_DESIGN
            if self.completed_count >= required_power_sample()
            else PowerSufficiency.INSUFFICIENT_SAMPLE
        )
        if self.power_sufficiency is not expected_power:
            raise ValueError("forward power sufficiency does not match exact counts")
        expected_disposition = (
            OutcomeScienceDisposition.INCONCLUSIVE
            if self.completed_count >= MINIMUM_CALIBRATION_SAMPLE
            else OutcomeScienceDisposition.INSUFFICIENT_SAMPLE
        )
        if self.disposition is not expected_disposition:
            raise ValueError("forward disposition does not match exact counts")
        return self


class OutcomeScienceReport(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    generated_at: UtcDatetime
    knowledge_cutoff_at: UtcDatetime
    protocol: OutcomeScienceProtocol
    case_set_sha256: Sha256Hex
    sample_size: int = Field(ge=0)
    genuine_forward_count: int = Field(ge=0)
    reconstructed_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    unavailable_count: int = Field(ge=0)
    favorable_count: int = Field(ge=0)
    adverse_count: int = Field(ge=0)
    genuine_forward_completed_count: int = Field(ge=0)
    genuine_forward_unavailable_count: int = Field(ge=0)
    genuine_forward_favorable_count: int = Field(ge=0)
    genuine_forward_adverse_count: int = Field(ge=0)
    reconstructed_completed_count: int = Field(ge=0)
    reconstructed_unavailable_count: int = Field(ge=0)
    reconstructed_favorable_count: int = Field(ge=0)
    reconstructed_adverse_count: int = Field(ge=0)
    strata: tuple[OutcomeScienceStratum, ...]
    disposition: OutcomeScienceDisposition
    limitations: tuple[ShortText, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def report_counts_are_consistent(self) -> Self:
        if self.generated_at != self.knowledge_cutoff_at:
            raise ValueError("outcome-science generation and knowledge cutoff must match")
        if self.generated_at < self.protocol.locked_at:
            raise ValueError("outcome-science report predates its locked protocol")
        if self.genuine_forward_count + self.reconstructed_count != self.sample_size:
            raise ValueError("outcome-science origin counts do not equal sample size")
        if self.completed_count + self.unavailable_count != self.sample_size:
            raise ValueError("outcome-science availability counts do not equal sample size")
        if self.favorable_count + self.adverse_count != self.completed_count:
            raise ValueError("outcome-science result counts do not equal completed count")
        if sum(item.sample_size for item in self.strata) != self.sample_size:
            raise ValueError("outcome-science strata do not cover the report sample")
        stratum_keys = tuple(
            (
                item.horizon,
                item.origin,
                item.publication_schema_version,
                item.signal_ruleset_version,
                item.signal_classification,
                item.analysis_model_name,
                item.analysis_model_digest,
                item.analysis_prompt_version,
                item.outcome_methodology_version,
                item.outcome_calculation_version,
                item.outcome_schema_version,
                item.provider_name,
                item.provider_terms_version,
            )
            for item in self.strata
        )
        if len(set(stratum_keys)) != len(stratum_keys):
            raise ValueError("outcome-science strata must be unique")
        forward = tuple(
            item for item in self.strata if item.origin is OutcomeOrigin.GENUINE_FORWARD
        )
        reconstructed = tuple(
            item for item in self.strata if item.origin is OutcomeOrigin.RECONSTRUCTED
        )
        expected_counts = (
            sum(item.sample_size for item in forward),
            sum(item.sample_size for item in reconstructed),
            sum(item.completed_count for item in forward),
            sum(item.unavailable_count for item in forward),
            sum(item.favorable_count for item in forward),
            sum(item.adverse_count for item in forward),
            sum(item.completed_count for item in reconstructed),
            sum(item.unavailable_count for item in reconstructed),
            sum(item.favorable_count for item in reconstructed),
            sum(item.adverse_count for item in reconstructed),
        )
        actual_counts = (
            self.genuine_forward_count,
            self.reconstructed_count,
            self.genuine_forward_completed_count,
            self.genuine_forward_unavailable_count,
            self.genuine_forward_favorable_count,
            self.genuine_forward_adverse_count,
            self.reconstructed_completed_count,
            self.reconstructed_unavailable_count,
            self.reconstructed_favorable_count,
            self.reconstructed_adverse_count,
        )
        if actual_counts != expected_counts:
            raise ValueError("outcome-science origin totals do not reconcile to strata")
        if (
            self.completed_count
            != self.genuine_forward_completed_count + self.reconstructed_completed_count
            or self.unavailable_count
            != self.genuine_forward_unavailable_count + self.reconstructed_unavailable_count
            or self.favorable_count
            != self.genuine_forward_favorable_count + self.reconstructed_favorable_count
            or self.adverse_count
            != self.genuine_forward_adverse_count + self.reconstructed_adverse_count
        ):
            raise ValueError("outcome-science total counts do not reconcile by origin")
        expected_disposition = (
            OutcomeScienceDisposition.INCONCLUSIVE
            if any(item.disposition is OutcomeScienceDisposition.INCONCLUSIVE for item in forward)
            else OutcomeScienceDisposition.INSUFFICIENT_SAMPLE
        )
        if self.disposition is not expected_disposition:
            raise ValueError("outcome-science report cannot pool version strata")
        return self


class OutcomeScienceSnapshot(ContractModel):
    """One private point-in-time population plus its deterministic report."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    population: OutcomeSciencePopulation
    report: OutcomeScienceReport

    @model_validator(mode="after")
    def population_and_report_reconcile(self) -> Self:
        if self.population.knowledge_cutoff_at != self.report.knowledge_cutoff_at:
            raise ValueError("outcome-science population and report cutoffs differ")
        if self.report.sample_size != self.population.terminal_outcome_count:
            raise ValueError("outcome-science report omits terminal population cases")
        if self.report.case_set_sha256 != _case_set_sha256(self.population.cases):
            raise ValueError("outcome-science report case hash does not match population")
        return self


def required_power_sample() -> int:
    """Return the fixed design's normal-approximation sample requirement."""

    with localcontext(CALCULATION_CONTEXT):
        null_variance = POWER_NULL_RATE * (Decimal(1) - POWER_NULL_RATE)
        alternative_variance = POWER_ALTERNATIVE_RATE * (Decimal(1) - POWER_ALTERNATIVE_RATE)
        numerator = (
            POWER_Z_ALPHA_OVER_TWO * null_variance.sqrt()
            + POWER_Z_BETA * alternative_variance.sqrt()
        ) ** 2
        difference = POWER_ALTERNATIVE_RATE - POWER_NULL_RATE
        value = numerator / (difference * difference)
        return int(value.to_integral_value(rounding=ROUND_CEILING))


def _wilson(favorable: int, total: int) -> tuple[Decimal | None, Decimal | None]:
    if total == 0:
        return None, None
    with localcontext(CALCULATION_CONTEXT):
        n = Decimal(total)
        proportion = Decimal(favorable) / n
        denominator = Decimal(1) + POWER_Z_ALPHA_OVER_TWO**2 / n
        center = (proportion + POWER_Z_ALPHA_OVER_TWO**2 / (Decimal(2) * n)) / denominator
        margin = (
            POWER_Z_ALPHA_OVER_TWO
            * (
                proportion * (Decimal(1) - proportion) / n
                + POWER_Z_ALPHA_OVER_TWO**2 / (Decimal(4) * n * n)
            ).sqrt()
            / denominator
        )
        return max(Decimal(0), center - margin), min(Decimal(1), center + margin)


def _case_set_sha256(cases: tuple[OutcomeScienceCase, ...]) -> str:
    payload = [
        item.model_dump(mode="json")
        for item in sorted(cases, key=lambda item: str(item.outcome.outcome_id))
    ]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_outcome_science_report(
    cases: tuple[OutcomeScienceCase, ...],
    *,
    generated_at: datetime,
    protocol: OutcomeScienceProtocol | None = None,
) -> OutcomeScienceReport:
    """Build a deterministic report without combining origins or version cohorts."""

    policy = protocol or OutcomeScienceProtocol()
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("outcome-science report timestamp must be timezone-aware")
    generated_utc = generated_at.astimezone(UTC)
    if generated_utc < policy.locked_at:
        raise ValueError("outcome-science report cannot predate its locked protocol")
    outcome_ids = tuple(item.outcome.outcome_id for item in cases)
    plan_keys = tuple(
        (
            item.outcome.plan.publication_id,
            item.outcome.plan.horizon,
            item.outcome.plan.provider_name,
        )
        for item in cases
    )
    if len(set(outcome_ids)) != len(outcome_ids) or len(set(plan_keys)) != len(plan_keys):
        raise ValueError("outcome-science cases must be unique")
    if any(item.outcome.appended_at > generated_utc for item in cases):
        raise ValueError("outcome-science report cannot include future-appended outcomes")
    if any(
        item.outcome.plan.origin is OutcomeOrigin.GENUINE_FORWARD
        and item.outcome.plan.enrolled_at < policy.locked_at
        for item in cases
    ):
        raise ValueError("forward outcome enrollment predates the science protocol lock")
    if any(
        item.outcome.plan.benchmark_symbol != policy.benchmark_symbol
        or item.outcome.plan.benchmark_mic != policy.benchmark_mic
        or item.outcome.plan.horizon not in policy.horizons
        for item in cases
    ):
        raise ValueError("outcome does not match the preregistered benchmark or horizons")

    grouped: defaultdict[OutcomeScienceStratumKey, list[OutcomeScienceCase]] = defaultdict(list)
    for item in cases:
        version = item.publication_version
        outcome = item.outcome
        group_key = (
            outcome.plan.horizon,
            outcome.plan.origin,
            version.publication_schema_version,
            version.signal_ruleset_version,
            version.signal_classification,
            version.analysis_model_name,
            version.analysis_model_digest,
            version.analysis_prompt_version,
            outcome.plan.methodology_version,
            outcome.calculation_version,
            outcome.schema_version,
            outcome.plan.provider_name,
            outcome.plan.provider_terms_version,
        )
        grouped[group_key].append(item)

    strata: list[OutcomeScienceStratum] = []
    for stratum_key in sorted(grouped, key=lambda value: tuple(str(item) for item in value)):
        selected = grouped[stratum_key]
        completed = [item for item in selected if item.outcome.status is OutcomeStatus.COMPLETED]
        favorable = sum(
            item.outcome.benchmark_relative_return is not None
            and item.outcome.benchmark_relative_return > 0
            for item in completed
        )
        adverse = len(completed) - favorable
        origin = stratum_key[1]
        assert isinstance(origin, OutcomeOrigin)
        if origin is OutcomeOrigin.GENUINE_FORWARD:
            rate = Decimal(favorable) / Decimal(len(completed)) if completed else None
            lower, upper = _wilson(favorable, len(completed))
            power = (
                PowerSufficiency.SUFFICIENT_FOR_PREREGISTERED_DESIGN
                if len(completed) >= policy.power_required_sample
                else PowerSufficiency.INSUFFICIENT_SAMPLE
            )
            disposition = (
                OutcomeScienceDisposition.INCONCLUSIVE
                if len(completed) >= policy.minimum_calibration_sample
                else OutcomeScienceDisposition.INSUFFICIENT_SAMPLE
            )
        else:
            rate = lower = upper = None
            power = PowerSufficiency.NOT_ASSESSED_RECONSTRUCTED
            disposition = OutcomeScienceDisposition.INCONCLUSIVE
        strata.append(
            OutcomeScienceStratum(
                horizon=stratum_key[0],
                origin=origin,
                publication_schema_version=stratum_key[2],
                signal_ruleset_version=stratum_key[3],
                signal_classification=stratum_key[4],
                analysis_model_name=stratum_key[5],
                analysis_model_digest=stratum_key[6],
                analysis_prompt_version=stratum_key[7],
                outcome_methodology_version=stratum_key[8],
                outcome_calculation_version=stratum_key[9],
                outcome_schema_version=stratum_key[10],
                provider_name=stratum_key[11],
                provider_terms_version=stratum_key[12],
                sample_size=len(selected),
                completed_count=len(completed),
                unavailable_count=len(selected) - len(completed),
                favorable_count=favorable,
                adverse_count=adverse,
                observed_favorable_rate=rate,
                wilson_lower=lower,
                wilson_upper=upper,
                power_sufficiency=power,
                disposition=disposition,
            )
        )

    completed_cases = [item for item in cases if item.outcome.status is OutcomeStatus.COMPLETED]
    favorable_count = sum(
        item.outcome.benchmark_relative_return is not None
        and item.outcome.benchmark_relative_return > 0
        for item in completed_cases
    )
    forward_cases = tuple(
        item for item in cases if item.outcome.plan.origin is OutcomeOrigin.GENUINE_FORWARD
    )
    reconstructed_cases = tuple(
        item for item in cases if item.outcome.plan.origin is OutcomeOrigin.RECONSTRUCTED
    )
    forward_completed_cases = tuple(
        item for item in forward_cases if item.outcome.status is OutcomeStatus.COMPLETED
    )
    reconstructed_completed_cases = tuple(
        item for item in reconstructed_cases if item.outcome.status is OutcomeStatus.COMPLETED
    )
    forward_favorable = sum(
        item.outcome.benchmark_relative_return is not None
        and item.outcome.benchmark_relative_return > 0
        for item in forward_completed_cases
    )
    reconstructed_favorable = sum(
        item.outcome.benchmark_relative_return is not None
        and item.outcome.benchmark_relative_return > 0
        for item in reconstructed_completed_cases
    )
    return OutcomeScienceReport(
        generated_at=generated_utc,
        knowledge_cutoff_at=generated_utc,
        protocol=policy,
        case_set_sha256=_case_set_sha256(cases),
        sample_size=len(cases),
        genuine_forward_count=len(forward_cases),
        reconstructed_count=len(reconstructed_cases),
        completed_count=len(completed_cases),
        unavailable_count=len(cases) - len(completed_cases),
        favorable_count=favorable_count,
        adverse_count=len(completed_cases) - favorable_count,
        genuine_forward_completed_count=len(forward_completed_cases),
        genuine_forward_unavailable_count=len(forward_cases) - len(forward_completed_cases),
        genuine_forward_favorable_count=forward_favorable,
        genuine_forward_adverse_count=len(forward_completed_cases) - forward_favorable,
        reconstructed_completed_count=len(reconstructed_completed_cases),
        reconstructed_unavailable_count=len(reconstructed_cases)
        - len(reconstructed_completed_cases),
        reconstructed_favorable_count=reconstructed_favorable,
        reconstructed_adverse_count=len(reconstructed_completed_cases) - reconstructed_favorable,
        strata=tuple(strata),
        disposition=(
            OutcomeScienceDisposition.INCONCLUSIVE
            if any(
                item.origin is OutcomeOrigin.GENUINE_FORWARD
                and item.disposition is OutcomeScienceDisposition.INCONCLUSIVE
                for item in strata
            )
            else OutcomeScienceDisposition.INSUFFICIENT_SAMPLE
        ),
        limitations=(
            "Supporting split-adjusted price returns are not authoritative evidence "
            "or total returns.",
            "Reconstructed outcomes are counted but excluded from calibration and "
            "power assessment.",
            "Each calibration row is isolated by horizon, signal class, and complete "
            "version lineage.",
            "Unavailable and non-positive benchmark-relative outcomes remain visible.",
            "Results are descriptive only and never establish market alpha or a "
            "trading instruction.",
        ),
    )


def build_outcome_science_snapshot(
    population: OutcomeSciencePopulation,
    *,
    protocol: OutcomeScienceProtocol | None = None,
) -> OutcomeScienceSnapshot:
    """Build the private report from one complete point-in-time population."""

    report = build_outcome_science_report(
        population.cases,
        generated_at=population.knowledge_cutoff_at,
        protocol=protocol,
    )
    return OutcomeScienceSnapshot(population=population, report=report)
