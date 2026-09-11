"""Future private human results retain closed, explicit provenance."""

import os
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import psycopg
import pytest
from psycopg.errors import InsufficientPrivilege
from pydantic import ValidationError

from kalki_market_intelligence.analysis.attempts import (
    AnalystAttemptOrigin,
    AnalystAttemptOutcome,
    AnalystAttemptReceipt,
    AnalystAttemptStart,
    AnalystFailureLayer,
    AnalystRetryScope,
    AnalystTerminalDisposition,
    AnalystWorkContext,
    AttemptCheckStatus,
)
from kalki_market_intelligence.analysis.contracts import AnalystRole
from kalki_market_intelligence.config import Settings
from kalki_market_intelligence.database import DatabaseOptions, DatabaseRuntime
from kalki_market_intelligence.forensics import ForensicInput, assess_forensics, choose_tier
from kalki_market_intelligence.radar.contracts import FilingCandidate
from kalki_market_intelligence.radar.sec_source import SecRadarClient, SecRadarDocument
from kalki_market_intelligence.radar.store import PostgresRadarStore
from kalki_market_intelligence.radar.worker import FilingRadarWorker
from kalki_market_intelligence.research.intake import (
    HumanLeadStatus,
    HumanResearchLead,
    parse_discord_submission,
)
from kalki_market_intelligence.research.results import (
    HumanAssessmentStatus,
    HumanDeterministicVerificationReceipt,
    HumanFilingDiffReceipt,
    HumanResearchDisposition,
    HumanResearchResult,
    HumanSecSourceReceipt,
    HumanSourceStatus,
    HumanXbrlReceipt,
)

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 28, 1, tzinfo=UTC)
LEAD_ID = UUID("51000000-0000-4000-8000-000000000001")
EVIDENCE_ID = UUID("52000000-0000-4000-8000-000000000001")
OWNER_PASSWORD_FILE = os.environ.get("KALKI_HUMAN_RESULT_GATE_OWNER_PASSWORD_FILE")
APP_PASSWORD_FILE = os.environ.get("KALKI_HUMAN_RESULT_GATE_APP_PASSWORD_FILE")
GATE_PORT = int(os.environ.get("KALKI_HUMAN_RESULT_GATE_PORT", "55441"))


def lead() -> HumanResearchLead:
    return HumanResearchLead.from_submission(
        discord_message_id="123456789012345678",
        submitter_user_id="223456789012345678",
        channel_id="323456789012345678",
        submitted_at=NOW,
        ticker="TEST",
        hypothesis="Review the latest authoritative filing.",
    ).model_copy(update={"lead_id": LEAD_ID})


def attempt_receipt() -> AnalystAttemptReceipt:
    start = AnalystAttemptStart(
        attempt_id=UUID("53000000-0000-4000-8000-000000000001"),
        invocation_id=UUID("54000000-0000-4000-8000-000000000001"),
        context=AnalystWorkContext(
            origin=AnalystAttemptOrigin.HUMAN,
            lead_id=LEAD_ID,
            ticker="TEST",
            cik="320193",
            accession_number="0000320193-26-000001",
            filing_form="8-K",
            work_attempt=1,
        ),
        provider_name="ollama-loopback",
        model_name="qwen3:4b",
        model_digest="a" * 64,
        role=AnalystRole.CATALYST_ANALYST,
        attempt_number=1,
        started_at=NOW,
        input_evidence_count=1,
        input_evidence_characters=500,
        system_prompt_characters=1_000,
        user_prompt_characters=2_000,
        context_tokens=4_096,
        maximum_output_tokens=768,
    )
    return AnalystAttemptReceipt(
        start=start,
        completed_at=NOW,
        latency_ms=1_000,
        response_sha256="b" * 64,
        response_characters=100,
        response_bytes=100,
        parse_status=AttemptCheckStatus.PASSED,
        schema_status=AttemptCheckStatus.PASSED,
        evidence_status=AttemptCheckStatus.PASSED,
        failure_layer=AnalystFailureLayer.NONE,
        retry_eligible=False,
        retry_scope=AnalystRetryScope.NONE,
        outcome=AnalystAttemptOutcome.ACCEPTED,
        terminal_disposition=AnalystTerminalDisposition.ACCEPTED,
    )


