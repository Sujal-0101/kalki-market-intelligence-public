"""Phase 43 deterministic contradiction contracts and adversarial boundaries."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import HttpUrl, ValidationError

from kalki_market_intelligence.forensics import (
    ClaimUnderReview,
    ContradictionDisposition,
    ContradictionFact,
    ContradictionFactKind,
    ContradictionFactUnit,
    ContradictionFamily,
    ContradictionPredicate,
    ContradictionReason,
    ContradictionReceipt,
    ConvergenceFactCompleteness,
    ConvergenceValidationRequest,
    ConvergenceValidationService,
    ForensicInput,
    check_deterministic_contradiction,
    financing_contradiction_facts,
    liquidity_contradiction_facts,
    ownership_contradiction_facts,
    share_count_contradiction_facts,
)
from kalki_market_intelligence.forensics.financing import (
    FinancingFilingReceipt,
    FinancingForm,
    extract_financing_evidence,
    parse_convertible_preferred_warrant_terms,
    parse_shelf_atm_terms,
)
from kalki_market_intelligence.providers.sec.ownership import parse_ownership_xml

NOW = datetime(2026, 9, 7, 14, 0, tzinfo=UTC)
CIK = "0000000043"
HASH = "43" * 32
FINANCING_FIXTURES = Path(__file__).parent / "fixtures" / "financing"


class ReceiptSink:
    def __init__(self) -> None:
        self.receipts: list[ContradictionReceipt] = []

    def append_receipt(self, receipt: ContradictionReceipt) -> ContradictionReceipt:
        self.receipts.append(receipt)
        return receipt


def claim(
    predicate: ContradictionPredicate,
    *,
    asserted_truth: bool = True,
    family: ContradictionFamily | None = None,
    comparison_scope_id: str = "scope-43",
    cik: str = CIK,
) -> ClaimUnderReview:
    expected_family = {
        ContradictionPredicate.CASH_AT_LEAST_CURRENT_LIABILITIES: (ContradictionFamily.LIQUIDITY),
        ContradictionPredicate.DILUTION_EXPOSURE_PRESENT: ContradictionFamily.DILUTION,
        ContradictionPredicate.NET_INSIDER_ACQUISITION: ContradictionFamily.INSIDER,
    }[predicate]
    return ClaimUnderReview(
        claim_id=UUID("43000000-0000-4000-8000-000000000001"),
        issuer_cik=cik,
        family=family or expected_family,
        predicate=predicate,
        asserted_truth=asserted_truth,
        comparison_scope_id=comparison_scope_id,
        as_of_date=date(2026, 9, 7),
        available_at=NOW - timedelta(minutes=2),
        retrieved_at=NOW - timedelta(minutes=1),
        source_record_id="validated-claim-43",
        source_content_sha256=HASH,
        evidence_ids=(UUID("43000000-0000-4000-8000-000000000002"),),
    )


def fact(
    kind: ContradictionFactKind,
    value: str,
    *,
    fact_number: int,
    as_of_date: date = date(2026, 9, 6),
    cik: str = CIK,
    available_at: datetime = NOW - timedelta(minutes=4),
    retrieved_at: datetime = NOW - timedelta(minutes=3),
    source_record_id: str | None = None,
    source_content_sha256: str = HASH,
    evidence_id: UUID | None = None,
    comparison_scope_id: str = "scope-43",
) -> ContradictionFact:
    unit = {
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
    }[kind]
    return ContradictionFact(
        fact_id=UUID(f"43000000-0000-4000-8000-{fact_number:012d}"),
        issuer_cik=cik,
        kind=kind,
        value=Decimal(value),
        unit=unit,
        currency="USD" if unit is ContradictionFactUnit.CURRENCY else None,
        comparison_scope_id=comparison_scope_id,
        as_of_date=as_of_date,
        available_at=available_at,
        retrieved_at=retrieved_at,
        source_record_id=source_record_id or f"exact-fact-{fact_number}",
        source_content_sha256=source_content_sha256,
        evidence_ids=(evidence_id or UUID(f"43000000-0000-4000-8001-{fact_number:012d}"),),
    )


def test_liquidity_claim_is_supported_or_conflicted_by_exact_values() -> None:
    facts = (
        fact(ContradictionFactKind.CURRENT_LIABILITIES, "90", fact_number=2),
        fact(ContradictionFactKind.CASH, "100", fact_number=1),
    )
    supported = check_deterministic_contradiction(
        claim(ContradictionPredicate.CASH_AT_LEAST_CURRENT_LIABILITIES),
        facts,
        knowledge_cutoff_at=NOW,
    )
    conflicted = check_deterministic_contradiction(
        claim(
            ContradictionPredicate.CASH_AT_LEAST_CURRENT_LIABILITIES,
            asserted_truth=False,
        ),
        facts,
        knowledge_cutoff_at=NOW,
    )
    assert supported.disposition is ContradictionDisposition.SUPPORTED
    assert supported.observed_truth is True
    assert conflicted.disposition is ContradictionDisposition.CONFLICTED
    assert conflicted.observed_truth is True
    assert supported.facts[0].kind is ContradictionFactKind.CASH


def test_missing_liquidity_fact_is_insufficient_and_never_safe() -> None:
    receipt = check_deterministic_contradiction(
        claim(ContradictionPredicate.CASH_AT_LEAST_CURRENT_LIABILITIES),
        (fact(ContradictionFactKind.CASH, "100", fact_number=1),),
        knowledge_cutoff_at=NOW,
    )
    assert receipt.disposition is ContradictionDisposition.INSUFFICIENT
    assert receipt.observed_truth is None
    assert receipt.reason is ContradictionReason.REQUIRED_FACTS_MISSING


def test_dilution_claim_uses_share_growth_or_explicit_instrument_exposure() -> None:
    prior = fact(
        ContradictionFactKind.SHARES_OUTSTANDING_PRIOR,
        "100",
        fact_number=1,
        as_of_date=date(2026, 6, 30),
    )
    current = fact(
        ContradictionFactKind.SHARES_OUTSTANDING_CURRENT,
        "100",
        fact_number=2,
        as_of_date=date(2026, 9, 6),
    )
    instrument = fact(
        ContradictionFactKind.DILUTIVE_INSTRUMENT_COUNT,
        "1",
        fact_number=3,
    )
    receipt = check_deterministic_contradiction(
        claim(ContradictionPredicate.DILUTION_EXPOSURE_PRESENT),
        (current, prior, instrument),
        knowledge_cutoff_at=NOW,
    )
    assert receipt.disposition is ContradictionDisposition.SUPPORTED
    assert receipt.observed_truth is True
    assert receipt.consumed_fact_ids == (instrument.fact_id,)


def test_equal_share_counts_without_complete_instrument_inventory_are_insufficient() -> None:
    receipt = check_deterministic_contradiction(
        claim(ContradictionPredicate.DILUTION_EXPOSURE_PRESENT),
        (
            fact(
                ContradictionFactKind.SHARES_OUTSTANDING_PRIOR,
                "100",
                fact_number=1,
                as_of_date=date(2026, 6, 30),
            ),
            fact(
                ContradictionFactKind.SHARES_OUTSTANDING_CURRENT,
                "100",
                fact_number=2,
            ),
            fact(ContradictionFactKind.REGISTERED_SHARES, "0", fact_number=3),
        ),
        knowledge_cutoff_at=NOW,
    )
    assert receipt.disposition is ContradictionDisposition.INSUFFICIENT
    assert receipt.observed_truth is None


def test_complete_zero_instrument_inventory_can_conflict_with_dilution_claim() -> None:
    receipt = check_deterministic_contradiction(
        claim(ContradictionPredicate.DILUTION_EXPOSURE_PRESENT),
        (
            fact(
                ContradictionFactKind.SHARES_OUTSTANDING_PRIOR,
                "100",
                fact_number=1,
                as_of_date=date(2026, 6, 30),
            ),
            fact(
                ContradictionFactKind.SHARES_OUTSTANDING_CURRENT,
                "100",
                fact_number=2,
            ),
            fact(
                ContradictionFactKind.DILUTIVE_INSTRUMENT_COUNT,
                "0",
                fact_number=3,
            ),
        ),
        knowledge_cutoff_at=NOW,
    )
    assert receipt.disposition is ContradictionDisposition.CONFLICTED
    assert receipt.observed_truth is False


def test_registration_alone_does_not_prove_issuer_dilution() -> None:
    receipt = check_deterministic_contradiction(
        claim(ContradictionPredicate.DILUTION_EXPOSURE_PRESENT),
        (fact(ContradictionFactKind.REGISTERED_SHARES, "50000000", fact_number=1),),
        knowledge_cutoff_at=NOW,
    )
    assert receipt.disposition is ContradictionDisposition.INSUFFICIENT
    assert receipt.observed_truth is None
    assert receipt.reason is ContradictionReason.REQUIRED_FACTS_MISSING


def test_form_144_notice_is_not_an_executed_insider_sale_or_acquisition() -> None:
    receipt = check_deterministic_contradiction(
        claim(ContradictionPredicate.NET_INSIDER_ACQUISITION, asserted_truth=False),
        (
            fact(
                ContradictionFactKind.FORM_144_PLANNED_SALE_SHARES,
                "5000",
                fact_number=1,
            ),
        ),
        knowledge_cutoff_at=NOW,
    )
    assert receipt.disposition is ContradictionDisposition.NOT_APPLICABLE
    assert receipt.observed_truth is None
    assert receipt.reason is ContradictionReason.PLANNED_SALE_IS_NOT_EXECUTED_TRANSACTION


def test_executed_insider_totals_determine_net_acquisition_without_directionality() -> None:
    receipt = check_deterministic_contradiction(
        claim(ContradictionPredicate.NET_INSIDER_ACQUISITION),
        (
            fact(ContradictionFactKind.INSIDER_DISPOSED_SHARES, "20", fact_number=2),
            fact(ContradictionFactKind.INSIDER_ACQUIRED_SHARES, "50", fact_number=1),
        ),
        knowledge_cutoff_at=NOW,
    )
    assert receipt.disposition is ContradictionDisposition.SUPPORTED
    assert receipt.observed_truth is True


def test_receipt_is_deterministic_and_irrelevant_facts_do_not_enter_it() -> None:
    reviewed_claim = claim(ContradictionPredicate.CASH_AT_LEAST_CURRENT_LIABILITIES)
    facts = (
        fact(ContradictionFactKind.CASH, "100", fact_number=1),
        fact(ContradictionFactKind.CURRENT_LIABILITIES, "90", fact_number=2),
        fact(ContradictionFactKind.REGISTERED_SHARES, "1000", fact_number=3),
    )
    first = check_deterministic_contradiction(reviewed_claim, facts, knowledge_cutoff_at=NOW)
    second = check_deterministic_contradiction(
        reviewed_claim, tuple(reversed(facts)), knowledge_cutoff_at=NOW
    )
    assert first == second
    assert len(first.facts) == 2


def test_cross_issuer_future_and_wrong_family_inputs_fail_closed() -> None:
    with pytest.raises(ValidationError, match="family"):
        claim(
            ContradictionPredicate.CASH_AT_LEAST_CURRENT_LIABILITIES,
            family=ContradictionFamily.DILUTION,
        )
    with pytest.raises(ValidationError, match="cross-issuer"):
        check_deterministic_contradiction(
            claim(ContradictionPredicate.CASH_AT_LEAST_CURRENT_LIABILITIES),
            (
                fact(
                    ContradictionFactKind.CASH,
                    "100",
                    fact_number=1,
                    cik="0000000044",
                ),
                fact(ContradictionFactKind.CURRENT_LIABILITIES, "90", fact_number=2),
            ),
            knowledge_cutoff_at=NOW,
        )
    with pytest.raises(ValidationError, match="knowledge cutoff"):
        check_deterministic_contradiction(
            claim(ContradictionPredicate.CASH_AT_LEAST_CURRENT_LIABILITIES),
            (
                fact(
                    ContradictionFactKind.CASH,
                    "100",
                    fact_number=1,
                    retrieved_at=NOW + timedelta(seconds=1),
                ),
                fact(ContradictionFactKind.CURRENT_LIABILITIES, "90", fact_number=2),
            ),
            knowledge_cutoff_at=NOW,
        )
    with pytest.raises(ValidationError, match="cross-scope"):
        check_deterministic_contradiction(
            claim(ContradictionPredicate.CASH_AT_LEAST_CURRENT_LIABILITIES),
            (
                fact(
                    ContradictionFactKind.CASH,
                    "100",
                    fact_number=1,
                    comparison_scope_id="different-period-scope",
                ),
                fact(ContradictionFactKind.CURRENT_LIABILITIES, "90", fact_number=2),
            ),
            knowledge_cutoff_at=NOW,
        )


def test_incomparable_fact_periods_are_insufficient_not_a_false_conflict() -> None:
    receipt = check_deterministic_contradiction(
        claim(ContradictionPredicate.CASH_AT_LEAST_CURRENT_LIABILITIES),
        (
            fact(
                ContradictionFactKind.CASH,
                "100",
                fact_number=1,
                as_of_date=date(2026, 6, 30),
            ),
            fact(
                ContradictionFactKind.CURRENT_LIABILITIES,
                "90",
                fact_number=2,
                as_of_date=date(2026, 9, 6),
            ),
        ),
        knowledge_cutoff_at=NOW,
    )
    assert receipt.disposition is ContradictionDisposition.INSUFFICIENT
    assert receipt.observed_truth is None
    assert receipt.reason is ContradictionReason.FACT_PERIODS_INCOMPARABLE


def test_conflicting_source_and_evidence_lineage_fail_closed() -> None:
    shared_evidence_id = UUID("43000000-0000-4000-8001-000000000043")
    with pytest.raises(ValidationError, match="source record has conflicting lineage"):
        check_deterministic_contradiction(
            claim(ContradictionPredicate.CASH_AT_LEAST_CURRENT_LIABILITIES),
            (
                fact(
                    ContradictionFactKind.CASH,
                    "100",
                    fact_number=1,
                    source_record_id="same-source-record",
                ),
                fact(
                    ContradictionFactKind.CURRENT_LIABILITIES,
                    "90",
                    fact_number=2,
                    source_record_id="same-source-record",
                    source_content_sha256="44" * 32,
                ),
            ),
            knowledge_cutoff_at=NOW,
        )
    with pytest.raises(ValidationError, match="evidence ID cannot identify different"):
        check_deterministic_contradiction(
            claim(ContradictionPredicate.CASH_AT_LEAST_CURRENT_LIABILITIES),
            (
                fact(
                    ContradictionFactKind.CASH,
                    "100",
                    fact_number=1,
                    evidence_id=shared_evidence_id,
                ),
                fact(
                    ContradictionFactKind.CURRENT_LIABILITIES,
                    "90",
                    fact_number=2,
                    source_content_sha256="44" * 32,
                    evidence_id=shared_evidence_id,
                ),
            ),
            knowledge_cutoff_at=NOW,
        )


def test_tampered_recomputable_receipt_fails_validation() -> None:
    receipt = check_deterministic_contradiction(
        claim(ContradictionPredicate.CASH_AT_LEAST_CURRENT_LIABILITIES),
        (
            fact(ContradictionFactKind.CASH, "100", fact_number=1),
            fact(ContradictionFactKind.CURRENT_LIABILITIES, "90", fact_number=2),
        ),
        knowledge_cutoff_at=NOW,
    )
    with pytest.raises(ValidationError, match="does not recompute"):
        receipt.model_copy(
            update={"disposition": ContradictionDisposition.CONFLICTED}
        ).model_validate(receipt.model_copy(update={"disposition": "CONFLICTED"}))


def test_financing_adapter_emits_positive_instrument_but_not_resale_registration() -> None:
    resale_bundle = extract_financing_evidence(
        (FINANCING_FIXTURES / "adial-2026-s3-resale-excerpt.html").read_bytes()
    )
    resale = FinancingFilingReceipt(
        accession_number="0001213900-26-095122",
        issuer_cik="0001513525",
        issuer_name="ADIAL PHARMACEUTICALS, INC.",
        form=FinancingForm.S_3,
        terms=parse_shelf_atm_terms(resale_bundle),
        evidence_bundle=resale_bundle,
        source_url=HttpUrl(
            "https://www.sec.gov/Archives/edgar/data/1513525/"
            "000121390026095122/ea0303591-s3_adial.htm"
        ),
        source_content_sha256=resale_bundle.source_content_sha256,
        accepted_at=NOW - timedelta(days=1),
        retrieved_at=NOW,
    )
    assert financing_contradiction_facts(resale) == ()

    warrant_bundle = extract_financing_evidence(
        (FINANCING_FIXTURES / "pluri-2026-424b5-warrant-excerpt.html").read_bytes()
    )
    warrant = FinancingFilingReceipt(
        accession_number="0001213900-26-095124",
        issuer_cik="0001158780",
        issuer_name="PLURI INC.",
        form=FinancingForm.FORM_424B5,
        terms=parse_convertible_preferred_warrant_terms(warrant_bundle),
        evidence_bundle=warrant_bundle,
        source_url=HttpUrl(
            "https://www.sec.gov/Archives/edgar/data/1158780/"
            "000121390026095124/ea0303593-424b5_pluri.htm"
        ),
        source_content_sha256=warrant_bundle.source_content_sha256,
        accepted_at=NOW - timedelta(days=1),
        retrieved_at=NOW,
    )
    facts = financing_contradiction_facts(warrant)
    assert len(facts) == 1
    assert facts[0].kind is ContradictionFactKind.DILUTIVE_INSTRUMENT_COUNT
    assert facts[0].value > 0


def test_liquidity_adapter_requires_evidence_and_preserves_missing_values() -> None:
    evidence_id = UUID("43000000-0000-4000-8001-000000000099")
    facts = liquidity_contradiction_facts(
        ForensicInput(cash_current=Decimal("100"), evidence_ids=(evidence_id,)),
        issuer_cik=CIK,
        comparison_scope_id="balance-sheet:2026-06-30",
        as_of_date=date(2026, 6, 30),
        currency="USD",
        available_at=NOW - timedelta(minutes=2),
        retrieved_at=NOW - timedelta(minutes=1),
        source_record_id="companyfacts-2026q2",
        source_content_sha256=HASH,
    )
    assert len(facts) == 1
    assert facts[0].kind is ContradictionFactKind.CASH
    result = check_deterministic_contradiction(
        claim(
            ContradictionPredicate.CASH_AT_LEAST_CURRENT_LIABILITIES,
            comparison_scope_id="balance-sheet:2026-06-30",
        ),
        facts,
        knowledge_cutoff_at=NOW,
    )
    assert result.disposition is ContradictionDisposition.INSUFFICIENT
    with pytest.raises(ValueError, match="exact evidence IDs"):
        liquidity_contradiction_facts(
            ForensicInput(cash_current=Decimal("100")),
            issuer_cik=CIK,
            comparison_scope_id="balance-sheet:2026-06-30",
            as_of_date=date(2026, 6, 30),
            currency="USD",
            available_at=NOW - timedelta(minutes=2),
            retrieved_at=NOW - timedelta(minutes=1),
            source_record_id="companyfacts-2026q2",
            source_content_sha256=HASH,
        )


def test_share_count_adapter_preserves_both_periods_and_observed_growth() -> None:
    evidence_id = UUID("43000000-0000-4000-8001-000000000098")
    facts = share_count_contradiction_facts(
        ForensicInput(
            shares_previous=Decimal("100"),
            shares_current=Decimal("125"),
            evidence_ids=(evidence_id,),
        ),
        issuer_cik=CIK,
        comparison_scope_id="shares:2026q2-to-2026q3",
        previous_as_of_date=date(2026, 6, 30),
        current_as_of_date=date(2026, 9, 6),
        available_at=NOW - timedelta(minutes=2),
        retrieved_at=NOW - timedelta(minutes=1),
        source_record_id="companyfacts-shares",
        source_content_sha256=HASH,
    )
    result = check_deterministic_contradiction(
        claim(
            ContradictionPredicate.DILUTION_EXPOSURE_PRESENT,
            comparison_scope_id="shares:2026q2-to-2026q3",
        ),
        facts,
        knowledge_cutoff_at=NOW,
    )
    assert result.disposition is ContradictionDisposition.SUPPORTED
    assert result.observed_truth is True


def test_ownership_adapter_binds_exact_date_and_derivative_scope() -> None:
    accession = "0001437749-26-029167"
    receipt = parse_ownership_xml(
        b"""<ownershipDocument><documentType>4</documentType>
        <periodOfReport>2026-09-06</periodOfReport><issuer>
        <issuerCik>0001001385</issuerCik><issuerName>NWPX Infrastructure, Inc.</issuerName>
        </issuer><reportingOwner><reportingOwnerId><rptOwnerName>One Owner</rptOwnerName>
        </reportingOwnerId></reportingOwner><nonDerivativeTable>
        <nonDerivativeTransaction><securityTitle><value>Common Stock</value></securityTitle>
        <transactionDate><value>2026-09-06</value></transactionDate><transactionCoding>
        <transactionCode>P</transactionCode></transactionCoding><transactionAmounts>
        <transactionShares><value>50</value></transactionShares>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
        </transactionAmounts><ownershipNature><directOrIndirectOwnership><value>D</value>
        </directOrIndirectOwnership></ownershipNature></nonDerivativeTransaction>
        <nonDerivativeTransaction><securityTitle><value>Common Stock</value></securityTitle>
        <transactionDate><value>2026-09-06</value></transactionDate><transactionCoding>
        <transactionCode>S</transactionCode></transactionCoding><transactionAmounts>
        <transactionShares><value>20</value></transactionShares>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
        </transactionAmounts><ownershipNature><directOrIndirectOwnership><value>D</value>
        </directOrIndirectOwnership></ownershipNature></nonDerivativeTransaction>
        </nonDerivativeTable></ownershipDocument>""",
        accession_number=accession,
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/1001385/"
            f"{accession.replace('-', '')}/primary_doc.xml"
        ),
        accepted_at=NOW - timedelta(minutes=2),
        retrieved_at=NOW - timedelta(minutes=1),
    )
    facts = ownership_contradiction_facts(
        receipt,
        transaction_date=date(2026, 9, 6),
        derivative=False,
    )
    assert [item.value for item in facts] == [Decimal("50"), Decimal("20")]
    result = check_deterministic_contradiction(
        claim(
            ContradictionPredicate.NET_INSIDER_ACQUISITION,
            comparison_scope_id=facts[0].comparison_scope_id,
            cik=receipt.issuer_cik,
        ),
        facts,
        knowledge_cutoff_at=NOW,
    )
    assert result.disposition is ContradictionDisposition.SUPPORTED
    with pytest.raises(ValueError, match="exact date and derivative scope"):
        ownership_contradiction_facts(receipt)


def test_private_service_persists_only_completeness_consistent_result() -> None:
    sink = ReceiptSink()
    service = ConvergenceValidationService(sink)
    request = ConvergenceValidationRequest(
        claim=claim(ContradictionPredicate.CASH_AT_LEAST_CURRENT_LIABILITIES),
        facts=(
            fact(ContradictionFactKind.CASH, "100", fact_number=1),
            fact(ContradictionFactKind.CURRENT_LIABILITIES, "90", fact_number=2),
        ),
        knowledge_cutoff_at=NOW,
        fact_completeness=ConvergenceFactCompleteness.REQUIRED_FACTS_COMPLETE,
    )
    receipt = service.evaluate_and_persist(request)
    assert receipt.disposition is ContradictionDisposition.SUPPORTED
    assert sink.receipts == [receipt]


def test_private_service_rejects_caller_completeness_disagreement_before_write() -> None:
    sink = ReceiptSink()
    service = ConvergenceValidationService(sink)
    request = ConvergenceValidationRequest(
        claim=claim(ContradictionPredicate.CASH_AT_LEAST_CURRENT_LIABILITIES),
        facts=(fact(ContradictionFactKind.CASH, "100", fact_number=1),),
        knowledge_cutoff_at=NOW,
        fact_completeness=ConvergenceFactCompleteness.REQUIRED_FACTS_COMPLETE,
    )
    with pytest.raises(ValueError, match="completeness classification"):
        service.evaluate_and_persist(request)
    assert sink.receipts == []


def test_private_service_accepts_explicit_partial_and_not_applicable_inputs() -> None:
    sink = ReceiptSink()
    service = ConvergenceValidationService(sink)
    partial = ConvergenceValidationRequest(
        claim=claim(ContradictionPredicate.CASH_AT_LEAST_CURRENT_LIABILITIES),
        facts=(fact(ContradictionFactKind.CASH, "100", fact_number=1),),
        knowledge_cutoff_at=NOW,
        fact_completeness=ConvergenceFactCompleteness.PARTIAL_VALIDATED_FACTS,
    )
    planned = ConvergenceValidationRequest(
        claim=claim(ContradictionPredicate.NET_INSIDER_ACQUISITION),
        facts=(
            fact(
                ContradictionFactKind.FORM_144_PLANNED_SALE_SHARES,
                "5000",
                fact_number=3,
            ),
        ),
        knowledge_cutoff_at=NOW,
        fact_completeness=ConvergenceFactCompleteness.NOT_APPLICABLE_CONTEXT,
    )
    assert (
        service.evaluate_and_persist(partial).disposition is ContradictionDisposition.INSUFFICIENT
    )
    assert (
        service.evaluate_and_persist(planned).disposition is ContradictionDisposition.NOT_APPLICABLE
    )
    assert len(sink.receipts) == 2
