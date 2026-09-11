"""Deterministic Phase 41 accounting/auditor/compliance contract tests."""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from kalki_market_intelligence.forensics.accounting import (
    MAXIMUM_ACCOUNTING_HTML_BYTES,
    AccountingComparisonDisposition,
    AccountingEvent,
    AccountingEventType,
    AccountingEvidenceExcerpt,
    AccountingEvidenceSignal,
    AccountingFilingReceipt,
    AccountingForm,
    AccountingParseError,
    AccountingTier0Receipt,
    build_accounting_filing_receipt,
    choose_accounting_tier,
    extract_accounting_evidence,
    normalize_accounting_form,
    normalized_accounting_visible_text,
)
from kalki_market_intelligence.forensics.tiers import EscalationReason
from kalki_market_intelligence.providers.sec.accounting import (
    AccountingFilingMetadata,
    SecAccountingIngestionService,
    accounting_filing_from_submissions,
)
from kalki_market_intelligence.providers.sec.client import (
    SecFetchedDocument,
    SecFetchedPrimaryDocument,
)

FIXTURES = Path(__file__).parent / "fixtures" / "accounting"
INSPECTED_AFTER = datetime(2026, 8, 31, 19, 20, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class OfficialCase:
    fixture: str
    accession_number: str
    cik: str
    issuer_name: str
    form: AccountingForm
    source_url: str
    source_sha256: str
    accepted_at: datetime
    expected_signals: frozenset[AccountingEvidenceSignal]
    expected_events: frozenset[AccountingEventType]
    absent_signals: frozenset[AccountingEvidenceSignal] = frozenset()


CASES = (
    OfficialCase(
        fixture="geovax-2026-item-3-01.html.gz.b64",
        accession_number="0001437749-26-029184",
        cik="832489",
        issuer_name="GeoVax Labs, Inc.",
        form=AccountingForm.FORM_8_K,
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/832489/000143774926029184/govx20260828_8k.htm"
        ),
        source_sha256="946d7815c63b0bd81d61bae6282da503317a73acbc9dc5c921630aef9e2aa3b0",
        accepted_at=datetime(2026, 8, 28, 16, 16, 41, tzinfo=UTC),
        expected_signals=frozenset(
            {
                AccountingEvidenceSignal.ITEM_3_01_NOTICE,
                AccountingEvidenceSignal.LISTING_NONCOMPLIANCE_LANGUAGE,
                AccountingEvidenceSignal.DELISTING_LANGUAGE,
            }
        ),
        expected_events=frozenset({AccountingEventType.LISTING_COMPLIANCE}),
    ),
    OfficialCase(
        fixture="groovy-2026-item-4-01.html.gz.b64",
        accession_number="0001499275-26-000007",
        cik="1499275",
        issuer_name="Groovy Company, Inc.",
        form=AccountingForm.FORM_8_K,
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/1499275/"
            "000149927526000007/groo-20250813_8k.htm"
        ),
        source_sha256="d6b78119092d1a39eb769e3ac1dc08c5de260c8711430e8d47138ca9eb15d128",
        accepted_at=datetime(2026, 5, 13, 18, 31, 7, tzinfo=UTC),
        expected_signals=frozenset(
            {
                AccountingEvidenceSignal.ITEM_4_01_NOTICE,
                AccountingEvidenceSignal.AUDITOR_DISMISSAL_LANGUAGE,
                AccountingEvidenceSignal.AUDITOR_DISAGREEMENT_LANGUAGE,
                AccountingEvidenceSignal.REPORTABLE_EVENT_LANGUAGE,
            }
        ),
        expected_events=frozenset(
            {
                AccountingEventType.AUDITOR_CHANGE,
                AccountingEventType.NON_RELIANCE_RESTATEMENT,
            }
        ),
    ),
    OfficialCase(
        fixture="highwire-2026-item-4-02.html.gz.b64",
        accession_number="0001683168-26-005550",
        cik="1413891",
        issuer_name="High Wire Networks, Inc.",
        form=AccountingForm.FORM_8_K,
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/1413891/000168316826005550/highwire_8k.htm"
        ),
        source_sha256="3edbb07bb31ceae32d1ef943bba2ab7f84d51992fe90eba6539c5ec259eb9138",
        accepted_at=datetime(2026, 7, 15, 19, 53, 44, tzinfo=UTC),
        expected_signals=frozenset(
            {
                AccountingEvidenceSignal.ITEM_4_02_NON_RELIANCE,
                AccountingEvidenceSignal.RESTATEMENT_LANGUAGE,
                AccountingEvidenceSignal.MATERIAL_WEAKNESS_LANGUAGE,
                AccountingEvidenceSignal.CONTROL_INEFFECTIVENESS_LANGUAGE,
                AccountingEvidenceSignal.REMEDIATION_LANGUAGE,
            }
        ),
        expected_events=frozenset(
            {
                AccountingEventType.NON_RELIANCE_RESTATEMENT,
                AccountingEventType.INTERNAL_CONTROLS,
            }
        ),
    ),
    OfficialCase(
        fixture="marwynn-2026-nt-10-k.html.gz.b64",
        accession_number="0001213900-26-083374",
        cik="2030522",
        issuer_name="Marwynn Holdings, Inc.",
        form=AccountingForm.NT_10_K,
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/2030522/"
            "000121390026083374/ea0299607-nt10k_marwynn.htm"
        ),
        source_sha256="cf83a0dd31cfcf1b15954678569b31f5ed5b8eeb3004c4b90a8743b57a2c20ca",
        accepted_at=datetime(2026, 7, 30, 20, 45, 1, tzinfo=UTC),
        expected_signals=frozenset({AccountingEvidenceSignal.LATE_FILING_NOTICE}),
        expected_events=frozenset({AccountingEventType.LATE_FILING}),
    ),
    OfficialCase(
        fixture="top-financial-2026-nt-10-q.html.gz.b64",
        accession_number="0001213900-26-090471",
        cik="1848275",
        issuer_name="TOP Financial Group Limited",
        form=AccountingForm.NT_10_Q,
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/1848275/"
            "000121390026090471/ea0302338-nt10q_top.htm"
        ),
        source_sha256="fb04d9fb60e61eaaeabc63fd8940b719fbfaec308db2e2e9fec841d14d6a9c7f",
        accepted_at=datetime(2026, 8, 17, 11, 0, 1, tzinfo=UTC),
        expected_signals=frozenset({AccountingEvidenceSignal.LATE_FILING_NOTICE}),
        expected_events=frozenset({AccountingEventType.LATE_FILING}),
    ),
    OfficialCase(
        fixture="aqua-metals-2026-10-q.html.gz.b64",
        accession_number="0001437749-26-025091",
        cik="1621832",
        issuer_name="Aqua Metals, Inc.",
        form=AccountingForm.FORM_10_Q,
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/1621832/"
            "000143774926025091/aqms20260630_10q.htm"
        ),
        source_sha256="6fa6c6a0700cae032558409762fc47f15c7b31fb52fbd01a3d3a18633da97bd1",
        accepted_at=datetime(2026, 7, 30, 20, 48, 8, tzinfo=UTC),
        expected_signals=frozenset({AccountingEvidenceSignal.GOING_CONCERN_LANGUAGE}),
        expected_events=frozenset({AccountingEventType.GOING_CONCERN}),
    ),
    OfficialCase(
        fixture="cs-diagnostics-2026-10-k.html.gz.b64",
        accession_number="0001214659-26-004694",
        cik="1106861",
        issuer_name="CS DIAGNOSTICS CORP.",
        form=AccountingForm.FORM_10_K,
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/1106861/000121465926004694/csd32026010k.htm"
        ),
        source_sha256="520212c4fb97b8717e563457e405a54b4a2cbe0634eba13c4058ea4eb6cad9f3",
        accepted_at=datetime(2026, 4, 15, 19, 54, 26, tzinfo=UTC),
        expected_signals=frozenset(
            {
                AccountingEvidenceSignal.GOING_CONCERN_LANGUAGE,
                AccountingEvidenceSignal.MATERIAL_WEAKNESS_LANGUAGE,
                AccountingEvidenceSignal.CONTROL_INEFFECTIVENESS_LANGUAGE,
                AccountingEvidenceSignal.REMEDIATION_LANGUAGE,
            }
        ),
        expected_events=frozenset(
            {
                AccountingEventType.GOING_CONCERN,
                AccountingEventType.INTERNAL_CONTROLS,
            }
        ),
        absent_signals=frozenset({AccountingEvidenceSignal.CONTROL_CHANGE_LANGUAGE}),
    ),
)