def resolved_result() -> HumanResearchResult:
    forensics = assess_forensics(ForensicInput(text="contract award", evidence_ids=(EVIDENCE_ID,)))
    decision = choose_tier(
        research_relevant=True,
        material_terms=True,
        context_chars=100,
        evidence_ids=(EVIDENCE_ID,),
        forensic_signals=forensics,
    )
    return HumanResearchResult.from_lead(
        lead(),
        source=HumanSecSourceReceipt(
            status=HumanSourceStatus.RESOLVED,
            ticker="TEST",
            canonical_cik="0000320193",
            company_name="Synthetic issuer",
            filing_form="8-K",
            accession_number="0000320193-26-000001",
            authoritative_url=(
                "https://www.sec.gov/Archives/edgar/data/320193/"
                "000032019326000001/0000320193-26-000001.txt"
            ),
            source_document_sha256="c" * 64,
            excerpt_sha256="d" * 64,
            filed_at=NOW,
            retrieved_at=NOW,
            reason="Resolved from SEC.",
        ),
        evidence_ids=(EVIDENCE_ID,),
        xbrl=HumanXbrlReceipt(
            status=HumanAssessmentStatus.ASSESSED,
            source_url="https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
            source_content_sha256="e" * 64,
            retrieved_at=NOW,
            normalized_fact_count=12,
            same_filing_fact_count=3,
            reason="CompanyFacts normalized.",
        ),
        filing_diff=HumanFilingDiffReceipt(
            status=HumanAssessmentStatus.NOT_ASSESSED,
            current_accession_number="0000320193-26-000001",
            current_source_content_sha256="c" * 64,
            reason="No prior filing was retrieved.",
        ),
        forensic_receipts=forensics,
        tier0_status=HumanAssessmentStatus.ASSESSED,
        tier0_decision=decision,
        analyst_status=HumanAssessmentStatus.ASSESSED,
        analyst_attempt_receipts=(attempt_receipt(),),
        deterministic_verification=HumanDeterministicVerificationReceipt(
            status=HumanAssessmentStatus.NOT_ASSESSED,
            reason="No numeric analyst claim was present.",
        ),
        disposition=HumanResearchDisposition.SUPPORTED,
        conclusion="The authoritative filing supports bounded follow-up research.",
        delivery_channel_id="423456789012345678",
        created_at=NOW,
    )


def test_v2_result_retains_complete_bounded_lineage_without_transcripts() -> None:
    result = resolved_result()

    assert result.version == "human-research-v2"
    assert result.source.canonical_cik == "0000320193"
    assert result.source.source_document_sha256 == "c" * 64
    assert result.xbrl.same_filing_fact_count == 3
    assert len(result.forensic_receipts) == 4
    assert result.tier0_decision is not None
    assert result.analyst_attempt_receipts[0].start.attempt_id == UUID(
        "53000000-0000-4000-8000-000000000001"
    )
    serialized = result.model_dump_json()
    assert "raw_response" not in serialized
    assert '"system_prompt":' not in serialized
    assert '"user_prompt":' not in serialized
    assert "chain_of_thought" not in serialized


def test_missing_source_and_assessments_are_explicit_not_fabricated() -> None:
    result = HumanResearchResult.from_lead(
        lead(),
        source=HumanSecSourceReceipt(
            status=HumanSourceStatus.UNRESOLVED,
            ticker="TEST",
            reason="No unambiguous SEC filing was resolved.",
        ),
        xbrl=HumanXbrlReceipt(
            status=HumanAssessmentStatus.NOT_ASSESSED,
            reason="No filing identity was resolved.",
        ),
        filing_diff=HumanFilingDiffReceipt(
            status=HumanAssessmentStatus.NOT_ASSESSED,
            reason="No current filing was resolved.",
        ),
        forensic_receipts=(),
        tier0_status=HumanAssessmentStatus.NOT_ASSESSED,
        tier0_decision=None,
        analyst_status=HumanAssessmentStatus.NOT_ASSESSED,
        analyst_attempt_receipts=(),
        deterministic_verification=HumanDeterministicVerificationReceipt(
            status=HumanAssessmentStatus.NOT_ASSESSED,
            reason="No analyst claims existed.",
        ),
        disposition=HumanResearchDisposition.INSUFFICIENT_EVIDENCE,
        conclusion="No authoritative filing evidence was resolved.",
        delivery_channel_id="423456789012345678",
        created_at=NOW,
    )

    assert result.source.accession_number is None
    assert result.xbrl.normalized_fact_count is None
    assert result.analyst_attempt_receipts == ()


