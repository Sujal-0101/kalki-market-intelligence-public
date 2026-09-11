"""Conservative deterministic forensic detector tests."""

from decimal import Decimal
from uuid import UUID

from kalki_market_intelligence.forensics import (
    ForensicInput,
    ForensicStatus,
    assess_forensics,
)

EVIDENCE = UUID("41000000-0000-4000-8000-000000000001")


def test_forensics_reports_dilution_and_distress_from_supplied_facts() -> None:
    results = assess_forensics(
        ForensicInput(
            shares_previous=Decimal("100"),
            shares_current=Decimal("125"),
            cash_current=Decimal("10"),
            current_liabilities=Decimal("25"),
            evidence_ids=(EVIDENCE,),
            text=(
                "The auditor expressed substantial doubt about going concern; "
                "a reverse split is proposed."
            ),
        )
    )
    by_id = {item.signal_id: item for item in results}
    assert by_id["share_count_growth"].status is ForensicStatus.POSITIVE
    assert by_id["liquidity_pressure"].status is ForensicStatus.POSITIVE
    assert by_id["going_concern"].status is ForensicStatus.POSITIVE
    assert by_id["reverse_split"].status is ForensicStatus.POSITIVE


def test_forensics_never_treats_missing_inputs_as_safe() -> None:
    # The worker explicitly supplies an empty extracted excerpt. It must have
    # the same not-assessed semantics as the contract default.
    results = assess_forensics(ForensicInput(text=""))
    by_id = {item.signal_id: item for item in results}
    assert by_id["share_count_growth"].status is ForensicStatus.UNKNOWN
    assert by_id["liquidity_pressure"].status is ForensicStatus.NOT_ASSESSED
    assert by_id["going_concern"].status is ForensicStatus.NOT_ASSESSED