PERIODIC_CASES = CASES[-2:]


def _body(fixture: str) -> bytes:
    encoded = "".join((FIXTURES / fixture).read_text(encoding="ascii").splitlines())
    return gzip.decompress(base64.b64decode(encoded, validate=True))


def _receipt(
    case: OfficialCase,
    *,
    prior_receipts: tuple[AccountingFilingReceipt, ...] = (),
    prior_search_complete: bool = False,
) -> AccountingFilingReceipt:
    return build_accounting_filing_receipt(
        accession_number=case.accession_number,
        issuer_cik=case.cik,
        issuer_name=case.issuer_name,
        form=case.form,
        source_url=case.source_url,
        body=_body(case.fixture),
        accepted_at=case.accepted_at,
        retrieved_at=INSPECTED_AFTER,
        prior_receipts=prior_receipts,
        prior_search_complete=prior_search_complete,
    )


@pytest.mark.parametrize("case", CASES, ids=lambda item: item.fixture)
def test_complete_official_sec_sources_reconcile_to_closed_evidence(case: OfficialCase) -> None:
    body = _body(case.fixture)
    assert hashlib.sha256(body).hexdigest() == case.source_sha256

    receipt = _receipt(case)
    visible = normalized_accounting_visible_text(body)
    signals = {signal for item in receipt.evidence_bundle.evidence for signal in item.signals}

    assert case.expected_signals <= signals
    assert not case.absent_signals & signals
    assert {item.event_type for item in receipt.events} == case.expected_events
    assert receipt.source_content_sha256 == case.source_sha256
    assert receipt.issuer_cik == case.cik.zfill(10)
    assert receipt.receipt_id == _receipt(case).receipt_id
    assert all(item.comparison == "PRIOR_COMPARISON_UNAVAILABLE" for item in receipt.events)
    for evidence in receipt.evidence_bundle.evidence:
        assert visible[evidence.start_offset : evidence.end_offset] == evidence.text
        assert len(evidence.text) <= 900


