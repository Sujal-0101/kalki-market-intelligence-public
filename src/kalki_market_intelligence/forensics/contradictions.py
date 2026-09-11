"""Closed deterministic checks for narrowly stated cross-source claims."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID, uuid5

from pydantic import Field, StringConstraints, model_validator

from kalki_market_intelligence.contracts.common import (
    ContractModel,
    Sha256Hex,
    ShortText,
    UtcDatetime,
)
from kalki_market_intelligence.forensics.detectors import ForensicInput
from kalki_market_intelligence.forensics.financing import (
    FinancingEventStatus,
    FinancingFilingReceipt,
    FinancingInstrument,
)
from kalki_market_intelligence.providers.sec.contracts import Cik
from kalki_market_intelligence.providers.sec.ownership import (
    OwnershipFilingReceipt,
    OwnershipForm,
)

CONTRADICTION_RULE_VERSION = "deterministic-contradiction-v2"
CONTRADICTION_ADAPTER_VERSION = "deterministic-contradiction-adapters-v1"
_CONTRADICTION_NAMESPACE = UUID("43000000-0000-4000-8000-000000000043")
_CONTRADICTION_FACT_NAMESPACE = UUID("43000000-0000-4000-8000-000000000044")
type CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


class ContradictionFamily(StrEnum):
    LIQUIDITY = "LIQUIDITY"
    DILUTION = "DILUTION"
    INSIDER = "INSIDER"


class ContradictionPredicate(StrEnum):
    CASH_AT_LEAST_CURRENT_LIABILITIES = "CASH_AT_LEAST_CURRENT_LIABILITIES"
    DILUTION_EXPOSURE_PRESENT = "DILUTION_EXPOSURE_PRESENT"
    NET_INSIDER_ACQUISITION = "NET_INSIDER_ACQUISITION"


class ContradictionDisposition(StrEnum):
    SUPPORTED = "SUPPORTED"
    CONFLICTED = "CONFLICTED"
    INSUFFICIENT = "INSUFFICIENT"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ContradictionReason(StrEnum):
    EXACT_FACTS_SUPPORT_CLAIM = "EXACT_FACTS_SUPPORT_CLAIM"
    EXACT_FACTS_CONFLICT_WITH_CLAIM = "EXACT_FACTS_CONFLICT_WITH_CLAIM"
    REQUIRED_FACTS_MISSING = "REQUIRED_FACTS_MISSING"
    FACT_PERIODS_INCOMPARABLE = "FACT_PERIODS_INCOMPARABLE"
    PLANNED_SALE_IS_NOT_EXECUTED_TRANSACTION = "PLANNED_SALE_IS_NOT_EXECUTED_TRANSACTION"


class ContradictionFactKind(StrEnum):
    CASH = "CASH"
    CURRENT_LIABILITIES = "CURRENT_LIABILITIES"
    SHARES_OUTSTANDING_PRIOR = "SHARES_OUTSTANDING_PRIOR"
    SHARES_OUTSTANDING_CURRENT = "SHARES_OUTSTANDING_CURRENT"
    REGISTERED_SHARES = "REGISTERED_SHARES"
    ISSUABLE_SHARES = "ISSUABLE_SHARES"
    DILUTIVE_INSTRUMENT_COUNT = "DILUTIVE_INSTRUMENT_COUNT"
    INSIDER_ACQUIRED_SHARES = "INSIDER_ACQUIRED_SHARES"
    INSIDER_DISPOSED_SHARES = "INSIDER_DISPOSED_SHARES"
    FORM_144_PLANNED_SALE_SHARES = "FORM_144_PLANNED_SALE_SHARES"


class ContradictionFactUnit(StrEnum):
    CURRENCY = "CURRENCY"
    SHARES = "SHARES"
    COUNT = "COUNT"


_FAMILY_BY_PREDICATE = {
    ContradictionPredicate.CASH_AT_LEAST_CURRENT_LIABILITIES: ContradictionFamily.LIQUIDITY,
    ContradictionPredicate.DILUTION_EXPOSURE_PRESENT: ContradictionFamily.DILUTION,
    ContradictionPredicate.NET_INSIDER_ACQUISITION: ContradictionFamily.INSIDER,
}

_UNIT_BY_FACT_KIND = {
    ContradictionFactKind.CASH: ContradictionFactUnit.CURRENCY,
    ContradictionFactKind.CURRENT_LIABILITIES: ContradictionFactUnit.CURRENCY,
    ContradictionFactKind.SHARES_OUTSTANDING_PRIOR: ContradictionFactUnit.SHARES,
    ContradictionFactKind.SHARES_OUTSTANDING_CURRENT: ContradictionFactUnit.SHARES,
    ContradictionFactKind.REGISTERED_SHARES: ContradictionFactUnit.SHARES,
    ContradictionFactKind.ISSUABLE_SHARES: ContradictionFactUnit.SHARES,
    ContradictionFactKind.DILUTIVE_INSTRUMENT_COUNT: ContradictionFactUnit.COUNT,
    ContradictionFactKind.INSIDER_ACQUIRED_SHARES: ContradictionFactUnit.SHARES,
    ContradictionFactKind.INSIDER_DISPOSED_SHARES: ContradictionFactUnit.SHARES,
    ContradictionFactKind.FORM_144_PLANNED_SALE_SHARES: ContradictionFactUnit.SHARES,
}

_FACT_KINDS_BY_PREDICATE = {
    ContradictionPredicate.CASH_AT_LEAST_CURRENT_LIABILITIES: frozenset(
        {ContradictionFactKind.CASH, ContradictionFactKind.CURRENT_LIABILITIES}
    ),
    ContradictionPredicate.DILUTION_EXPOSURE_PRESENT: frozenset(
        {
            ContradictionFactKind.SHARES_OUTSTANDING_PRIOR,
            ContradictionFactKind.SHARES_OUTSTANDING_CURRENT,
            ContradictionFactKind.REGISTERED_SHARES,
            ContradictionFactKind.ISSUABLE_SHARES,
            ContradictionFactKind.DILUTIVE_INSTRUMENT_COUNT,
        }
    ),
    ContradictionPredicate.NET_INSIDER_ACQUISITION: frozenset(
        {
            ContradictionFactKind.INSIDER_ACQUIRED_SHARES,
            ContradictionFactKind.INSIDER_DISPOSED_SHARES,
            ContradictionFactKind.FORM_144_PLANNED_SALE_SHARES,
        }
    ),
}


class ClaimUnderReview(ContractModel):
    """One exact Boolean assertion whose source is retained for audit."""

    claim_id: UUID
    issuer_cik: Cik
    family: ContradictionFamily
    predicate: ContradictionPredicate
    asserted_truth: bool
    comparison_scope_id: ShortText
    as_of_date: date
    available_at: UtcDatetime
    retrieved_at: UtcDatetime
    source_record_id: ShortText
    source_content_sha256: Sha256Hex
    evidence_ids: tuple[UUID, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def family_time_and_evidence_are_closed(self) -> Self:
        if _FAMILY_BY_PREDICATE[self.predicate] is not self.family:
            raise ValueError("claim predicate does not belong to its family")
        if self.retrieved_at < self.available_at:
            raise ValueError("claim retrieval cannot precede availability")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("claim evidence IDs must be unique")
        return self


class ContradictionFact(ContractModel):
    """One independently extracted numeric fact with immutable source lineage."""

    fact_id: UUID
    issuer_cik: Cik
    kind: ContradictionFactKind
    value: Decimal = Field(ge=0, allow_inf_nan=False)
    unit: ContradictionFactUnit
    currency: CurrencyCode | None = None
    comparison_scope_id: ShortText
    as_of_date: date
    available_at: UtcDatetime
    retrieved_at: UtcDatetime
    source_record_id: ShortText
    source_content_sha256: Sha256Hex
    evidence_ids: tuple[UUID, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def unit_time_and_evidence_are_closed(self) -> Self:
        if self.unit is not _UNIT_BY_FACT_KIND[self.kind]:
            raise ValueError("fact unit does not match its closed kind")
        if (self.unit is ContradictionFactUnit.CURRENCY) != (self.currency is not None):
            raise ValueError("currency is required exactly for currency facts")
        if self.retrieved_at < self.available_at:
            raise ValueError("fact retrieval cannot precede availability")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("fact evidence IDs must be unique")
        return self


class ContradictionReceipt(ContractModel):
    """Recomputable content-free result; it is not a directional market signal."""

    receipt_id: UUID
    claim: ClaimUnderReview
    facts: tuple[ContradictionFact, ...] = Field(default=(), max_length=8)
    knowledge_cutoff_at: UtcDatetime
    disposition: ContradictionDisposition
    observed_truth: bool | None
    reason: ContradictionReason
    consumed_fact_ids: tuple[UUID, ...] = Field(default=(), max_length=8)
    receipt_sha256: Sha256Hex
    rule_version: str = CONTRADICTION_RULE_VERSION

    @model_validator(mode="after")
    def result_recomputes_exactly(self) -> Self:
        if self.rule_version != CONTRADICTION_RULE_VERSION:
            raise ValueError("unsupported contradiction rule version")
        if self.claim.available_at > self.knowledge_cutoff_at:
            raise ValueError("claim was unavailable at the knowledge cutoff")
        if self.claim.retrieved_at > self.knowledge_cutoff_at:
            raise ValueError("claim was not retrieved by the knowledge cutoff")
        if self.claim.as_of_date > self.knowledge_cutoff_at.date():
            raise ValueError("claim as-of date follows the knowledge cutoff")
        fact_keys = tuple((item.kind, item.fact_id.hex) for item in self.facts)
        if fact_keys != tuple(sorted(fact_keys)):
            raise ValueError("contradiction facts must use deterministic order")
        if len({item.kind for item in self.facts}) != len(self.facts):
            raise ValueError("a contradiction receipt cannot repeat a fact kind")
        if len({item.fact_id for item in self.facts}) != len(self.facts):
            raise ValueError("a contradiction receipt cannot repeat a fact ID")
        currencies = {item.currency for item in self.facts if item.currency is not None}
        if len(currencies) > 1:
            raise ValueError("currency facts must use one currency")
        source_identities: dict[str, tuple[str, UtcDatetime, UtcDatetime]] = {}
        evidence_sources: dict[UUID, tuple[str, str]] = {}
        for fact in self.facts:
            if fact.issuer_cik != self.claim.issuer_cik:
                raise ValueError("cross-issuer contradiction facts are forbidden")
            if fact.comparison_scope_id != self.claim.comparison_scope_id:
                raise ValueError("cross-scope contradiction facts are forbidden")
            if fact.available_at > self.knowledge_cutoff_at:
                raise ValueError("fact was unavailable at the knowledge cutoff")
            if fact.retrieved_at > self.knowledge_cutoff_at:
                raise ValueError("fact was not retrieved by the knowledge cutoff")
            if fact.as_of_date > self.claim.as_of_date:
                raise ValueError("fact follows the claim as-of date")
            source_identity = (
                fact.source_content_sha256,
                fact.available_at,
                fact.retrieved_at,
            )
            prior_source_identity = source_identities.setdefault(
                fact.source_record_id, source_identity
            )
            if prior_source_identity != source_identity:
                raise ValueError("one fact source record has conflicting lineage")
            for evidence_id in fact.evidence_ids:
                evidence_source = (
                    fact.source_record_id,
                    fact.source_content_sha256,
                )
                prior_evidence_source = evidence_sources.setdefault(evidence_id, evidence_source)
                if prior_evidence_source != evidence_source:
                    raise ValueError("one evidence ID cannot identify different sources")
        expected = _evaluate(self.claim, self.facts)
        actual = (
            self.disposition,
            self.observed_truth,
            self.reason,
            self.consumed_fact_ids,
        )
        if actual != expected:
            raise ValueError("contradiction result does not recompute from exact facts")
        expected_hash = _receipt_hash(
            self.claim,
            self.facts,
            self.knowledge_cutoff_at,
            *expected,
        )
        if self.receipt_sha256 != expected_hash:
            raise ValueError("contradiction receipt hash does not reconcile")
        if self.receipt_id != uuid5(_CONTRADICTION_NAMESPACE, expected_hash):
            raise ValueError("contradiction receipt identity does not reconcile")
        return self


type _Evaluation = tuple[
    ContradictionDisposition,
    bool | None,
    ContradictionReason,
    tuple[UUID, ...],
]


def check_deterministic_contradiction(
    claim: ClaimUnderReview,
    facts: tuple[ContradictionFact, ...],
    *,
    knowledge_cutoff_at: UtcDatetime,
) -> ContradictionReceipt:
    """Evaluate a narrow claim from exact facts available at one knowledge cutoff."""

    relevant_kinds = _FACT_KINDS_BY_PREDICATE[claim.predicate]
    relevant = tuple(
        sorted(
            (item for item in facts if item.kind in relevant_kinds),
            key=lambda item: (item.kind, item.fact_id.hex),
        )
    )
    evaluation = _evaluate(claim, relevant)
    receipt_hash = _receipt_hash(
        claim,
        relevant,
        knowledge_cutoff_at,
        *evaluation,
    )
    return ContradictionReceipt(
        receipt_id=uuid5(_CONTRADICTION_NAMESPACE, receipt_hash),
        claim=claim,
        facts=relevant,
        knowledge_cutoff_at=knowledge_cutoff_at,
        disposition=evaluation[0],
        observed_truth=evaluation[1],
        reason=evaluation[2],
        consumed_fact_ids=evaluation[3],
        receipt_sha256=receipt_hash,
    )


_POTENTIALLY_DILUTIVE_INSTRUMENTS = frozenset(
    {
        FinancingInstrument.CONVERTIBLE_DEBT,
        FinancingInstrument.PREFERRED_EQUITY,
        FinancingInstrument.WARRANT,
        FinancingInstrument.WARRANT_REPRICING,
        FinancingInstrument.WARRANT_EXERCISE_INDUCEMENT,
        FinancingInstrument.EQUITY_LINE,
    }
)


def financing_contradiction_facts(
    receipt: FinancingFilingReceipt,
) -> tuple[ContradictionFact, ...]:
    """Project only explicit positive dilution exposure from a validated filing."""

    qualifying = tuple(
        term
        for term in receipt.terms
        if term.instrument in _POTENTIALLY_DILUTIVE_INSTRUMENTS
        and term.status not in {FinancingEventStatus.TERMINATED, FinancingEventStatus.UNKNOWN}
        and term.issuable_shares is not None
        and term.issuable_shares > 0
    )
    if not qualifying:
        return ()
    evidence_ids = tuple(
        sorted(
            {evidence_id for term in qualifying for evidence_id in term.evidence_ids},
            key=lambda item: item.hex,
        )
    )
    if len(evidence_ids) > 16:
        raise ValueError("dilution exposure provenance exceeds the fact boundary")
    scope = f"financing:{receipt.accession_number}"
    return (
        _build_fact(
            issuer_cik=receipt.issuer_cik,
            kind=ContradictionFactKind.DILUTIVE_INSTRUMENT_COUNT,
            value=Decimal(len(qualifying)),
            unit=ContradictionFactUnit.COUNT,
            currency=None,
            comparison_scope_id=scope,
            as_of_date=receipt.accepted_at.date(),
            available_at=receipt.accepted_at,
            retrieved_at=receipt.retrieved_at,
            source_record_id=str(receipt.accession_number),
            source_content_sha256=receipt.source_content_sha256,
            evidence_ids=evidence_ids,
        ),
    )


def liquidity_contradiction_facts(
    inputs: ForensicInput,
    *,
    issuer_cik: Cik,
    comparison_scope_id: ShortText,
    as_of_date: date,
    currency: CurrencyCode,
    available_at: UtcDatetime,
    retrieved_at: UtcDatetime,
    source_record_id: ShortText,
    source_content_sha256: Sha256Hex,
) -> tuple[ContradictionFact, ...]:
    """Bind already-extracted liquidity values to explicit source/time metadata."""

    values = (
        (ContradictionFactKind.CASH, inputs.cash_current),
        (ContradictionFactKind.CURRENT_LIABILITIES, inputs.current_liabilities),
    )
    available_values = tuple((kind, value) for kind, value in values if value is not None)
    if not available_values:
        return ()
    if not inputs.evidence_ids:
        raise ValueError("liquidity facts require exact evidence IDs")
    return tuple(
        _build_fact(
            issuer_cik=issuer_cik,
            kind=kind,
            value=value,
            unit=ContradictionFactUnit.CURRENCY,
            currency=currency,
            comparison_scope_id=comparison_scope_id,
            as_of_date=as_of_date,
            available_at=available_at,
            retrieved_at=retrieved_at,
            source_record_id=source_record_id,
            source_content_sha256=source_content_sha256,
            evidence_ids=inputs.evidence_ids,
        )
        for kind, value in available_values
    )


def share_count_contradiction_facts(
    inputs: ForensicInput,
    *,
    issuer_cik: Cik,
    comparison_scope_id: ShortText,
    previous_as_of_date: date,
    current_as_of_date: date,
    available_at: UtcDatetime,
    retrieved_at: UtcDatetime,
    source_record_id: ShortText,
    source_content_sha256: Sha256Hex,
) -> tuple[ContradictionFact, ...]:
    """Bind point-in-time share counts without inferring missing period values."""

    values = (
        (
            ContradictionFactKind.SHARES_OUTSTANDING_PRIOR,
            inputs.shares_previous,
            previous_as_of_date,
        ),
        (
            ContradictionFactKind.SHARES_OUTSTANDING_CURRENT,
            inputs.shares_current,
            current_as_of_date,
        ),
    )
    available_values = tuple(
        (kind, value, as_of) for kind, value, as_of in values if value is not None
    )
    if not available_values:
        return ()
    if not inputs.evidence_ids:
        raise ValueError("share-count facts require exact evidence IDs")
    return tuple(
        _build_fact(
            issuer_cik=issuer_cik,
            kind=kind,
            value=value,
            unit=ContradictionFactUnit.SHARES,
            currency=None,
            comparison_scope_id=comparison_scope_id,
            as_of_date=as_of,
            available_at=available_at,
            retrieved_at=retrieved_at,
            source_record_id=source_record_id,
            source_content_sha256=source_content_sha256,
            evidence_ids=inputs.evidence_ids,
        )
        for kind, value, as_of in available_values
    )


def ownership_contradiction_facts(
    receipt: OwnershipFilingReceipt,
    *,
    transaction_date: date | None = None,
    derivative: bool | None = None,
) -> tuple[ContradictionFact, ...]:
    """Project one exact ownership-filing scope without directional interpretation."""

    evidence_id = uuid5(
        _CONTRADICTION_FACT_NAMESPACE,
        f"ownership-source|{receipt.accession_number}|{receipt.source_content_sha256}",
    )
    source_fields = {
        "issuer_cik": receipt.issuer_cik,
        "available_at": receipt.accepted_at,
        "retrieved_at": receipt.retrieved_at,
        "source_record_id": str(receipt.accession_number),
        "source_content_sha256": receipt.source_content_sha256,
        "evidence_ids": (evidence_id,),
    }
    if receipt.form in {OwnershipForm.FORM_144, OwnershipForm.FORM_144_A}:
        assert receipt.form_144_notice is not None
        scope = f"ownership:{receipt.accession_number}:planned-sale"
        return (
            _build_fact(
                **source_fields,
                kind=ContradictionFactKind.FORM_144_PLANNED_SALE_SHARES,
                value=receipt.form_144_notice.units_to_be_sold,
                unit=ContradictionFactUnit.SHARES,
                currency=None,
                comparison_scope_id=scope,
                as_of_date=receipt.period_or_event_date,
            ),
        )
    if receipt.form.is_schedule_13d or receipt.form.is_schedule_13g:
        return ()
    if transaction_date is None or derivative is None:
        raise ValueError("Section 16 facts require an exact date and derivative scope")
    selected = tuple(
        item
        for item in receipt.insider_transactions
        if item.transaction_date == transaction_date and item.derivative is derivative
    )
    if not selected:
        return ()
    scope = (
        f"ownership:{receipt.accession_number}:{transaction_date.isoformat()}:"
        f"{'derivative' if derivative else 'non-derivative'}"
    )
    acquired = sum(
        (item.shares for item in selected if item.acquired_or_disposed == "A"),
        start=Decimal(0),
    )
    disposed = sum(
        (item.shares for item in selected if item.acquired_or_disposed == "D"),
        start=Decimal(0),
    )
    common = {
        **source_fields,
        "unit": ContradictionFactUnit.SHARES,
        "currency": None,
        "comparison_scope_id": scope,
        "as_of_date": transaction_date,
    }
    return (
        _build_fact(
            **common,
            kind=ContradictionFactKind.INSIDER_ACQUIRED_SHARES,
            value=acquired,
        ),
        _build_fact(
            **common,
            kind=ContradictionFactKind.INSIDER_DISPOSED_SHARES,
            value=disposed,
        ),
    )


def _build_fact(**values: object) -> ContradictionFact:
    identity_payload = {
        **values,
        "adapter_version": CONTRADICTION_ADAPTER_VERSION,
    }
    encoded = json.dumps(identity_payload, sort_keys=True, default=str, separators=(",", ":"))
    fact_id = uuid5(_CONTRADICTION_FACT_NAMESPACE, encoded)
    return ContradictionFact.model_validate({"fact_id": fact_id, **values})


def _evaluate(
    claim: ClaimUnderReview,
    facts: tuple[ContradictionFact, ...],
) -> _Evaluation:
    by_kind = {item.kind: item for item in facts}
    observed: bool | None
    consumed: tuple[ContradictionFact, ...]
    if claim.predicate is ContradictionPredicate.CASH_AT_LEAST_CURRENT_LIABILITIES:
        required = (
            ContradictionFactKind.CASH,
            ContradictionFactKind.CURRENT_LIABILITIES,
        )
        if not all(kind in by_kind for kind in required):
            return _insufficient(facts)
        cash, liabilities = (by_kind[kind] for kind in required)
        if cash.as_of_date != liabilities.as_of_date:
            return _incomparable(facts)
        if cash.currency != liabilities.currency:
            raise ValueError("liquidity facts must use the same currency")
        observed = cash.value >= liabilities.value
        consumed = (cash, liabilities)
    elif claim.predicate is ContradictionPredicate.DILUTION_EXPOSURE_PRESENT:
        prior = by_kind.get(ContradictionFactKind.SHARES_OUTSTANDING_PRIOR)
        current = by_kind.get(ContradictionFactKind.SHARES_OUTSTANDING_CURRENT)
        direct = tuple(
            by_kind[kind]
            for kind in (
                ContradictionFactKind.ISSUABLE_SHARES,
                ContradictionFactKind.DILUTIVE_INSTRUMENT_COUNT,
            )
            if kind in by_kind
        )
        registration = by_kind.get(ContradictionFactKind.REGISTERED_SHARES)
        share_pair_complete = prior is not None and current is not None
        if prior is not None and current is not None and prior.as_of_date >= current.as_of_date:
            return _incomparable(facts)
        direct_positive = any(item.value > 0 for item in direct)
        if direct_positive:
            observed = True
            consumed = direct
        elif share_pair_complete:
            assert prior is not None and current is not None
            if current.value > prior.value:
                observed = True
                consumed = (prior, current, *direct)
            else:
                instrument_count = by_kind.get(ContradictionFactKind.DILUTIVE_INSTRUMENT_COUNT)
                # No observed share growth alone cannot establish that an issuer
                # has no outstanding dilution exposure. A closed zero-instrument
                # count is also required; positive registration context prevents
                # the stronger negative conclusion.
                if (
                    instrument_count is None
                    or instrument_count.value != 0
                    or (registration is not None and registration.value > 0)
                ):
                    return _insufficient(facts)
                observed = False
                consumed = (prior, current, instrument_count)
        else:
            # A registration may cover already-issued selling-holder shares or an
            # unused shelf. It cannot prove issuer dilution by itself.
            return _insufficient(facts)
    else:
        acquired = by_kind.get(ContradictionFactKind.INSIDER_ACQUIRED_SHARES)
        disposed = by_kind.get(ContradictionFactKind.INSIDER_DISPOSED_SHARES)
        planned = by_kind.get(ContradictionFactKind.FORM_144_PLANNED_SALE_SHARES)
        if acquired is None and disposed is None and planned is not None:
            return (
                ContradictionDisposition.NOT_APPLICABLE,
                None,
                ContradictionReason.PLANNED_SALE_IS_NOT_EXECUTED_TRANSACTION,
                (planned.fact_id,),
            )
        if acquired is None or disposed is None:
            return _insufficient(facts)
        if acquired.as_of_date != disposed.as_of_date:
            return _incomparable(facts)
        observed = acquired.value > disposed.value
        consumed = (acquired, disposed)

    disposition = (
        ContradictionDisposition.SUPPORTED
        if observed is claim.asserted_truth
        else ContradictionDisposition.CONFLICTED
    )
    reason = (
        ContradictionReason.EXACT_FACTS_SUPPORT_CLAIM
        if disposition is ContradictionDisposition.SUPPORTED
        else ContradictionReason.EXACT_FACTS_CONFLICT_WITH_CLAIM
    )
    return disposition, observed, reason, tuple(item.fact_id for item in consumed)


def _insufficient(facts: tuple[ContradictionFact, ...]) -> _Evaluation:
    return (
        ContradictionDisposition.INSUFFICIENT,
        None,
        ContradictionReason.REQUIRED_FACTS_MISSING,
        tuple(item.fact_id for item in facts),
    )


def _incomparable(facts: tuple[ContradictionFact, ...]) -> _Evaluation:
    return (
        ContradictionDisposition.INSUFFICIENT,
        None,
        ContradictionReason.FACT_PERIODS_INCOMPARABLE,
        tuple(item.fact_id for item in facts),
    )


def _receipt_hash(
    claim: ClaimUnderReview,
    facts: tuple[ContradictionFact, ...],
    knowledge_cutoff_at: UtcDatetime,
    disposition: ContradictionDisposition,
    observed_truth: bool | None,
    reason: ContradictionReason,
    consumed_fact_ids: tuple[UUID, ...],
) -> str:
    payload = {
        "claim": claim.model_dump(mode="json"),
        "facts": [item.model_dump(mode="json") for item in facts],
        "knowledge_cutoff_at": knowledge_cutoff_at.isoformat(),
        "disposition": disposition,
        "observed_truth": observed_truth,
        "reason": reason,
        "consumed_fact_ids": [str(item) for item in consumed_fact_ids],
        "rule_version": CONTRADICTION_RULE_VERSION,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
