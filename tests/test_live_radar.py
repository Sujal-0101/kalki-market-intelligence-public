"""Filing-radar contracts, source parsing, extraction, and public surface tests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from fastapi.testclient import TestClient

from kalki_market_intelligence.notifications.templates import (
    RadarNotification,
    render_radar_notification,
)
from kalki_market_intelligence.providers.sec.client import HttpResult, RateLimiter
from kalki_market_intelligence.quantitative.claim_verification import (
    NumericVerification,
    NumericVerificationStatus,
)
from kalki_market_intelligence.radar.contracts import (
    BriefEvidence,
    PublicVerificationReceipt,
    RadarClassification,
    ResearchBrief,
    WorkerSnapshot,
    WorkerState,
)
from kalki_market_intelligence.radar.extraction import (
    MAXIMUM_EXCERPT_CHARACTERS,
    extract_research_excerpt,
)
from kalki_market_intelligence.radar.sec_links import (
    ValidatedSecFilingLinks,
    public_sec_filing_links,
)
from kalki_market_intelligence.radar.sec_source import (
    SecRadarClient,
    SecRadarDocument,
    latest_submission_candidate,
    parse_master_index,
    parse_ticker_mapping,
)
from kalki_market_intelligence.web.app import create_public_web_app
from kalki_market_intelligence.web.operations import FunnelSnapshot
from kalki_market_intelligence.web.repository import MemoryResearchRepository

NOW = datetime(2026, 8, 24, 16, tzinfo=UTC)
FILING_URL = "https://www.sec.gov/Archives/edgar/data/320193/0000320193-26-000001.txt"


def brief() -> ResearchBrief:
    return ResearchBrief(
        brief_id=UUID("31000000-0000-4000-8000-000000000001"),
        accession_number="0000320193-26-000001",
        cik="320193",
        company_name="Synthetic <script> issuer",
        ticker="TEST",
        exchange="Nasdaq",
        filing_form="8-K",
        filed_at=NOW - timedelta(hours=3),
        retrieved_at=NOW - timedelta(hours=1),
        published_at=NOW,
        source_url=FILING_URL,
        source_document_sha256="a" * 64,
        classification=RadarClassification.OPPORTUNITY,
        attention_points=67,
        risk_points=22,
        evidence_strength_points=80,
        headline="TEST · 8-K filing radar",
        summary="The synthetic company announced a contract award.",
        why_it_matters="One evidence-bound catalyst requires follow-up research.",
        evidence=(
            BriefEvidence(
                evidence_id=UUID("32000000-0000-4000-8000-000000000001"),
                quote="The synthetic company announced a contract award.",
                excerpt_sha256="b" * 64,
                source_url=FILING_URL,
                source_document_sha256="a" * 64,
                available_at=NOW - timedelta(hours=1),
                retrieved_at=NOW - timedelta(hours=1),
            ),
        ),
        model_name="fixture-model",
        model_digest="c" * 64,
        prompt_version="analyst-v1",
        limitations=("Synthetic test record; not market evidence.",),
    )


def linked_brief() -> tuple[ResearchBrief, ValidatedSecFilingLinks]:
    accession = "0000320193-26-000001"
    source_hash = "a" * 64
    base = "https://www.sec.gov/Archives/edgar/data/320193/000032019326000001"
    source_url = f"{base}/{accession}.txt"
    record = brief()
    record = record.model_copy(
        update={
            "source_url": source_url,
            "evidence": tuple(
                item.model_copy(update={"source_url": source_url}) for item in record.evidence
            ),
        }
    )
    receipt = ValidatedSecFilingLinks(
        receipt_id=uuid5(
            NAMESPACE_URL,
            f"kalki-sec-links:{accession}:{source_hash}:1.0.0",
        ),
        canonical_cik="0000320193",
        accession_number=accession,
        complete_submission_url=source_url,
        archive_index_url=f"{base}/{accession}-index.html",
        primary_document_url=f"{base}/event.htm",
        complete_submission_sha256=source_hash,
        archive_index_sha256="d" * 64,
        primary_document_sha256="e" * 64,
        inline_xbrl_validated=False,
        validated_at=NOW - timedelta(minutes=30),
    )
    return record, receipt


def snapshot(
    state: WorkerState = WorkerState.IDLE, *, error_code: str | None = None
) -> WorkerSnapshot:
    return WorkerSnapshot(
        state=state,
        heartbeat_at=NOW,
        last_success_at=NOW,
        next_run_at=NOW + timedelta(minutes=15),
        last_error_code=error_code,
        discovered_count=8,
        pending_count=2,
        published_count=1,
        discord_enabled=True,
        model_name="fixture-model",
    )


def verified_brief() -> ResearchBrief:
    payload = brief().model_dump(mode="json")
    payload.update(
        {
            "schema_version": "2.0.0",
            "prompt_version": "analyst-v2",
            "verification": PublicVerificationReceipt(
                verifier_model_name="gemma4:12b-it-q4_K_M",
                verifier_model_digest="d" * 64,
                reviewed_at=NOW - timedelta(minutes=1),
                analyst_retry_count=0,
            ).model_dump(mode="json"),
        }
    )
    return ResearchBrief.model_validate(payload)


def document(body: bytes, media_type: str) -> SecRadarDocument:
    return SecRadarDocument(
        url="https://www.sec.gov/Archives/edgar/daily-index/2026/QTR3/master.20260824.idx",
        body=body,
        content_sha256="d" * 64,
        retrieved_at=NOW,
        media_type=media_type,
    )


class FakeTransport:
    def __init__(self, response: HttpResult) -> None:
        self.response = response

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        maximum_bytes: int,
    ) -> HttpResult:
        return self.response


class PublicFunnelTrapRepository(MemoryResearchRepository):
    def get_funnel_snapshot(self) -> FunnelSnapshot | None:
        raise AssertionError("the public application must not query private funnel telemetry")


def test_latest_submission_candidate_preserves_sec_identity_and_accession() -> None:
    payload = {
        "name": "Example issuer",
        "filings": {
            "recent": {
                "form": ["S-1", "10-Q"],
                "accessionNumber": ["0000320193-26-000009", "0000320193-26-000010"],
                "filingDate": ["2026-08-01", "2026-08-20"],
            }
        },
    }
    result = latest_submission_candidate(
        document(
            json.dumps(payload).encode(),
            "application/json",
        ),
        cik="320193",
        ticker="TEST",
    )
    assert result is not None
    assert result.accession_number == "0000320193-26-000010"
    assert result.source_url.endswith("/000032019326000010/0000320193-26-000010.txt")
    assert result.cik == "0000320193"


def test_filing_accepts_canonical_sec_archive_directory() -> None:
    client = SecRadarClient(
        user_agent="Kalki tests test@example.com",
        transport=FakeTransport(
            HttpResult(
                url="https://www.sec.gov/Archives/edgar/data/789019/000119312526323660/0001193125-26-323660.txt",
                status_code=200,
                headers={"content-type": "text/plain"},
                body=b"filing",
            )
        ),
    )
    fetched = client.filing(
        "https://www.sec.gov/Archives/edgar/data/789019/000119312526323660/0001193125-26-323660.txt"
    )
    assert fetched.body == b"filing"


def test_official_ticker_and_master_indexes_form_listed_candidates() -> None:
    mapping_payload = {
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [[320193, "Synthetic issuer", "TEST", "Nasdaq"]],
    }
    mapping = parse_ticker_mapping(
        document(json.dumps(mapping_payload).encode(), "application/json")
    )
    master = b"\n".join(
        (
            b"CIK|Company Name|Form Type|Date Filed|Filename",
            b"320193|Synthetic issuer|8-K|2026-08-24|edgar/data/320193/0000320193-26-000001.txt",
            b"320193|Synthetic issuer|4|2026-08-24|edgar/data/320193/0000320193-26-000002.txt",
            b"999999|Unlisted issuer|8-K|2026-08-24|edgar/data/999999/0000999999-26-000001.txt",
        )
    )

    candidates = parse_master_index(document(master, "text/plain"), mapping)

    assert len(candidates) == 1
    assert candidates[0].ticker == "TEST"
    assert candidates[0].source_url == FILING_URL


def test_extraction_selects_bounded_visible_catalyst_and_risk_windows() -> None:
    raw = (
        b"<html><script>ignore this contract</script><body>"
        b"The company announced a strategic agreement and contract award. "
        b"Management also identified a material weakness.</body></html>"
    )

    extracted = extract_research_excerpt(raw)

    assert extracted.is_research_relevant
    assert "strategic agreement" in extracted.opportunity_terms
    assert "material weakness" in extracted.risk_terms
    assert "ignore this contract" not in extracted.text
    assert len(extracted.text) <= MAXIMUM_EXCERPT_CHARACTERS


def test_extraction_budget_keeps_diverse_evidence_and_only_reports_retained_terms() -> None:
    opportunity_sections = " ".join(
        f"Section {index} disclosed a {term}. " + ("ordinary context " * 45)
        for index, term in enumerate(
            (
                "contract",
                "award",
                "partnership",
                "approval",
                "guidance",
                "record revenue",
                "acquisition",
                "commercial launch",
            ),
            start=1,
        )
    )
    late_risk = (
        "Management stated that these conditions raise substantial doubt as a going concern."
    )

    extracted = extract_research_excerpt(f"<body>{opportunity_sections}{late_risk}</body>".encode())

    assert len(extracted.text) <= MAXIMUM_EXCERPT_CHARACTERS
    assert "contract" in extracted.opportunity_terms
    assert "going concern" in extracted.risk_terms
    assert late_risk in extracted.text
    assert all(term in extracted.text.casefold() for term in extracted.opportunity_terms)
    assert all(term in extracted.text.casefold() for term in extracted.risk_terms)


def test_extraction_windows_never_begin_or_end_inside_a_word() -> None:
    prefix = "prefixword " * 80
    suffix = " suffixword" * 80

    extracted = extract_research_excerpt(
        f"<html><body>{prefix}contract award{suffix}</body></html>".encode()
    )

    assert extracted.text.startswith("prefixword ")
    assert extracted.text.endswith(" suffixword")


def test_public_radar_is_filterable_typed_escaped_and_observable() -> None:
    repository = MemoryResearchRepository(briefs=(brief(),), worker_snapshot=snapshot())
    app = create_public_web_app(repository)
    client = TestClient(app)

    root = client.get("/", follow_redirects=False)
    page = client.get("/radar?classification=opportunity&query=test")
    api = client.get("/api/v1/radar?classification=opportunity&query=test")
    detail = client.get(f"/radar/{brief().brief_id}")
    status = client.get("/api/v1/radar/status")
    stylesheet = client.get("/static/app.css")
    mark = client.get("/static/kalki-mark.svg")
    favicon = client.get("/static/favicon.svg")
    social_card = client.get("/static/social-card.png")

    assert root.status_code == 307
    assert root.headers["location"] == "/radar"
    assert page.status_code == api.status_code == detail.status_code == status.status_code == 200
    assert "Synthetic &lt;script&gt; issuer" in page.text
    assert "Synthetic <script> issuer" not in page.text
    assert api.json()[0]["score_interpretation"] == ("heuristic_research_priority_not_probability")
    assert status.json()["published_count"] == 1
    assert "script-src 'none'" in page.headers["content-security-policy"]
    assert "The filing observatory" in page.text
    assert "Latest publication" in page.text
    assert "Sweep, angle, and distance are non-quantitative" in page.text
    assert "From filing to public record" in page.text
    assert "Normalized filing evidence" in detail.text
    assert "This text came from validated structured local-model output" in detail.text
    assert "predates independent local-model verification" in detail.text
    assert "Independent review" in page.text
    assert "They are neither confidence percentages nor return probabilities" in detail.text
    assert (
        stylesheet.status_code
        == mark.status_code
        == favicon.status_code
        == social_card.status_code
        == 200
    )
    assert 'property="og:image"' in page.text
    assert "prefers-reduced-motion: reduce" in stylesheet.text
    assert "@keyframes sweep" in stylesheet.text
    assert "<script" not in page.text.casefold()
    assert "<script" not in detail.text.casefold()


def test_public_application_never_queries_private_funnel_telemetry() -> None:
    response = TestClient(create_public_web_app(PublicFunnelTrapRepository())).get("/radar")

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("state", "error_code"),
    [
        (WorkerState.RUNNING, None),
        (WorkerState.IDLE, None),
        (WorkerState.WAITING_FOR_CONFIGURATION, None),
        (WorkerState.DEGRADED, "bounded_public_error"),
    ],
)
def test_observatory_states_are_truthful_without_fabricated_blips(
    state: WorkerState, error_code: str | None
) -> None:
    app = create_public_web_app(
        MemoryResearchRepository(worker_snapshot=snapshot(state, error_code=error_code))
    )

    page = TestClient(app).get("/radar")

    assert page.status_code == 200
    assert f"state-{state.value}" in page.text
    assert "No published security blips" in page.text
    assert "instrument-blip" not in page.text
    assert "Kalki does not manufacture activity" in page.text
    assert ("Degraded state:" in page.text) is (state is WorkerState.DEGRADED)


def test_verified_dossier_exposes_only_truthful_public_model_lineage() -> None:
    verifier_snapshot = snapshot().model_copy(
        update={
            "verifier_enabled": True,
            "verifier_model_name": "gemma4:12b-it-q4_K_M",
            "verifier_reviews": 1,
            "verifier_approvals": 1,
        }
    )
    app = create_public_web_app(
        MemoryResearchRepository(
            briefs=(verified_brief(),),
            worker_snapshot=verifier_snapshot,
        )
    )

    page = TestClient(app).get(f"/radar/{verified_brief().brief_id}")
    pulse = TestClient(app).get("/radar")

    assert "Independent verifier · passed" in page.text
    assert "gemma4:12b-it-q4_K_M" in page.text
    assert "Deterministic validation remained final authority" in page.text
    assert "1 passed" in pulse.text
    assert "verifier prompt" not in page.text.casefold()


def test_dossier_exposes_deterministic_numeric_receipts_without_model_traces() -> None:
    payload = brief().model_dump(mode="json")
    payload["numeric_verifications"] = [
        NumericVerification(
            claim_id="CASH-01",
            evidence_id="32000000-0000-4000-8000-000000000001",
            claimed_value=Decimal("12.5"),
            source_value=Decimal("12.5"),
            tolerance=Decimal("0"),
            status=NumericVerificationStatus.VERIFIED,
            note="Claimed value matches the independently extracted value within tolerance.",
        ).model_dump(mode="json")
    ]
    record = ResearchBrief.model_validate(payload)
    page = TestClient(create_public_web_app(MemoryResearchRepository(briefs=(record,)))).get(
        f"/radar/{record.brief_id}"
    )

    assert page.status_code == 200
    assert "Deterministic claim checks" in page.text
    assert "verified" in page.text
    assert "CASH-01" in page.text
    assert "chain-of-thought" not in page.text.casefold()
    assert "raw response" not in page.text.casefold()


class IndexTransport:
    def __init__(self, unavailable_status: int = 404) -> None:
        self.urls: list[str] = []
        self.unavailable_status = unavailable_status

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        maximum_bytes: int,
    ) -> HttpResult:
        self.urls.append(url)
        status = 200 if url.endswith("master.20260821.idx") else self.unavailable_status
        return HttpResult(
            url=url,
            status_code=status,
            headers={"content-type": "text/plain"},
            body=b"index" if status == 200 else b"missing",
        )


@pytest.mark.parametrize("unavailable_status", [403, 404])
def test_daily_index_discovery_falls_back_over_non_filing_days_with_identification(
    unavailable_status: int,
) -> None:
    transport = IndexTransport(unavailable_status)
    client = SecRadarClient(
        user_agent="Kalki tests monitored@example.com",
        transport=transport,
        limiter=RateLimiter(10, monotonic=lambda: 0, sleep=lambda _: None),
        retry_sleep=lambda _: None,
        now=lambda: NOW,
    )

    result = client.latest_master_index(NOW.date())

    assert result.body == b"index"
    assert len(transport.urls) == 4
    assert transport.urls[-1].endswith("/2026/QTR3/master.20260821.idx")


def test_companyfacts_rejects_non_numeric_cik_before_network() -> None:
    client = SecRadarClient(
        user_agent="Kalki tests monitored@example.com",
        transport=IndexTransport(),
        limiter=RateLimiter(10, monotonic=lambda: 0, sleep=lambda _: None),
        retry_sleep=lambda _: None,
        now=lambda: NOW,
    )
    with pytest.raises(ValueError, match="companyfacts CIK"):
        client.companyfacts("not-a-cik")


def test_radar_discord_template_is_bounded_research_only_and_deduplicated() -> None:
    notification = RadarNotification(brief=brief())
    payload = render_radar_notification(notification)

    assert len(payload.content) <= 2_000
    assert "not financial advice" in payload.content
    assert "No action is requested" in payload.content
    assert "https://localhost/radar/" in payload.content
    assert notification.notification_key == RadarNotification(brief=brief()).notification_key
    assert payload.allowed_mentions.parse == ()


def test_radar_discord_template_uses_operator_public_hostname() -> None:
    payload = render_radar_notification(
        RadarNotification(brief=brief()),
        public_hostname="public.example",
    )

    assert "https://public.example/radar/" in payload.content
    assert "YOUR_PUBLIC_HOSTNAME" not in payload.content


def test_stored_sec_links_are_minimized_for_web_and_discord() -> None:
    record, receipt = linked_brief()
    public_links = public_sec_filing_links(receipt)
    notification = RadarNotification(brief=record, sec_links=public_links)
    payload = render_radar_notification(notification)
    repository = MemoryResearchRepository(briefs=(record,), sec_link_receipts=(receipt,))
    page = TestClient(create_public_web_app(repository)).get(f"/radar/{record.brief_id}")

    assert receipt.primary_document_url in payload.content
    assert receipt.archive_index_sha256 not in payload.content
    assert page.status_code == 200
    assert receipt.primary_document_url in page.text
    assert receipt.archive_index_url in page.text
    assert receipt.archive_index_sha256 not in page.text
    assert "Open historical complete SEC submission" not in page.text