@pytest.mark.parametrize("case", PERIODIC_CASES, ids=lambda item: item.fixture)
def test_periodic_sources_replay_exact_submissions_acquisition_and_parser(
    case: OfficialCase,
) -> None:
    metadata_by_accession = {
        "0001437749-26-025091": {
            "filingDate": "2026-07-30",
            "reportDate": "2026-06-30",
            "fileNumber": "001-37515",
            "primaryDocDescription": "FORM 10-Q",
        },
        "0001214659-26-004694": {
            "filingDate": "2026-04-15",
            "reportDate": "2025-12-31",
            "fileNumber": "000-29611",
            "primaryDocDescription": "",
        },
    }
    primary_document = case.source_url.rsplit("/", 1)[1]
    row = metadata_by_accession[case.accession_number]
    submissions_body = json.dumps(
        {
            "cik": case.cik.zfill(10),
            "name": case.issuer_name,
            "filings": {
                "recent": {
                    "accessionNumber": [case.accession_number],
                    "filingDate": [row["filingDate"]],
                    "reportDate": [row["reportDate"]],
                    "acceptanceDateTime": [case.accepted_at.isoformat().replace("+00:00", "Z")],
                    "form": [case.form.value],
                    "fileNumber": [row["fileNumber"]],
                    "primaryDocument": [primary_document],
                    "primaryDocDescription": [row["primaryDocDescription"]],
                }
            },
        },
        separators=(",", ":"),
    ).encode()
    submissions = SecFetchedDocument(
        endpoint="submissions",
        cik=case.cik.zfill(10),
        url=f"https://data.sec.gov/submissions/CIK{case.cik.zfill(10)}.json",
        status_code=200,
        headers={"content-type": "application/json"},
        body=submissions_body,
        content_sha256=hashlib.sha256(submissions_body).hexdigest(),
        retrieved_at=INSPECTED_AFTER,
    )
    metadata = accounting_filing_from_submissions(
        submissions,
        accession_number=case.accession_number,
    )
    assert isinstance(metadata, AccountingFilingMetadata)

    class ExactPrimaryClient:
        def fetch_primary_html_document(
            self,
            *,
            cik: str | int,
            accession_number: str,
            document_name: str,
        ) -> SecFetchedPrimaryDocument:
            assert str(cik).zfill(10) == case.cik.zfill(10)
            assert accession_number == case.accession_number
            assert document_name == primary_document
            body = _body(case.fixture)
            return SecFetchedPrimaryDocument(
                cik=case.cik.zfill(10),
                accession_number=case.accession_number,
                document_name=primary_document,
                url=case.source_url,
                status_code=200,
                headers={"content-type": "text/html"},
                body=body,
                content_sha256=hashlib.sha256(body).hexdigest(),
                retrieved_at=INSPECTED_AFTER,
            )

    receipt = SecAccountingIngestionService(ExactPrimaryClient()).ingest(
        metadata,
        prior_receipts=(),
        prior_search_complete=False,
    )
    signals = {signal for item in receipt.evidence_bundle.evidence for signal in item.signals}
    assert case.expected_signals <= signals
    assert not case.absent_signals & signals
    assert {item.event_type for item in receipt.events} == case.expected_events


