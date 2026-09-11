"""Source-specific eligibility for private deterministic convergence receipts."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from kalki_market_intelligence.contracts.common import ContractModel, UtcDatetime
from kalki_market_intelligence.forensics.contradictions import (
    ClaimUnderReview,
    ContradictionFact,
    ContradictionFamily,
    ContradictionPredicate,
    financing_contradiction_facts,
    liquidity_contradiction_facts,
    ownership_contradiction_facts,
)
from kalki_market_intelligence.forensics.convergence_service import (
    ConvergenceFactCompleteness,
    ConvergenceValidationRequest,
)
from kalki_market_intelligence.forensics.detectors import ForensicInput
from kalki_market_intelligence.forensics.financing import (
    FinancingFilingReceipt,
    FinancingTier0Receipt,
    choose_financing_tier,
)
from kalki_market_intelligence.forensics.ownership import (
    OwnershipTier0Receipt,
    choose_ownership_tier,
)
from kalki_market_intelligence.providers.sec.contracts import (
    AccessionNumber,
    Cik,
    SecFactRecord,
)
from kalki_market_intelligence.providers.sec.ownership import (
    OwnershipFilingReceipt,
    OwnershipForm,
)

CONVERGENCE_PRODUCER_VERSION = "convergence-producers-v1"
_CLAIM_NAMESPACE = UUID("43000000-0000-4000-8000-000000000045")
_EVIDENCE_NAMESPACE = UUID("43000000-0000-4000-8000-000000000046")


class ConvergenceProducerSource(StrEnum):
    XBRL_LIQUIDITY = "XBRL_LIQUIDITY"
    FINANCING = "FINANCING"
    OWNERSHIP_SECTION_16 = "OWNERSHIP_SECTION_16"
    OWNERSHIP_FORM_144 = "OWNERSHIP_FORM_144"


class ConvergenceProducerReason(StrEnum):
    ELIGIBLE_COMPLETE_FACTS = "ELIGIBLE_COMPLETE_FACTS"
    ELIGIBLE_NOT_APPLICABLE_CONTEXT = "ELIGIBLE_NOT_APPLICABLE_CONTEXT"
    NO_RELEVANT_VALIDATED_FACTS = "NO_RELEVANT_VALIDATED_FACTS"
    AMBIGUOUS_XBRL_CONTEXT = "AMBIGUOUS_XBRL_CONTEXT"
    UNSUPPORTED_SOURCE_CONTEXT = "UNSUPPORTED_SOURCE_CONTEXT"


class ConvergenceProducerDecision(ContractModel):
    """Content-free closed decision preceding optional receipt persistence."""

    source: ConvergenceProducerSource
    source_record_id: str = Field(min_length=1, max_length=255)
    source_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: ConvergenceProducerReason
    requests: tuple[ConvergenceValidationRequest, ...] = Field(default=(), max_length=16)
    producer_version: str = CONVERGENCE_PRODUCER_VERSION

    @model_validator(mode="after")
    def decision_is_closed(self) -> ConvergenceProducerDecision:
        eligible = self.reason in {
            ConvergenceProducerReason.ELIGIBLE_COMPLETE_FACTS,
            ConvergenceProducerReason.ELIGIBLE_NOT_APPLICABLE_CONTEXT,
        }
        if eligible != bool(self.requests):
            raise ValueError("producer eligibility must match request presence")
        if self.producer_version != CONVERGENCE_PRODUCER_VERSION:
            raise ValueError("unsupported convergence producer version")
        return self


def financing_convergence_decision(
    receipt: FinancingFilingReceipt,
    routing: FinancingTier0Receipt,
    *,
    knowledge_cutoff_at: UtcDatetime,
) -> ConvergenceProducerDecision:
    """Admit only explicit, active, issuable financing exposure."""

    receipt = FinancingFilingReceipt.model_validate(receipt.model_dump(mode="json"))
    routing = FinancingTier0Receipt.model_validate(routing.model_dump(mode="json"))
    if choose_financing_tier(receipt) != routing:
        raise ValueError("financing routing does not revalidate from its filing receipt")
    source_hash = _record_hash(routing)
    facts = financing_contradiction_facts(receipt)
    if not facts:
        return _decision(
            ConvergenceProducerSource.FINANCING,
            f"financing-routing:{receipt.accession_number}",
            source_hash,
            ConvergenceProducerReason.NO_RELEVANT_VALIDATED_FACTS,
        )
    request = _request(
        issuer_cik=receipt.issuer_cik,
        predicate=ContradictionPredicate.DILUTION_EXPOSURE_PRESENT,
        asserted_truth=True,
        comparison_scope_id=facts[0].comparison_scope_id,
        as_of_date=receipt.accepted_at.date(),
        available_at=receipt.accepted_at,
        retrieved_at=receipt.retrieved_at,
        source_record_id=f"financing-routing:{receipt.accession_number}",
        source_content_sha256=source_hash,
        facts=facts,
        knowledge_cutoff_at=knowledge_cutoff_at,
        completeness=ConvergenceFactCompleteness.REQUIRED_FACTS_COMPLETE,
    )
    return _decision(
        ConvergenceProducerSource.FINANCING,
        f"financing-routing:{receipt.accession_number}",
        source_hash,
        ConvergenceProducerReason.ELIGIBLE_COMPLETE_FACTS,
        (request,),
    )


def ownership_convergence_decision(
    receipt: OwnershipFilingReceipt,
    routing: OwnershipTier0Receipt,
    *,
    knowledge_cutoff_at: UtcDatetime,
    previous_schedule_form: OwnershipForm | None = None,
) -> ConvergenceProducerDecision:
    """Admit exact Section 16 scopes or Form 144 not-applicable context."""

    receipt = OwnershipFilingReceipt.model_validate(receipt.model_dump(mode="json"))
    routing = OwnershipTier0Receipt.model_validate(routing.model_dump(mode="json"))
    if choose_ownership_tier(receipt, previous_schedule_form=previous_schedule_form) != routing:
        raise ValueError("ownership routing does not revalidate from its filing receipt")
    source_hash = _record_hash(routing)
    source_record_id = f"ownership-routing:{receipt.accession_number}"
    if receipt.form.is_schedule_13d or receipt.form.is_schedule_13g:
        return _decision(
            ConvergenceProducerSource.OWNERSHIP_SECTION_16,
            source_record_id,
            source_hash,
            ConvergenceProducerReason.UNSUPPORTED_SOURCE_CONTEXT,
        )
    if receipt.form in {OwnershipForm.FORM_144, OwnershipForm.FORM_144_A}:
        facts = ownership_contradiction_facts(receipt)
        request = _request(
            issuer_cik=receipt.issuer_cik,
            predicate=ContradictionPredicate.NET_INSIDER_ACQUISITION,
            asserted_truth=False,
            comparison_scope_id=facts[0].comparison_scope_id,
            as_of_date=receipt.period_or_event_date,
            available_at=receipt.accepted_at,
            retrieved_at=receipt.retrieved_at,
            source_record_id=source_record_id,
            source_content_sha256=source_hash,
            facts=facts,
            knowledge_cutoff_at=knowledge_cutoff_at,
            completeness=ConvergenceFactCompleteness.NOT_APPLICABLE_CONTEXT,
        )
        return _decision(
            ConvergenceProducerSource.OWNERSHIP_FORM_144,
            source_record_id,
            source_hash,
            ConvergenceProducerReason.ELIGIBLE_NOT_APPLICABLE_CONTEXT,
            (request,),
        )
    scopes = sorted(
        {(item.transaction_date, item.derivative) for item in receipt.insider_transactions}
    )
    requests = tuple(
        _ownership_request(
            receipt,
            source_record_id=source_record_id,
            source_content_sha256=source_hash,
            transaction_date=transaction_date,
            derivative=derivative,
            knowledge_cutoff_at=knowledge_cutoff_at,
        )
        for transaction_date, derivative in scopes
    )
    if not requests:
        return _decision(
            ConvergenceProducerSource.OWNERSHIP_SECTION_16,
            source_record_id,
            source_hash,
            ConvergenceProducerReason.NO_RELEVANT_VALIDATED_FACTS,
        )
    return _decision(
        ConvergenceProducerSource.OWNERSHIP_SECTION_16,
        source_record_id,
        source_hash,
        ConvergenceProducerReason.ELIGIBLE_COMPLETE_FACTS,
        requests,
    )


_CASH_TAGS = frozenset(
    {
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    }
)
_CURRENT_LIABILITIES_TAG = "LiabilitiesCurrent"


def xbrl_liquidity_convergence_decision(
    facts: Sequence[SecFactRecord],
    *,
    issuer_cik: Cik,
    accession_number: AccessionNumber,
    filing_form: str,
    knowledge_cutoff_at: UtcDatetime,
) -> ConvergenceProducerDecision:
    """Admit one unambiguous same-filing USD instant cash/liabilities pair."""

    same_filing = tuple(
        item
        for item in facts
        if item.cik == issuer_cik
        and item.accession_number == accession_number
        and item.form == filing_form
        and item.unit == "USD"
        and item.period_start is None
        and (item.tag in _CASH_TAGS or item.tag == _CURRENT_LIABILITIES_TAG)
        and item.available_at <= knowledge_cutoff_at
        and item.retrieved_at <= knowledge_cutoff_at
    )
    source_hash = _facts_manifest_hash(same_filing, issuer_cik, accession_number)
    source_record_id = f"xbrl-liquidity:{accession_number}"
    by_period: dict[date, list[SecFactRecord]] = defaultdict(list)
    for item in same_filing:
        by_period[item.period_end].append(item)
    complete: list[tuple[date, SecFactRecord, SecFactRecord]] = []
    ambiguous_periods: set[date] = set()
    for period_end, period_facts in by_period.items():
        cash_candidates = [item for item in period_facts if item.tag in _CASH_TAGS]
        liability_candidates = [
            item for item in period_facts if item.tag == _CURRENT_LIABILITIES_TAG
        ]
        if len(cash_candidates) == 1 and len(liability_candidates) == 1:
            complete.append((period_end, cash_candidates[0], liability_candidates[0]))
        elif cash_candidates and liability_candidates:
            ambiguous_periods.add(period_end)
    if not complete:
        return _decision(
            ConvergenceProducerSource.XBRL_LIQUIDITY,
            source_record_id,
            source_hash,
            (
                ConvergenceProducerReason.AMBIGUOUS_XBRL_CONTEXT
                if ambiguous_periods
                else ConvergenceProducerReason.NO_RELEVANT_VALIDATED_FACTS
            ),
        )
    latest_period = max(by_period)
    latest = [item for item in complete if item[0] == latest_period]
    if len(latest) != 1 or latest_period in ambiguous_periods:
        return _decision(
            ConvergenceProducerSource.XBRL_LIQUIDITY,
            source_record_id,
            source_hash,
            ConvergenceProducerReason.AMBIGUOUS_XBRL_CONTEXT,
        )
    _, cash, liabilities = latest[0]
    if cash.source_content_sha256 != liabilities.source_content_sha256:
        raise ValueError("XBRL liquidity pair must share one CompanyFacts source")
    evidence_ids = (
        uuid5(_EVIDENCE_NAMESPACE, f"xbrl-fact:{cash.record_id}"),
        uuid5(_EVIDENCE_NAMESPACE, f"xbrl-fact:{liabilities.record_id}"),
    )
    available_at = max(cash.available_at, liabilities.available_at)
    retrieved_at = max(cash.retrieved_at, liabilities.retrieved_at)
    scope = f"xbrl-liquidity:{accession_number}:{latest_period.isoformat()}:USD"
    projected = liquidity_contradiction_facts(
        ForensicInput(
            cash_current=cash.value,
            current_liabilities=liabilities.value,
            evidence_ids=evidence_ids,
        ),
        issuer_cik=issuer_cik,
        comparison_scope_id=scope,
        as_of_date=latest_period,
        currency="USD",
        available_at=available_at,
        retrieved_at=retrieved_at,
        source_record_id=f"companyfacts:{accession_number}:{latest_period.isoformat()}",
        source_content_sha256=cash.source_content_sha256,
    )
    request = _request(
        issuer_cik=issuer_cik,
        predicate=ContradictionPredicate.CASH_AT_LEAST_CURRENT_LIABILITIES,
        asserted_truth=True,
        comparison_scope_id=scope,
        as_of_date=latest_period,
        available_at=available_at,
        retrieved_at=retrieved_at,
        source_record_id=source_record_id,
        source_content_sha256=source_hash,
        facts=projected,
        knowledge_cutoff_at=knowledge_cutoff_at,
        completeness=ConvergenceFactCompleteness.REQUIRED_FACTS_COMPLETE,
    )
    return _decision(
        ConvergenceProducerSource.XBRL_LIQUIDITY,
        source_record_id,
        source_hash,
        ConvergenceProducerReason.ELIGIBLE_COMPLETE_FACTS,
        (request,),
    )


def _ownership_request(
    receipt: OwnershipFilingReceipt,
    *,
    source_record_id: str,
    source_content_sha256: str,
    transaction_date: date,
    derivative: bool,
    knowledge_cutoff_at: UtcDatetime,
) -> ConvergenceValidationRequest:
    facts = ownership_contradiction_facts(
        receipt, transaction_date=transaction_date, derivative=derivative
    )
    return _request(
        issuer_cik=receipt.issuer_cik,
        predicate=ContradictionPredicate.NET_INSIDER_ACQUISITION,
        asserted_truth=True,
        comparison_scope_id=facts[0].comparison_scope_id,
        as_of_date=transaction_date,
        available_at=receipt.accepted_at,
        retrieved_at=receipt.retrieved_at,
        source_record_id=source_record_id,
        source_content_sha256=source_content_sha256,
        facts=facts,
        knowledge_cutoff_at=knowledge_cutoff_at,
        completeness=ConvergenceFactCompleteness.REQUIRED_FACTS_COMPLETE,
    )


def _request(
    *,
    issuer_cik: Cik,
    predicate: ContradictionPredicate,
    asserted_truth: bool,
    comparison_scope_id: str,
    as_of_date: date,
    available_at: datetime,
    retrieved_at: datetime,
    source_record_id: str,
    source_content_sha256: str,
    facts: tuple[ContradictionFact, ...],
    knowledge_cutoff_at: datetime,
    completeness: ConvergenceFactCompleteness,
) -> ConvergenceValidationRequest:
    family = {
        ContradictionPredicate.CASH_AT_LEAST_CURRENT_LIABILITIES: ContradictionFamily.LIQUIDITY,
        ContradictionPredicate.DILUTION_EXPOSURE_PRESENT: ContradictionFamily.DILUTION,
        ContradictionPredicate.NET_INSIDER_ACQUISITION: ContradictionFamily.INSIDER,
    }[predicate]
    claim_payload = {
        "issuer_cik": issuer_cik,
        "predicate": predicate.value,
        "asserted_truth": asserted_truth,
        "comparison_scope_id": comparison_scope_id,
        "as_of_date": as_of_date.isoformat(),
        "source_record_id": source_record_id,
        "source_content_sha256": source_content_sha256,
        "producer_version": CONVERGENCE_PRODUCER_VERSION,
    }
    encoded = json.dumps(claim_payload, sort_keys=True, separators=(",", ":"))
    claim_evidence_id = uuid5(_EVIDENCE_NAMESPACE, encoded)
    if any(
        (fact.source_record_id, fact.source_content_sha256)
        == (source_record_id, source_content_sha256)
        for fact in facts
    ):
        raise ValueError("producer claim and facts require distinct validated lineage")
    if any(claim_evidence_id in fact.evidence_ids for fact in facts):
        raise ValueError("producer claim and fact evidence identities must remain distinct")
    claim = ClaimUnderReview(
        claim_id=uuid5(_CLAIM_NAMESPACE, encoded),
        issuer_cik=issuer_cik,
        family=family,
        predicate=predicate,
        asserted_truth=asserted_truth,
        comparison_scope_id=comparison_scope_id,
        as_of_date=as_of_date,
        available_at=available_at,
        retrieved_at=retrieved_at,
        source_record_id=source_record_id,
        source_content_sha256=source_content_sha256,
        evidence_ids=(claim_evidence_id,),
    )
    return ConvergenceValidationRequest(
        claim=claim,
        facts=facts,
        knowledge_cutoff_at=knowledge_cutoff_at,
        fact_completeness=completeness,
    )


def _record_hash(record: ContractModel) -> str:
    encoded = json.dumps(record.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _facts_manifest_hash(
    facts: Sequence[SecFactRecord], issuer_cik: str, accession_number: str
) -> str:
    payload = {
        "issuer_cik": issuer_cik,
        "accession_number": accession_number,
        "fact_record_ids": sorted(item.record_id for item in facts),
        "producer_version": CONVERGENCE_PRODUCER_VERSION,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _decision(
    source: ConvergenceProducerSource,
    source_record_id: str,
    source_content_sha256: str,
    reason: ConvergenceProducerReason,
    requests: tuple[ConvergenceValidationRequest, ...] = (),
) -> ConvergenceProducerDecision:
    return ConvergenceProducerDecision(
        source=source,
        source_record_id=source_record_id,
        source_content_sha256=source_content_sha256,
        reason=reason,
        requests=requests,
    )