def test_resolved_source_and_analyst_status_fail_closed_when_lineage_is_missing() -> None:
    with pytest.raises(ValidationError, match="complete immutable lineage"):
        HumanSecSourceReceipt(
            status=HumanSourceStatus.RESOLVED,
            canonical_cik="0000320193",
            reason="Incomplete fixture.",
        )

    payload = resolved_result().model_dump(mode="json")
    payload["analyst_attempt_receipts"] = []
    with pytest.raises(ValidationError, match="analyst assessment status"):
        HumanResearchResult.model_validate(payload)


def test_forward_migration_preserves_legacy_rows_and_requires_v2_for_new_rows() -> None:
    migration = (ROOT / "migrations/0012_human_result_provenance.sql").read_text()
    compose = (ROOT / "compose.production.yaml").read_text()
    restore = (ROOT / "scripts/restore-postgres-gate.sh").read_text()

    assert "UPDATE research_human_results" not in migration
    assert "ADD COLUMN schema_version text" in migration
    assert "research_human_results_require_v2" in migration
    assert "research_analyst_attempts" in migration
    assert "0012_human_result_provenance.sql" in compose
    assert "0012_human_result_provenance" in restore


class FakeHumanStore:
    def __init__(self, queued: HumanResearchLead) -> None:
        self.queued: HumanResearchLead | None = queued
        self.result: HumanResearchResult | None = None
        self.transition: tuple[UUID, HumanLeadStatus] | None = None

    def claim_human_lead(self, *, now: datetime) -> HumanResearchLead | None:
        queued, self.queued = self.queued, None
        return queued

    def human_analyst_attempt_receipts(self, lead_id: UUID) -> tuple[AnalystAttemptReceipt, ...]:
        assert lead_id == LEAD_ID
        return (attempt_receipt(),)

    def record_human_result(self, result: HumanResearchResult, *, channel_id: str) -> bool:
        assert channel_id == result.delivery_channel_id
        self.result = result
        return True

    def transition_human_lead(
        self,
        lead_id: UUID,
        status: HumanLeadStatus,
        *,
        now: datetime,
        detail: str,
    ) -> None:
        self.transition = (lead_id, status)


class FakeHumanSecClient(SecRadarClient):
    def __init__(self) -> None:
        pass

    def filing(self, source_url: str) -> SecRadarDocument:
        body = b"The company announced a strategic agreement and contract award."
        return SecRadarDocument(
            url=source_url,
            body=body,
            content_sha256=sha256(body).hexdigest(),
            retrieved_at=NOW,
            media_type="text/plain",
        )

    def companyfacts(self, cik: str) -> SecRadarDocument:
        body = b'{"cik":320193,"entityName":"Synthetic issuer","facts":{}}'
        return SecRadarDocument(
            url="https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
            body=body,
            content_sha256=sha256(body).hexdigest(),
            retrieved_at=NOW,
            media_type="application/json",
        )


def test_worker_does_not_claim_private_lead_without_results_channel() -> None:
    queued = lead()
    store = FakeHumanStore(queued)
    worker = object.__new__(FilingRadarWorker)
    worker._settings = Settings(_env_file=None)
    worker._store = cast(Any, store)
    worker._now = lambda: NOW

    worker._process_one_human_lead(
        client=FakeHumanSecClient(),
        candidates=(),
        ticker_mapping={},
    )

    assert store.queued == queued
    assert store.result is None


def test_discord_lead_flows_through_sec_analysis_to_versioned_private_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed = parse_discord_submission(
        {
            "id": "123456789012345678",
            "channel_id": "323456789012345678",
            "timestamp": NOW.isoformat(),
            "content": "$TEST review the latest filing",
            "author": {"id": "223456789012345678"},
        },
        channel_id="323456789012345678",
        allowlist=frozenset({"223456789012345678"}),
    ).model_copy(update={"lead_id": LEAD_ID, "status": HumanLeadStatus.ANALYZING, "attempts": 1})
    store = FakeHumanStore(parsed)
    worker = object.__new__(FilingRadarWorker)
    worker._settings = Settings(
        discord_intake_results_channel_id="222222222222222222",
        _env_file=None,
    )
    worker._store = cast(Any, store)
    worker._pipeline = cast(Any, object())
    worker._now = lambda: NOW
    candidate = FilingCandidate(
        accession_number="0000320193-26-000001",
        cik="320193",
        company_name="Synthetic issuer",
        ticker="TEST",
        exchange="Nasdaq",
        filing_form="8-K",
        filed_at=NOW,
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/320193/"
            "000032019326000001/0000320193-26-000001.txt"
        ),
        discovered_at=NOW,
    )

    monkeypatch.setattr(
        "kalki_market_intelligence.radar.worker.analyze_filing",
        lambda *args, **kwargs: (
            type("Evidence", (), {"evidence_id": EVIDENCE_ID})(),
            (),
        ),
    )
    monkeypatch.setattr(
        "kalki_market_intelligence.radar.worker.build_research_brief",
        lambda *args, **kwargs: type(
            "Brief",
            (),
            {
                "summary": "Validated bounded analyst conclusion.",
                "numeric_verifications": (),
            },
        )(),
    )

    worker._process_one_human_lead(
        client=FakeHumanSecClient(),
        candidates=(candidate,),
        ticker_mapping={"320193": ("TEST", "Nasdaq")},
    )

    assert store.result is not None
    assert store.result.version == "human-research-v2"
    assert store.result.source.status is HumanSourceStatus.RESOLVED
    assert store.result.source.canonical_cik == "0000320193"
    assert store.result.xbrl.status is HumanAssessmentStatus.ASSESSED
    assert store.result.tier0_decision is not None
    assert len(store.result.analyst_attempt_receipts) == 1
    assert store.transition == (LEAD_ID, HumanLeadStatus.COMPLETED)