def test_complete_prior_search_and_real_same_issuer_change_are_distinct() -> None:
    prior_case = OfficialCase(
        fixture="genprex-2026-07-30-item-3-01.html.gz.b64",
        accession_number="0001437749-26-025074",
        cik="1595248",
        issuer_name="Genprex, Inc.",
        form=AccountingForm.FORM_8_K,
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/1595248/000143774926025074/gnpx20260730_8k.htm"
        ),
        source_sha256="01233817665193d9dc37fe31bd4139f15a3f50a6c307362b4a89c52f1182d4d2",
        accepted_at=datetime(2026, 7, 30, 20, 31, 2, tzinfo=UTC),
        expected_signals=frozenset(),
        expected_events=frozenset({AccountingEventType.LISTING_COMPLIANCE}),
    )
    current_case = OfficialCase(
        fixture="genprex-2026-08-05-item-3-01.html.gz.b64",
        accession_number="0001437749-26-025938",
        cik="1595248",
        issuer_name="Genprex, Inc.",
        form=AccountingForm.FORM_8_K,
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/1595248/000143774926025938/gnpx20260805_8k.htm"
        ),
        source_sha256="dc4380326fe08b2dd49cee1ac34da56054ff0dc7a2caf98bf5c39218c6286ce1",
        accepted_at=datetime(2026, 8, 5, 20, 31, 46, tzinfo=UTC),
        expected_signals=frozenset(),
        expected_events=frozenset({AccountingEventType.LISTING_COMPLIANCE}),
    )
    prior = _receipt(prior_case, prior_search_complete=True)
    current = _receipt(
        current_case,
        prior_receipts=(prior,),
        prior_search_complete=True,
    )
    event = current.events[0]

    assert prior.events[0].comparison is AccountingComparisonDisposition.NEW_DISCLOSURE
    assert event.comparison is AccountingComparisonDisposition.CHANGED_DISCLOSURE
    assert event.prior_accession_number == prior.accession_number
    assert event.prior_event_id == prior.events[0].event_id
    assert event.prior_event_fingerprint != event.event_fingerprint
    assert AccountingEvidenceSignal.REGAINED_COMPLIANCE_LANGUAGE in event.signals


def test_untrusted_markup_and_unsupported_current_items_do_not_create_evidence() -> None:
    body = b"""
    <html><script>Item 4.02 restatement material weakness fraud</script>
    <body>Item 1.01 Entry into a Material Definitive Agreement. Ordinary agreement text.
    Item 9.01 Financial Statements and Exhibits.</body></html>
    """
    bundle = extract_accounting_evidence(body, form=AccountingForm.FORM_8_K)
    assert bundle.evidence == ()


def test_hidden_only_source_fails_and_routine_policy_heading_is_not_an_event() -> None:
    with pytest.raises(AccountingParseError, match="no visible text"):
        extract_accounting_evidence(
            b"<html><template>Item 4.02 restatement</template></html>",
            form=AccountingForm.FORM_8_K,
        )

    bundle = extract_accounting_evidence(
        b"<html><body>Significant Accounting Policies. Ordinary note text.</body></html>",
        form=AccountingForm.FORM_10_K,
    )
    assert bundle.evidence == ()


def test_closed_versions_evidence_identity_and_order_fail_closed() -> None:
    receipt = _receipt(CASES[0])

    payload = receipt.model_dump(mode="json")
    payload["parser_version"] = "future-unreviewed-parser"
    with pytest.raises(ValidationError, match="sec-accounting-compliance-v1"):
        AccountingFilingReceipt.model_validate(payload)

    payload = receipt.model_dump(mode="json")
    payload["evidence_bundle"]["evidence"][0]["evidence_id"] = str(uuid4())
    with pytest.raises(ValidationError, match="evidence identity does not reconcile"):
        AccountingFilingReceipt.model_validate(payload)

    event_with_multiple_evidence = next(
        item for item in receipt.events if len(item.evidence_ids) > 1
    )
    payload = receipt.model_dump(mode="json")
    for event in payload["events"]:
        if event["event_id"] == str(event_with_multiple_evidence.event_id):
            event["evidence_ids"] = list(reversed(event["evidence_ids"]))
    with pytest.raises(ValidationError, match="deterministic source order"):
        AccountingFilingReceipt.model_validate(payload)


