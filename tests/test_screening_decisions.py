"""Closed autonomous screening provenance and publication-gate tests."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from kalki_market_intelligence.analysis.ollama import ModelProviderError
from kalki_market_intelligence.analysis.pipeline import AnalysisRejected
from kalki_market_intelligence.radar.contracts import (
    BriefEvidence,
    FilingCandidate,
    RadarClassification,
    ResearchBrief,
)
from kalki_market_intelligence.radar.extraction import ExtractedFiling
from kalki_market_intelligence.radar.research import (
    finalize_deterministically_validated_brief,
)
from kalki_market_intelligence.radar.screening import (
    AutonomousScreeningDecision,
    ScreeningDisposition,
    ScreeningReason,
)
from kalki_market_intelligence.radar.sec_links import ValidatedSecFilingLinks
from kalki_market_intelligence.radar.sec_source import SecRadarDocument
from kalki_market_intelligence.radar.store import ClaimedCandidate
from kalki_market_intelligence.radar.worker import (
    FilingRadarWorker,
    VerifierUnavailableError,
    _incomplete_reason,
    _maximum_candidate_attempts,
)
from kalki_market_intelligence.web.app import create_public_web_app
from kalki_market_intelligence.web.contracts import (
    PublicScreenedFiling,
    PublicScreeningActivity,
    PublicScreeningReason,
    PublicScreeningWindow,
)
from kalki_market_intelligence.web.repository import MemoryResearchRepository

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 28, 12, tzinfo=UTC)
ACCESSION = "0000320193-26-000001"
SOURCE_URL = (
    "https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/0000320193-26-000001.txt"
)
ATTEMPT_ID = UUID("61000000-0000-4000-8000-000000000001")
RUN_ID = UUID("62000000-0000-4000-8000-000000000001")
WORKER_COMPLETE_BODY = b"""<DOCUMENT>
<TYPE>8-K
<FILENAME>event.htm
The company announced a strategic agreement and contract award.
</DOCUMENT>"""
WORKER_COMPLETE_SHA256 = sha256(WORKER_COMPLETE_BODY).hexdigest()


def decision(
    disposition: ScreeningDisposition = ScreeningDisposition.QUALIFIED,
    reason: ScreeningReason = ScreeningReason.VALIDATED_PUBLICATION,
) -> AutonomousScreeningDecision:
    return AutonomousScreeningDecision(
        decision_id=UUID("63000000-0000-4000-8000-000000000001"),
        accession_number=ACCESSION,
        decided_at=NOW,
        disposition=disposition,
        reason=reason,
        work_attempt=1,
        run_id=RUN_ID,
        analyst_attempt_ids=(ATTEMPT_ID,),
        source_document_sha256="a" * 64,
    )


def brief() -> ResearchBrief:
    return ResearchBrief(
        brief_id=UUID("64000000-0000-4000-8000-000000000001"),
        accession_number=ACCESSION,
        cik="320193",
        company_name="Synthetic issuer",
        ticker="TEST",
        exchange="Nasdaq",
        filing_form="8-K",
        filed_at=NOW - timedelta(hours=2),
        retrieved_at=NOW - timedelta(hours=1),
        published_at=NOW,
        source_url=SOURCE_URL,
        source_document_sha256="a" * 64,
        classification=RadarClassification.WATCH,
        attention_points=40,
        risk_points=20,
        evidence_strength_points=65,
        headline="TEST filing radar",
        summary="A bounded supported filing statement.",
        why_it_matters="The filing warrants evidence-backed follow-up.",
        evidence=(
            BriefEvidence(
                evidence_id=UUID("65000000-0000-4000-8000-000000000001"),
                quote="A bounded supported filing statement.",
                excerpt_sha256="b" * 64,
                source_url=SOURCE_URL,
                source_document_sha256="a" * 64,
                available_at=NOW - timedelta(hours=1),
                retrieved_at=NOW - timedelta(hours=1),
            ),
        ),
        model_name="qwen3:4b",
        model_digest="c" * 64,
        prompt_version="analyst-v2",
        limitations=("Synthetic contract fixture; not market evidence.",),
    )


def test_screening_dispositions_are_closed_and_require_matching_lineage() -> None:
    assert decision().disposition is ScreeningDisposition.QUALIFIED

    with pytest.raises(ValidationError, match="terminal disposition"):
        decision(ScreeningDisposition.SCREENED_OUT, ScreeningReason.ANALYST_TIMEOUT)

    with pytest.raises(ValidationError, match="terminal disposition"):
        decision(ScreeningDisposition.ANALYSIS_INCOMPLETE, ScreeningReason.UNKNOWN)

    payload = decision().model_dump(mode="json")
    payload["analyst_attempt_ids"] = []
    with pytest.raises(ValidationError, match="analyst and source lineage"):
        AutonomousScreeningDecision.model_validate(payload)


def test_no_findings_requires_completed_attempt_identity() -> None:
    payload = decision(
        ScreeningDisposition.SCREENED_OUT,
        ScreeningReason.NO_VALIDATED_FINDINGS,
    ).model_dump(mode="json")
    payload["analyst_attempt_ids"] = []

    with pytest.raises(ValidationError, match="no-findings"):
        AutonomousScreeningDecision.model_validate(payload)


def test_disabled_optional_verifier_has_truthful_version_3_public_lineage() -> None:
    finalized = finalize_deterministically_validated_brief(brief(), validated_at=NOW)

    assert finalized.schema_version == "3.0.0"
    assert finalized.verification is None
    assert finalized.publication_gate is not None
    assert finalized.publication_gate.mode.value == "deterministic_only"
    assert finalized.publication_gate.independent_verifier_status == "disabled"


def test_terminal_failure_reason_uses_runtime_evidence_not_company_inference() -> None:
    timeout = ModelProviderError("local Ollama request failed: TimeoutError")
    timeout.__cause__ = TimeoutError()

    assert _incomplete_reason(timeout, "analyst") is ScreeningReason.ANALYST_TIMEOUT
    assert (
        _incomplete_reason(AnalysisRejected(("invalid_evidence_id",), 2), "analyst")
        is ScreeningReason.EVIDENCE_VALIDATION_REJECTED
    )
    assert (
        _incomplete_reason(ValueError("bad facts"), "companyfacts_normalization")
        is ScreeningReason.COMPANYFACTS_NORMALIZATION_FAILURE
    )


def test_local_analyst_retries_stop_at_three_but_verifier_recovery_stays_bounded() -> None:
    timeout = ModelProviderError("local Ollama request failed: TimeoutError")
    timeout.__cause__ = TimeoutError()

    assert _maximum_candidate_attempts(timeout) == 3
    assert _maximum_candidate_attempts(AnalysisRejected(("invalid_type",), 2)) == 3
    assert _maximum_candidate_attempts(VerifierUnavailableError("unavailable")) == 6


def test_forward_migration_is_append_only_and_does_not_rewrite_legacy_rows() -> None:
    migration = (ROOT / "migrations/0013_autonomous_screening_decisions.sql").read_text()

    assert "CREATE TABLE research_autonomous_screening_decisions" in migration
    assert "CREATE TABLE research_autonomous_screening_state" in migration
    assert "research_autonomous_screening_decisions_no_update_delete" in migration
    assert "research_autonomous_screening_decisions_no_truncate" in migration
    assert "autonomous_decision_id" in migration
    assert "version 3 deterministic-only publication lineage" in migration
    assert "UPDATE research_autonomous_screening_decisions" not in migration
    assert "INSERT INTO research_autonomous_screening_decisions SELECT" not in migration


def test_public_screened_surface_is_closed_escaped_and_excludes_incomplete_detail() -> None:
    screened = PublicScreenedFiling(
        ticker="TEST",
        company_name="Synthetic <script> issuer",
        filing_form="8-K",
        filed_at=NOW - timedelta(hours=2),
        screened_at=NOW,
        reason=PublicScreeningReason.NO_VALIDATED_FINDINGS,
        source_url=SOURCE_URL,
    )
    activity = PublicScreeningActivity(
        observed_at=NOW,
        telemetry_started_at=NOW - timedelta(hours=1),
        windows=(
            PublicScreeningWindow(
                hours=24,
                telemetry_complete=False,
                processed=3,
                completed_deep_analysis=2,
                screened_out=1,
                qualified=0,
                analysis_incomplete=2,
            ),
            PublicScreeningWindow(
                hours=168,
                telemetry_complete=False,
                processed=3,
                completed_deep_analysis=2,
                screened_out=1,
                qualified=0,
                analysis_incomplete=2,
            ),
        ),
    )
    repository = MemoryResearchRepository(screened_filings=(screened,), screening_activity=activity)
    client = TestClient(create_public_web_app(repository))

    api = client.get("/api/v1/screened")
    page = client.get("/screened")
    summary = client.get("/api/v1/screened/activity")

    assert api.status_code == page.status_code == summary.status_code == 200
    assert set(api.json()[0]) == {
        "ticker",
        "company_name",
        "filing_form",
        "filed_at",
        "screened_at",
        "terminal_result",
        "reason",
        "source_url",
    }
    assert api.json()[0]["terminal_result"] == "SCREENED_OUT"
    assert summary.json()["windows"][0]["analysis_incomplete"] == 2
    assert "Analysis-incomplete work is counted separately" in page.text
    assert "Synthetic &lt;script&gt; issuer" in page.text
    assert "Synthetic <script> issuer" not in page.text
    serialized = api.text.casefold()
    for forbidden in (
        "lead_id",
        "discord",
        "prompt",
        "raw_response",
        "timeout",
        "stack trace",
        "/home/",
    ):
        assert forbidden not in serialized


def test_public_screened_repository_query_selects_only_autonomous_closed_fields() -> None:
    source = (ROOT / "src/kalki_market_intelligence/web/repository.py").read_text()
    postgres = source.split("class PostgresResearchRepository", 1)[1]
    method = postgres.split("def list_screened_filings", 1)[1].split(
        "def get_screening_activity", 1
    )[0]

    assert "WHERE d.disposition = 'SCREENED_OUT'" in method
    assert "research_candidates" in method
    assert "research_human" not in method
    assert "record" not in method
    assert "last_error_code" not in method


class _WorkerStore:
    def __init__(self, candidate: FilingCandidate) -> None:
        self.claimed: ClaimedCandidate | None = ClaimedCandidate(
            candidate=candidate,
            attempts=1,
            reconsideration=None,
            first_audit=None,
        )
        self.published: (
            tuple[ResearchBrief, AutonomousScreeningDecision, ValidatedSecFilingLinks] | None
        ) = None
        self.runs: list[object] = []
        self.completed: list[dict[str, object]] = []

    def append_pipeline_event(self, event: object) -> None:
        pass

    def discover(self, candidates: object) -> int:
        return 0

    def requeue_stale_processing(self, **kwargs: object) -> int:
        return 0

    def counts(self) -> tuple[int, int, int]:
        return 1, 0, int(self.published is not None)

    def claim(self, **kwargs: object) -> ClaimedCandidate | None:
        selected, self.claimed = self.claimed, None
        return selected

    def record_tier_decision(self, *args: object, **kwargs: object) -> None:
        pass

    def increment_counter(self, *args: object, **kwargs: object) -> None:
        pass

    def candidate_analyst_attempt_ids(self, accession_number: str) -> tuple[UUID, ...]:
        assert accession_number == ACCESSION
        return (ATTEMPT_ID,)

    def record_deterministic_publication(
        self,
        record: ResearchBrief,
        screening: AutonomousScreeningDecision,
        sec_links: ValidatedSecFilingLinks,
    ) -> None:
        self.published = record, screening, sec_links

    def complete_candidate(self, *args: object, **kwargs: object) -> None:
        self.completed.append(dict(kwargs))

    def claim_human_lead(self, **kwargs: object) -> None:
        return None

    def append_run(self, run: object) -> None:
        self.runs.append(run)

    def generate_engineering_measurements(self, **kwargs: object) -> int:
        return 0

    def verifier_counts(self) -> tuple[int, int, int]:
        return 0, 0, 0

    def save_snapshot(self, snapshot: object) -> None:
        pass


class _WorkerSecClient:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def ticker_mapping(self) -> object:
        return object()

    def latest_master_index(self, day: object) -> object:
        return object()

    def filing(self, source_url: str) -> SecRadarDocument:
        return SecRadarDocument(
            url=source_url,
            body=WORKER_COMPLETE_BODY,
            content_sha256=WORKER_COMPLETE_SHA256,
            retrieved_at=NOW - timedelta(minutes=10),
            media_type="text/plain",
        )

    def fetch(self, url: str, *, media_types: frozenset[str]) -> SecRadarDocument:
        del media_types
        body = b'<a href="event.htm">event.htm</a>' if url.endswith("-index.html") else b"html"
        return SecRadarDocument(
            url=url,
            body=body,
            content_sha256=sha256(body).hexdigest(),
            retrieved_at=NOW - timedelta(minutes=8),
            media_type="text/html",
        )

    def companyfacts(self, cik: str) -> SecRadarDocument:
        return SecRadarDocument(
            url="https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
            body=b'{"cik":320193,"entityName":"Synthetic issuer","facts":{}}',
            content_sha256="d" * 64,
            retrieved_at=NOW - timedelta(minutes=9),
            media_type="application/json",
        )


def test_disabled_optional_verifier_publishes_qualified_deterministic_brief(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = FilingCandidate(
        accession_number=ACCESSION,
        cik="320193",
        company_name="Synthetic issuer",
        ticker="TEST",
        exchange="Nasdaq",
        filing_form="8-K",
        filed_at=NOW - timedelta(hours=2),
        source_url=SOURCE_URL,
        discovered_at=NOW - timedelta(hours=1),
    )
    store = _WorkerStore(candidate)
    worker = object.__new__(FilingRadarWorker)
    object.__setattr__(
        worker,
        "_settings",
        SimpleNamespace(
            sec_user_agent="Kalki test test@example.com",
            sec_requests_per_second=2,
            sec_timeout_seconds=30,
            sec_maximum_response_bytes=1_000_000,
            worker_batch_size=1,
            worker_poll_seconds=900,
            worker_verifier_enabled=False,
            worker_verifier_model="gemma-disabled",
            worker_model="qwen3:4b",
            discord_enabled=False,
        ),
    )
    object.__setattr__(worker, "_store", store)
    object.__setattr__(worker, "_now", lambda: NOW)
    object.__setattr__(worker, "_pipeline", object())
    monkeypatch.setattr("kalki_market_intelligence.radar.worker.SecRadarClient", _WorkerSecClient)
    monkeypatch.setattr("kalki_market_intelligence.radar.worker.parse_ticker_mapping", lambda _: {})
    monkeypatch.setattr(
        "kalki_market_intelligence.radar.worker.parse_master_index", lambda *_: (candidate,)
    )
    monkeypatch.setattr(
        "kalki_market_intelligence.radar.worker.extract_research_excerpt",
        lambda _: ExtractedFiling(
            text="strategic agreement and contract award",
            content_sha256="e" * 64,
            opportunity_terms=("contract award",),
            risk_terms=(),
        ),
    )
    monkeypatch.setattr(
        "kalki_market_intelligence.radar.worker.analyze_filing",
        lambda *args, **kwargs: (object(), ()),
    )
    monkeypatch.setattr(
        "kalki_market_intelligence.radar.worker.build_research_brief",
        lambda **kwargs: brief().model_copy(
            update={
                "source_document_sha256": WORKER_COMPLETE_SHA256,
                "evidence": tuple(
                    item.model_copy(update={"source_document_sha256": WORKER_COMPLETE_SHA256})
                    for item in brief().evidence
                ),
            }
        ),
    )

    sleep_seconds = worker.run_once()

    assert sleep_seconds == 900
    assert store.published is not None, store.runs
    published, screening, sec_links = store.published
    assert published.schema_version == "3.0.0"
    assert published.verification is None
    assert screening.disposition is ScreeningDisposition.QUALIFIED
    assert screening.reason is ScreeningReason.VALIDATED_PUBLICATION
    assert sec_links.primary_document_url.endswith("/event.htm")
