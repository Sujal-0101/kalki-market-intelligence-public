"""Small deterministic primary-source forensic detectors.

These detectors deliberately report unavailable inputs instead of interpreting
absence as safety.  They are pure functions and are not yet wired into worker
qualification, so production behavior remains unchanged while fixtures mature.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints

from kalki_market_intelligence.contracts.common import ContractModel, ShortText


class ForensicStatus(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    UNKNOWN = "unknown"
    NOT_ASSESSED = "not_assessed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ForensicInput(ContractModel):
    """Bounded values and source identifiers supplied by deterministic parsing."""

    shares_current: Decimal | None = Field(default=None, ge=0)
    shares_previous: Decimal | None = Field(default=None, ge=0)
    cash_current: Decimal | None = None
    current_liabilities: Decimal | None = None
    evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=16)
    text: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] = ""


class ForensicSignal(ContractModel):
    signal_id: ShortText
    status: ForensicStatus
    explanation: ShortText
    evidence_ids: tuple[UUID, ...] = Field(max_length=16)
    calculation_version: str = "1.0.0"


def assess_forensics(inputs: ForensicInput) -> tuple[ForensicSignal, ...]:
    """Run conservative dilution, liquidity, and distress indicators."""

    return (
        _share_growth(inputs),
        _liquidity(inputs),
        _text_indicator(
            inputs,
            signal_id="going_concern",
            terms=("going concern", "substantial doubt"),
            explanation="Primary-source text contains a going-concern indicator.",
        ),
        _text_indicator(
            inputs,
            signal_id="reverse_split",
            terms=("reverse split", "reverse stock split"),
            explanation="Primary-source text contains a reverse-split indicator.",
        ),
    )


def _share_growth(inputs: ForensicInput) -> ForensicSignal:
    if inputs.shares_current is None or inputs.shares_previous is None:
        status = ForensicStatus.UNKNOWN
        explanation = "Share-count comparison was not assessed because a period is missing."
    elif inputs.shares_previous == 0:
        status = ForensicStatus.INSUFFICIENT_EVIDENCE
        explanation = "Share-count comparison is undefined because the prior count is zero."
    elif inputs.shares_current > inputs.shares_previous:
        status = ForensicStatus.POSITIVE
        explanation = "Reported shares outstanding increased versus the prior period."
    else:
        status = ForensicStatus.NEGATIVE
        explanation = "No deterministic share-count growth was observed."
    return ForensicSignal(
        signal_id="share_count_growth",
        status=status,
        explanation=explanation,
        evidence_ids=inputs.evidence_ids,
    )


def _liquidity(inputs: ForensicInput) -> ForensicSignal:
    if inputs.cash_current is None or inputs.current_liabilities is None:
        return ForensicSignal(
            signal_id="liquidity_pressure",
            status=ForensicStatus.NOT_ASSESSED,
            explanation="Liquidity pressure was not assessed because required facts are missing.",
            evidence_ids=inputs.evidence_ids,
        )
    status = (
        ForensicStatus.POSITIVE
        if inputs.cash_current < inputs.current_liabilities
        else ForensicStatus.NEGATIVE
    )
    explanation = (
        "Cash is below current liabilities in the supplied period."
        if status is ForensicStatus.POSITIVE
        else "Cash is not below current liabilities in the supplied period."
    )
    return ForensicSignal(
        signal_id="liquidity_pressure",
        status=status,
        explanation=explanation,
        evidence_ids=inputs.evidence_ids,
    )


def _text_indicator(
    inputs: ForensicInput, *, signal_id: str, terms: tuple[str, ...], explanation: str
) -> ForensicSignal:
    if not inputs.text:
        status = ForensicStatus.NOT_ASSESSED
        message = "Text indicator was not assessed because no bounded filing text was supplied."
    elif any(term in inputs.text.casefold() for term in terms):
        status = ForensicStatus.POSITIVE
        message = explanation
    else:
        status = ForensicStatus.NEGATIVE
        message = "No deterministic indicator was found in the supplied bounded text."
    return ForensicSignal(
        signal_id=signal_id,
        status=status,
        explanation=message,
        evidence_ids=inputs.evidence_ids,
    )