def test_future_retrieved_prior_receipt_cannot_create_look_ahead_comparison() -> None:
    prior_case = CASES[0]
    prior = _receipt(prior_case, prior_search_complete=True)
    current = build_accounting_filing_receipt(
        accession_number="0001437749-26-029185",
        issuer_cik=prior_case.cik,
        issuer_name=prior_case.issuer_name,
        form=prior_case.form,
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/832489/000143774926029185/govx20260828_8k.htm"
        ),
        body=_body(prior_case.fixture),
        accepted_at=datetime(2026, 8, 29, 16, 16, 41, tzinfo=UTC),
        retrieved_at=datetime(2026, 8, 29, 17, 0, tzinfo=UTC),
        prior_receipts=(prior,),
        prior_search_complete=False,
    )

    assert all(
        item.comparison is AccountingComparisonDisposition.PRIOR_COMPARISON_UNAVAILABLE
        for item in current.events
    )


def test_source_url_chronology_size_and_comparison_fail_closed() -> None:
    case = CASES[0]
    with pytest.raises(ValidationError, match="matching SEC primary document"):
        build_accounting_filing_receipt(
            accession_number=case.accession_number,
            issuer_cik=case.cik,
            issuer_name=case.issuer_name,
            form=case.form,
            source_url=CASES[1].source_url,
            body=_body(case.fixture),
            accepted_at=case.accepted_at,
            retrieved_at=INSPECTED_AFTER,
            prior_search_complete=True,
        )
    with pytest.raises(ValidationError, match="cannot precede"):
        build_accounting_filing_receipt(
            accession_number=case.accession_number,
            issuer_cik=case.cik,
            issuer_name=case.issuer_name,
            form=case.form,
            source_url=case.source_url,
            body=_body(case.fixture),
            accepted_at=INSPECTED_AFTER,
            retrieved_at=case.accepted_at,
            prior_search_complete=True,
        )
    with pytest.raises(AccountingParseError, match="oversized"):
        extract_accounting_evidence(
            b"x" * (MAXIMUM_ACCOUNTING_HTML_BYTES + 1),
            form=AccountingForm.FORM_10_K,
        )


def test_closed_schema_has_no_fraud_conclusion_or_unbounded_model_content() -> None:
    fields = set(AccountingFilingReceipt.model_fields)
    event_fields = set(AccountingEvent.model_fields)
    evidence_fields = set(AccountingEvidenceExcerpt.model_fields)
    prohibited = {"fraud", "prompt", "response", "reasoning", "hypothesis", "score"}
    assert not fields & prohibited
    assert not event_fields & prohibited
    assert not evidence_fields & prohibited


def test_accounting_routing_is_model_free_and_source_bound() -> None:
    receipt = _receipt(CASES[2])
    routing = choose_accounting_tier(receipt)

    assert routing.event_types == (
        AccountingEventType.INTERNAL_CONTROLS,
        AccountingEventType.NON_RELIANCE_RESTATEMENT,
    )
    assert routing.decision.reason is EscalationReason.ACCOUNTING_COMPLIANCE_CONTEXT
    assert routing.decision.tier == 0
    assert routing.decision.outcome == "retain"
    assert not routing.decision.requires_model
    assert set(routing.decision.evidence_ids) == {
        evidence_id for event in receipt.events for evidence_id in event.evidence_ids
    }
    assert routing.decision.estimated_context_chars <= 9_000

    payload = routing.model_dump(mode="json")
    payload["decision"]["requires_model"] = True
    with pytest.raises(ValidationError, match="model-free Tier-0"):
        AccountingTier0Receipt.model_validate(payload)


def test_accounting_form_normalization_is_closed() -> None:
    assert normalize_accounting_form(" nt 10-q ") is AccountingForm.NT_10_Q
    with pytest.raises(AccountingParseError, match="unsupported accounting form"):
        normalize_accounting_form("20-F")
