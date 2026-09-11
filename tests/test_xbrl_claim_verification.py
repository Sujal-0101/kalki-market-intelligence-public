"""Focused XBRL-backed numeric verification tests."""

from datetime import UTC, date, datetime
from decimal import Decimal

from kalki_market_intelligence.providers.sec.contracts import SecFactRecord
from kalki_market_intelligence.quantitative import (
    NumericClaim,
    NumericVerificationStatus,
    verify_numeric_claim_against_xbrl,
)


def fact(value: str, *, tag: str = "Revenue") -> SecFactRecord:
    return SecFactRecord(
        record_id="a" * 64,
        cik="0000000001",
        entity_name="Fixture issuer",
        taxonomy="us-gaap",
        tag=tag,
        label=tag,
        description=None,
        unit="USD",
        value=Decimal(value),
        period_start=date(2026, 1, 1),
        period_end=date(2026, 3, 31),
        filed_date=date(2026, 4, 30),
        accession_number="0000000001-26-000001",
        form="10-Q",
        fiscal_year=2026,
        fiscal_period="Q1",
        frame=None,
        available_at=datetime(2026, 4, 30, tzinfo=UTC),
        retrieved_at=datetime(2026, 4, 30, tzinfo=UTC),
        source_content_sha256="b" * 64,
    )


def claim(value: str) -> NumericClaim:
    return NumericClaim(
        claim_id="C01",
        evidence_id="evidence-1",
        claimed_value=Decimal(value),
        unit="USD",
        xbrl_tag="Revenue",
        period_end=date(2026, 3, 31),
        form="10-Q",
    )


def test_xbrl_match_is_verified() -> None:
    result = verify_numeric_claim_against_xbrl(
        claim("12.5"), [fact("12.5")], accession_number="0000000001-26-000001"
    )
    assert result.status is NumericVerificationStatus.VERIFIED


def test_xbrl_context_ambiguity_is_partial_not_guessed() -> None:
    duplicate_context = fact("13.5").model_copy(update={"period_start": date(2025, 1, 1)})
    result = verify_numeric_claim_against_xbrl(
        claim("12.5"),
        [fact("12.5"), duplicate_context],
        accession_number="0000000001-26-000001",
    )
    assert result.status is NumericVerificationStatus.PARTIALLY_VERIFIED


def test_xbrl_missing_filing_fact_is_unverifiable() -> None:
    result = verify_numeric_claim_against_xbrl(
        claim("12.5"), [fact("12.5")], accession_number="0000000001-26-000002"
    )
    assert result.status is NumericVerificationStatus.UNVERIFIABLE


def test_unrelated_xbrl_context_is_not_misclassified_as_conflicting() -> None:
    unrelated_claim = claim("99").model_copy(update={"xbrl_tag": "GrossProfit"})
    result = verify_numeric_claim_against_xbrl(
        unrelated_claim,
        [fact("12.5"), fact("13.5", tag="OtherRevenue")],
        accession_number="0000000001-26-000001",
    )
    assert result.status is NumericVerificationStatus.UNVERIFIABLE


def test_same_value_wrong_concept_or_period_is_ignored() -> None:
    wrong_concept = fact("12.5", tag="Assets")
    wrong_period = fact("12.5")
    wrong_period = wrong_period.model_copy(update={"period_end": date(2025, 12, 31)})
    result = verify_numeric_claim_against_xbrl(
        claim("12.5"),
        [wrong_concept, wrong_period],
        accession_number="0000000001-26-000001",
    )
    assert result.status is NumericVerificationStatus.UNVERIFIABLE
