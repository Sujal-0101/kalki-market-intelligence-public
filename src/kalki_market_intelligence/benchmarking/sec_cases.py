"""Local, reproducible SEC-analysis cases for production-model comparison."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal
from uuid import UUID

from kalki_market_intelligence.analysis.contracts import (
    AnalystEvidence,
    AnalystRole,
    Assessment,
)
from kalki_market_intelligence.contracts.evidence import SourceClass

CaseCapability = Literal[
    "catalyst",
    "risk",
    "identity",
    "numeric_correction",
    "uncertainty",
]
SourceKind = Literal["real_public_sec_excerpt", "synthetic_sec_style_test"]


@dataclass(frozen=True, slots=True)
class SecModelCase:
    """One bounded case with deterministic, capability-specific expectations."""

    name: str
    source_kind: SourceKind
    capability: CaseCapability
    role: AnalystRole
    knowledge_cutoff_at: datetime
    evidence: tuple[AnalystEvidence, ...]
    expected_assessment: Assessment
    required_terms: tuple[str, ...] = ()
    numeric_terms: tuple[str, ...] = ()
    identity_terms: tuple[str, ...] = ()
    forbidden_terms: tuple[str, ...] = (
        "buy the stock",
        "sell the stock",
        "guaranteed return",
        "price target",
    )


def _evidence(
    *,
    evidence_id: str,
    subject_id: str,
    source_id: str,
    text: str,
    published_at: datetime,
    source_kind: SourceKind,
    locator: str,
    available_at: datetime | None = None,
    retrieved_at: datetime | None = None,
) -> AnalystEvidence:
    synthetic = source_kind == "synthetic_sec_style_test"
    selected_available_at = available_at or published_at
    selected_retrieved_at = retrieved_at or selected_available_at
    return AnalystEvidence(
        evidence_id=UUID(evidence_id),
        subject_id=UUID(subject_id),
        source_id=UUID(source_id),
        source_class=SourceClass.DISCOVERY_ONLY if synthetic else SourceClass.SEC,
        publisher=(
            "Synthetic SEC-style fixture; not a real issuer"
            if synthetic
            else "U.S. Securities and Exchange Commission"
        ),
        locator=locator,
        text=text,
        content_sha256=sha256(text.encode("utf-8")).hexdigest(),
        published_at=published_at,
        available_at=selected_available_at,
        retrieved_at=selected_retrieved_at,
    )


_MINE_EXCERPT = (
    "24, 2026 – Mayfair Gold Corp. ( “Mayfair”, “Mayfair Gold” , or the “Company” ) "
    "(TSXV: MFG, NYSE American: MINE) is pleased to announce the appointments of "
    "Desmond “Des” Tranquilla as Chief Projects Officer and Ruben Wallin as Senior "
    "Vice President, Sustainability. The appointments deepen the Company’s management "
    "as the project advances on two critical fronts : The Ontario government’s One "
    "Project, One Process (“1P1P”) approvals process and a construction decision in "
    "2028. Drew Anwyll, P.Eng., CEO of Mayfair Gold, stated: “I am pleased to welcome "
    "Des and Ruben to Mayfair Gold as we advance Fenn-Gib toward a construction decision "
    ". Their appointments strengthen two critical areas of project execution on an "
    "accelerated timeline. Des brings the integrity, collaborative approach, and proven "
    "leadership across project development experience"
)

_CONTRACT_EXCERPT = (
    "SYNTHETIC TEST EXCERPT — NOT A REAL FILING. Aster Vale Systems Inc. (ticker AVSI) "
    "entered a binding supply agreement with Municipal Grid Authority on July 15, 2026. "
    "The stated contract value is CAD 14.2 million over 30 months. The excerpt does not "
    "disclose gross margin, cancellation rights, or a revenue-recognition schedule."
)

_RISK_EXCERPT = (
    "SYNTHETIC TEST EXCERPT — NOT A REAL FILING. Cedar Harbor Devices Inc. reported "
    "cash of USD 2.4 million at quarter end and USD 7.8 million of notes due March 31, "
    "2027. Management stated that these conditions raise substantial doubt about the "
    "company's ability to continue as a going concern. No refinancing waiver was disclosed."
)

_IDENTITY_EXCERPT = (
    "SYNTHETIC TEST EXCERPT — NOT A REAL FILING. Aurelia Systems Inc., whose Nasdaq "
    "ticker is AURX, appointed Dana Iqbal as Chief Financial Officer. Northstar Holdings "
    "LLC is named only as the former owner of an unrelated leased facility."
)

_MISSING_EXCERPT = (
    "SYNTHETIC TEST EXCERPT — NOT A REAL FILING. Meridian Fieldworks Inc. stated only "
    "that management is exploring strategic alternatives. The excerpt identifies no "
    "transaction, counterparty, agreement, contract value, timing, or expected proceeds."
)

_CORRECTION_A = (
    "SYNTHETIC TEST EXCERPT — NOT A REAL FILING. The original quarterly report stated "
    "that revenue was USD 18.0 million."
)
_CORRECTION_B = (
    "SYNTHETIC TEST EXCERPT — NOT A REAL FILING. This later correction revises quarterly "
    "revenue to USD 21.0 million and expressly supersedes the original figure."
)

SEC_MODEL_CASES = (
    SecModelCase(
        name="real_mine_6k_catalyst",
        source_kind="real_public_sec_excerpt",
        capability="catalyst",
        role=AnalystRole.CATALYST_ANALYST,
        knowledge_cutoff_at=datetime(2026, 8, 25, 4, 14, 42, tzinfo=UTC),
        evidence=(
            _evidence(
                evidence_id="61111111-1111-4111-8111-111111111111",
                subject_id="68232555-5555-4555-8555-555555555555",
                source_id="62116340-2620-4011-8011-111111111111",
                text=_MINE_EXCERPT,
                published_at=datetime(2026, 8, 24, tzinfo=UTC),
                available_at=datetime(2026, 8, 25, 4, 14, 42, tzinfo=UTC),
                retrieved_at=datetime(2026, 8, 25, 4, 14, 42, tzinfo=UTC),
                source_kind="real_public_sec_excerpt",
                locator=(
                    "https://www.sec.gov/Archives/edgar/data/1823255/0002116340-26-000011.txt"
                ),
            ),
        ),
        expected_assessment=Assessment.EVIDENCE_SUFFICIENT,
        required_terms=("Mayfair Gold", "Fenn-Gib"),
        identity_terms=("MINE", "Mayfair Gold"),
        numeric_terms=("2028",),
    ),
    SecModelCase(
        name="synthetic_8k_contract_catalyst",
        source_kind="synthetic_sec_style_test",
        capability="catalyst",
        role=AnalystRole.CATALYST_ANALYST,
        knowledge_cutoff_at=datetime(2026, 7, 16, tzinfo=UTC),
        evidence=(
            _evidence(
                evidence_id="71111111-1111-4111-8111-111111111111",
                subject_id="79999999-9999-4999-8999-999999999999",
                source_id="7aaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                text=_CONTRACT_EXCERPT,
                published_at=datetime(2026, 7, 15, 14, tzinfo=UTC),
                source_kind="synthetic_sec_style_test",
                locator="fixture:synthetic-8k-contract",
            ),
        ),
        expected_assessment=Assessment.EVIDENCE_SUFFICIENT,
        required_terms=("binding supply agreement", "Municipal Grid Authority"),
        identity_terms=("Aster Vale Systems", "AVSI"),
        numeric_terms=("14.2", "30"),
    ),
    SecModelCase(
        name="synthetic_10q_going_concern_risk",
        source_kind="synthetic_sec_style_test",
        capability="risk",
        role=AnalystRole.BULL_BEAR_RISK_ANALYST,
        knowledge_cutoff_at=datetime(2026, 7, 20, tzinfo=UTC),
        evidence=(
            _evidence(
                evidence_id="72222222-2222-4222-8222-222222222222",
                subject_id="78888888-8888-4888-8888-888888888888",
                source_id="7bbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                text=_RISK_EXCERPT,
                published_at=datetime(2026, 7, 19, 14, tzinfo=UTC),
                source_kind="synthetic_sec_style_test",
                locator="fixture:synthetic-10q-going-concern",
            ),
        ),
        expected_assessment=Assessment.EVIDENCE_SUFFICIENT,
        required_terms=("going concern", "refinancing"),
        identity_terms=("Cedar Harbor Devices",),
        numeric_terms=("2.4", "7.8", "2027"),
    ),
    SecModelCase(
        name="synthetic_identity_collision",
        source_kind="synthetic_sec_style_test",
        capability="identity",
        role=AnalystRole.DOCUMENT_INTERPRETER,
        knowledge_cutoff_at=datetime(2026, 7, 22, tzinfo=UTC),
        evidence=(
            _evidence(
                evidence_id="73333333-3333-4333-8333-333333333333",
                subject_id="77777777-7777-4777-8777-777777777777",
                source_id="7ccccccc-cccc-4ccc-8ccc-cccccccccccc",
                text=_IDENTITY_EXCERPT,
                published_at=datetime(2026, 7, 21, 14, tzinfo=UTC),
                source_kind="synthetic_sec_style_test",
                locator="fixture:synthetic-identity-collision",
            ),
        ),
        expected_assessment=Assessment.EVIDENCE_SUFFICIENT,
        required_terms=("Chief Financial Officer",),
        identity_terms=("Aurelia Systems", "AURX"),
    ),
    SecModelCase(
        name="synthetic_missing_transaction_refusal",
        source_kind="synthetic_sec_style_test",
        capability="uncertainty",
        role=AnalystRole.CATALYST_ANALYST,
        knowledge_cutoff_at=datetime(2026, 7, 24, tzinfo=UTC),
        evidence=(
            _evidence(
                evidence_id="74444444-4444-4444-8444-444444444444",
                subject_id="76666666-6666-4666-8666-666666666666",
                source_id="7ddddddd-dddd-4ddd-8ddd-dddddddddddd",
                text=_MISSING_EXCERPT,
                published_at=datetime(2026, 7, 23, 14, tzinfo=UTC),
                source_kind="synthetic_sec_style_test",
                locator="fixture:synthetic-missing-transaction",
            ),
        ),
        expected_assessment=Assessment.INSUFFICIENT_EVIDENCE,
    ),
    SecModelCase(
        name="synthetic_8k_numeric_correction",
        source_kind="synthetic_sec_style_test",
        capability="numeric_correction",
        role=AnalystRole.CONTRADICTION_ANALYST,
        knowledge_cutoff_at=datetime(2026, 7, 27, tzinfo=UTC),
        evidence=(
            _evidence(
                evidence_id="75555555-5555-4555-8555-555555555555",
                subject_id="75555555-5555-4555-8555-555555555550",
                source_id="7eeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
                text=_CORRECTION_A,
                published_at=datetime(2026, 7, 25, 14, tzinfo=UTC),
                source_kind="synthetic_sec_style_test",
                locator="fixture:synthetic-original-revenue",
            ),
            _evidence(
                evidence_id="76666666-6666-4666-8666-666666666666",
                subject_id="75555555-5555-4555-8555-555555555550",
                source_id="7fffffff-ffff-4fff-8fff-ffffffffffff",
                text=_CORRECTION_B,
                published_at=datetime(2026, 7, 26, 14, tzinfo=UTC),
                source_kind="synthetic_sec_style_test",
                locator="fixture:synthetic-corrected-revenue",
            ),
        ),
        expected_assessment=Assessment.CONFLICTING_EVIDENCE,
        required_terms=("supersedes",),
        numeric_terms=("18.0", "21.0"),
    ),
)
