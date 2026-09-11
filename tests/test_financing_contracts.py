"""Closed Phase 40 financing and dilution contracts."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import HttpUrl, ValidationError

from kalki_market_intelligence.forensics.financing import (
    FinancingEventContext,
    FinancingEventStatus,
    FinancingEvidenceSignal,
    FinancingFilingReceipt,
    FinancingForm,
    FinancingInstrument,
    FinancingParseError,
    FinancingTerm,
    IssuerProceedsStatus,
    MoneyBasis,
    ReportedAmountStatus,
    ReportedMoney,
    choose_financing_tier,
    extract_financing_evidence,
    normalize_financing_form,
    parse_convertible_preferred_warrant_terms,
    parse_debt_terms,
    parse_equity_line_terms,
    parse_private_placement_terms,
    parse_public_offering_terms,
    parse_shelf_atm_terms,
    parse_warrant_change_terms,
)

NOW = datetime(2026, 8, 29, tzinfo=UTC)
EVIDENCE = UUID("41000000-0000-4000-8000-000000000040")
FIXTURES = Path(__file__).parent / "fixtures" / "financing"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("S-1", FinancingForm.S_1),
        ("s-3/a", FinancingForm.S_3_A),
        ("424B5", FinancingForm.FORM_424B5),
        ("8-k", FinancingForm.FORM_8_K),
    ],
)
def test_supported_financing_forms_are_closed(raw: str, expected: FinancingForm) -> None:
    assert normalize_financing_form(raw) is expected


def test_unsupported_prospectus_form_fails_closed() -> None:
    with pytest.raises(FinancingParseError, match="unsupported"):
        normalize_financing_form("F-3")


def test_resale_registration_does_not_claim_completed_issuance() -> None:
    bundle = extract_financing_evidence(
        (FIXTURES / "adial-2026-s3-resale-excerpt.html").read_bytes()
    )
    term = parse_shelf_atm_terms(bundle)[0]
    receipt = FinancingFilingReceipt(
        accession_number="0001213900-26-095122",
        issuer_cik="0001513525",
        issuer_name="ADIAL PHARMACEUTICALS, INC.",
        form=FinancingForm.S_3,
        terms=(term,),
        evidence_bundle=bundle,
        source_url=HttpUrl(
            "https://www.sec.gov/Archives/edgar/data/1513525/000121390026095122/"
            "ea0303591-s3_adial.htm"
        ),
        source_content_sha256=bundle.source_content_sha256,
        accepted_at=NOW,
        retrieved_at=NOW,
    )
    assert receipt.terms[0].status is FinancingEventStatus.REGISTERED
    assert receipt.terms[0].offered_shares == Decimal("25148970")
    assert receipt.terms[0].issuable_shares is None
    assert receipt.terms[0].money == ()


def test_real_resale_fixture_retains_no_proceeds_and_issuable_context() -> None:
    bundle = extract_financing_evidence(
        (FIXTURES / "adial-2026-s3-resale-excerpt.html").read_bytes()
    )
    signals = {signal for evidence in bundle.evidence for signal in evidence.signals}
    assert FinancingEvidenceSignal.REGISTRATION_RESALE in signals
    assert FinancingEvidenceSignal.PROCEEDS_LANGUAGE in signals
    assert FinancingEvidenceSignal.ISSUABLE_SECURITIES in signals
    assert all(len(item.text) <= 720 for item in bundle.evidence)
    assert sum(len(item.text) for item in bundle.evidence) <= 8_000
    terms = parse_shelf_atm_terms(bundle)
    assert len(terms) == 1
    assert terms[0].instrument is FinancingInstrument.RESALE_REGISTRATION
    assert terms[0].offered_shares == Decimal("25148970")
    assert terms[0].issuer_proceeds_status is IssuerProceedsStatus.NONE_TO_ISSUER
    assert terms[0].money == ()


def test_real_atm_fixture_separates_capacity_from_disclosed_sales() -> None:
    body = (FIXTURES / "kazia-2026-424b5-atm-excerpt.html").read_bytes()
    first = extract_financing_evidence(body)
    second = extract_financing_evidence(body)
    signals = {signal for evidence in first.evidence for signal in evidence.signals}
    assert FinancingEvidenceSignal.ATM_PROGRAM in signals
    assert FinancingEvidenceSignal.OFFERING_CAPACITY in signals
    assert FinancingEvidenceSignal.ACTUAL_SALES_DISCLOSED in signals
    assert first == second
    assert all("net proceeds" not in item.text.casefold() for item in first.evidence)
    terms = parse_shelf_atm_terms(first)
    assert len(terms) == 1
    assert terms[0].instrument is FinancingInstrument.ATM_PROGRAM
    assert terms[0].status is FinancingEventStatus.AMENDED
    assert terms[0].sold_shares == Decimal("510000")
    assert terms[0].issuer_proceeds_status is IssuerProceedsStatus.UNKNOWN
    assert [(item.amount, item.basis) for item in terms[0].money] == [
        (Decimal("80000000"), MoneyBasis.MAXIMUM_AGGREGATE_OFFERING),
        (Decimal("5106516"), MoneyBasis.AGGREGATE_SALE_PRICE),
    ]


def test_capacity_and_aggregate_sale_price_are_not_relabelled_as_proceeds() -> None:
    bundle = extract_financing_evidence(
        (FIXTURES / "kazia-2026-424b5-atm-excerpt.html").read_bytes()
    )
    term = parse_shelf_atm_terms(bundle)[0]
    assert MoneyBasis.GROSS_PROCEEDS not in {item.basis for item in term.money}
    assert MoneyBasis.NET_PROCEEDS not in {item.basis for item in term.money}
    with pytest.raises(ValidationError, match="reported issuer proceeds"):
        FinancingTerm(
            instrument=FinancingInstrument.ATM_PROGRAM,
            status=FinancingEventStatus.AVAILABLE,
            money=(
                ReportedMoney(
                    amount=Decimal("100"),
                    currency="USD",
                    basis=MoneyBasis.MAXIMUM_AGGREGATE_OFFERING,
                ),
            ),
            issuer_proceeds_status=IssuerProceedsStatus.REPORTED,
            evidence_ids=(EVIDENCE,),
        )


def test_real_priced_public_offering_preserves_only_explicit_terms() -> None:
    body = (FIXTURES / "wellchange-2026-424b4-priced-offering-excerpt.html").read_bytes()
    bundle = extract_financing_evidence(body)
    signals = {signal for evidence in bundle.evidence for signal in evidence.signals}
    assert FinancingEvidenceSignal.PUBLIC_OFFERING in signals
    assert FinancingEvidenceSignal.OFFERING_PRICE in signals
    terms = parse_public_offering_terms(bundle)
    assert len(terms) == 1
    term = terms[0]
    assert term.instrument is FinancingInstrument.PUBLIC_OFFERING
    assert term.status is FinancingEventStatus.PRICED
    assert term.offered_shares == Decimal("50000000")
    assert term.price_per_share == Decimal("0.15")
    assert term.sold_shares is None
    assert term.money == ()
    assert term.closing_on is None
    assert term.issuer_proceeds_status is IssuerProceedsStatus.UNKNOWN

    receipt = FinancingFilingReceipt(
        accession_number="0001213900-26-094944",
        issuer_cik="0001990251",
        issuer_name="Wellchange Holdings Company Limited",
        form=FinancingForm.FORM_424B4,
        terms=terms,
        evidence_bundle=bundle,
        source_url=HttpUrl(
            "https://www.sec.gov/Archives/edgar/data/1990251/000121390026094944/"
            "ea0303809-424b4_wellchange.htm"
        ),
        source_content_sha256=bundle.source_content_sha256,
        accepted_at=NOW,
        retrieved_at=NOW,
    )
    assert receipt.terms == terms


def test_public_offering_does_not_infer_price_or_proceeds_from_separate_contexts() -> None:
    bundle = extract_financing_evidence(
        b"<p>We are offering up to 10,000,000 common shares.</p>"
        b"<p>A historical public offering price of $4.00 per common share was reported.</p>"
        b"<p>Estimated net proceeds may vary.</p>"
    )
    assert parse_public_offering_terms(bundle) == ()


def test_real_pipe_keeps_expected_proceeds_distinct_from_completed_cash() -> None:
    bundle = extract_financing_evidence(
        (FIXTURES / "madison-air-2026-8k-pipe-excerpt.html").read_bytes()
    )
    terms = parse_private_placement_terms(bundle)
    assert len(terms) == 1
    term = terms[0]
    assert term.instrument is FinancingInstrument.PIPE
    assert term.status is FinancingEventStatus.PRICED
    assert term.offered_shares == Decimal("90108130")
    assert term.price_per_share == Decimal("24.97")
    assert term.closing_on is None
    assert term.money == (
        ReportedMoney(
            amount=Decimal("2250000000"),
            currency="USD",
            basis=MoneyBasis.GROSS_PROCEEDS,
            amount_status=ReportedAmountStatus.EXPECTED,
        ),
    )


def test_real_convertible_and_preferred_terms_remain_separate() -> None:
    bundle = extract_financing_evidence(
        (FIXTURES / "mobix-2026-8k-convertible-preferred-excerpt.html").read_bytes()
    )
    terms = parse_convertible_preferred_warrant_terms(bundle)
    assert [term.instrument for term in terms] == [
        FinancingInstrument.CONVERTIBLE_DEBT,
        FinancingInstrument.PREFERRED_EQUITY,
    ]
    convertible, preferred = terms
    assert convertible.status is FinancingEventStatus.CLOSED
    assert convertible.money[0].amount == Decimal("1200000")
    assert convertible.money[0].basis is MoneyBasis.PRINCIPAL
    assert convertible.interest_rate_percent == Decimal("10")
    assert convertible.maturity_on == date(2026, 12, 25)
    assert convertible.covenant_text == ("customary affirmative and negative covenants",)
    assert convertible.conversion_price is None
    assert preferred.status is FinancingEventStatus.PROPOSED
    assert preferred.offered_shares == Decimal("1000")
    assert preferred.money[0].amount == Decimal("1000")
    assert preferred.money[0].basis is MoneyBasis.GROSS_PROCEEDS


def test_real_private_placement_warrant_retains_exercise_terms() -> None:
    bundle = extract_financing_evidence(
        (FIXTURES / "pluri-2026-424b5-warrant-excerpt.html").read_bytes()
    )
    terms = parse_convertible_preferred_warrant_terms(bundle)
    assert len(terms) == 1
    term = terms[0]
    assert term.instrument is FinancingInstrument.WARRANT
    assert term.status is FinancingEventStatus.PRICED
    assert term.issuable_shares == Decimal("2228940")
    assert term.exercise_price == Decimal("1.65")
    assert term.sold_shares is None


def test_real_warrant_repricing_retains_previous_and_amended_prices() -> None:
    bundle = extract_financing_evidence(
        (FIXTURES / "virtuix-2026-8k-warrant-repricing-excerpt.html").read_bytes()
    )
    terms = parse_warrant_change_terms(bundle)
    assert len(terms) == 1
    term = terms[0]
    assert term.instrument is FinancingInstrument.WARRANT_REPRICING
    assert term.status is FinancingEventStatus.AMENDED
    assert term.previous_exercise_price == Decimal("4.00")
    assert term.exercise_price == Decimal("3.00")
    assert term.sold_shares is None
    assert term.money == ()


def test_real_warrant_exercise_inducement_keeps_conditional_terms_proposed() -> None:
    bundle = extract_financing_evidence(
        (FIXTURES / "aim-2026-8k-warrant-inducement-excerpt.html").read_bytes()
    )
    terms = parse_warrant_change_terms(bundle)
    assert len(terms) == 1
    term = terms[0]
    assert term.instrument is FinancingInstrument.WARRANT_EXERCISE_INDUCEMENT
    assert term.status is FinancingEventStatus.PROPOSED
    assert term.price_per_share == Decimal("0.48")
    assert term.issuable_shares == Decimal("17439856")
    assert term.exercise_price == Decimal("0.60")
    assert term.sold_shares is None
    assert term.money == (
        ReportedMoney(
            amount=Decimal("4200000"),
            currency="USD",
            basis=MoneyBasis.GROSS_PROCEEDS,
            amount_status=ReportedAmountStatus.EXPECTED,
        ),
    )


def test_inducement_without_new_warrant_price_fails_closed() -> None:
    bundle = extract_financing_evidence(
        b"<p>The holders agreed to exercise the Existing Warrants for cash at a reduced "
        b"exercise price of $0.48 per share in consideration for new warrants to purchase "
        b"up to 10,000 shares.</p>"
    )
    assert parse_warrant_change_terms(bundle) == ()


def test_real_terminated_equity_line_is_not_available_capacity() -> None:
    bundle = extract_financing_evidence(
        (FIXTURES / "momentus-2026-8k-equity-line-termination-excerpt.html").read_bytes()
    )
    terms = parse_equity_line_terms(bundle)
    assert len(terms) == 1
    term = terms[0]
    assert term.instrument is FinancingInstrument.EQUITY_LINE
    assert term.status is FinancingEventStatus.TERMINATED
    assert term.money[0].amount == Decimal("50000000")
    assert term.money[0].basis is MoneyBasis.COMMITMENT
    assert term.issuer_proceeds_status is IssuerProceedsStatus.UNKNOWN


def test_equity_line_without_explicit_termination_fails_closed() -> None:
    bundle = extract_financing_evidence(
        b"<p>The Equity Purchase Agreement provided the Company the right, but not the "
        b"obligation, to direct the Investor to purchase up to $50,000,000 in shares.</p>"
    )
    assert parse_equity_line_terms(bundle) == ()


def test_real_closed_debt_offering_retains_principal_rate_and_maturity() -> None:
    bundle = extract_financing_evidence(
        (FIXTURES / "valvoline-2026-8k-debt-excerpt.html").read_bytes()
    )
    terms = parse_debt_terms(bundle)
    assert len(terms) == 1
    term = terms[0]
    assert term.instrument is FinancingInstrument.DEBT
    assert term.status is FinancingEventStatus.CLOSED
    assert term.money[0].amount == Decimal("600000000")
    assert term.money[0].basis is MoneyBasis.PRINCIPAL
    assert term.interest_rate_percent == Decimal("6.125")
    assert term.maturity_on == date(2034, 8, 15)


def test_debt_due_year_conflict_fails_closed() -> None:
    bundle = extract_financing_evidence(
        b"<p>The Company closed its previously announced notes offering of $10 million "
        b"aggregate principal amount of its 5% senior notes due 2034.</p>"
        b"<p>The Notes will mature on August 15, 2035.</p>"
    )
    with pytest.raises(FinancingParseError, match="due year conflicts"):
        parse_debt_terms(bundle)


def test_financing_tier0_retains_context_without_direction_or_model() -> None:
    bundle = extract_financing_evidence(
        (FIXTURES / "valvoline-2026-8k-debt-excerpt.html").read_bytes()
    )
    receipt = FinancingFilingReceipt(
        accession_number="0001628280-26-058633",
        issuer_cik="0001674910",
        issuer_name="Valvoline Inc.",
        form=FinancingForm.FORM_8_K,
        terms=parse_debt_terms(bundle),
        evidence_bundle=bundle,
        source_url=HttpUrl(
            "https://www.sec.gov/Archives/edgar/data/1674910/000162828026058633/vvv-20260824.htm"
        ),
        source_content_sha256=bundle.source_content_sha256,
        accepted_at=NOW,
        retrieved_at=NOW,
    )
    routing = choose_financing_tier(receipt)
    assert routing.event_context is FinancingEventContext.DEBT_FINANCING
    assert routing.decision.tier == 0
    assert routing.decision.outcome.value == "retain"
    assert routing.decision.requires_model is False
    assert routing.decision.forensic_signals == ()


def test_financing_extraction_ignores_hidden_instructions_and_bounds_input() -> None:
    bundle = extract_financing_evidence(
        b"<script>we have sold $999999999</script><p>No financing terms.</p>"
    )
    assert bundle.evidence == ()
    with pytest.raises(FinancingParseError, match="size boundary"):
        extract_financing_evidence(b"x" * 8_000_001)


def test_receipt_rejects_unextracted_evidence_reference() -> None:
    bundle = extract_financing_evidence(
        (FIXTURES / "adial-2026-s3-resale-excerpt.html").read_bytes()
    )
    with pytest.raises(ValidationError, match="extracted evidence"):
        FinancingFilingReceipt(
            accession_number="0001213900-26-095122",
            issuer_cik="0001513525",
            issuer_name="ADIAL PHARMACEUTICALS, INC.",
            form=FinancingForm.S_3,
            terms=(
                FinancingTerm(
                    instrument=FinancingInstrument.SHELF_REGISTRATION,
                    status=FinancingEventStatus.REGISTERED,
                    evidence_ids=(EVIDENCE,),
                ),
            ),
            evidence_bundle=bundle,
            source_url=HttpUrl(
                "https://www.sec.gov/Archives/edgar/data/1513525/000121390026095122/"
                "ea0303591-s3_adial.htm"
            ),
            source_content_sha256=bundle.source_content_sha256,
            accepted_at=NOW,
            retrieved_at=NOW,
        )


def test_instrument_specific_terms_cannot_be_reassigned() -> None:
    with pytest.raises(ValidationError, match="only a warrant event"):
        FinancingTerm(
            instrument=FinancingInstrument.ATM_PROGRAM,
            status=FinancingEventStatus.AVAILABLE,
            exercise_price=Decimal("1.25"),
            evidence_ids=(EVIDENCE,),
        )
    with pytest.raises(ValidationError, match="maturity requires"):
        FinancingTerm(
            instrument=FinancingInstrument.PUBLIC_OFFERING,
            status=FinancingEventStatus.PRICED,
            maturity_on=date(2030, 1, 1),
            evidence_ids=(EVIDENCE,),
        )