@pytest.mark.skipif(
    OWNER_PASSWORD_FILE is None or APP_PASSWORD_FILE is None,
    reason="Phase 36 human-result PostgreSQL gate is not running",
)
def test_postgres_result_is_immutable_attempt_linked_and_privately_deliverable() -> None:
    assert OWNER_PASSWORD_FILE is not None
    assert APP_PASSWORD_FILE is not None
    owner_password = Path(OWNER_PASSWORD_FILE).read_text(encoding="utf-8").strip()
    with psycopg.connect(
        host="127.0.0.1",
        port=GATE_PORT,
        dbname="kalki",
        user="kalki_owner",
        password=owner_password,
    ) as owner:
        owner.execute(
            """
            INSERT INTO research_human_leads (
                lead_id, discord_message_id, submitter_user_id, channel_id, submitted_at,
                ticker, hypothesis, original_submission_sha256, dedupe_key, status,
                attempts, created_at, updated_at
            ) VALUES (%s, '123456789012345678', '223456789012345678',
                      '323456789012345678', %s, 'TEST', %s, %s, %s, 'analyzing', 1, %s, %s)
            """,
            (
                LEAD_ID,
                NOW,
                lead().hypothesis,
                lead().original_submission_sha256,
                lead().dedupe_key,
                NOW,
                NOW,
            ),
        )

    runtime = DatabaseRuntime(
        DatabaseOptions(
            host="127.0.0.1",
            port=GATE_PORT,
            name="kalki",
            user="kalki_app",
            password_file=Path(APP_PASSWORD_FILE),
            minimum_pool_size=1,
            maximum_pool_size=2,
        )
    )
    runtime.open()
    result = resolved_result()
    try:
        store = PostgresRadarStore(runtime.connection)
        receipt = result.analyst_attempt_receipts[0]
        store.start_analyst_attempt(receipt.start)
        store.finish_analyst_attempt(receipt)
        assert store.record_human_result(result, channel_id=result.delivery_channel_id)
        claimed = store.claim_human_result_delivery(now=NOW)
        assert claimed is not None
        assert claimed[0] == result.result_id
        assert claimed[1]["version"] == "human-research-v2"
        store.complete_human_result_delivery(
            result.result_id,
            now=NOW,
            message_id="523456789012345678",
        )
        with pytest.raises(InsufficientPrivilege):
            with runtime.connection() as connection:
                connection.execute(
                    "UPDATE research_human_results SET created_at = now() WHERE result_id = %s",
                    (result.result_id,),
                )
    finally:
        runtime.close()

    with psycopg.connect(
        host="127.0.0.1",
        port=GATE_PORT,
        dbname="kalki",
        user="kalki_owner",
        password=owner_password,
    ) as owner:
        row = owner.execute(
            """
            SELECT r.schema_version, r.source_status, r.accession_number,
                   r.analyst_attempt_ids, r.delivery_channel_id,
                   d.status, d.discord_message_id, r.record
            FROM research_human_results r
            JOIN research_human_result_deliveries d USING (result_id)
            WHERE r.result_id = %s
            """,
            (result.result_id,),
        ).fetchone()
    assert row is not None
    assert row[:7] == (
        "2.0.0",
        "resolved",
        "0000320193-26-000001",
        [receipt.start.attempt_id],
        "423456789012345678",
        "delivered",
        "523456789012345678",
    )
    assert HumanResearchResult.model_validate(row[7]) == result
