"""Source-specific Phase 43 producer eligibility remains fail closed."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from pydantic import HttpUrl

from kalki_market_intelligence.forensics import (
    ContradictionDisposition,
    ContradictionReceipt,
    ConvergenceProducerReason,
    ConvergenceValidationService,
    FinancingFilingReceipt,
    FinancingForm,
    choose_financing_tier,
    financing_convergence_decision,
    ownership_convergence_decision,
    xbrl_liquidity_convergence_decision,
)
from kalki_market_intelligence.forensics.financing import (
    extract_financing_evidence,
    parse_convertible_preferred_warrant_terms,
    parse_shelf_atm_terms,
)
from kalki_market_intelligence.forensics.ownership import choose_ownership_tier
from kalki_market_intelligence.providers.sec.contracts import SecFactRecord
from kalki_market_intelligence.providers.sec.ownership import parse_ownership_xml

NOW = datetime(2026, 9, 7, 20, 0, tzinfo=UTC)
FIXTURES = Path(__file__).parent / "fixtures" / "financing"


class Sink:
    def __init__(self) -> None:
        self.items: list[ContradictionReceipt] = []

    def append_receipt(self, receipt: ContradictionReceipt) -> ContradictionReceipt:
        self.items.append(receipt)
        return receipt


def _financing_receipt(*, resale: bool) -> FinancingFilingReceipt:
    name = (
        "adial-2026-s3-resale-excerpt.html" if resale else "pluri-2026-424b5-warrant-excerpt.html"
    )
    bundle = extract_financing_evidence((FIXTURES / name).read_bytes())
    terms = (
        parse_shelf_atm_terms(bundle)
        if resale
        else parse_convertible_preferred_warrant_terms(bundle)
    )
    accession = "0001213900-26-095122" if resale else "0001213900-26-095124"
    cik = "0001513525" if resale else "0001158780"
    form = FinancingForm.S_3 if resale else FinancingForm.FORM_424B5
    return FinancingFilingReceipt(
        accession_number=accession,
        issuer_cik=cik,
        issuer_name="Validated issuer",
        form=form,
        terms=terms,
        evidence_bundle=bundle,
        source_url=HttpUrl(
            f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
            f"{accession.replace('-', '')}/primary.htm"
        ),
        source_content_sha256=bundle.source_content_sha256,
        accepted_at=NOW - timedelta(hours=2),
        retrieved_at=NOW - timedelta(hours=1),
    )


def _xbrl_fact(*, tag: str, value: str, number: int, period_end: date) -> SecFactRecord:
    return SecFactRecord(
        record_id=f"{number:064x}",
        cik="0001001385",
        entity_name="Validated issuer",
        taxonomy="us-gaap",
        tag=tag,
        label=tag,
        description=None,
        unit="USD",
        value=Decimal(value),
        period_start=None,
        period_end=period_end,
        filed_date=date(2026, 8, 7),
        accession_number="0001001385-26-000043",
        form="10-Q",
        fiscal_year=None,
        fiscal_period=None,
        frame=None,
        available_at=NOW - timedelta(hours=2),
        retrieved_at=NOW - timedelta(hours=1),
        source_content_sha256="43" * 32,
    )


def test_financing_producer_admits_only_explicit_active_issuable_exposure() -> None:
    warrant = _financing_receipt(resale=False)
    eligible = financing_convergence_decision(
        warrant,
        choose_financing_tier(warrant),
        knowledge_cutoff_at=NOW,
    )
    assert eligible.reason is ConvergenceProducerReason.ELIGIBLE_COMPLETE_FACTS
    sink = Sink()
    receipt = ConvergenceValidationService(sink).evaluate_and_persist(eligible.requests[0])
    assert receipt.disposition is ContradictionDisposition.SUPPORTED

    resale = _financing_receipt(resale=True)
    excluded = financing_convergence_decision(
        resale,
        choose_financing_tier(resale),
        knowledge_cutoff_at=NOW,
    )
    assert excluded.reason is ConvergenceProducerReason.NO_RELEVANT_VALIDATED_FACTS
    assert excluded.requests == ()


def test_ownership_producer_separates_executed_and_planned_transactions() -> None:
    accession = "0001437749-26-029167"
    section16 = parse_ownership_xml(
        b"""<ownershipDocument><documentType>4</documentType>
        <periodOfReport>2026-09-06</periodOfReport><issuer>
        <issuerCik>0001001385</issuerCik><issuerName>Issuer</issuerName></issuer>
        <reportingOwner><reportingOwnerId><rptOwnerName>Owner</rptOwnerName>
        </reportingOwnerId></reportingOwner><nonDerivativeTable>
        <nonDerivativeTransaction><securityTitle><value>Common</value></securityTitle>
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
            f"{accession.replace('-', '')}/primary.xml"
        ),
        accepted_at=NOW - timedelta(hours=2),
        retrieved_at=NOW - timedelta(hours=1),
    )
    decision = ownership_convergence_decision(
        section16,
        choose_ownership_tier(section16),
        knowledge_cutoff_at=NOW,
    )
    assert decision.reason is ConvergenceProducerReason.ELIGIBLE_COMPLETE_FACTS
    result = ConvergenceValidationService(Sink()).evaluate_and_persist(decision.requests[0])
    assert result.disposition is ContradictionDisposition.CONFLICTED


def test_xbrl_liquidity_requires_one_exact_same_period_pair() -> None:
    period = date(2026, 6, 30)
    facts = (
        _xbrl_fact(
            tag="CashAndCashEquivalentsAtCarryingValue",
            value="100",
            number=1,
            period_end=period,
        ),
        _xbrl_fact(tag="LiabilitiesCurrent", value="90", number=2, period_end=period),
    )
    decision = xbrl_liquidity_convergence_decision(
        facts,
        issuer_cik="0001001385",
        accession_number="0001001385-26-000043",
        filing_form="10-Q",
        knowledge_cutoff_at=NOW,
    )
    assert decision.reason is ConvergenceProducerReason.ELIGIBLE_COMPLETE_FACTS
    result = ConvergenceValidationService(Sink()).evaluate_and_persist(decision.requests[0])
    assert result.disposition is ContradictionDisposition.SUPPORTED

    ambiguous = xbrl_liquidity_convergence_decision(
        (
            *facts,
            _xbrl_fact(
                tag="CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
                value="100",
                number=3,
                period_end=period,
            ),
        ),
        issuer_cik="0001001385",
        accession_number="0001001385-26-000043",
        filing_form="10-Q",
        knowledge_cutoff_at=NOW,
    )
    assert ambiguous.reason is ConvergenceProducerReason.AMBIGUOUS_XBRL_CONTEXT
    assert ambiguous.requests == ()
